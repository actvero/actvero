"""G4-01: real LiteLLM selector, fake deployment metadata, no sockets."""

import asyncio
import random
import socket
from collections import Counter
from uuid import UUID

import pytest

from app.modules.llm.catalog_schemas import ModelBinding
from app.modules.llm.routing_selector import RouterSelectorPrototype, deployment_id


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("selector prototype must not use sockets")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture(scope="module")
def selector():
    # A single SDK Router avoids multiplying global callbacks. SDK 1.102.1
    # has no safe Router.close(); its lifetime is the test process.
    prototype = RouterSelectorPrototype()
    prototype.startup()
    return prototype


def binding(number: int, *, priority: int = 10, weight: int = 1) -> ModelBinding:
    return ModelBinding(
        channel_id=UUID(int=number),
        upstream_id=f"model-{number}",
        priority=priority,
        weight=weight,
    )


@pytest.mark.asyncio
async def test_requires_explicit_startup_and_empty_candidates(selector):
    with pytest.raises(RuntimeError, match="startup"):
        await RouterSelectorPrototype().select([])
    assert await selector.select([]) is None


@pytest.mark.asyncio
async def test_priority_and_same_tier_weight(selector):
    high_one = binding(1, weight=1)
    high_three = binding(2, weight=3)
    low = binding(3, priority=0, weight=10000)
    counts = Counter()
    saved_state = random.getstate()
    random.seed(404)
    try:
        for _ in range(600):
            selected = await selector.select([high_one, high_three, low])
            counts[selected.channel_id] += 1
    finally:
        random.setstate(saved_state)
    assert counts[low.channel_id] == 0
    assert 100 < counts[high_one.channel_id] < 210
    assert 390 < counts[high_three.channel_id] < 500


@pytest.mark.asyncio
async def test_exact_candidate_set_tried_exclusion_and_bypass(selector, monkeypatch):
    a, b = binding(11), binding(12, priority=0)
    assert await selector.select([a, b]) == a
    assert await selector.select([b]) == b  # Platform removed an attempted binding.
    assert await selector.select([a, b], specific=(b.channel_id, b.upstream_id)) == b
    assert await selector.select([a], specific=(b.channel_id, b.upstream_id)) is None

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("fixed/diagnostic target must bypass SDK selection")

    monkeypatch.setattr(selector._router, "async_get_available_deployment", forbidden)
    assert await selector.select([a], specific=(a.channel_id, a.upstream_id)) == a


@pytest.mark.asyncio
async def test_stable_id_duplicate_rejection_and_config_change(selector):
    a, b = binding(21), binding(22)
    assert deployment_id(a) == deployment_id(binding(21))
    persistent = a.model_copy(update={"binding_id": UUID(int=999)})
    assert deployment_id(persistent) == str(UUID(int=999))
    with pytest.raises(ValueError, match="duplicate"):
        await selector.select([a, a])
    await selector.select([a, b])
    rebuilds = selector.rebuilds
    await selector.select([b, a])
    assert selector.rebuilds == rebuilds
    raised = b.model_copy(update={"priority": 100})
    assert await selector.select([a, raised]) == raised
    assert selector.rebuilds == rebuilds + 1
    reweighted = raised.model_copy(update={"weight": 9})
    assert await selector.select([a, reweighted]) == reweighted
    assert selector.rebuilds == rebuilds + 2


@pytest.mark.asyncio
async def test_concurrent_candidate_snapshots_do_not_cross_select(selector):
    pools = [[binding(i)] for i in range(30, 70)]
    pools += [[binding(71, priority=100), binding(72, priority=0)]] * 20
    chosen = await asyncio.gather(*(selector.select(pool) for pool in pools))
    assert all(pick in pool for pick, pool in zip(chosen, pools, strict=True))
    assert all(pick.channel_id != UUID(int=72) for pick in chosen[40:])


@pytest.mark.asyncio
async def test_selector_only_does_not_update_usage_but_sdk_callbacks_are_global(selector):
    import litellm

    router = selector._router
    cache = router.cache.in_memory_cache.cache_dict
    before = set(cache)
    callbacks = tuple(
        callback
        for callback in litellm.success_callback
        if getattr(callback, "__self__", None) is router
    )
    assert len(callbacks) == 1
    await selector.select([binding(81)])
    await selector.select([binding(82)])
    assert set(cache) == before
    assert all(
        deployment["litellm_params"]["api_key"] == "g4-selector-never-send"
        for deployment in router.model_list
    )
    assert (
        len(
            [
                callback
                for callback in litellm.success_callback
                if getattr(callback, "__self__", None) is router
            ]
        )
        == 1
    )

    # The registered callback has no ownership gate: an unrelated SDK call
    # carrying deployment metadata can mutate this prototype Router's cache.
    callbacks[0](
        {
            "litellm_params": {
                "metadata": {"model_group": "another-router"},
                "model_info": {"id": "another-router-deployment"},
            }
        },
        None,
        None,
        None,
    )
    assert "another-router-deployment:successes" in cache
    failure_callbacks = [
        callback
        for callback in litellm.failure_callback
        if getattr(callback, "__self__", None) is router
    ]
    error = type("SimulatedRateLimit", (Exception,), {"status_code": 429})("simulated")
    failure_callbacks[0](
        {
            "exception": error,
            "litellm_params": {
                "metadata": {"model_group": "another-router"},
                "model_info": {"id": "another-router-deployment"},
            },
        },
        None,
        None,
        None,
    )
    assert "another-router-deployment:fails" in cache
    assert not hasattr(router, "aclose")
