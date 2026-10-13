"""Bounded, atomic model import. Preview is read-only; receipts make retries safe."""

import hashlib
import json
from collections import Counter
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import or_, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB
from app.modules.llm.catalog_router import configure
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding, ModelOperation
from app.modules.llm.import_schemas import (
    ImportCommit,
    ImportInput,
    ImportPreview,
    ImportPreviewItem,
    ImportResult,
    ImportResultItem,
    ImportStatus,
)
from app.modules.llm.models import CatalogModel, ModelImportReceipt
from app.modules.llm.providers.model_hints import model_hint
from app.modules.llm.router import administrator, channel, editable
from app.modules.members.service import Access, record

router = APIRouter(prefix="/api/v1/llm/model-imports", tags=["llm-model-imports"])


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


async def preview_plan(
    db: DB, actor: Access, body: ImportInput
) -> tuple[ImportPreview, dict[UUID, CatalogModel]]:
    source = await channel(db, actor, body.channel_id)
    editable(source)
    if source.version != body.channel_version:
        raise HTTPException(409, "渠道已更新，请刷新来源后重新预览")
    registered = {item["id"] for item in source.models}
    names = [item.slug if item.slug is not None else item.upstream_id for item in body.items]
    targets = [item.target_id for item in body.items if item.target_id]
    models = list(
        await db.scalars(
            select(CatalogModel).where(
                CatalogModel.tenant_id == actor.tenant.id,
                or_(CatalogModel.slug.in_(names), CatalogModel.id.in_(targets)),
            )
        )
    )
    by_id, by_slug = {m.id: m for m in models}, {m.slug: m for m in models}
    duplicates = Counter(
        name for name, item in zip(names, body.items, strict=True) if item.action == "create"
    )
    rows: list[ImportPreviewItem] = []
    # Track planned additions as well as persisted ones for shared link targets.
    planned: dict[tuple[UUID, str], set[tuple[UUID, str]]] = {}
    for item, slug in zip(body.items, names, strict=True):
        hint = model_hint(source.provider, item.upstream_id, source.declared_apis)
        kinds = item.kinds if item.kinds is not None else [hint.kind] if hint.kind else []
        row = ImportPreviewItem(
            **{**item.model_dump(), "slug": slug, "name": item.name or slug[:100], "kinds": kinds},
            hint=hint,
            status=item.action,
        )
        rows.append(row)
        if item.action == "skip":
            continue
        if item.upstream_id not in registered:
            row.errors.append("上游模型已从渠道移除")
        if any(kind not in hint.available_kinds for kind in kinds):
            row.errors.append("渠道不支持所选接口")
        if hint.mode and not hint.kind and kinds:
            row.errors.append("此模型的接口暂不可用，可稍后配置")
        if item.action == "create":
            if slug in by_slug or duplicates[slug] > 1:
                row.errors.append("技术名称已存在，请改名、关联现有模型或跳过")
            try:
                CatalogInput(slug=slug, name=row.name or "", operations=[])
            except ValidationError:
                row.errors.append("技术名称或展示名称格式不正确")
            row.added_bindings = len(kinds)
        else:
            target = by_id.get(item.target_id) if item.target_id else None
            if target is None or target.archived:
                row.errors.append("请选择未归档的目标模型")
            else:
                row.target_version = target.version
                row.slug, row.name = target.slug, target.name
                operations = {
                    op.kind: op
                    for op in CatalogInput.model_validate(target.configuration).operation_configs()
                }
                if not kinds or any(kind not in operations for kind in kinds):
                    row.errors.append("请选择目标模型已有的接口")
                else:
                    for kind in kinds:
                        op = operations[kind]
                        bindings = planned.setdefault(
                            (target.id, kind), {(b.channel_id, b.upstream_id) for b in op.bindings}
                        )
                        key = (source.id, item.upstream_id)
                        if key not in bindings:
                            if len(bindings) >= 50:
                                row.errors.append("目标接口的渠道关联已达 50 条")
                            bindings.add(key)
                            row.added_bindings += 1
                    if not row.added_bindings:
                        row.status = "unchanged"
        if row.errors:
            row.status = "error"
    create_count = sum(row.status == "create" for row in rows)
    linked = {row.target_id for row in rows if row.status == "link"}
    binding_count = sum(row.added_bindings for row in rows if row.status in ("create", "link"))
    # A revision is concurrency evidence, not authorization. Commit rebuilds and validates the plan.
    revision = fingerprint(
        [
            body.model_dump(mode="json"),
            source.version,
            [row.model_dump(mode="json") for row in rows],
            sorted((str(m.id), m.version, m.archived) for m in models),
        ]
    )
    return ImportPreview(
        revision=revision,
        items=rows,
        create_count=create_count,
        link_count=len(linked),
        binding_count=binding_count,
        can_commit=not any(row.errors for row in rows) and bool(create_count or linked),
    ), by_id


