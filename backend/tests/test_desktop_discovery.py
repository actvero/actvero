"""Anonymous discovery namespaces, complete cache invalidation and safe branding."""

import io
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.tenants.models import Installation, Tenant

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/desktop/metadata"


async def anonymous(env):  # noqa: F811
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://127.0.0.1:5194"
    )


async def test_discovery_anonymous_stable_namespace_and_cache(env):  # noqa: F811
    async with await anonymous(env) as client:
        first = await client.get(PATH)
        assert first.status_code == 200
        value = first.json()
        assert value["contract_version"] == 1
        assert "reauthentication_days" in value
        UUID(value["instance_id"])
        UUID(value["branding"]["revision"])
        assert value["branding"]["name"] == "Actvero"
        assert value["branding"]["assets"] == {}
        assert value["branding"]["favicon_url"].endswith("/favicon.ico")
        assert "same_origin_identity" not in value["capabilities"]
        assert "smtp" not in first.text and "secret" not in first.text
        assert "set-cookie" not in first.headers
        same = await client.get(PATH)
        assert same.json() == value and same.headers["etag"] == first.headers["etag"]
        for etag in (
            first.headers["etag"],
            "W/" + first.headers["etag"],
            '"other", ' + first.headers["etag"],
        ):
            cached = await client.get(PATH, headers={"if-none-match": etag})
            assert cached.status_code == 304 and not cached.content
        # A setting change invalidates the full discovery document, not just the brand.
        env.provider.settings.desktop_recovery_days = 31
        assert (
            await client.get(PATH, headers={"if-none-match": first.headers["etag"]})
        ).status_code == 200
        env.provider.settings.oidc_issuer = "http://127.0.0.1:5194/identity/realms/actvero"
        assert (await client.get(PATH)).json()["capabilities"]["same_origin_identity"] == 1
        # Display branding is independent from organization selection/names.
        async with env.sessions() as db:
            db.add(Tenant(name="organization is not the deployment brand"))
            await db.commit()
        assert (await client.get(PATH)).json()["branding"]["name"] == "Actvero"


async def test_brand_changes_invalidate_and_do_not_change_instance_or_leak_remote_logo(env):  # noqa: F811
    actor = await operator(env)
    async with await anonymous(env) as client:
        first = await client.get(PATH)
        instance = first.json()["instance_id"]
        await actor.api.put("/api/v1/platform/settings", json={"platform_name": "Company"})
        second = await client.get(PATH, headers={"if-none-match": first.headers["etag"]})
        assert second.status_code == 200
        assert second.json()["branding"]["name"] == "Company"
        assert second.json()["branding"]["revision"] != first.json()["branding"]["revision"]
        await actor.api.put("/api/v1/platform/settings", json={"platform_name": "Company"})
        assert (await client.get(PATH)).headers["etag"] == second.headers["etag"]
        async with env.sessions() as db:
            install = await db.get(Installation, 1)
            install.platform_logo_url = "https://external.example.com/untrusted.svg"
            await db.commit()
        assert "logo_url" not in (await client.get(PATH)).json()["branding"]
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "blue").save(image, format="PNG")
        await actor.api.put(
            "/api/v1/platform/settings/logo",
            content=image.getvalue(),
            headers={"content-type": "image/png"},
        )
        third = (await client.get(PATH)).json()
        logo = third["branding"]["logo_url"]
        assert logo.startswith("http://127.0.0.1:5194/api/v1/platform/logo?v=")
        assert third["branding"]["revision"] != second.json()["branding"]["revision"]
        assert (await client.get(logo)).headers["content-type"] == "image/webp"
        assert (await client.get("/api/v1/platform/logo?v=" + str(uuid4()))).status_code == 404
        await actor.api.delete("/api/v1/platform/settings/logo")
        fourth = (await client.get(PATH)).json()
        assert "logo_url" not in fourth["branding"]
        assert fourth["branding"]["revision"] != third["branding"]["revision"]
        assert fourth["instance_id"] == third["instance_id"] == instance
        assert (
            await client.get(logo)
        ).status_code == 200  # Published asset references remain valid.


async def test_missing_installation_does_not_issue_ephemeral_namespace(env):  # noqa: F811
    async with env.sessions() as db:
        await db.delete(await db.get(Installation, 1))
        await db.commit()
    async with await anonymous(env) as client:
        result = await client.get(PATH)
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "installation_unavailable"
