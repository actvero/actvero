"""Isolated G4-01 prototype for LiteLLM's public deployment selector.

The caller supplies bindings already filtered by Actvero authorization, operation,
manual state, compatibility, RouteHealth, and attempted bindings. This module is
not connected to production routing. ``startup`` is explicit because constructing
a LiteLLM Router registers process-wide callbacks in SDK 1.102.1.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from app.modules.llm.catalog_schemas import ModelBinding

if TYPE_CHECKING:
    from litellm.router import Router

_MODEL_GROUP = "actvero-g4-selector-only"
_MODEL = "openai/gpt-4o-mini"
_PLACEHOLDER_KEY = "g4-selector-never-send"


def deployment_id(binding: ModelBinding) -> str:
    """Prefer G2's persistent binding ID; map older records deterministically."""
    persistent_id = getattr(binding, "binding_id", None)
    if persistent_id is not None:
        return str(persistent_id)
    legacy = f"{binding.channel_id}:{binding.upstream_id}".encode()
    return "legacy-" + hashlib.sha256(legacy).hexdigest()


class RouterSelectorPrototype:
    """One SDK Router, with serialized snapshot updates and selection.

    Router 1.102.1 has no safe public per-instance close/unregister API. Keep
    this prototype separate from the live gateway until callback lifecycle is
    resolved; do not call Router.reset(), which clears process-wide callbacks.
    """

    def __init__(self) -> None:
        self._router: Router | None = None
        self._lock = asyncio.Lock()
        self._snapshot: tuple[tuple[str, int, int], ...] | None = None
        self.rebuilds = 0

    def startup(self) -> None:
        if self._router is not None:
            raise RuntimeError("selector already started")
        from litellm.router import Router

        self._router = Router(
            model_list=[],
            routing_strategy="simple-shuffle",
            num_retries=0,
            disable_cooldowns=True,
            enable_pre_call_checks=False,
            enable_health_check_routing=False,
        )

    async def select(
        self,
        candidates: Sequence[ModelBinding],
        *,
        specific: tuple[UUID, str] | None = None,
    ) -> ModelBinding | None:
        """Select an eligible binding, or bypass SDK for a fixed/diagnostic target."""
        router = self._router
        if router is None:
            raise RuntimeError("selector startup is required")
        by_id: dict[str, ModelBinding] = {}
        for binding in candidates:
            ident = deployment_id(binding)
            if ident in by_id:
                raise ValueError("duplicate deployment ID among eligible bindings")
            by_id[ident] = binding
        if specific is not None:
            return next(
                (
                    binding
                    for binding in candidates
                    if (binding.channel_id, binding.upstream_id) == specific
                ),
                None,
            )
        if not by_id:
            return None

        snapshot = tuple(
            sorted((ident, binding.priority, binding.weight) for ident, binding in by_id.items())
        )
        # SDK set_model_list mutates its indices. The lock also prevents a
        # concurrent request from selecting another request's candidate set.
        async with self._lock:
            if self._snapshot != snapshot:
                router.set_model_list(
                    [
                        {
                            "model_name": _MODEL_GROUP,
                            "litellm_params": {
                                "model": _MODEL,
                                "api_key": _PLACEHOLDER_KEY,
                                "order": 1000 - priority,
                                "weight": weight,
                            },
                            "model_info": {"id": ident},
                        }
                        for ident, priority, weight in snapshot
                    ]
                )
                self._snapshot = snapshot
                self.rebuilds += 1
            selected = await router.async_get_available_deployment(
                model=_MODEL_GROUP, request_kwargs={}
            )
        return by_id[selected["model_info"]["id"]]
