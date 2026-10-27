"""Ordinary installers may enter the public catalog without changing update feeds."""

import pytest
from test_client_distribution import BASE, add, files, plan, release, verified
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.client_distribution import worker

pytestmark = pytest.mark.asyncio


async def ordinary(api, version="0.1.15"):
    row = await release(api, version)
    response = await api.put(
        BASE + "/releases/" + row["id"],
        json={
            "expected_revision": row["revision"],
            "version": version,
            "updates_enabled": False,
            "minimum_os": {},
            "source_commit": "a" * 40,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "target,role,platform,architecture",
    [("mac-arm64", "installer", "macos", "arm64"), ("win-x64", "payload", "windows", "x64")],
)
async def test_installer_only_publication_and_revision_guard(
    env,  # noqa: F811
    monkeypatch,
    target,
    role,
    platform,
    architecture,
):
    env.provider.settings.app_url = "https://platform.example.com"
    actor = await operator(env)
    row = await ordinary(actor.api)
    missing = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/plan",
        json={"expected_revision": row["revision"], "targets": [target]},
    )
    assert missing.status_code == 422
    payload, _ = files(monkeypatch)
    await add(actor.api, row, role, payload, target)
    assert await worker.run_once(env.app)
    row = (await actor.api.get(BASE + "/releases/" + row["id"])).json()
    prepared = await plan(actor.api, row, [target])
    endpoint = BASE + "/releases/" + row["id"] + "/publish"
    published = await actor.api.post(endpoint, json={"plan_id": prepared["id"]})
    assert published.status_code == 200, published.text
    assert published.json()["updates_enabled"] is False
    repeated = await actor.api.post(endpoint, json={"plan_id": prepared["id"]})
    assert repeated.json()["revision"] == published.json()["revision"]
    public = (await actor.api.get("/api/v1/platform/downloads/public")).json()
    assert public["recommendations"][0]["release_id"] == row["id"]
    asset = public["items"][0]["assets"][0]
    assert asset["platform"] == platform and asset["architecture"] == architecture
    assert asset["minimum_os"] == "" and asset["sha256"]
    entry = await actor.api.get(
        "/api/v1/platform/downloads/" + row["id"] + "/file",
        params={"platform": platform, "architecture": architecture},
    )
    assert entry.status_code == 307 and entry.headers["location"] == asset["url"]
    binary = await actor.api.get(asset["url"])
    assert binary.status_code == 307 and binary.headers["location"].startswith("https://files.")
    assert (await actor.api.get(BASE + "/heads")).json()["items"] == []
    feed = "latest-mac.yml" if platform == "macos" else "latest.yml"
    assert (
        await actor.api.get(f"/api/v1/client-updates/actvero/{target}/{feed}")
    ).status_code == 404
    edit = await actor.api.put(
        BASE + "/releases/" + row["id"],
        json={"expected_revision": published.json()["revision"], "version": row["version"]},
    )
    assert edit.status_code == 409


async def test_download_only_does_not_change_existing_feed_or_its_version_floor(
    env,  # noqa: F811
    monkeypatch,
):
    env.provider.settings.app_url = "https://platform.example.com"
    actor = await operator(env)
    row = await verified(env, monkeypatch, actor)
    prepared = await plan(actor.api, row)
    published = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/publish", json={"plan_id": prepared["id"]}
    )
    feed = "/api/v1/client-updates/actvero/win-x64/latest.yml"
    before = (await actor.api.get(feed)).content
    heads = (await actor.api.get(BASE + "/heads")).json()
    ordinary_row = await ordinary(actor.api, "9.0.0")
    data, _ = files(monkeypatch)
    await add(actor.api, ordinary_row, "payload", data)
    assert await worker.run_once(env.app)
    ordinary_row = (await actor.api.get(BASE + "/releases/" + ordinary_row["id"])).json()
    prepared = await plan(actor.api, ordinary_row)
    result = await actor.api.post(
        BASE + "/releases/" + ordinary_row["id"] + "/publish",
        json={"plan_id": prepared["id"]},
    )
    assert result.status_code == 200, result.text
    assert (await actor.api.get(feed)).content == before
    assert (await actor.api.get(BASE + "/heads")).json() == heads
    assert (
        await actor.api.post(
            BASE + "/releases/" + row["id"] + "/withdraw",
            json={"expected_revision": published.json()["revision"]},
        )
    ).status_code == 200
    successor = await verified(env, monkeypatch, actor, "2.0.0")
    await plan(actor.api, successor)


async def test_switching_to_updates_invalidates_download_plan_and_requires_update_files(
    env,  # noqa: F811
    monkeypatch,
):
    env.provider.settings.app_url = "https://platform.example.com"
    actor = await operator(env)
    row = await ordinary(actor.api)
    data, _ = files(monkeypatch)
    await add(actor.api, row, "installer", data, "mac-arm64")
    assert await worker.run_once(env.app)
    row = (await actor.api.get(BASE + "/releases/" + row["id"])).json()
    prepared = await plan(actor.api, row, ["mac-arm64"])
    changed = await actor.api.put(
        BASE + "/releases/" + row["id"],
        json={
            "expected_revision": row["revision"],
            "version": row["version"],
            "updates_enabled": True,
            "minimum_os": {"mac-arm64": "macOS 13"},
        },
    )
    assert changed.status_code == 200
    assert (
        await actor.api.post(
            BASE + "/releases/" + row["id"] + "/publish", json={"plan_id": prepared["id"]}
        )
    ).status_code == 409
    incomplete = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/plan",
        json={"expected_revision": changed.json()["revision"], "targets": ["mac-arm64"]},
    )
    assert incomplete.status_code == 422
    assert (await actor.api.get(BASE + "/heads")).json()["items"] == []
