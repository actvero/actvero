"""Actvero authorization in front of the native New API control plane."""

import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.modules.auth.service import DB, mutation_session, now
from app.modules.members.service import Access, record
from app.modules.model_gateway import client, service
from app.modules.model_gateway.access_status import (
    PublicationNames,
    PublicationPreview,
    PublicationPreviewInput,
    PublicationStatuses,
)
from app.modules.model_gateway.authorization import administrator
from app.modules.model_gateway.models import GatewayDirectory
from app.modules.model_gateway.publication import PublicationInput
from app.modules.model_gateway.schemas import (
    GatewayChannelInput,
    GatewayChannelPatch,
    GatewayChannelStatus,
    GatewayDeleteInput,
    GatewayDirectoryView,
    GatewayDiscoveryInput,
    GatewayMappingInput,
    GatewayModelInput,
    GatewayPriceInput,
    GatewayPricePreview,
    GatewayReferenceImport,
    GatewayResult,
    GatewayStatus,
    GatewayTestInput,
    GatewayVendorInput,
)


async def protect_mutation(request: Request, db: DB) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        await mutation_session(request, db)


router = APIRouter(
    prefix="/api/v1/model-gateway",
    tags=["model-gateway"],
    dependencies=[Depends(protect_mutation)],
)


async def audit(db: DB, actor: Access, action: str, target: str) -> None:
    record(
        db,
        actor,
        "model_gateway." + action,
        uuid5(NAMESPACE_URL, f"{actor.tenant.id}:{target}"),
        target,
    )
    await db.commit()


@router.get("/status")
async def status(request: Request, db: DB) -> GatewayStatus:
    actor = await administrator(request, db)
    config = client.connection(request, actor.tenant.id)
    if config is None:
        return GatewayStatus(configured=False, backend="direct")
    try:
        await client.call(request, actor.tenant.id, "GET", "/api/channel/", params={"page_size": 1})
    except HTTPException as exc:
        return GatewayStatus(configured=True, backend="newapi", error=str(exc.detail))
    return GatewayStatus(
        configured=True, backend="newapi", connected=True, console_url=config.base_url
    )


@router.get("/channels")
async def channels(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=200),
    model: str = Query("", max_length=200),
    group: str = Query("", max_length=100),
    state: str = Query("", pattern=r"^(enabled|disabled)?$"),
    type: int | None = Query(None, ge=1, le=1000),
    sort_by: Literal[
        "id", "name", "priority", "balance", "response_time", "test_time"
    ] = "priority",
    sort_order: Literal["asc", "desc"] = "desc",
) -> GatewayResult:
    actor = await administrator(request, db)
    data = await client.call(
        request,
        actor.tenant.id,
        "GET",
        "/api/channel/search" if q or model else "/api/channel/",
        params={
            "p": page,
            "page_size": page_size,
            "keyword": q,
            "model": model,
            "group": group,
            "status": state,
            **({"type": type} if type is not None else {}),
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    )
    return GatewayResult(data=service.page_view(data, "channel"))


@router.get("/channel-options")
async def channel_options(request: Request, db: DB) -> GatewayResult:
    actor = await administrator(request, db)
    bases = await client.call(request, actor.tenant.id, "GET", "/api/channel/default_base_urls")
    groups = await client.call(request, actor.tenant.id, "GET", "/api/group/")
    status = service.object_value(await client.call(request, actor.tenant.id, "GET", "/api/status"))
    quota = status.get("quota_per_unit")
    return GatewayResult(
        data={
            "base_urls": bases,
            "groups": groups,
            "quota_per_unit": quota if isinstance(quota, (int, float)) and quota > 0 else None,
        }
    )


@router.post("/channels/discover")
async def discover(request: Request, db: DB, body: GatewayDiscoveryInput) -> GatewayDirectoryView:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request,
        actor.tenant.id,
        "POST",
        "/api/channel/fetch_models",
        payload={
            "type": body.type,
            "base_url": body.base_url,
            "key": body.key.get_secret_value(),
        },
    )
    return GatewayDirectoryView(models=data, fetched_at=now())


@router.post("/channels")
async def create_channel(request: Request, db: DB, body: GatewayChannelInput) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    if body.key is None or not body.key.get_secret_value():
        raise HTTPException(422, "请填写渠道凭据")
    payload = service.channel_payload(body)
    payload["status"] = 1
    result = await client.call(
        request,
        actor.tenant.id,
        "POST",
        "/api/channel/",
        payload={
            "mode": "single",
            "channel": payload,
        },
    )
    await audit(db, actor, "channel.create", body.name)
    return GatewayResult(data=result)


