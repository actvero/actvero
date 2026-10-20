"""Serialized monetary admission and exact settlement in admission-time quota windows."""

import hmac
import re
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AcceptedRequestConflict
from app.modules.auth.service import now
from app.modules.desktop.errors import fail
from app.modules.llm.audio_schemas import SpeechInput, TranscriptionInput
from app.modules.llm.catalog_schemas import RATE_FIELDS, CatalogInput, TokenPrice
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import EmbeddingInput, RerankInput
from app.modules.llm.models import ModelCall, QuotaClock, UsageSettlement
from app.modules.llm.points import current_conversion, decimal_text
from app.modules.llm.settlement_evidence import evaluate
from app.modules.members.service import BusinessActor
from app.modules.quota.service import matching_policies


def amount_for(price: TokenPrice | None, usage: dict[str, Any]) -> Decimal | None:
    if price is None:
        return None
    keys = {
        "tokens": "input_tokens",
        "characters": "input_characters",
        "search_units": "search_units",
        "images": "image_count",
        "seconds": "audio_duration_ms",
    }
    quantity = usage.get(keys[price.metric])
    if quantity is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 80
        total = Decimal(quantity) * price.input / price.unit
        if price.metric == "seconds":
            total /= 1000
        if price.metric == "tokens":
            for key in RATE_FIELDS[1:]:
                count = usage.get(key + "_tokens")
                rate = getattr(price, key)
                if count is None and rate is not None or count and rate is None:
                    return None
                if count:
                    total += Decimal(count) * rate / 1000000
        return total


