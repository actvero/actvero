"""Brand publication, immutable references and identity boundary regression."""

import asyncio
import base64
import io
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.platform.brand_sync import sync_identity
from app.modules.tenants.models import BrandAsset

pytestmark = pytest.mark.asyncio


def png(size=(600, 150), color=(30, 40, 50, 120)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return {"content": base64.b64encode(output.getvalue()).decode()}


async def current(actor):
    return (await actor.api.get("/api/v1/platform/branding/settings")).json()


async def publish(actor, **changes):
    old = await current(actor)
    return await actor.api.put(
        "/api/v1/platform/branding/settings",
        json={
            "revision": old["revision"],
            "platform_name": old["name"],
            "assets": {},
            **changes,
        },
    )


async def test_atomic_publication_preserves_shape_alpha_and_immutable_urls(env):  # noqa: F811
    actor = await operator(env)
    response = await publish(
        actor,
        platform_name="Example Platform",
        assets={"wordmark_light": png(), "mark_light": png((512, 512))},
    )
    assert response.status_code == 200
    value = response.json()
    assert value["identity_status"] == "pending"
    image = await actor.api.get(value["assets"]["wordmark_light"])
    with Image.open(io.BytesIO(image.content)) as opened:
        assert opened.size == (600, 150)
        assert opened.getpixel((0, 0)) == (30, 40, 50, 120)
    old_url = value["assets"]["wordmark_light"]
    assert (
        await publish(actor, assets={"wordmark_light": png(color=(0, 0, 0, 255))})
    ).status_code == 200
    assert (await actor.api.get(old_url)).content == image.content
    not_modified = await actor.api.get(old_url, headers={"if-none-match": image.headers["etag"]})
    assert not_modified.status_code == 304
    favicon = await actor.api.get(value["favicon_url"])
    with Image.open(io.BytesIO(favicon.content)) as opened:
        assert opened.format == "ICO"
        assert (16, 16) in opened.ico.sizes()
    apple = await actor.api.get(value["apple_icon_url"])
    assert Image.open(io.BytesIO(apple.content)).size == (180, 180)
    assert (await actor.api.get(old_url.replace("image.png", "huge.png"))).status_code == 404
    session = (await actor.api.get("/api/v1/auth/session")).json()
    assert session["platform_name"] == "Example Platform"
    assert (await actor.api.get(session["platform_logo_url"])).headers[
        "content-type"
    ] == "image/webp"
    actor.api.cookies.clear()
    public = await actor.api.get("/api/v1/platform/branding")
    assert public.status_code == 200 and "set-cookie" not in public.headers
    assert set(public.json()) == {
        "name",
        "revision",
        "assets",
        "asset_ids",
        "favicon_url",
        "apple_icon_url",
    }


async def test_conflict_invalid_image_and_foreign_assets_do_not_partially_publish(env):  # noqa: F811
    actor = await operator(env)
    before = await current(actor)
    bad = await publish(
        actor,
        platform_name="Must not persist",
        assets={
            "mark_light": png(),
            "wordmark_light": {"content": base64.b64encode(b"<svg/>").decode()},
        },
    )
    assert bad.status_code == 422
    assert (await current(actor))["name"] == before["name"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BrandAsset)) == 0
    assert (await publish(actor, assets={"mark_light": str(uuid4())})).status_code == 409
    assert (await publish(actor, revision=str(uuid4()))).status_code == 409
    assert (
        await publish(actor, assets={"mark_light": {"content": "not base64"}})
    ).status_code == 422
    assert (await publish(actor, platform_name="\r\nInjected")).status_code == 422
    assert (await publish(actor, assets={"mark_dark": png()})).status_code == 422
    assert (await current(actor))["revision"] == before["revision"]


async def test_brand_write_requires_operator_and_csrf(env):  # noqa: F811
    actor = await operator(env)
    member = await env.client(role="member")
    assert (await member.api.get("/api/v1/platform/branding/settings")).status_code == 403
    assert (
        await actor.api.put(
            "/api/v1/platform/branding/settings",
            json={
                "platform_name": "A",
                "revision": (await current(actor))["revision"],
                "assets": {},
            },
            headers={"x-csrf-token": "bad"},
        )
    ).status_code == 403


async def test_reset_keeps_historical_asset_and_does_not_change_identity(env):  # noqa: F811
    actor = await operator(env)
    value = (await publish(actor, assets={"mark_light": png()})).json()
    await publish(
        actor,
        platform_name="Actvero",
        assets={
            k: None
            for k in ["mark_light", "mark_dark", "wordmark_light", "wordmark_dark", "favicon"]
        },
    )
    after = await current(actor)
    assert after["assets"] == {}
    assert (await actor.api.get(value["assets"]["mark_light"])).status_code == 200
    assert (await actor.api.get("/api/v1/auth/session")).json()["authenticated"]