@router.get("/channels/{channel_id}")
async def get_channel(request: Request, db: DB, channel_id: int) -> GatewayResult:
    actor = await administrator(request, db)
    return GatewayResult(
        data=service.channel_view(await service.get_channel(request, actor.tenant.id, channel_id))
    )


@router.put("/channels/{channel_id}")
async def update_channel(
    request: Request, db: DB, channel_id: int, body: GatewayChannelInput
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    current = await service.get_channel(request, actor.tenant.id, channel_id)
    service.check_revision(service.channel_view(current), body.revision)
    # Preserve native settings not represented by this form. Never echo them to
    # the browser; New API validates whether the token can modify each field.
    payload = current | service.channel_payload(body)
    for field in ("status", "key", "channel_info", "other_info"):
        payload.pop(field, None)
    if body.key and body.key.get_secret_value():
        payload["key"] = body.key.get_secret_value()
    payload["id"] = channel_id
    await client.call(request, actor.tenant.id, "PUT", "/api/channel/", payload=payload)
    if body.key or body.base_url != current.get("base_url") or body.type != current.get("type"):
        await service.invalidate_directory(db, actor.tenant.id, channel_id)
    await audit(db, actor, "channel.update", str(channel_id))
    return GatewayResult(
        data=service.channel_view(await service.get_channel(request, actor.tenant.id, channel_id))
    )


@router.post("/channels/{channel_id}/status")
async def channel_status(
    request: Request, db: DB, channel_id: int, body: GatewayChannelStatus
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    result = await client.call(
        request,
        actor.tenant.id,
        "POST",
        f"/api/channel/{channel_id}/status",
        payload=body.model_dump(),
    )
    await audit(db, actor, "channel.status", str(channel_id))
    return GatewayResult(data=result)


@router.patch("/channels/{channel_id}/fields")
async def patch_channel_fields(
    request: Request, db: DB, channel_id: int, body: GatewayChannelPatch
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    current = await service.get_channel(request, actor.tenant.id, channel_id)
    if body.models is not None or body.revision:
        service.check_revision(service.channel_view(current), body.revision)
    changes = body.model_dump(exclude={"revision"}, exclude_none=True)
    if not changes:
        raise HTTPException(422, "请选择要修改的渠道字段")
    if "models" in changes:
        changes["models"] = ",".join(changes["models"])
    # Native partial updates retain provider-specific settings and credentials.
    # Never resend a credential merely to adjust routing or a model list.
    await client.call(
        request,
        actor.tenant.id,
        "PUT",
        "/api/channel/",
        payload={"id": channel_id, **changes},
    )
    await audit(db, actor, "channel.fields", str(channel_id))
    return GatewayResult(
        data=service.channel_view(await service.get_channel(request, actor.tenant.id, channel_id))
    )


@router.delete("/channels/{channel_id}")
async def delete_channel(request: Request, db: DB, channel_id: int) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    result = await client.call(request, actor.tenant.id, "DELETE", f"/api/channel/{channel_id}")
    await service.invalidate_directory(db, actor.tenant.id, channel_id)
    await audit(db, actor, "channel.delete", str(channel_id))
    return GatewayResult(data=result)


@router.get("/channels/{channel_id}/directory")
async def directory(request: Request, db: DB, channel_id: int) -> GatewayDirectoryView:
    actor = await administrator(request, db)
    return await service.directory(request, db, actor.tenant.id, channel_id)


@router.post("/channels/{channel_id}/directory")
async def refresh_directory(request: Request, db: DB, channel_id: int) -> GatewayDirectoryView:
    actor = await administrator(request, db, write=True)
    raw = await service.get_channel(request, actor.tenant.id, channel_id)
    data = await client.call(
        request, actor.tenant.id, "GET", f"/api/channel/fetch_models/{channel_id}"
    )
    view = GatewayDirectoryView(models=data, fetched_at=now())
    if len(view.models) > 5000:
        raise HTTPException(502, "上游目录超过缓存上限")
    row = await db.get(GatewayDirectory, (actor.tenant.id, channel_id))
    if row is None:
        row = GatewayDirectory(tenant_id=actor.tenant.id, channel_id=channel_id)
        db.add(row)
    row.models = view.models
    row.fetched_at = now()
    row.connection_id = client.connection_id(
        await client.relay_connection(request, actor.tenant.id)
    )
    row.channel_snapshot = service.directory_identity(raw)
    await audit(db, actor, "channel.discover", str(channel_id))
    return view


@router.post("/channels/{channel_id}/test")
async def test_channel(
    request: Request, db: DB, channel_id: int, body: GatewayTestInput
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    result = await client.call(
        request,
        actor.tenant.id,
        "GET",
        f"/api/channel/test/{channel_id}",
        params={
            **({"model": body.model} if body.model else {}),
            **({"endpoint_type": body.endpoint_type} if body.endpoint_type != "auto" else {}),
            **({"stream": "true"} if body.stream else {}),
        },
    )
    await audit(db, actor, "channel.test", str(channel_id))
    return GatewayResult(data=result)


@router.get("/models")
async def models(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=200),
    state: str = Query("", pattern=r"^(visible|unavailable|hidden|partial)?$"),
) -> GatewayResult:
    actor = await administrator(request, db)
    data = await client.call(
        request,
        actor.tenant.id,
        "GET",
        "/api/models/search",
        params={
            "p": page,
            "page_size": page_size,
            "keyword": q,
            "include_channel_models": "true",
            "square_state": state,
        },
    )
    return GatewayResult(data=service.page_view(data, "model"))


@router.post("/models")
async def create_model(request: Request, db: DB, body: GatewayModelInput) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request,
        actor.tenant.id,
        "POST",
        "/api/models/",
        payload=body.model_dump(exclude={"revision"}),
    )
    await audit(db, actor, "model.create", body.model_name)
    return GatewayResult(data=service.model_view(data))


@router.put("/models/{model_id}")
async def update_model(
    request: Request, db: DB, model_id: int, body: GatewayModelInput
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    current = await client.call(request, actor.tenant.id, "GET", f"/api/models/{model_id}")
    service.check_revision(service.model_view(current), body.revision)
    data = await client.call(
        request,
        actor.tenant.id,
        "PUT",
        "/api/models/",
        payload={
            **body.model_dump(exclude={"revision"}),
            "id": model_id,
        },
    )
    await audit(db, actor, "model.update", body.model_name)
    return GatewayResult(data=service.model_view(data))


@router.post("/models/{model_id}/delete")
async def delete_model(
    request: Request, db: DB, model_id: int, body: GatewayDeleteInput
) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request,
        actor.tenant.id,
        "DELETE",
        f"/api/models/{model_id}",
        params={
            "remove_from_channels": str(body.remove_from_channels).lower(),
            "remove_pricing": str(body.remove_pricing).lower(),
        },
    )
    await audit(db, actor, "model.delete", str(model_id))
    return GatewayResult(data=data)


@router.get("/mappings")
async def mappings(
    request: Request, db: DB, model_name: str = Query(min_length=1, max_length=128)
) -> GatewayResult:
    actor = await administrator(request, db)
    channels = await service.all_channels(request, actor.tenant.id)
    rows = []
    for row in channels:
        names = (row.get("models") or "").split(",")
        mapping = json.loads(row.get("model_mapping") or "{}")
        rows.append(
            {
                "channel": row,
                "associated": model_name in names,
                "upstream_id": mapping.get(model_name, model_name),
            }
        )
    return GatewayResult(data=rows)


@router.put("/mappings")
async def update_mapping(request: Request, db: DB, body: GatewayMappingInput) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    raw = await service.get_channel(request, actor.tenant.id, body.channel_id)
    service.check_revision(service.channel_view(raw), body.revision)
    names = list(dict.fromkeys(n for n in (raw.get("models") or "").split(",") if n))
    mapping = json.loads(raw.get("model_mapping") or "{}")
    if body.remove:
        names = [n for n in names if n != body.model_name]
        mapping.pop(body.model_name, None)
    else:
        if body.model_name not in names:
            names.append(body.model_name)
        if body.model_name == body.upstream_id:
            mapping.pop(body.model_name, None)
        else:
            mapping[body.model_name] = body.upstream_id
    payload = raw | {"models": ",".join(names), "model_mapping": json.dumps(mapping)}
    for field in ("status", "key", "channel_info", "other_info"):
        payload.pop(field, None)
    await client.call(request, actor.tenant.id, "PUT", "/api/channel/", payload=payload)
    await audit(db, actor, "mapping.update", f"{body.channel_id}:{body.model_name}")
    return GatewayResult(
        data=service.channel_view(
            await service.get_channel(request, actor.tenant.id, body.channel_id)
        )
    )


@router.get("/prices")
async def prices(request: Request, db: DB, model: str = Query(max_length=128)) -> GatewayResult:
    actor = await administrator(request, db)
    result = service.object_value(
        await client.call(
            request, actor.tenant.id, "GET", "/api/option/model_pricing", params={"model": model}
        )
    )
    status = service.object_value(await client.call(request, actor.tenant.id, "GET", "/api/status"))
    quota = status.get("quota_per_unit")
    if not isinstance(quota, (int, float)) or quota <= 0:
        raise HTTPException(502, "模型网关没有返回有效的价格换算单位")
    return GatewayResult(
        data={
            "entries": result.get("entries", []),
            "empty_version": result.get("empty_version"),
            "quota_per_unit": quota,
        }
    )


@router.put("/prices")
async def update_prices(request: Request, db: DB, body: GatewayPriceInput) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request,
        actor.tenant.id,
        "PATCH",
        "/api/option/model_pricing",
        payload={"changes": [body.model_dump()]},
    )
    await audit(db, actor, "pricing.update", body.model_name)
    return GatewayResult(data=data)


@router.post("/prices/preview")
async def price_preview(request: Request, db: DB, body: GatewayPricePreview) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    return GatewayResult(
        data=await client.call(
            request,
            actor.tenant.id,
            "POST",
            "/api/option/model_pricing/preview",
            payload=body.model_dump(),
        )
    )


@router.get("/vendors")
async def vendors(request: Request, db: DB) -> GatewayResult:
    actor = await administrator(request, db)
    return GatewayResult(
        data=await client.call(
            request, actor.tenant.id, "GET", "/api/vendors/", params={"p": 1, "page_size": 100}
        )
    )


@router.post("/vendors")
async def create_vendor(request: Request, db: DB, body: GatewayVendorInput) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request, actor.tenant.id, "POST", "/api/vendors/", payload=body.model_dump()
    )
    await audit(db, actor, "vendor.create", body.name)
    return GatewayResult(data=data)


