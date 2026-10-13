"""真实 Keycloak + PostgreSQL 桌面协议联调。仅使用本次创建的隔离 Realm/schema。

不打印凭据或授权 URL。finally 仅删除本次成功创建的随机测试 Realm/schema。
不是 macOS/Windows Electron 实机测试，不向桌面项目写代码。
"""

import asyncio
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.core import models  # noqa: F401
from app.core.config import Settings
from app.main import create_app
from app.modules.auth.service import now
from app.modules.desktop.service import pkce
from app.modules.members.models import Membership
from app.modules.users.models import LoginIdentity

stage = "prepare"


def check(response, expected=200):
    assert response.status_code == expected, (
        f"HTTP {response.status_code}, expected {expected}"
    )
    return (
        response.json() if "json" in response.headers.get("content-type", "") else None
    )


class Callback(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Verified. Return to desktop.")

    def log_message(self, *args):
        pass


class Browser:
    async def __aenter__(self):
        self.process = await asyncio.create_subprocess_exec(
            "node",
            str(root / "scripts/verify-desktop-browser.mjs"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return self

    async def __aexit__(self, *args):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), timeout=15)

    async def get(self, url):
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.get(url)


async def browser_authorize(browser, url, username, password):
    browser.process.stdin.write(
        (
            json.dumps({"url": url, "username": username, "password": password}) + "\n"
        ).encode()
    )
    await browser.process.stdin.drain()
    line = await asyncio.wait_for(browser.process.stdout.readline(), timeout=50)
    assert line, "Test browser exited"
    result = json.loads(line)
    if "error" in result:
        print("Browser diagnostic", result)
    assert "error" not in result, "Browser login failed"
    return result["callback"], result["prompted"]


async def main():
    global stage
    env = dotenv_values(root / ".env")
    live = Settings()
    origin = live.oidc_issuer.rsplit("/realms/", 1)[0]
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost"}
    realm = "actvero-desktop-test-" + uuid4().hex[:12]
    schema = "desktop_live_" + uuid4().hex
    web_secret, provisioner_secret, password = (
        secrets.token_urlsafe(32) for _ in range(3)
    )
    callback = HTTPServer(("127.0.0.1", 0), Callback)
    callback_b = HTTPServer(("127.0.0.1", 0), Callback)
    for server in (callback, callback_b):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    app_url = f"http://127.0.0.1:{callback.server_port}"
    template = (root / "identity/bootstrap/actvero-realm.json").read_text()
    for key, value in {
        "ACTVERO_WEB_CLIENT_SECRET": web_secret,
        "ACTVERO_PROVISIONER_CLIENT_SECRET": provisioner_secret,
        "ACTVERO_APP_URL": app_url,
    }.items():
        template = template.replace("${" + key + "}", value)
    definition = json.loads(template)
    definition["realm"] = realm
    definition["displayName"] = "Actvero isolated desktop test"
    owner = create_async_engine(live.database_url.get_secret_value())
    engine = create_async_engine(
        live.database_url.get_secret_value(),
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    made_realm = made_schema = False
    settings = Settings(
        _env_file=None,
        database_url=None,
        app_url=app_url,
        oidc_issuer=origin + "/realms/" + realm,
        web_client_secret=web_secret,
        provisioner_client_secret=provisioner_secret,
        session_encryption_key=Fernet.generate_key().decode(),
    )
    headers = {}
    async with httpx.AsyncClient(timeout=30) as admin:
        try:
            stage = "create isolated realm/schema"
            auth = await admin.post(
                origin + "/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": env["KC_BOOTSTRAP_ADMIN_USERNAME"],
                    "password": env["KC_BOOTSTRAP_ADMIN_PASSWORD"],
                },
            )
            headers = {"Authorization": "Bearer " + check(auth)["access_token"]}
            version = check(
                await admin.get(origin + "/admin/serverinfo", headers=headers)
            )["systemInfo"]["version"]
            response = await admin.post(
                origin + "/admin/realms", headers=headers, json=definition
            )
            check(response, 201)
            made_realm = True
            async with owner.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            made_schema = True
            # Exercise the real Alembic migration chain in the isolated schema.
            from alembic import command
            from alembic.config import Config

            # Alembic env uses Settings; run on a dedicated connection supplied to it.
            async with engine.begin() as conn:

                def migrate(sync):
                    cfg = Config(str(root / "backend/alembic.ini"))
                    cfg.set_main_option(
                        "script_location", str(root / "backend/migrations")
                    )
                    cfg.attributes["connection"] = sync
                    command.upgrade(cfg, "head")

                await conn.run_sync(migrate)
            app = create_app(settings)
            async with app.router.lifespan_context(app):
                app.state.database.engine = engine
                app.state.database.sessions = sessions
                async with (
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url=settings.app_url,
                        headers={"origin": settings.app_url},
                    ) as web,
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url=settings.app_url,
                    ) as api,
                    Browser() as browser,
                ):
                    stage = "initialize + actual Web OIDC"
                    initial = check(await web.get("/api/v1/auth/session"))
                    web.headers["x-csrf-token"] = initial["csrf"]
                    username = "desktop-check@example.com"
                    check(
                        await web.post(
                            "/api/v1/setup/register",
                            json={
                                "organization_name": "隔离桌面联调",
                                "name": "联调管理员",
                                "email": username,
                                "password": password,
                            },
                        )
                    )
                    response = await web.get("/api/v1/auth/login")
                    assert response.status_code == 307
                    return_to, used_password = await browser_authorize(
                        browser, response.headers["location"], username, password
                    )
                    assert used_password
                    response = await web.get(return_to)
                    assert (
                        response.status_code == 303
                        and response.headers["location"] == "/"
                    ), "Web callback failed"
                    context = check(await web.get("/api/v1/auth/session"))
                    assert context["authenticated"] and context["organization"]
                    web.headers["x-csrf-token"] = context["csrf"]
                    tenant_id = context["organization"]["tenant_id"]
                    print("PASS real Web login + initial organization")

                    async def desktop_login(name, fresh=False, port=None):
                        verifier = secrets.token_urlsafe(32)
                        started = check(
                            await api.post(
                                "/api/v1/desktop/login/start",
                                json={
                                    "contract_version": 1,
                                    "redirect_uri": f"http://127.0.0.1:{port or callback.server_port}/actvero/callback",
                                    "code_challenge": pkce(verifier),
                                    "device_name": name,
                                    "os": "macOS",
                                    "app_version": "0.1.0",
                                    "reauthenticate": fresh,
                                },
                            )
                        )
                        location, submitted = await browser_authorize(
                            browser, started["authorization_url"], username, password
                        )
                        query = parse_qs(urlsplit(location).query)
                        assert (
                            query["state"][0] == started["state"]
                            and query["iss"][0] == settings.oidc_issuer
                        )
                        if not port:
                            assert (await browser.get(location)).status_code == 200
                        payload = {
                            "attempt_id": started["attempt_id"],
                            "code": query["code"][0],
                            "state": query["state"][0],
                            "issuer": query["iss"][0],
                            "code_verifier": verifier,
                        }
                        return (
                            check(
                                await api.post(
                                    "/api/v1/desktop/login/exchange", json=payload
                                )
                            ),
                            payload,
                            submitted,
                        )

                    def bearer(t):
                        return {"Authorization": "Bearer " + t["access_token"]}

                    stage = "native dynamic loopback/shared SSO"
                    first, first_proof, first_prompt = await desktop_login("设备 A")
                    second, _second_proof, second_prompt = await desktop_login(
                        "设备 B", port=callback_b.server_port
                    )
                    assert not first_prompt and not second_prompt, (
                        "Expected shared browser SSO"
                    )
                    assert first["device_session_id"] != second["device_session_id"]
                    for t in (first, second):
                        me = check(
                            await api.get("/api/v1/desktop/me", headers=bearer(t))
                        )
                        assert me["user"]["id"] == context["user"]["id"]
                        bootstrap = check(
                            await api.get(
                                "/api/v1/desktop/bootstrap",
                                params={"tenant_id": tenant_id},
                                headers=bearer(t),
                            )
                        )
                        assert {m["status"] for m in bootstrap["modules"]} == {
                            "not_implemented"
                        }
                    print(
                        "PASS public client + S256 + two dynamic ports + shared SSO identity"
                    )
                    stage = "rotation/lost-response/concurrent logout"
                    body = {
                        "refresh_token": first["refresh_token"],
                        "request_id": str(uuid4()),
                    }
                    results = await asyncio.gather(
                        *[
                            api.post("/api/v1/desktop/refresh", json=body)
                            for _ in range(2)
                        ]
                    )
                    refreshed = [check(res) for res in results]
                    assert (
                        refreshed[0]["refresh_token"] == refreshed[1]["refresh_token"]
                    )
                    check(
                        await api.post(
                            "/api/v1/desktop/refresh",
                            json={**body, "request_id": str(uuid4())},
                        ),
                        409,
                    )
                    check(
                        await web.delete(
                            "/api/v1/account/devices/" + first["device_session_id"]
                        )
                    )
                    check(
                        await api.get(
                            "/api/v1/desktop/me", headers=bearer(refreshed[0])
                        ),
                        401,
                    )
                    check(
                        await api.post(
                            "/api/v1/desktop/login/exchange", json=first_proof
                        ),
                        401,
                    )
                    check(await api.post("/api/v1/desktop/refresh", json=body), 401)
                    check(await api.get("/api/v1/desktop/me", headers=bearer(second)))
                    check(await web.get(f"/api/v1/enterprises/{tenant_id}/members"))
                    print(
                        "PASS refresh idempotency + remote revoke A; B and Web remain active"
                    )
                    stage = "membership pause + trusted reauthentication"
                    async with sessions() as db:
                        member = await db.scalar(select(Membership))
                        member.status = "paused"
                        member.revoked_at = now()
                        await db.commit()
                    check(
                        await api.get(
                            "/api/v1/desktop/bootstrap",
                            params={"tenant_id": tenant_id},
                            headers=bearer(second),
                        ),
                        403,
                    )
                    async with sessions() as db:
                        member = await db.scalar(select(Membership))
                        member.status = "active"
                        await db.commit()
                    check(
                        await api.get(
                            "/api/v1/desktop/bootstrap",
                            params={"tenant_id": tenant_id},
                            headers=bearer(second),
                        ),
                        401,
                    )
                    stale, _, prompted = await desktop_login("恢复前 SSO")
                    assert not prompted
                    check(
                        await api.get(
                            "/api/v1/desktop/bootstrap",
                            params={"tenant_id": tenant_id},
                            headers=bearer(stale),
                        ),
                        401,
                    )
                    await asyncio.sleep(1.1)  # OIDC auth_time has second precision.
                    fresh, _, prompted = await desktop_login("重新验证", fresh=True)
                    assert prompted
                    check(
                        await api.get(
                            "/api/v1/desktop/bootstrap",
                            params={"tenant_id": tenant_id},
                            headers=bearer(fresh),
                        )
                    )
                    print("PASS member pause/restore requires new trusted auth_time")
                    stage = "account disabled / credential boundaries"
                    async with sessions() as db:
                        identity = await db.scalar(select(LoginIdentity))
                        subject = identity.subject
                    check(
                        await admin.put(
                            origin + "/admin/realms/" + realm + "/users/" + subject,
                            headers=headers,
                            json={"enabled": False},
                        ),
                        204,
                    )
                    check(
                        await api.get("/api/v1/desktop/me", headers=bearer(fresh)), 401
                    )
                    check(
                        await api.get(
                            f"/api/v1/enterprises/{tenant_id}/members",
                            headers=bearer(fresh),
                        ),
                        401,
                    )
                    check(
                        await api.get(
                            "/api/v1/desktop/bootstrap",
                            params={"tenant_id": str(uuid4())},
                            headers=bearer(fresh),
                        ),
                        401,
                    )
                    print(
                        "PASS upstream disabled account + desktop credential cannot administer"
                    )
                    print("LIVE VERIFIED Keycloak " + version)
        finally:
            for server in (callback, callback_b):
                server.shutdown()
                server.server_close()
            await engine.dispose()
            if made_schema:
                async with owner.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await owner.dispose()
            if made_realm:
                # Delete only the exact random realm successfully created by this invocation.
                response = await admin.delete(
                    origin + "/admin/realms/" + realm, headers=headers
                )
                assert response.status_code == 204, (
                    "Failed to remove isolated test realm"
                )
            print("Isolated test resources cleaned; existing realm/data unchanged.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:  # noqa: BLE001 - redact upstream URLs and credentials at CLI boundary
        print("FAILED stage=" + stage + " type=" + type(error).__name__)
        if isinstance(error, AssertionError):
            print(str(error))
        raise SystemExit(1) from None
