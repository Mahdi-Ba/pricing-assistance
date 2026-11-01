"""Deterministic Persian explanations, one template per reason code and flag (task 9.4).

The text is built only from the engine result and the reference offer, so it can never
disagree with the numbers. An optional LLM rephrasing (llm-assistance) must keep every number;
otherwise this text is shown.
"""

from dataclasses import dataclass
from datetime import datetime

from pricing_assistant.core.persian import jalali_datetime, toman
from pricing_assistant.pricing.engine import Flag, Reason, RecommendationResult


@dataclass(frozen=True, slots=True)
class ReferenceOffer:
    seller: str | None
    source_name: str
    observed_at: datetime


def _competitor(ref: ReferenceOffer | None) -> str:
    if ref is None:
        return "رقیب"
    seller = ref.seller or ref.source_name
    if ref.seller and ref.source_name and ref.seller != ref.source_name:
        return f"«{seller}» در {ref.source_name}"
    return f"«{seller}»"


def _market(result: RecommendationResult, ref: ReferenceOffer | None) -> str:
    assert result.market_ref_rial is not None  # noqa: S101 - only called with a market reference
    when = f" (مشاهده: {jalali_datetime(ref.observed_at)})" if ref else ""
    return (
        f"کمترین قیمت معتبر بازار {toman(result.market_ref_rial)} از {_competitor(ref)}{when} است"
    )


def explain(result: RecommendationResult, ref: ReferenceOffer | None = None) -> str:
    floor = toman(result.floor_rial) if result.floor_rial is not None else None
    reason = result.reason
    parts: list[str]
    if reason is Reason.ABOVE_MARKET:
        parts = [
            f"{_market(result, ref)}؛ قیمت فعلی ما بالاتر است.",
            f"پیشنهاد: کاهش به {toman(result.suggested_price_rial or 0)}؛ کف سود {floor} است.",
        ]
    elif reason is Reason.BELOW_MARKET:
        parts = [
            f"{_market(result, ref)}؛ قیمت فعلی ما پایین‌تر از دامنه تحمل است.",
            f"پیشنهاد: افزایش به {toman(result.suggested_price_rial or 0)}؛ کف سود {floor} است.",
        ]
    elif reason is Reason.CAPPED_BY_CEILING:
        parts = [
            f"{_market(result, ref)}.",
            f"پیشنهاد: افزایش تا سقف تعیین‌شده {toman(result.ceiling_rial or 0)}؛ کف سود {floor} است.",
        ]
    elif reason is Reason.WITHIN_TOLERANCE:
        parts = [f"{_market(result, ref)}؛ قیمت ما در دامنه تحمل است و تغییری پیشنهاد نمی‌شود."]
    elif reason is Reason.NO_CHANGE_AFTER_ROUNDING:
        parts = [f"{_market(result, ref)}؛ پس از گرد کردن، قیمت پیشنهادی با قیمت فعلی برابر است."]
    elif reason is Reason.MARKET_BELOW_FLOOR:
        parts = [
            f"{_market(result, ref)} که از کف سود {floor} پایین‌تر است.",
            "هیچ قیمتی پیشنهاد نمی‌شود؛ تصمیم با کارشناس است.",
        ]
    else:
        parts = [_INSUFFICIENT[reason]]
    if Flag.UNDERCUT_LOST in result.flags:
        parts.append("توجه: پس از گرد کردن، قیمت پیشنهادی دیگر پایین‌تر از قیمت بازار نیست.")
    if Flag.LIMITED_BY_FLOOR in result.flags:
        parts.append("کاهش بیشتر به‌خاطر کف سود ممکن نیست.")
    if result.excluded_outlier_ids:
        parts.append(
            "پیشنهاد(های) بسیار ارزان‌تر از میانه بازار تا تأیید کارشناس در محاسبه لحاظ نشده‌اند."
        )
    return " ".join(parts)


_INSUFFICIENT: dict[Reason, str] = {
    Reason.MISSING_COST: "داده ناکافی: بهای تمام‌شده معتبر برای این کالا ثبت نشده است.",
    Reason.TAX_BASIS_UNSET: "داده ناکافی: قاعده سود پیش‌فرض با نرخ مالیات بر ارزش افزوده تعریف نشده است.",
    Reason.MISSING_CURRENT_PRICE: "داده ناکافی: قیمت فعلی این کالا در فروشگاه ثبت نشده است.",
    Reason.PENDING_REVIEW: "داده ناکافی: تطبیق پیشنهادهای رقبا هنوز تأیید نشده است؛ صف تطبیق را بررسی کنید.",
    Reason.STALE_EVIDENCE: "داده ناکافی: قیمت‌های رقبا قدیمی است؛ منبع را بررسی کنید.",
    Reason.BELOW_MIN_OFFERS: "داده ناکافی: تعداد پیشنهادهای معتبر کمتر از حداقل تعیین‌شده است.",
    Reason.NO_OFFERS: "داده ناکافی: پیشنهاد معتبر و هم‌شرایطی از رقبا یافت نشد.",
}