@router.get("/reference")
async def reference(request: Request, db: DB) -> GatewayResult:
    actor = await administrator(request, db)
    return GatewayResult(
        data=await client.call(
            request,
            actor.tenant.id,
            "GET",
            "/api/models/sync_upstream/preview",
            params={"locale": "zh"},
        )
    )


@router.get("/logs")
async def logs(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    model_name: str = Query("", max_length=200),
    request_id: str = Query("", max_length=128),
) -> GatewayResult:
    actor = await administrator(request, db)
    data = service.object_value(
        await client.call(
            request,
            actor.tenant.id,
            "GET",
            "/api/log/",
            params={
                "p": page,
                "page_size": 20,
                "model_name": model_name,
                "request_id": request_id,
            },
        )
    )
    # Native logs may contain prompts and completions. The management list is
    # limited to execution/usage metadata, not request bodies or credentials.
    allowed = (
        "id",
        "created_at",
        "type",
        "model_name",
        "channel",
        "channel_name",
        "group",
        "request_id",
        "upstream_request_id",
        "prompt_tokens",
        "completion_tokens",
        "use_time",
        "is_stream",
        "quota",
    )
    items = [{k: row.get(k) for k in allowed} for row in data.get("items", [])]
    config = client.require_connection(request, actor.tenant.id)
    if config.namespace:
        for item in items:
            for key in ("model_name", "channel_name", "group"):
                if isinstance(item.get(key), str):
                    item[key] = item[key].removeprefix(config.namespace)
    return GatewayResult(data={"items": items, "total": data.get("total", 0)})


