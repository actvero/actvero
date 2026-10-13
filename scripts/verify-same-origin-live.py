"""Verify real OIDC/Web/native PKCE on an empty, disposable same-origin deployment.

Refuses an initialized installation unless its owned test credentials exist.
No existing application user credentials are read.
"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.modules.desktop.service import pkce  # noqa: E402


async def main():
    origin = "http://127.0.0.1:56194"
    issuer = origin + "/identity/realms/actvero"
    async with (
        httpx.AsyncClient(base_url=origin, timeout=30, trust_env=False) as web,
        httpx.AsyncClient(base_url=origin, timeout=30, trust_env=False) as api,
    ):
        initial = (await web.get("/api/v1/auth/session")).json()
        state_file = root / ".local/same-origin-rehearsal/login.json"
        initialized = initial["setup_complete"] or initial["setup_account_created"]
        assert not initialized or state_file.exists(), (
            "Refusing an unowned initialized installation"
        )
        web.headers.update({"origin": origin, "x-csrf-token": initial["csrf"]})
        if state_file.exists():
            owned = json.loads(state_file.read_text())
            assert owned["origin"] == origin and owned["username"].startswith("isolated-edge-")
            password, username = owned["password"], owned["username"]
        else:
            password = secrets.token_urlsafe(32)
            username = "isolated-edge-" + uuid4().hex + "@example.com"
            fd = os.open(state_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump({"origin": origin, "username": username, "password": password}, handle)
        if not initialized:
            r = await web.post(
                "/api/v1/setup/register",
                json={
                    "organization_name": "Isolated edge verification",
                    "name": "Test",
                    "email": username,
                    "password": password,
                },
            )
            assert r.status_code == 200, (r.status_code, r.json().get("error", {}).get("message"))
        browser = await asyncio.create_subprocess_exec(
            "node",
            str(root / "scripts/verify-same-origin-browser.mjs"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def authorize(url, cookies=None):
            assert urlsplit(url).netloc == urlsplit(origin).netloc
            browser.stdin.write(
                (
                    json.dumps(
                        {
                            "url": url,
                            "username": username,
                            "password": password,
                            "cookies": cookies or [],
                        }
                    )
                    + "\n"
                ).encode()
            )
            await browser.stdin.drain()
            data = json.loads(await asyncio.wait_for(browser.stdout.readline(), timeout=45))
            assert "error" not in data, data
            return data

        try:
            metadata = await api.get("/api/v1/desktop/metadata")
            assert metadata.status_code == 200 and metadata.json()["contract_version"] == 1
            assert metadata.json()["capabilities"]["dependency_contract"] == 3
            assert metadata.json()["capabilities"]["same_origin_identity"] == 1
            assert "reauthentication_days" in metadata.json()
            assert (
                await api.get(
                    "/api/v1/desktop/metadata", headers={"If-None-Match": metadata.headers["ETag"]}
                )
            ).status_code == 304
            discovery = (await api.get(issuer + "/.well-known/openid-configuration")).json()
            assert discovery["issuer"] == issuer
            for key in (
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
                "end_session_endpoint",
            ):
                assert discovery[key].startswith(issuer + "/")
            response = await web.get("/api/v1/auth/login")
            assert response.status_code == 307
            proof = await authorize(
                response.headers["location"],
                [
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "url": origin,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                    for cookie in web.cookies.jar
                ],
            )
            assert urlsplit(proof["callback"]).path == "/api/v1/auth/callback"
            for cookie in proof["cookies"]:
                web.cookies.set(
                    cookie["name"], cookie["value"], domain="127.0.0.1", path=cookie["path"]
                )
            context = (await web.get("/api/v1/auth/session")).json()
            assert context["authenticated"] and context["organization"]
            print("PASS real same-origin Web code exchange, theme and retained user/organization")
            verifier = secrets.token_urlsafe(32)
            started = await api.post(
                "/api/v1/desktop/login/start",
                json={
                    "contract_version": 1,
                    "redirect_uri": "http://127.0.0.1:49161/actvero/callback",
                    "code_challenge": pkce(verifier),
                    "device_name": "Isolated",
                    "os": "macOS",
                    "app_version": "test",
                },
            )
            assert started.status_code == 200
            data = started.json()
            proof = await authorize(data["authorization_url"])
            assert not proof["prompted"]
            query = parse_qs(urlsplit(proof["callback"]).query)
            assert query["iss"][0] == issuer and query["state"][0] == data["state"]
            tokens = await api.post(
                "/api/v1/desktop/login/exchange",
                json={
                    "attempt_id": data["attempt_id"],
                    "code": query["code"][0],
                    "issuer": issuer,
                    "state": query["state"][0],
                    "code_verifier": verifier,
                },
            )
            assert tokens.status_code == 200
            me = (
                await api.get(
                    "/api/v1/desktop/me",
                    headers={"Authorization": "Bearer " + tokens.json()["access_token"]},
                )
            ).json()
            assert me["user"]["id"] == context["user"]["id"]
            assert me["account_url"] == origin + "/account"
            assert (await api.get(issuer + "/account/")).status_code == 200
            print("PASS real native S256/shared SSO, exact same user, account entry")
            assert (await api.get("/identity/admin/")).status_code == 404
            assert (await api.get("/identity/health/ready")).status_code == 404
            assert (
                await api.get("/api/v1/ready", headers={"Host": "evil.example"})
            ).status_code == 421
            injected = await api.get(
                issuer + "/.well-known/openid-configuration",
                headers={
                    "X-Forwarded-Host": "evil.example",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Port": "443",
                },
            )
            assert injected.json()["issuer"] == issuer
            print("PASS private admin/management paths, Host and forwarded-header injection")
        finally:
            browser.stdin.close()
            try:
                await asyncio.wait_for(browser.wait(), timeout=15)
            except TimeoutError:
                browser.kill()
                await browser.wait()


if __name__ == "__main__":
    asyncio.run(main())