def points(value: Decimal, ratio: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 80
        return value * ratio


def exact_sum(values: Iterable[Decimal], initial: Decimal = Decimal(0)) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 80
        return sum(values, initial)


def reserve_amount(
    config: CatalogInput,
    body: ChatInput | EmbeddingInput | RerankInput | ImageInput | SpeechInput | TranscriptionInput,
) -> Decimal:
    price = config.budget_price
    if price is None:
        fail(409, "pricing_required", "模型尚未配置积分计价")
    with localcontext() as ctx:
        ctx.prec = 80
        if isinstance(body, TranscriptionInput):
            if price.metric != "seconds" or price.unit != 1:
                fail(409, "pricing_required", "转写需要每秒计价")
            return Decimal(body.duration_ms) * price.input / 1000
        if isinstance(body, SpeechInput):
            if price.metric != "characters":
                fail(409, "pricing_required", "语音合成需要字符计价")
            return Decimal(len(body.input)) * price.input / 1000000
        if isinstance(body, ImageInput):
            if price.metric != "images" or price.unit != 1:
                fail(409, "pricing_required", "图片生成需要每张计价")
            return price.input  # One image, explicit flat price; no guessed token usage.
        if isinstance(body, ChatInput):
            if not config.context_window or not config.max_output or price.output is None:
                fail(409, "limits_required", "模型尚未配置上下文、输出上限与价格")
            # Reserve a configured upper bound, never advertise a tokenizer guess as actual usage.
            input_rate = max(getattr(price, k) or Decimal(0) for k in RATE_FIELDS if k != "output")
            return (
                Decimal(body._input_reservation or config.context_window) * input_rate
                + Decimal(body.max_tokens or body.max_completion_tokens or config.max_output)
                * price.output
            ) / 1000000
        texts = (
            ([body.input] if isinstance(body.input, str) else body.input)
            if isinstance(body, EmbeddingInput)
            else [body.query, *body.documents]
        )
        if price.metric == "search_units":
            if config.retrieval.max_search_units is None:
                fail(409, "reservation_limit_required", "请配置每次重排的搜索单位预占上限")
            quantity = config.retrieval.max_search_units
        elif price.metric == "characters":
            quantity = sum(len(t) for t in texts)
        else:
            quantity = sum(len(t.encode("utf-8")) + 16 for t in texts)
        return Decimal(quantity) * price.input / 1000000


async def snapshot(
    db: AsyncSession, actor: BusinessActor, *, activate: bool = False, at: datetime | None = None
) -> dict[str, Any]:
    policies = await matching_policies(db, actor.tenant.id, actor.member.id)
    if not policies:
        return {"status": "unconfigured", "policy": None, "windows": []}
    policy = policies[0]
    clock = await db.get(QuotaClock, actor.member.id, populate_existing=True)
    saved = dict(clock.windows) if clock else {}
    stamp = at if at is not None else now()
    # Weekly windows span at most eight UTC days across timezone/DST changes.
    horizon = max([192, *[r["hours"] for r in policy.rules if r["kind"] == "fixed_hours"]])
    entries = list(
        await db.scalars(
            select(UsageSettlement).where(
                UsageSettlement.tenant_id == actor.tenant.id,
                UsageSettlement.member_id == actor.member.id,
                UsageSettlement.status.in_(("reserved", "review", "settled")),
                UsageSettlement.created_at >= stamp - timedelta(hours=horizon),
            )
        )
    )
    windows = []
    for rule in policy.rules:
        start: datetime | None
        end: datetime | None
        if rule["kind"] == "calendar_week":
            local = stamp.astimezone(ZoneInfo(rule["timezone"]))
            date = local.date() - timedelta(days=(local.weekday() - rule["week_start"]) % 7)
            start = datetime.combine(date, time(), local.tzinfo)
            end = start + timedelta(days=7)
        else:
            hours = rule["hours"]
            key = str(hours)
            old = saved.get(key)
            start = datetime.fromisoformat(old["start"]) if old else None
            end = start + timedelta(hours=hours) if start else None
            previous_end = end
            if end is not None and end <= stamp:
                start = end = None
            if start is None:
                # Switching away from a duration and back must still include
                # calls admitted since its last window ended. Normal expiry
                # cannot resurrect calls belonging to the finished window.
                recent = [
                    e.created_at
                    for e in entries
                    if stamp - timedelta(hours=hours) < e.created_at <= stamp
                    and (previous_end is None or e.created_at >= previous_end)
                ]
                if recent:
                    start = min(recent)
                    end = start + timedelta(hours=hours)
            if start is None and activate:
                start, end = stamp, stamp + timedelta(hours=hours)
            if start is not None and activate:
                saved[key] = {"start": start.isoformat()}
        in_window = [
            e
            for e in entries
            if start is not None and end is not None and start <= e.created_at < end
        ]
        used = exact_sum(
            (
                points(e.amount, e.ratio)
                for e in in_window
                if e.status == "settled" and e.amount is not None
            ),
            Decimal(0),
        )
        held = exact_sum(
            points(e.reserved_amount, e.ratio)
            for e in in_window
            if e.status in ("reserved", "review")
        )
        cap = Decimal(rule["points"])
        windows.append(
            {
                "rule": rule,
                "used": decimal_text(used),
                "reserved": decimal_text(held),
                "remaining": decimal_text(
                    max(Decimal(0), exact_sum([used.copy_negate(), held.copy_negate()], cap))
                ),
                "started_at": start.astimezone(UTC).isoformat() if start else None,
                "resets_at": end.astimezone(UTC).isoformat() if end else None,
            }
        )
    if activate:
        if clock is None:
            clock = QuotaClock(member_id=actor.member.id, tenant_id=actor.tenant.id, windows=saved)
            db.add(clock)
        else:
            clock.windows = saved
    return {
        "status": "active",
        "policy": {"id": str(policy.id), "name": policy.name, "version": policy.version},
        "windows": windows,
    }


async def check_request(
    db: AsyncSession, actor: BusinessActor, idempotency_key: str | None, fingerprint: str | None
) -> None:
    """Call under the tenant lock after current model and operation authorization."""
    if idempotency_key is None:
        return
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
        fail(422, "invalid_idempotency_key", "无效幂等标识")
    existing = await db.scalar(
        select(UsageSettlement).where(
            UsageSettlement.tenant_id == actor.tenant.id,
            UsageSettlement.member_id == actor.member.id,
            UsageSettlement.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return
    conflict = bool(
        existing.request_fingerprint
        and (
            fingerprint is None
            or not hmac.compare_digest(existing.request_fingerprint, fingerprint)
        )
    )
    log = await db.get(ModelCall, existing.id, populate_existing=True)
    raise AcceptedRequestConflict(
        "idempotency_conflict" if conflict else "duplicate_request",
        "此幂等标识已用于不同请求，不能重复发送"
        if conflict
        else "此请求已经受理，请按调用标识查询本人用量记录",
        call_id=str(existing.id),
        call_status=log.status if log else "unknown",
        settlement_status=existing.status,
    )


async def reserve(
    db: AsyncSession,
    actor: BusinessActor,
    log: ModelCall,
    config: CatalogInput,
    body: ChatInput | EmbeddingInput | RerankInput | ImageInput | SpeechInput | TranscriptionInput,
    idempotency_key: str | None,
    *,
    request_fingerprint: str | None = None,
) -> None:
    await check_request(db, actor, idempotency_key, request_fingerprint)
    conversion = await current_conversion(db, actor.tenant.id)
    if conversion is None or config.budget_price is None:
        fail(409, "pricing_required", "管理员尚未完成积分计价")
    if config.budget_price.currency != conversion.currency:
        fail(409, "currency_mismatch", "模型计价币种与积分换算不一致")
    amount = reserve_amount(config, body)
    if config.routing.mode == "auto" and config.routing.fallback and config.routing.retry_uncertain:
        # Opting into uncertain retries must also cover their possible additional consumption.
        amount = points(amount, Decimal(config.routing.max_attempts))
    admitted_at = now()
    state = await snapshot(db, actor, activate=True, at=admitted_at)
    if state["status"] != "active":
        fail(409, "quota_policy_required", "管理员尚未配置额度策略")
    needed = points(amount, conversion.points_per_currency)
    for window in state["windows"]:
        if needed > Decimal(window["remaining"]):
            fail(429, "quota_exceeded", "积分额度不足，请降低输出上限或等待额度恢复")
    # One instant defines the accepted request and its quota membership, even
    # if a flush/commit crosses an hourly or weekly boundary.
    log.created_at = admitted_at
    await db.flush()  # call FK exists before the reservation
    db.add(
        UsageSettlement(
            id=log.id,
            tenant_id=actor.tenant.id,
            member_id=actor.member.id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            currency=conversion.currency,
            conversion_id=conversion.id,
            ratio=conversion.points_per_currency,
            reserved_amount=amount,
            price=config.budget_price.model_dump(mode="json"),
            policy_snapshot=state,
            usage={},
            status="reserved",
            reason="",
            created_at=admitted_at,
        )
    )


async def complete(
    db: AsyncSession,
    call_id: UUID,
    usage: dict[str, Any],
    *,
    delivered: bool,
    certainly_unused: bool = False,
    expected_version: int = 1,
    manual: bool = False,
    recover_interrupted: bool = False,
) -> bool:
    row = await db.get(UsageSettlement, call_id, populate_existing=True, with_for_update=True)
    # Only the outbox's provisional interrupted-call recovery may replace its
    # own first review. A manual reconciliation advances the version/status and
    # remains authoritative; other review decisions are still sticky.
    allowed = ("reserved", "review") if manual or recover_interrupted else ("reserved",)
    if row is None or row.status not in allowed or row.version != expected_version:
        return False
    price = TokenPrice.model_validate(row.price)
    if manual:
        amount = amount_for(price, usage) if delivered else None
        row.usage = usage
        row.evidence = {
            **row.evidence,
            "manual": {
                "source": "verified_manual",
                "version": expected_version,
                "action": "release" if certainly_unused else "settle",
            },
        }
    else:
        log = await db.get(ModelCall, call_id, populate_existing=True)
        if certainly_unused and log is not None and not log.attempts and not delivered:
            # A completed Router rejection before its deployment hook proves no
            # dispatch. A crashed/pending intent never sets this flag.
            row.usage = {}
            row.evidence = {
                "evidence_version": 1,
                "decision": "release",
                "reason": "sdk_no_dispatch",
            }
            row.amount, row.status, row.settled_at = Decimal(0), "released", now()
            row.version += 1
            return True
        decision = evaluate(price, log.attempts if log else [], delivered=delivered)
        amount = amount_for(price, decision.usage) if decision.action == "settle" else None
        certainly_unused = decision.action == "release"
        row.usage = decision.usage
        row.evidence = decision.metadata
    if amount is not None:
        row.amount, row.status, row.settled_at = amount, "settled", now()
    elif certainly_unused:
        row.amount, row.status, row.settled_at = Decimal(0), "released", now()
    else:
        row.status = "review"
    row.version += 1
    return True