@router.post("/reference/import")
async def import_reference(request: Request, db: DB, body: GatewayReferenceImport) -> GatewayResult:
    actor = await administrator(request, db, write=True)
    data = await client.call(
        request,
        actor.tenant.id,
        "POST",
        "/api/models/sync_upstream",
        payload={"locale": "zh", **body.model_dump()},
    )
    await audit(db, actor, "model.import", str(len(body.selections)))
    return GatewayResult(data=data)


@router.get("/publication")
async def publication_view(
    request: Request, db: DB, model: str = Query(max_length=128)
) -> GatewayResult:
    from app.modules.model_gateway import publication

    actor = await administrator(request, db)
    config = await client.relay_connection(request, actor.tenant.id)
    from app.modules.model_gateway.capabilities import resolve

    automatic = resolve(
        model, config.relay_group, await service.all_channels(request, actor.tenant.id)
    )
    return GatewayResult(
        data={
            **publication.view(await publication.find(db, actor.tenant.id, model)),
            "automatic": automatic,
            "relay_ready": bool(config.relay_key and config.relay_token_id),
            "group": config.relay_group,
        }
    )


@router.post("/publication/status")
async def publication_statuses(
    request: Request, db: DB, body: PublicationNames
) -> PublicationStatuses:
    from app.modules.model_gateway.access_status import inspect

    actor = await administrator(request, db)
    return PublicationStatuses(
        items=await inspect(request, db, actor, list(dict.fromkeys(body.models)))
    )


