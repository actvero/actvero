from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.modules.llm import routing
from app.modules.llm.binding_identity import (
    legacy_binding_id,
    project_binding_ids,
    reconcile_binding_ids,
)
from app.modules.llm.catalog_schemas import CatalogInput


def config(channel: UUID, upstream: str = "upstream", **binding: object) -> CatalogInput:
    return CatalogInput.model_validate(
        {
            "name": "Shared model",
            "slug": "public-name",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [{"channel_id": str(channel), "upstream_id": upstream, **binding}],
                }
            ],
        }
    )


def test_old_json_projects_id_without_mutating_or_changing_health_key() -> None:
    model_id, channel_id, tenant_id = uuid4(), uuid4(), uuid4()
    old = config(channel_id, enabled=True)
    original = old.model_dump(mode="json")
    projected = project_binding_ids(model_id, old)
    binding = projected.operations[0].bindings[0]
    assert binding.binding_id == legacy_binding_id(model_id, "chat", channel_id, "upstream")
    assert projected.bindings[0].binding_id == binding.binding_id
    assert old.model_dump(mode="json") == original
    assert routing.health_key(tenant_id, model_id, "chat", old.bindings[0]) == routing.health_key(
        tenant_id, model_id, "chat", binding
    )


def test_legacy_tuple_reuses_identity_and_new_binding_is_closed() -> None:
    model_id, channel_id = uuid4(), uuid4()
    old = config(channel_id, enabled=True, priority=42)
    update = CatalogInput.model_validate(
        {
            "name": "Shared model",
            "slug": "public-name",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [
                        {"channel_id": str(channel_id), "upstream_id": "upstream"},
                        {"channel_id": str(channel_id), "upstream_id": "another"},
                    ],
                }
            ],
        }
    )
    merged = reconcile_binding_ids(model_id, update, old)
    first, second = merged.operations[0].bindings
    assert first.binding_id == legacy_binding_id(model_id, "chat", channel_id, "upstream")
    assert first.enabled and first.priority == 42
    assert second.binding_id and second.binding_id != first.binding_id and not second.enabled


def test_retarget_requires_existing_identity_and_preserves_it() -> None:
    model_id, channel_id = uuid4(), uuid4()
    old = config(channel_id)
    identity = legacy_binding_id(model_id, "chat", channel_id, "upstream")
    without_id = config(channel_id, "changed")
    with pytest.raises(HTTPException) as error:
        reconcile_binding_ids(model_id, without_id, old)
    assert error.value.status_code == 409
    updated = reconcile_binding_ids(
        model_id, config(channel_id, "changed", binding_id=str(identity)), old
    )
    assert updated.operations[0].bindings[0].binding_id == identity


@pytest.mark.parametrize("forged", [uuid4(), UUID(int=0)])
def test_foreign_identity_is_rejected(forged: UUID) -> None:
    model_id, channel_id = uuid4(), uuid4()
    with pytest.raises(HTTPException) as error:
        reconcile_binding_ids(
            model_id, config(channel_id, binding_id=str(forged)), config(channel_id)
        )
    assert error.value.status_code == 409


def test_duplicate_identity_in_one_request_is_rejected() -> None:
    model_id, channel_id = uuid4(), uuid4()
    identity = legacy_binding_id(model_id, "chat", channel_id, "upstream")
    old = config(channel_id)
    incoming = CatalogInput.model_validate(
        {
            "name": "Shared model",
            "slug": "public-name",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [
                        {
                            "binding_id": str(identity),
                            "channel_id": str(channel_id),
                            "upstream_id": "upstream",
                        },
                        {
                            "binding_id": str(identity),
                            "channel_id": str(channel_id),
                            "upstream_id": "other",
                        },
                    ],
                }
            ],
        }
    )
    with pytest.raises(HTTPException) as error:
        reconcile_binding_ids(model_id, incoming, old)
    assert error.value.status_code == 409


def test_empty_operation_draft_accepts_legacy_client_without_index_error() -> None:
    model_id = uuid4()
    previous = CatalogInput.model_validate({"name": "Draft", "slug": "draft", "operations": []})
    incoming = CatalogInput.model_validate({"name": "Draft", "slug": "draft"})
    result = reconcile_binding_ids(model_id, incoming, previous)
    assert result.bindings == []
