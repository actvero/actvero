"""A bounded, credential-free models.dev snapshot; never an inference provider."""

import asyncio
import ipaddress
import json
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.outbound import PinnedTransport, resolve
from app.modules.auth.service import DB, now
from app.modules.auth.service import provider as auth_provider
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    Declaration,
    ModelCapabilities,
    ReasoningOption,
    TokenPrice,
)
from app.modules.llm.reference_quotes import QuoteSnapshot
from app.modules.llm.router import administrator

URL = "https://models.dev/api.json"
MAX_BYTES = 16_000_000
TTL = 3600
MAX_STALE = 7 * 86400
router = APIRouter(prefix="/api/v1/llm", tags=["llm-models"])


class ReferenceModel(BaseModel):
    provider: str
    provider_name: str
    model_id: str
    name: str
    context_window: int | None
    max_output: int | None
    capabilities: ModelCapabilities
    reasoning_options: list[ReasoningOption]
    price: TokenPrice | None
    price_notes: list[str]
    canonical_model_id: str | None = None
    developer: str | None = None
    developer_name: str | None = None
    family: str | None = None
    max_input: int | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    temperature: Declaration = "unknown"
    release_date: str | None = None
    last_updated: str | None = None
    knowledge: str | None = None
    status: Literal["alpha", "beta", "deprecated"] | None = None
    source_url: str | None = None
    price_importable: bool = False
    price_conditions: list[str] = Field(default_factory=list)
    quote_snapshot: QuoteSnapshot | None = None
    quote_items: list["QuoteItem"] = Field(default_factory=list)


class QuoteItem(BaseModel):
    key: str
    value: str
    status: Literal["compatible", "needs_details", "reference_only", "invalid"]
    reason: str


class ReferenceFacet(BaseModel):
    id: str
    name: str


class ReferenceFacets(BaseModel):
    providers: list[ReferenceFacet] = Field(default_factory=list)
    developers: list[ReferenceFacet] = Field(default_factory=list)


class ReferencePage(BaseModel):
    items: list[ReferenceModel]
    total: int
    fetched_at: datetime
    stale: bool
    skipped: int
    facets: ReferenceFacets = Field(default_factory=ReferenceFacets)
    page_size: int = 20


def declaration(value: Any) -> Declaration:
    return "supported" if value is True else "unsupported" if value is False else "unknown"


def safe_document_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or "." not in host
            or host.endswith((".local", ".internal"))
        ):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def source_url(model: dict[str, Any], provider: dict[str, Any]) -> str | None:
    links = model.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and link.get("type") in ("docs", "model_card"):
                if url := safe_document_url(link.get("url")):
                    return url
    return safe_document_url(provider.get("doc"))


def simple_text(value: Any) -> str | None:
    return value[:200] if isinstance(value, str) and value else None


def modalities_of(value: Any) -> list[str]:
    allowed = {"text", "audio", "image", "video", "pdf"}
    return (
        [item for item in value if isinstance(item, str) and item in allowed]
        if isinstance(value, list)
        else []
    )


def decimal_text(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=decimal_text)