@router.post("/publication/preview")
async def publication_preview(
    request: Request, db: DB, body: PublicationPreviewInput
) -> PublicationPreview:
    from app.modules.model_gateway.access_status import preview

    actor = await administrator(request, db)
    return await preview(request, db, actor, body)


@router.put("/publication")
async def save_publication(request: Request, db: DB, body: PublicationInput) -> GatewayResult:
    from app.modules.model_gateway import publication

    actor = await administrator(request, db, write=True)
    row = await publication.save(request, db, actor, body)
    result = publication.view(row)
    await audit(db, actor, "publication.update", body.model_name)
    return GatewayResult(data=result)


@router.get("/settlements")
async def gateway_settlements(
    request: Request, db: DB, page: int = Query(1, ge=1)
) -> GatewayResult:
    from sqlalchemy import func, select

    from app.modules.llm.models import CatalogModel, ModelCall, UsageSettlement

    actor = await administrator(request, db)
    conditions = [
        UsageSettlement.tenant_id == actor.tenant.id,
        UsageSettlement.price["engine"].astext == "newapi",
        UsageSettlement.status == "review",
    ]
    total = await db.scalar(select(func.count()).select_from(UsageSettlement).where(*conditions))
    rows = await db.execute(
        select(UsageSettlement, ModelCall, CatalogModel.name)
        .join(ModelCall, ModelCall.id == UsageSettlement.id)
        .join(CatalogModel, CatalogModel.id == ModelCall.model_id)
        .where(*conditions)
        .order_by(UsageSettlement.created_at.desc())
        .offset((page - 1) * 20)
        .limit(20)
    )
    return GatewayResult(
        data={
            "items": [
                {
                    "id": str(s.id),
                    "version": s.version,
                    "model": name,
                    "created_at": s.created_at.isoformat(),
                    "reason": s.reason,
                    "request_id": (
                        c.attempts[-1].get("gateway_request_id") if c.attempts else None
                    ),
                }
                for s, c, name in rows
            ],
            "total": total or 0,
        }
    )


@router.post("/settlements/{call_id}/recheck")
async def recheck_settlement(
    call_id: UUID, request: Request, db: DB, version: int = Query(ge=1)
) -> GatewayResult:
    import copy

    from sqlalchemy import select

    from app.modules.llm.models import ModelCall, UsageSettlement
    from app.modules.model_gateway import billing
    from app.modules.tenants.models import Tenant

    actor = await administrator(request, db, write=True)
    row = await db.get(UsageSettlement, call_id)
    log = await db.get(ModelCall, call_id)
    if (
        not row
        or row.tenant_id != actor.tenant.id
        or row.price.get("engine") != "newapi"
        or not log
    ):
        raise HTTPException(404, "网关结算记录不存在")
    if row.version != version or row.status != "review":
        raise HTTPException(409, "结算记录已变化，请刷新后重试")
    evidence: dict[str, Any] = {
        "tenant_id": str(actor.tenant.id),
        "complete": True,
        "attempts": copy.deepcopy(log.attempts),
    }
    await billing.reconcile(request, evidence)
    if not evidence["attempts"] or not all(a.get("gateway_ledger") for a in evidence["attempts"]):
        raise HTTPException(409, "仍未取得可确认的网关账单，已保留待核对状态")
    await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
    await db.refresh(row, with_for_update=True)
    if row.version != version or row.status != "review":
        raise HTTPException(409, "结算记录已变化，请刷新后重试")
    log.attempts = evidence["attempts"]
    billing.complete(row, log, certainly_unused=False)
    await audit(db, actor, "settlement.recheck", str(call_id))
    return GatewayResult(data={"status": row.status, "version": row.version})
