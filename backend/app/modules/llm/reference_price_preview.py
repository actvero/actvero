"""Exact administrator-confirmed currency preview, without market-rate lookup."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.modules.llm.catalog_schemas import RATE_FIELDS, Currency, TokenPrice
from app.modules.llm.schemas import Input


class ReferencePricePreviewInput(Input):
    price: TokenPrice
    target_currency: Currency
    fx_rate: str = Field(pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,15})?$", max_length=25)
    fx_date: date

    @model_validator(mode="after")
    def positive_rate(self) -> Self:
        rate = Decimal(self.fx_rate)
        if rate <= 0 or (self.price.currency == self.target_currency and rate != 1):
            raise ValueError("换算汇率须为正数，同币种汇率须为 1")
        return self


class ReferencePricePreview(BaseModel):
    price: TokenPrice
    fx_rate: str
    fx_date: date
    rounding_notes: list[str] = Field(default_factory=list)


def preview(body: ReferencePricePreviewInput) -> ReferencePricePreview:
    data = body.price.model_dump()
    notes = []
    with localcontext() as context:
        context.prec = 50
        for key in RATE_FIELDS:
            source = getattr(body.price, key)
            if source is None:
                continue
            converted = source * Decimal(body.fx_rate)
            rounded = converted.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            if rounded == 0 and converted != 0:
                raise ValueError("换算单价低于平台精度，不能按零价导入")
            if rounded != converted:
                notes.append(f"{key}：{converted:f} → {rounded:f}（四舍五入至 12 位小数）")
            data[key] = format(rounded, "f")
    data["currency"] = body.target_currency
    price = TokenPrice.model_validate(data)
    return ReferencePricePreview(
        price=price,
        fx_rate=body.fx_rate,
        fx_date=body.fx_date,
        rounding_notes=notes,
    )
