from decimal import Decimal, localcontext
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB
from app.modules.llm.catalog_schemas import (
    RATE_FIELDS,
    PointConversionInput,
    PointConversionSettings,
    PointConversionView,
    PointPrice,
    TokenPrice,
)
from app.modules.llm.models import PointConversion, UsageSettlement
from app.modules.llm.router import administrator
from app.modules.members.service import record

router = APIRouter(prefix="/api/v1/llm", tags=["llm-points"])


def decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


async def current_conversion(db: AsyncSession, tenant_id: UUID) -> PointConversion | None:
    row: PointConversion | None = await db.scalar(
        select(PointConversion)
        .where(PointConversion.tenant_id == tenant_id)
        .order_by(PointConversion.version.desc())
        .limit(1)
    )
    return row


def conversion_view(row: PointConversion) -> PointConversionView:
    return PointConversionView.model_validate(
        {
            "id": row.id,
            "version": row.version,
            "currency": row.currency,
            "points_per_currency": decimal_text(row.points_per_currency),
            "created_at": row.created_at,
        }
    )


def point_price(
    price: TokenPrice | None, conversion: PointConversion | None, amount: Decimal | None = None
) -> PointPrice:
    result = PointPrice(
        status="no_price", conversion=conversion_view(conversion) if conversion else None
    )
    if price is None:
        return result
    result.currency, result.metric = price.currency, price.metric
    result.unit = 1 if price.metric in {"images", "seconds"} else 1000000
    if conversion is None:
        result.status = "unconfigured"
        return result
    if price.currency != conversion.currency:
        result.status = "currency_mismatch"
        return result
    result.status = "ready"
    with localcontext() as ctx:
        ctx.prec = 80
        result.rates = {
            key: decimal_text(rate * conversion.points_per_currency)
            if (rate := getattr(price, key)) is not None
            else None
            for key in RATE_FIELDS
        }
        if amount is not None:
            result.total = decimal_text(amount * conversion.points_per_currency)
    return result


@router.get("/point-conversion", response_model=PointConversionSettings)
async def settings(request: Request, db: DB) -> PointConversionSettings:
    actor = await administrator(request, db)
    row = await current_conversion(db, actor.tenant.id)
    return PointConversionSettings(conversion=conversion_view(row) if row else None)


@router.put("/point-conversion", response_model=PointConversionSettings)
async def configure(
    request: Request, db: DB, body: PointConversionInput, _: Mutation
) -> PointConversionSettings:
    actor = await administrator(request, db, write=True)
    current = await current_conversion(db, actor.tenant.id)
    if body.version != (current.version if current else 0):
        raise HTTPException(409, "积分换算已被修改，请关闭并重新打开")
    if (
        current
        and current.currency != body.currency
        and await db.scalar(
            select(UsageSettlement.id).where(UsageSettlement.tenant_id == actor.tenant.id).limit(1)
        )
    ):
        raise HTTPException(409, "已有消费账本，不能直接更换计价币种")
    ratio = Decimal(body.points_per_currency)
    if current and current.currency == body.currency and current.points_per_currency == ratio:
        return PointConversionSettings(conversion=conversion_view(current))
    row = PointConversion(
        tenant_id=actor.tenant.id,
        currency=body.currency,
        points_per_currency=ratio,
        version=body.version + 1,
    )
    db.add(row)
    await db.flush()
    record(
        db,
        actor,
        "llm.points.configure",
        row.id,
        "模型积分换算",
        {
            "version": str(row.version),
            "currency": row.currency,
            "points_per_currency": decimal_text(ratio),
        },
    )
    result = PointConversionSettings(conversion=conversion_view(row))
    await db.commit()
    return result


@router.post("/point-prices/preview", response_model=PointPrice)
async def preview(request: Request, db: DB, body: TokenPrice, _: Mutation) -> PointPrice:
    actor = await administrator(request, db)
    return point_price(body, await current_conversion(db, actor.tenant.id))