async def test_identity_sync_preserves_security_settings_and_retries_unknown_outcome(env):  # noqa: F811
    actor = await operator(env)
    await publish(actor, platform_name="Brand <safe>", assets={"wordmark_light": png()})
    remote = {
        "attributes": {"unrelated": "keep"},
        "smtpServer": {"host": "smtp.example", "password": "secret"},
        "enabled": True,
    }
    env.provider.admin = AsyncMock(
        side_effect=[httpx.Response(200, json=remote), OSError("offline")]
    )
    with pytest.raises(OSError):
        await sync_identity(env.app.state.database, env.provider)
    assert (await current(actor))["identity_status"] == "pending"
    env.provider.admin = AsyncMock(
        side_effect=[httpx.Response(200, json=remote), httpx.Response(204)]
    )
    assert await sync_identity(env.app.state.database, env.provider)
    payload = env.provider.admin.await_args.kwargs["json"]
    assert payload["attributes"]["unrelated"] == "keep"
    assert payload["smtpServer"] == {**remote["smtpServer"], "fromDisplayName": "Brand <safe>"}
    assert payload["displayNameHtml"] == "Brand &lt;safe&gt;"
    assert set(payload) == {
        "attributes",
        "displayName",
        "displayNameHtml",
        "emailTheme",
        "smtpServer",
    }
    assert (await current(actor))["identity_status"] == "applied"
    assert not await sync_identity(env.app.state.database, env.provider)
    assert env.provider.admin.await_count == 2


async def test_spa_bootstrap_and_title_are_escaped_before_javascript(env, tmp_path):  # noqa: F811
    actor = await operator(env)
    name = "</script><script>alert(1)</script>"
    await publish(actor, platform_name=name)
    root = env.provider.settings.static_dir
    # App resolves its static root at construction; override the existing closure
    # using a new app against the same isolated database and identity provider.
    from app.main import create_app

    (tmp_path / "index.html").write_text(
        '<html><head><title>Actvero</title><link rel="icon" href="/favicon.ico">'
        "</head><body></body></html>"
    )
    settings = env.provider.settings.model_copy(update={"static_dir": tmp_path})
    app = create_app(settings)
    app.state.database = env.app.state.database
    app.state.identity_provider = env.provider
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=settings.app_url
    ) as client:
        html = await client.get("/login")
    assert html.status_code == 200
    assert "&lt;/script&gt;" in html.text
    assert "<script>alert(1)</script>" not in html.text
    assert "\\u003c/script\\u003e" in html.text
    assert html.headers["cache-control"] == "no-store"
    assert env.provider.settings.static_dir == root


async def test_concurrent_publication_has_one_winner_and_no_orphan_images(env):  # noqa: F811
    actor = await operator(env)
    before = await current(actor)
    replies = await asyncio.gather(
        *[
            actor.api.put(
                "/api/v1/platform/branding/settings",
                json={
                    "revision": before["revision"],
                    "platform_name": name,
                    "assets": {"mark_light": png()},
                },
            )
            for name in ("First", "Second")
        ]
    )
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BrandAsset)) == 1


async def test_chunked_upload_limit_and_animated_images_leave_brand_unchanged(env):  # noqa: F811
    actor = await operator(env)
    before = await current(actor)

    async def chunks():
        for _ in range(15):
            yield b" " * 1_000_000

    response = await actor.api.put(
        "/api/v1/platform/branding/settings",
        content=chunks(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    animation = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(
        animation,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (16, 16), "blue")],
    )
    invalid = await publish(
        actor, assets={"mark_light": {"content": base64.b64encode(animation.getvalue()).decode()}}
    )
    assert invalid.status_code == 422
    assert (await current(actor))["revision"] == before["revision"]


async def test_invitation_email_uses_uncropped_wordmark_and_immutable_image(env):  # noqa: F811
    actor = await operator(env)
    saved = (
        await publish(actor, platform_name="Example Platform", assets={"wordmark_light": png()})
    ).json()
    preview = (await actor.api.get("/api/v1/platform/mail/preview")).json()
    assert saved["assets"]["wordmark_light"] in preview["html"]
    assert 'width="32"' not in preview["html"]
    stable = await actor.api.get("/api/v1/platform/branding/email-logo.png")
    assert Image.open(io.BytesIO(stable.content)).size == (600, 150)
