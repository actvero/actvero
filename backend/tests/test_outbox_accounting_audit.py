"""A delayed final journal entry must survive recovery and never overwrite manual billing."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from llm_billing_helpers import billing
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, configured, credentials, entries, payload, upstream
from test_mcp import listening

from app.modules.llm import settlement

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("manual", [False, True])
async def test_final_checkpoint_racing_expired_replay_is_retained_and_applied(
    env, monkeypatch, manual
):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        outbox = env.app.state.llm_outbox
        flush = outbox.flush_one
        monkeypatch.setattr(outbox, "flush_one", AsyncMock(side_effect=ConnectionError()))
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert response.status_code == 200
        path = next(outbox.directory.glob("*.json"))
        final = json.loads(path.read_text())
        expired = deepcopy(final)
        expired.update(complete=False, expires_at=0, status="pending", delivered=False, usage={})
        expired["attempts"][-1].update(
            status="pending", usage_evidence=[], upstream_terminal=False, sent=None, uncertain=True
        )
        outbox.write(expired)
        complete = settlement.complete

        async def arriving_final(*args, **kwargs):
            result = await complete(*args, **kwargs)
            # Final evidence reaches disk after the worker read the expired
            # intent, but before it commits/deletes the processed journal file.
            await outbox.checkpoint(final)
            return result

        monkeypatch.setattr(settlement, "complete", arriving_final)
        await flush(path)
        assert path.exists(), "an old replay must not delete a newer final checkpoint"
        monkeypatch.setattr(settlement, "complete", complete)
        review = (await entries(admin))[0]
        assert review["status"] == "review"
        if manual:
            response = await admin.api.post(
                "/api/v1/llm/settlements/" + review["id"] + "/reconcile",
                json={
                    "version": review["version"],
                    "action": "release",
                    "reason": "Verified externally in this test",
                },
            )
            assert response.status_code == 200, response.text
        await flush(path)
        after = (await entries(admin))[0]
        assert after["status"] == ("released" if manual else "settled")
        assert after["points"] == ("0" if manual else "0.0244")
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert log["status"] == "succeeded" and log["usage"]["output_tokens"] == 10
        assert len(state["calls"]) == 1
        version = after["version"]
        outbox.write(final)
        await flush(path)
        assert (await entries(admin))[0]["version"] == version
        assert not path.exists()
