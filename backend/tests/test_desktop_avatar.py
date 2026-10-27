"""Avatar persistence and private desktop delivery use isolated database sessions."""

from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select
from test_desktop import bearer, login, native_client
from test_identity_access import env as identity_env

from app.modules.desktop.oidc import NativeIdentity
from app.modules.users.models import User

env = identity_env
pytestmark = pytest.mark.asyncio


async def test_saved_avatar_reaches_desktop_and_tracks_replacement_and_removal(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    one, other = await env.client(), await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, one)
        other_tokens, _ = await login(env, monkeypatch, api, other)
        previous = None
        for color in ("red", "blue"):
            output = BytesIO()
            Image.new("RGB", (100, 80), color).save(output, format="PNG")
            saved = await one.api.put(
                "/api/v1/account/avatar",
                content=output.getvalue(),
                headers={"content-type": "image/png"},
            )
            assert saved.status_code == 200
            me = await api.get("/api/v1/desktop/me", headers=bearer(tokens))
            assert me.status_code == 200
            url = me.json()["user"]["avatar_url"]
            assert url.startswith("/api/v1/desktop/avatar?v=") and url != previous
            previous = url
            downloaded = await api.get(url, headers=bearer(tokens))
            assert downloaded.status_code == 200
            assert downloaded.headers["content-type"] == "image/webp"
            assert "no-store" in downloaded.headers["cache-control"]
            async with env.sessions() as db:
                assert (
                    await db.scalar(select(User.avatar_data).where(User.id == one.user.id))
                    == downloaded.content
                )
            assert (await api.get(url)).status_code == 401
            assert (await api.get(url, headers=bearer(other_tokens))).status_code == 404
        assert (await one.api.delete("/api/v1/account/avatar")).status_code == 200
        me = await api.get("/api/v1/desktop/me", headers=bearer(tokens))
        assert me.json()["user"]["avatar_url"] is None
        assert (await api.get(previous, headers=bearer(tokens))).status_code == 404


async def test_member_avatar_urls_are_scoped_to_authorized_member_details(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    output = BytesIO()
    Image.new("RGB", (32, 32), "green").save(output, format="PNG")
    assert (
        await member.api.put(
            "/api/v1/account/avatar",
            content=output.getvalue(),
            headers={"content-type": "image/png"},
        )
    ).status_code == 200
    path = f"/api/v1/enterprises/{admin.tenant.id}/members/{member.member.id}"
    details = await admin.api.get(path)
    assert details.status_code == 200
    avatar = details.json()["avatar_url"]
    assert avatar.startswith(path + "/avatar?v=")
    response = await admin.api.get(avatar)
    assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
    assert "no-store" in response.headers["cache-control"]
    assert (await member.api.get(avatar)).status_code == 403
    assert (await outsider.api.get(avatar)).status_code == 403
    matches = (await admin.api.get("/api/v1/quota/matches")).json()["items"]
    assert (
        next(item for item in matches if item["member_id"] == str(member.member.id))["avatar_url"]
        == avatar
    )
