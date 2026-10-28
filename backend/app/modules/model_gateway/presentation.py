"""Member-facing names over stable native model identifiers."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.auth.service import DB, now
from app.modules.llm.models import CatalogModel
from app.modules.model_gateway import client
from app.modules.model_gateway.publication import PublicationInput, configuration, find


async def enrich(db: DB, tenant_id: UUID, models: list[dict[str, Any]]) -> None:
    names = [m["model_name"] for m in models if m.get("name_rule") == 0]
    rows = await db.scalars(
        select(CatalogModel).where(
            CatalogModel.tenant_id == tenant_id, CatalogModel.slug.in_(names)
        )
    )
    publications = {row.slug: row for row in rows if row.configuration.get("gateway")}
    for model in models:
        row = publications.get(model["model_name"]) if model.get("name_rule") == 0 else None
        model["display_name"] = row.name if row and row.name != row.slug else ""
        if row:
            # A stale metadata editor cannot overwrite a newer presentation name.
            model["revision"] = client.revision(
                {"native": model["revision"], "display_name": row.name}
            )


async def prepare(
    request: Request, db: DB, tenant_id: UUID, model: dict[str, Any], display_name: Any
) -> tuple[CatalogModel | None, str, dict[str, Any]] | None:
    if not isinstance(display_name, str) or len(display_name.strip()) > 100:
        raise HTTPException(422, "展示名称最多 100 个字符")
    display_name = display_name.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in display_name):
        raise HTTPException(422, "展示名称不能包含换行或控制字符")
    if model.get("name_rule", 0) != 0:
        if display_name:
            raise HTTPException(422, "展示名称只能设置在精确匹配的模型上")
        return None
    name = model.get("model_name")
    row = await find(db, tenant_id, name) if isinstance(name, str) else None
    # Metadata-only names that cannot be published remain editable without an override.
    if not display_name and (not row or not row.configuration.get("gateway")):
        return None
    try:
        body = PublicationInput(model_name=name, name=display_name or str(name)[:100])
    except ValidationError as exc:
        raise HTTPException(422, "请核对模型调用 ID 和展示名称") from exc
    if row and not row.configuration.get("gateway"):
        if display_name:
            raise HTTPException(409, "已有同名旧模型，请先处理旧模型后再设置展示名称")
        return None
    if (row and row.name == body.name) or (not row and not display_name):
        return None
    if row:
        # Cosmetic edits preserve access, capabilities, resource identity and bindings.
        return row, body.name, {**row.configuration, "name": body.name}
    connection = client.connection(request, tenant_id)
    if connection is None:
        raise HTTPException(409, "请先连接模型网关")
    config = configuration(tenant_id, connection.base_url, body, {}).model_dump(mode="json")
    return None, body.name, config


async def save(
    db: DB,
    tenant_id: UUID,
    model_name: str,
    change: tuple[CatalogModel | None, str, dict[str, Any]],
) -> None:
    row, name, config = change
    if row is None:
        db.add(
            CatalogModel(
                tenant_id=tenant_id, slug=model_name, name=name, configuration=config, version=1
            )
        )
    else:
        row.name, row.configuration = name, config
        row.version += 1
        row.updated_at = now()
    await db.flush()