def bounded_quote(cost: Any) -> tuple[dict[str, Any], list[QuoteItem]]:
    """Keep cost data as inert JSON, dropping only malformed or oversized items."""
    if not isinstance(cost, dict):
        return {}, []
    raw: dict[str, Any] = {}
    items: list[QuoteItem] = []
    if len(cost) > 64:
        return {}, [QuoteItem(key="cost", value="—", status="invalid", reason="报价项目过多")]

    def safe(value: Any, depth: int = 0) -> Any:
        if depth > 5:
            raise ValueError("报价嵌套过深")
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (Decimal, int)) and not isinstance(value, bool):
            number = Decimal(value)
            if not number.is_finite() or abs(number) > Decimal("1000000000"):
                raise ValueError("数值超出范围")
            return format(number, "f")
        if isinstance(value, str) and len(value) <= 200:
            return value
        if isinstance(value, list) and len(value) <= 30:
            return [safe(item, depth + 1) for item in value]
        if isinstance(value, dict) and len(value) <= 30:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 64:
                    raise ValueError("报价字段无效")
                result[key] = safe(item, depth + 1)
            return result
        raise ValueError("报价内容无效或过长")

    labels = {
        "input": "输入",
        "output": "输出",
        "cache_read": "缓存读取",
        "cache_write": "缓存写入",
        "tiers": "阶梯",
        "context_over_200k": "长上下文",
    }
    for key, value in cost.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 64:
            continue
        if any(
            secret in key.casefold()
            for secret in ("secret", "password", "api_key", "authorization")
        ):
            continue
        try:
            normalized = safe(value)
            if len(json.dumps(normalized, ensure_ascii=False)) > 4000:
                raise ValueError("报价项目过长")
        except (ValueError, InvalidOperation):
            items.append(
                QuoteItem(key=key, value="—", status="invalid", reason="该报价项目格式无效，未保存")
            )
            continue
        raw[key] = normalized
        status: Literal["compatible", "needs_details", "reference_only", "invalid"]
        reason: str
        if key in ("input", "output", "cache_read"):
            try:
                number = Decimal(normalized) if isinstance(normalized, str) else Decimal("NaN")
                if not number.is_finite() or number < 0 or number > 1000000000:
                    raise InvalidOperation
                if number != number.quantize(Decimal("0.000000000001")):
                    status, reason = "reference_only", "超过当前每百万 Token 单价的 12 位小数精度"
                else:
                    status, reason = (
                        "compatible",
                        "同为 Token 计量；采用前须补齐基础输入/输出并核对币种与用途",
                    )
            except (InvalidOperation, ValueError):
                status, reason = "invalid", "不是有效的非负 Token 单价"
        elif key == "cache_write":
            status, reason = "needs_details", "缺少缓存时长，不能映射到 5 分钟或 1 小时"
        else:
            status, reason = "reference_only", "当前计量规则无法完整表达此条件"
        items.append(
            QuoteItem(
                key=key,
                value=(normalized if isinstance(normalized, str) else decimal_text(normalized))[
                    :500
                ],
                status=status,
                reason=f"{labels.get(key, key)}：{reason}",
            )
        )
    for key in ("input", "output"):
        if key not in cost:
            items.append(
                QuoteItem(
                    key=key, value="—", status="invalid", reason="基础费率未提供；不能作为完整价格"
                )
            )
    if len(json.dumps(raw, ensure_ascii=False)) > 12000:
        return {}, [
            QuoteItem(key="cost", value="—", status="invalid", reason="报价整体过长，未保存")
        ]
    return raw, items


def price_conditions(cost: Any, price: TokenPrice | None) -> list[str]:
    if not isinstance(cost, dict):
        return []
    conditions: list[str] = []
    labels = {
        "reasoning": "独立思考费率",
        "cache_write": "缓存写入费率（未给出可映射时长）",
        "input_audio": "音频输入费率",
        "output_audio": "音频输出费率",
        "tiers": "上下文阶梯费率",
        "context_over_200k": "超过 200K 上下文费率",
    }
    for key, value in cost.items():
        if key in ("input", "output", "cache_read"):
            continue
        conditions.append(
            f"{labels.get(key, '其他费率 ' + key)}：{decimal_text(value)}；当前价格结构不能完整表达"
        )
    if "input" not in cost or "output" not in cost or price is None:
        conditions.append("基础输入和输出 Token 价不完整或无效，不能导入完整价格")
    return conditions


def importable_price(cost: Any, price: TokenPrice | None) -> bool:
    return (
        isinstance(cost, dict)
        and price is not None
        and price.output is not None
        and set(cost) <= {"input", "output", "cache_read"}
    )


def price_reference(cost: Any) -> tuple[TokenPrice | None, list[str]]:
    if not isinstance(cost, dict):
        return None, []
    notes = []
    if any(key in cost for key in ("tiers", "context_over_200k")):
        notes.append("含阶梯价格，基础单价仅供浏览，不能作为完整价格导入。")
    if any(
        key not in {"input", "output", "cache_read", "tiers", "context_over_200k"} for key in cost
    ):
        notes.append("含额外媒体、推理或缓存写入费率，不能作为完整价格导入。")
    try:
        # Decimal is constructed by json.loads before any binary float conversion.
        fields = {
            k: format(cost[k], "f") if isinstance(cost[k], Decimal) else str(cost[k])
            for k in ("input", "output", "cache_read")
            if k in cost
        }
        price = TokenPrice.model_validate({"currency": "USD", "unit": 1000000, **fields})
        return price, notes
    except ValidationError:
        return None, ["缺少可用的输入／输出参考价。"]


