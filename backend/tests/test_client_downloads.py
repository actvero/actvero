import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.auth.models import WebSession
from app.modules.platform.download_models import ClientReleaseEvent
from app.modules.tenants.models import PlatformOperator

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/platform/downloads"


def asset(**changes):
    return (
        dict(
            platform="windows",
            architecture="x64",
            url="https://downloads.example.com/actvero.exe",
            filename="actvero.exe",
            minimum_os="Windows 11",
            size_bytes=123456,
            sha256="a" * 64,
        )
        | changes
    )


def draft(**changes):
    return (
        dict(
            expected_revision=0,
            version="1.2.0",
            release_date="2026-10-06",
            notes="Release notes",
            assets=[asset()],
        )
        | changes
    )


async def create(actor, **changes):
    release_id = str(uuid4())
    response = await actor.api.put(BASE + "/" + release_id, json=draft(**changes))
    assert response.status_code == 200, response.text
    return response.json()


async def publish(actor, row, recommend=True):
    response = await actor.api.post(
        BASE + "/" + row["id"] + "/publish",
        json={"expected_revision": row["revision"], "recommend": recommend},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_public_catalog_is_anonymous_offline_identity_and_has_no_private_metadata(env):  # noqa: F811
    actor = await operator(env)
    row = await create(actor)
    async with env.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(WebSession))
    env.provider.inspect.reset_mock()
    env.provider.inspect.side_effect = RuntimeError("identity offline")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url=env.provider.settings.app_url
    ) as public:
        response = await public.get(BASE + "/public")
        assert response.json() == {"items": [], "recommendations": []}
        assert response.headers["Cache-Control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert row["id"] not in response.text
    env.provider.inspect.assert_not_awaited()
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WebSession)) == before


async def test_platform_only_csrf_community_and_revocation(env):  # noqa: F811
    admin = await env.client()
    assert (await admin.api.get(BASE)).status_code == 404
    actor = await operator(env)
    member = await env.client(role="member", tenant=admin.tenant)
    for other in (admin, member):
        assert (await other.api.get(BASE)).status_code == 403
        assert (await other.api.put(BASE + "/" + str(uuid4()), json=draft())).status_code == 403
    for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://foreign.example"}):
        assert (
            await actor.api.put(BASE + "/" + str(uuid4()), json=draft(), headers=headers)
        ).status_code == 403
    row = await create(actor)
    async with env.sessions() as db:
        (await db.get(PlatformOperator, actor.user.id)).status = "paused"
        await db.commit()
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/" + row["id"], None),
        ("POST", "/" + row["id"] + "/publish", {"expected_revision": 1, "recommend": True}),
        ("DELETE", "/" + row["id"], {"expected_revision": 1}),
    ):
        assert (await actor.api.request(method, BASE + suffix, json=body)).status_code == 403
    assert (await actor.api.get(BASE + "/public")).json()["items"] == []


async def test_publish_recommend_redirect_and_withdraw_stale_link(env):  # noqa: F811
    actor = await operator(env)
    row = await create(
        actor,
        assets=[
            asset(),
            asset(
                platform="macos",
                architecture="arm64",
                filename="actvero.dmg",
                minimum_os="macOS 14",
                url="https://downloads.example.com/mac.dmg",
            ),
        ],
    )
    file_url = BASE + "/" + row["id"] + "/file?platform=windows&architecture=x64"
    assert (await actor.api.get(file_url)).status_code == 404
    row = await publish(actor, row)
    response = await actor.api.get(BASE + "/public")
    assert len(response.json()["recommendations"]) == 2
    assert set(response.json()["items"][0]) == {"id", "version", "release_date", "notes", "assets"}
    response = await actor.api.get(file_url)
    assert response.status_code == 307
    assert response.headers["location"] == asset()["url"]
    assert response.headers["Cache-Control"] == "no-store"
    response = await actor.api.post(
        BASE + "/" + row["id"] + "/withdraw", json={"expected_revision": row["revision"]}
    )
    assert response.status_code == 200
    assert (await actor.api.get(BASE + "/public")).json() == {"items": [], "recommendations": []}
    assert (await actor.api.get(file_url)).status_code == 404
    events = (await actor.api.get(BASE + "/" + row["id"] + "/events")).json()
    assert [e["action"] for e in events] == ["withdrawn", "published", "created"]
    assert all("url" not in e for e in events)