@router.post("/preview", response_model=ImportPreview)
async def preview(request: Request, db: DB, body: ImportInput, _csrf: Mutation) -> ImportPreview:
    actor = await administrator(request, db)
    plan, _ = await preview_plan(db, actor, body)
    return plan


async def receipt(db: DB, actor: Access, request_id: UUID) -> ModelImportReceipt | None:
    result: ModelImportReceipt | None = await db.scalar(
        select(ModelImportReceipt).where(
            ModelImportReceipt.tenant_id == actor.tenant.id,
            ModelImportReceipt.request_id == request_id,
            ModelImportReceipt.actor_id == actor.user.id,
        )
    )
    return result


@router.get("/{request_id}", response_model=ImportStatus)
async def status(request_id: UUID, request: Request, db: DB) -> ImportStatus:
    actor = await administrator(request, db)
    previous = await receipt(db, actor, request_id)
    return ImportStatus(
        committed=previous is not None,
        result=ImportResult.model_validate(previous.result) if previous else None,
    )


@router.post("/commit", response_model=ImportResult)
async def commit(request: Request, db: DB, body: ImportCommit, _csrf: Mutation) -> ImportResult:
    # Channel, model and membership writes share this tenant lock.
    actor = await administrator(request, db, write=True)
    signature = fingerprint(body.model_dump(mode="json"))
    previous = await receipt(db, actor, body.request_id)
    if previous:
        if previous.fingerprint != signature:
            raise HTTPException(409, "此提交标识已用于其他导入，请重新预览")
        return ImportResult.model_validate(previous.result)
    data = ImportInput.model_validate(body.model_dump(exclude={"request_id", "revision"}))
    plan, models = await preview_plan(db, actor, data)
    if plan.revision != body.revision:
        raise HTTPException(409, "来源或目标已更新，请重新预览；本次未写入")
    if not plan.can_commit:
        raise HTTPException(422, "请先处理预览中的问题或选择有变更的模型")
    results = []
    changed: dict[UUID, tuple[CatalogModel, CatalogInput, bool]] = {}
    source = await channel(db, actor, body.channel_id)
    for item in plan.items:
        result = ImportResultItem(upstream_id=item.upstream_id, status="skipped")
        results.append(result)
        if item.status == "skip":
            continue
        if item.status == "create":
            row = CatalogModel(id=uuid4(), tenant_id=actor.tenant.id)
            config = CatalogInput(
                slug=item.slug or item.upstream_id,
                name=item.name or item.upstream_id[:100],
                reference={
                    "provider": source.provider,
                    "model_id": item.upstream_id,
                    "channel_id": source.id,
                },
                operations=[
                    ModelOperation(kind=kind, channel_id=source.id, upstream_id=item.upstream_id)
                    for kind in item.kinds or []
                ],
            )
            changed[row.id] = (row, config, True)
            result.status = "created"
        else:
            assert item.target_id is not None
            row = models[item.target_id]
            config = (
                changed[row.id][1]
                if row.id in changed
                else CatalogInput.model_validate(row.configuration)
            )
            config.operations = config.operation_configs()
            if item.status == "link":
                changed[row.id] = (row, config, False)
            result.status = "linked" if item.status == "link" else "unchanged"
        for operation in config.operation_configs():
            if operation.kind not in (item.kinds or []):
                continue
            if not any(
                b.channel_id == source.id and b.upstream_id == item.upstream_id
                for b in operation.bindings
            ):
                operation.bindings.append(
                    ModelBinding(channel_id=source.id, upstream_id=item.upstream_id, enabled=False)
                )
        result.model_id, result.slug = row.id, config.slug
        result.added_bindings = item.added_bindings
    for row, config, created in changed.values():
        await configure(db, actor, row, config)
        if created:
            db.add(row)
        else:
            row.version += 1
        await db.flush()
        record(
            db,
            actor,
            "llm.model.create" if created else "llm.model.update",
            row.id,
            row.name,
            {"source": "channel_import", "request_id": str(body.request_id)},
        )
    batch_result = ImportResult(request_id=body.request_id, items=results)
    db.add(
        ModelImportReceipt(
            tenant_id=actor.tenant.id,
            actor_id=actor.user.id,
            request_id=body.request_id,
            fingerprint=signature,
            result=batch_result.model_dump(mode="json"),
        )
    )
    await db.commit()
    return batch_result