def parse_catalog(
    payload: bytes, *, fetched_at: datetime | None = None
) -> tuple[list[ReferenceModel], int]:
    data = json.loads(payload, parse_float=Decimal)
    fetched_at = fetched_at or now()
    if not isinstance(data, dict) or len(data) > 2000:
        raise ValueError("Invalid provider directory")
    models = []
    skipped = 0
    count = 0
    provider_names = {
        provider_id: provider["name"][:100]
        for provider_id, provider in data.items()
        if isinstance(provider_id, str)
        and isinstance(provider, dict)
        and isinstance(provider.get("name"), str)
    }
    for provider_id, provider in data.items():
        if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
            skipped += 1
            continue
        if not 1 <= len(provider_id) <= 100 or not isinstance(provider.get("name"), str):
            skipped += len(provider["models"])
            continue
        for model_id, model in provider["models"].items():
            count += 1
            if count > 100000:
                raise ValueError("Too many models")
            try:
                if not isinstance(model, dict):
                    raise ValueError("Invalid model")
                limits = model.get("limit") or {}
                modalities = model.get("modalities") or {}
                if not isinstance(limits, dict) or not isinstance(modalities, dict):
                    raise ValueError("Invalid limits or modalities")
                vision = "unknown"
                if isinstance(modalities.get("input"), list):
                    vision = "supported" if "image" in modalities["input"] else "unsupported"
                config = CatalogInput.model_validate(
                    {
                        "slug": model_id,
                        "name": model.get("name"),
                        "context_window": limits.get("context"),
                        "max_output": limits.get("output"),
                        "capabilities": {
                            "tools": declaration(model.get("tool_call")),
                            "structured_output": declaration(model.get("structured_output")),
                            "vision": vision,
                            "reasoning": declaration(model.get("reasoning")),
                        },
                        "reasoning_options": model.get("reasoning_options") or [],
                    }
                )
                cost = model.get("cost")
                raw_cost, quote_items = bounded_quote(cost)
                price, notes = price_reference(cost)
                conditions = price_conditions(raw_cost, price)
                quote_snapshot = (
                    QuoteSnapshot(
                        provider=provider_id,
                        model_id=model_id,
                        fetched_at=fetched_at,
                        source_updated_at=(simple_text(model.get("last_updated")) or "")[:100]
                        or None,
                        currency="USD",
                        unit=1000000,
                        metric="tokens",
                        source_url=source_url(model, provider),
                        raw_cost=raw_cost,
                        conditions=[item[:1000] for item in conditions[:32]],
                    )
                    if raw_cost
                    else None
                )
                canonical = simple_text(model.get("canonical_model_id"))
                parts = canonical.split("/", 1) if canonical else []
                lab = parts[0] if len(parts) == 2 and all(parts) else None
                if lab is None:
                    canonical = None
                models.append(
                    ReferenceModel(
                        provider=provider_id,
                        provider_name=provider["name"][:100],
                        model_id=model_id,
                        name=config.name,
                        context_window=config.context_window,
                        max_output=config.max_output,
                        capabilities=config.capabilities,
                        reasoning_options=config.reasoning_options,
                        price=price,
                        price_notes=notes,
                        canonical_model_id=canonical,
                        developer=lab,
                        developer_name=provider_names.get(lab, lab) if lab else None,
                        family=simple_text(model.get("family")),
                        max_input=limits.get("input"),
                        input_modalities=modalities_of(modalities.get("input")),
                        output_modalities=modalities_of(modalities.get("output")),
                        temperature=declaration(model.get("temperature")),
                        release_date=simple_text(model.get("release_date")),
                        last_updated=simple_text(model.get("last_updated")),
                        knowledge=simple_text(model.get("knowledge")),
                        status=model.get("status")
                        if model.get("status") in ("alpha", "beta", "deprecated")
                        else None,
                        source_url=source_url(model, provider),
                        price_importable=importable_price(cost, price),
                        price_conditions=conditions,
                        quote_snapshot=quote_snapshot,
                        quote_items=quote_items,
                    )
                )
            except (ValueError, TypeError, AttributeError):
                skipped += 1
    if not models:
        raise ValueError("Empty or invalid catalog")
    models.sort(key=lambda m: (m.provider_name.casefold(), m.name.casefold(), m.model_id))
    return models, skipped