async def test_two_operators_concurrent_save_only_one_revision_commits(env):  # noqa: F811
    first, second = await operator(env), await operator(env)
    row = await create(first)
    payload = draft(expected_revision=1)
    responses = await asyncio.gather(
        first.api.put(BASE + "/" + row["id"], json=payload | {"notes": "first"}),
        second.api.put(BASE + "/" + row["id"], json=payload | {"notes": "second"}),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    saved = (await first.api.get(BASE + "/" + row["id"])).json()
    assert saved["revision"] == 2 and saved["notes"] in ("first", "second")
    assert len((await first.api.get(BASE + "/" + row["id"] + "/events")).json()) == 2


async def test_publication_and_recommendation_require_current_revision_and_real_target(env):  # noqa: F811
    actor = await operator(env)
    row = await create(actor)
    row = await publish(actor, row, recommend=False)
    assert (await actor.api.get(BASE + "/public")).json()["recommendations"] == []
    endpoint = BASE + "/" + row["id"] + "/recommend"
    assert (
        await actor.api.post(
            endpoint, json={"expected_revision": 1, "platform": "windows", "architecture": "x64"}
        )
    ).status_code == 409
    assert (
        await actor.api.post(
            endpoint, json={"expected_revision": 2, "platform": "macos", "architecture": "arm64"}
        )
    ).status_code == 409
    response = await actor.api.post(
        endpoint, json={"expected_revision": 2, "platform": "windows", "architecture": "x64"}
    )
    assert response.status_code == 200
    assert len((await actor.api.get(BASE + "/public")).json()["recommendations"]) == 1


async def test_new_version_recommendation_does_not_change_other_architectures_or_fall_back(env):  # noqa: F811
    actor = await operator(env)
    first = await publish(actor, await create(actor))
    second = await publish(
        actor,
        await create(
            actor,
            version="1.3.0",
            assets=[
                asset(
                    platform="macos",
                    architecture="universal",
                    filename="universal.dmg",
                    minimum_os="macOS 14",
                    url="https://downloads.example.com/all.dmg",
                )
            ],
        ),
    )
    recs = (await actor.api.get(BASE + "/public")).json()["recommendations"]
    assert {r["release_id"] for r in recs} == {first["id"], second["id"]}
    newer = await publish(actor, await create(actor, version="1.4.0"))
    assert len((await actor.api.get(BASE + "/public")).json()["items"]) == 3
    await actor.api.post(
        BASE + "/" + newer["id"] + "/withdraw", json={"expected_revision": newer["revision"]}
    )
    recs = (await actor.api.get(BASE + "/public")).json()["recommendations"]
    assert [r["release_id"] for r in recs] == [second["id"]]


async def test_published_installer_is_immutable_notes_editable_and_withdraw_can_republish(env):  # noqa: F811
    actor = await operator(env)
    row = await publish(actor, await create(actor))
    path = BASE + "/" + row["id"]
    for changes in (
        {"version": "evil"},
        {"release_date": "2026-10-07"},
        {"assets": [asset(url="https://downloads.example.com/replaced.exe")]},
    ):
        assert (
            await actor.api.put(path, json=draft(expected_revision=2, **changes))
        ).status_code == 409
    response = await actor.api.put(path, json=draft(expected_revision=2, notes="Updated notes"))
    assert response.status_code == 200 and response.json()["assets"] == row["assets"]
    row = (await actor.api.post(path + "/withdraw", json={"expected_revision": 3})).json()
    row = await publish(actor, row)
    assert row["revision"] == 5 and row["status"] == "published"


async def test_response_loss_uuid_recovery_and_unique_version(env):  # noqa: F811
    actor = await operator(env)
    release_id = str(uuid4())
    path = BASE + "/" + release_id
    assert (await actor.api.put(path, json=draft())).status_code == 200
    assert (await actor.api.put(path, json=draft())).status_code == 409
    assert (await actor.api.get(path)).json()["revision"] == 1
    assert (await actor.api.put(BASE + "/" + str(uuid4()), json=draft())).status_code == 409
    assert (await actor.api.get(BASE)).json()["total"] == 1


async def test_draft_delete_retains_audit_published_delete_rejected_and_list_filter(env):  # noqa: F811
    actor = await operator(env)
    row = await create(actor)
    other = await publish(actor, await create(actor, version="1.3.0"))
    assert (await actor.api.get(BASE + "?status=draft&q=1.2")).json()["total"] == 1
    assert (
        await actor.api.request("DELETE", BASE + "/" + row["id"], json={"expected_revision": 1})
    ).status_code == 200
    assert (await actor.api.get(BASE + "/" + row["id"])).status_code == 404
    async with env.sessions() as db:
        events = (
            await db.scalars(
                select(ClientReleaseEvent).where(ClientReleaseEvent.release_id == row["id"])
            )
        ).all()
        assert {e.action for e in events} == {"created", "deleted"}
    assert (
        await actor.api.request(
            "DELETE", BASE + "/" + other["id"], json={"expected_revision": other["revision"]}
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.com/a.exe",
        "https://u:p@example.com/a.exe",
        "https://example.com/a.exe#secret",
        "https://example.com/a b.exe",
        "https://example.com:invalid/a.exe",
        "https://example.com/\\evil",
        "https://[invalid/a.exe",
    ],
)
async def test_download_url_input_validation(env, url):  # noqa: F811
    actor = await operator(env)
    response = await actor.api.put(BASE + "/" + str(uuid4()), json=draft(assets=[asset(url=url)]))
    assert response.status_code == 422
    assert (await actor.api.get(BASE)).json()["total"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"architecture": "universal"},
        {"filename": "../bad.exe"},
        {"size_bytes": 0},
        {"size_bytes": "123"},
        {"sha256": "wrong"},
    ],
)
async def test_asset_constraints(env, changes):  # noqa: F811
    actor = await operator(env)
    assert (
        await actor.api.put(BASE + "/" + str(uuid4()), json=draft(assets=[asset(**changes)]))
    ).status_code == 422


async def test_incomplete_draft_can_save_but_not_publish_and_missing_values_not_zero(env):  # noqa: F811
    actor = await operator(env)
    row = await create(
        actor, assets=[asset(url="", filename="", minimum_os="", size_bytes=None, sha256="")]
    )
    assert row["assets"][0]["size_bytes"] is None
    assert (
        await actor.api.post(
            BASE + "/" + row["id"] + "/publish", json={"expected_revision": 1, "recommend": True}
        )
    ).status_code == 422
    assert (await actor.api.get(BASE + "/" + row["id"])).json()["revision"] == 1
    assert (await actor.api.get(BASE + "/public")).json()["items"] == []
    assert (
        await actor.api.put(
            BASE + "/" + str(uuid4()), json=draft(version="duplicates", assets=[asset(), asset()])
        )
    ).status_code == 422
