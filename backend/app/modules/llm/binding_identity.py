"""Stable model binding identity, independent of route health fingerprints."""

import json
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException

from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding, OperationKind

BINDING_NAMESPACE = UUID("57f64cb7-0847-5c90-a40b-e34596bb325d")


def legacy_binding_id(model_id: UUID, operation: str, channel_id: UUID, upstream_id: str) -> UUID:
    """Migration and read-only projection use exactly the same canonical tuple."""
    name = json.dumps(
        [str(model_id), operation, str(channel_id), upstream_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(BINDING_NAMESPACE, name)


def projected_binding_id(model_id: UUID, operation: OperationKind, binding: ModelBinding) -> UUID:
    return binding.binding_id or legacy_binding_id(
        model_id, operation, binding.channel_id, binding.upstream_id
    )


def project_binding_ids(model_id: UUID, config: CatalogInput) -> CatalogInput:
    """Add identities to an API response without changing the stored JSON."""
    result = config.model_copy(deep=True)
    for operation in result.operation_configs():
        for binding in operation.bindings:
            binding.binding_id = projected_binding_id(model_id, operation.kind, binding)
    if result.operations is not None:
        # Pydantic creates a fresh legacy projection when the operation list is parsed.
        first = result.operations[0] if result.operations else None
        result.bindings = first.bindings if first else []
    else:
        for binding in result.bindings:
            binding.binding_id = projected_binding_id(model_id, result.kind, binding)
    return result


def reconcile_binding_ids(
    model_id: UUID,
    incoming: CatalogInput,
    previous: CatalogInput | None,
) -> CatalogInput:
    """Assign new IDs and preserve only identities owned by this model and operation."""
    old_by_id: dict[UUID, tuple[OperationKind, ModelBinding]] = {}
    old_by_target: dict[tuple[OperationKind, UUID, str], list[UUID]] = {}
    if previous:
        for old_config in previous.operation_configs():
            for binding in old_config.bindings:
                old_identity = projected_binding_id(model_id, old_config.kind, binding)
                if old_identity in old_by_id:
                    raise HTTPException(409, "模型绑定身份重复，请先刷新配置")
                old_by_id[old_identity] = (old_config.kind, binding)
                old_by_target.setdefault(
                    (old_config.kind, binding.channel_id, binding.upstream_id), []
                ).append(old_identity)

    result = incoming.model_copy(deep=True)
    operations = result.operations if result.operations is not None else [result]
    previous_operations = previous.operation_configs() if previous else []
    if (
        previous_operations
        and result.operations is None
        and "bindings" not in result.model_fields_set
    ):
        result.bindings = previous_operations[0].bindings
    seen: set[UUID] = set()
    for operation in operations:
        old_operation = next((op for op in previous_operations if op.kind == operation.kind), None)
        if old_operation is not None and result.operations is not None:
            for field in type(old_operation).model_fields:
                if field not in operation.model_fields_set:
                    setattr(operation, field, getattr(old_operation, field))
        old_for_operation = {
            identity: binding
            for identity, (kind, binding) in old_by_id.items()
            if kind == operation.kind
        }
        matched_old: set[UUID] = set()
        unclaimed: list[ModelBinding] = []
        for binding in operation.bindings:
            identity: UUID | None = binding.binding_id
            if identity is not None:
                owned = old_by_id.get(identity)
                if owned is None or owned[0] != operation.kind:
                    raise HTTPException(409, "绑定身份不属于当前模型操作，请刷新配置")
                matched_old.add(identity)
            else:
                matches = old_by_target.get(
                    (operation.kind, binding.channel_id, binding.upstream_id), []
                )
                if len(matches) > 1:
                    raise HTTPException(409, "绑定目标不唯一，请刷新配置并提供绑定身份")
                if matches:
                    identity = matches[0]
                    matched_old.add(identity)
                else:
                    unclaimed.append(binding)
                    continue
            if identity in seen:
                raise HTTPException(409, "绑定身份重复，请刷新配置")
            seen.add(identity)
            binding.binding_id = identity
            old = old_for_operation[identity]
            for field in (
                "price",
                "enabled",
                "priority",
                "weight",
                "compatibility_key",
                "chat_options",
            ):
                if field not in binding.model_fields_set:
                    setattr(binding, field, getattr(old, field))
            if "limits" not in binding.chat_options.model_fields_set:
                binding.chat_options.limits = old.chat_options.limits
        if unclaimed and any(identity not in matched_old for identity in old_for_operation):
            raise HTTPException(409, "绑定目标已变化，请刷新配置并提供绑定身份")
        for binding in unclaimed:
            identity = uuid4()
            while identity in seen:
                identity = uuid4()
            binding.binding_id = identity
            seen.add(identity)
            if "enabled" not in binding.model_fields_set:
                binding.enabled = False
    if result.operations is not None:
        first = result.operations[0] if result.operations else None
        result.bindings = first.bindings if first else []
    else:
        result.bindings = operations[0].bindings
    return result