async def fetch_catalog(settings: Settings) -> bytes:
    transport = PinnedTransport(
        URL, lambda url: resolve(url, [], dns=settings.llm_public_dns), max_bytes=MAX_BYTES
    )
    async with asyncio.timeout(20):
        async with httpx2.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=15
        ) as client:
            async with client.stream(
                "GET", URL, headers={"Accept": "application/json", "Accept-Encoding": "identity"}
            ) as response:
                if response.status_code != 200:
                    raise ValueError("Catalog unavailable")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Compressed catalog rejected")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ValueError("Catalog too large")
                    body.extend(chunk)
                return bytes(body)


class ReferenceCache:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.models: list[ReferenceModel] = []
        self.fetched_at: datetime | None = None
        self.loaded_at = 0.0
        self.retry_at = 0.0
        self.skipped = 0

    async def get(self, settings: Settings) -> tuple[list[ReferenceModel], datetime, bool, int]:
        async with self.lock:
            clock = time.monotonic()
            if clock >= self.retry_at and (not self.models or clock - self.loaded_at >= TTL):
                try:
                    payload = await fetch_catalog(settings)
                    fetched_at = now()
                    models, skipped = parse_catalog(payload, fetched_at=fetched_at)
                    self.models, self.skipped = models, skipped
                    self.loaded_at, self.fetched_at = time.monotonic(), fetched_at
                except (httpx2.HTTPError, HTTPException, TimeoutError, ValueError, OSError):
                    self.retry_at = time.monotonic() + 60
            age = time.monotonic() - self.loaded_at
            if not self.models or self.fetched_at is None or age > MAX_STALE:
                raise HTTPException(503, "公开模型目录暂不可用，可稍后重试或手动填写")
            return self.models, self.fetched_at, age >= TTL, self.skipped


def facets_for(models: list[ReferenceModel]) -> ReferenceFacets:
    providers = {model.provider: model.provider_name for model in models}
    developers = {
        model.developer: model.developer_name or model.developer
        for model in models
        if model.developer
    }
    return ReferenceFacets(
        providers=[
            ReferenceFacet(id=key, name=value)
            for key, value in sorted(
                providers.items(), key=lambda item: (item[1].casefold(), item[0])
            )
        ],
        developers=[
            ReferenceFacet(id=key, name=value)
            for key, value in sorted(
                developers.items(), key=lambda item: (item[1].casefold(), item[0])
            )
        ],
    )


def select_models(
    models: list[ReferenceModel],
    *,
    q: str = "",
    provider: str | None = None,
    developer: str | None = None,
    tools: Declaration | None = None,
    structured_output: Declaration | None = None,
    reasoning: Declaration | None = None,
    input_modality: str | None = None,
    output_modality: str | None = None,
    min_context: int | None = None,
    price: Literal["all", "available", "importable"] = "all",
    status: Literal["all", "exclude_deprecated", "alpha", "beta", "deprecated"] = "all",
    sort: Literal[
        "relevance", "name", "context", "input_price", "output_price", "released"
    ] = "relevance",
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
) -> list[ReferenceModel]:
    terms = q.casefold().split()

    def matches(model: ReferenceModel) -> bool:
        searchable = " ".join(
            (
                model.provider,
                model.provider_name,
                model.model_id,
                model.name,
                model.canonical_model_id or "",
                model.developer_name or "",
                model.family or "",
            )
        ).casefold()
        return (
            all(term in searchable for term in terms)
            and (provider is None or model.provider == provider)
            and (developer is None or model.developer == developer)
            and (tools is None or model.capabilities.tools == tools)
            and (
                structured_output is None
                or model.capabilities.structured_output == structured_output
            )
            and (reasoning is None or model.capabilities.reasoning == reasoning)
            and (input_modality is None or input_modality in model.input_modalities)
            and (output_modality is None or output_modality in model.output_modalities)
            and (
                min_context is None
                or model.context_window is not None
                and model.context_window >= min_context
            )
            and (
                price == "all"
                or price == "available"
                and model.price is not None
                or price == "importable"
                and model.price_importable
            )
            and (
                status == "all"
                or status == "exclude_deprecated"
                and model.status != "deprecated"
                or model.status == status
            )
        )

    selected = [model for model in models if matches(model)]

    def name_key(model: ReferenceModel) -> tuple[str, str, str]:
        return model.name.casefold(), model.provider_name.casefold(), model.model_id.casefold()

    def relevance_key(model: ReferenceModel) -> tuple[int, tuple[str, str, str]]:
        exact_preferred = bool(
            preferred_model and model.model_id.casefold() == preferred_model.casefold()
        )
        canonical_preferred = bool(
            preferred_model
            and model.canonical_model_id
            and model.canonical_model_id.casefold() == preferred_model.casefold()
        )
        same_provider = bool(preferred_provider and model.provider == preferred_provider)
        query_exact = bool(
            q.strip()
            and q.strip().casefold()
            in {
                model.model_id.casefold(),
                model.name.casefold(),
                (model.canonical_model_id or "").casefold(),
            }
        )
        if same_provider and (exact_preferred or canonical_preferred):
            rank = 0
        elif exact_preferred or canonical_preferred:
            rank = 1
        elif query_exact:
            rank = 2
        elif same_provider:
            rank = 3
        else:
            rank = 4
        return rank, name_key(model)

    if sort == "relevance":
        return sorted(selected, key=relevance_key)
    if sort == "name":
        return sorted(selected, key=name_key)
    if sort == "context":
        return sorted(
            selected,
            key=lambda model: (
                model.context_window is None,
                -(model.context_window or 0),
                name_key(model),
            ),
        )
    if sort in ("input_price", "output_price"):
        field = "input" if sort == "input_price" else "output"
        return sorted(
            selected,
            key=lambda model: (
                not model.price_importable or model.price is None,
                getattr(model.price, field)
                if model.price_importable and model.price
                else Decimal(0),
                name_key(model),
            ),
        )
    return sorted(
        selected,
        key=lambda model: (
            model.release_date is None,
            -(
                int(model.release_date[:4])
                if model.release_date and model.release_date[:4].isdigit()
                else 0
            ),
            -(
                int(model.release_date[5:7])
                if model.release_date and model.release_date[5:7].isdigit()
                else 0
            ),
            -(
                int(model.release_date[8:10])
                if model.release_date and model.release_date[8:10].isdigit()
                else 0
            ),
            name_key(model),
        ),
    )


def page_models(
    filtered: list[ReferenceModel],
    all_models: list[ReferenceModel],
    *,
    page: int,
    page_size: int,
    fetched_at: datetime,
    stale: bool,
    skipped: int,
) -> ReferencePage:
    return ReferencePage(
        items=filtered[(page - 1) * page_size : page * page_size],
        total=len(filtered),
        fetched_at=fetched_at,
        stale=stale,
        skipped=skipped,
        facets=facets_for(all_models),
        page_size=page_size,
    )


@router.get("/reference-models", response_model=ReferencePage, summary="管理员查询公开模型参考资料")
async def listing(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    provider: str | None = Query(default=None, max_length=100),
    developer: str | None = Query(default=None, max_length=100),
    tools: Declaration | None = None,
    structured_output: Declaration | None = None,
    reasoning: Declaration | None = None,
    input_modality: str | None = Query(default=None, max_length=30),
    output_modality: str | None = Query(default=None, max_length=30),
    min_context: int | None = Query(default=None, ge=1),
    price: Literal["all", "available", "importable"] = "all",
    status: Literal["all", "exclude_deprecated", "alpha", "beta", "deprecated"] = "all",
    sort: Literal[
        "relevance", "name", "context", "input_price", "output_price", "released"
    ] = "relevance",
    preferred_provider: str | None = Query(default=None, max_length=100),
    preferred_model: str | None = Query(default=None, max_length=200),
) -> ReferencePage:
    await administrator(request, db)
    if not hasattr(request.app.state, "llm_reference_cache"):
        request.app.state.llm_reference_cache = ReferenceCache()
    cache: ReferenceCache = request.app.state.llm_reference_cache
    models, fetched_at, stale, skipped = await cache.get(auth_provider(request).settings)
    filtered = select_models(
        models,
        q=q,
        provider=provider,
        developer=developer,
        tools=tools,
        structured_output=structured_output,
        reasoning=reasoning,
        input_modality=input_modality,
        output_modality=output_modality,
        min_context=min_context,
        price=price,
        status=status,
        sort=sort,
        preferred_provider=preferred_provider,
        preferred_model=preferred_model,
    )
    return page_models(
        filtered,
        models,
        page=page,
        page_size=page_size,
        fetched_at=fetched_at,
        stale=stale,
        skipped=skipped,
    )
