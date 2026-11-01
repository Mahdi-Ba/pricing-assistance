"""Snapshot tests: one deterministic explanation per reason code and flag (task 9.4)."""

import pytest

from pricing_assistant.pricing.engine import Flag, Outcome, Reason, RecommendationResult
from pricing_assistant.pricing.explain import ReferenceOffer, explain
from tests.support.engine import NOW

REF = ReferenceOffer(seller="لیون کامپیوتر", source_name="ترب", observed_at=NOW)
MARKET = "کمترین قیمت معتبر بازار ۸٬۶۰۰٬۰۰۰ تومان از «لیون کامپیوتر» در ترب (مشاهده: ۳ آبان ۱۴۰۵، ۱۵:۳۰) است"


def result(
    reason: Reason, outcome: Outcome = Outcome.DECREASE, **kw: object
) -> RecommendationResult:
    values: dict[str, object] = {
        "floor_rial": 84_000_000,
        "market_ref_rial": 86_000_000,
        "suggested_price_rial": 85_500_000,
    }
    values.update(kw)
    return RecommendationResult(outcome, reason, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("res", "expected"),
    [
        (
            result(Reason.ABOVE_MARKET),
            f"{MARKET}؛ قیمت فعلی ما بالاتر است. پیشنهاد: کاهش به ۸٬۵۵۰٬۰۰۰ تومان؛ کف سود ۸٬۴۰۰٬۰۰۰ تومان است.",
        ),
        (
            result(Reason.BELOW_MARKET, Outcome.INCREASE),
            f"{MARKET}؛ قیمت فعلی ما پایین‌تر از دامنه تحمل است. پیشنهاد: افزایش به ۸٬۵۵۰٬۰۰۰ تومان؛ کف سود ۸٬۴۰۰٬۰۰۰ تومان است.",
        ),
        (
            result(Reason.CAPPED_BY_CEILING, Outcome.INCREASE, ceiling_rial=115_000_000),
            f"{MARKET}. پیشنهاد: افزایش تا سقف تعیین‌شده ۱۱٬۵۰۰٬۰۰۰ تومان؛ کف سود ۸٬۴۰۰٬۰۰۰ تومان است.",
        ),
        (
            result(Reason.WITHIN_TOLERANCE, Outcome.HOLD, suggested_price_rial=None),
            f"{MARKET}؛ قیمت ما در دامنه تحمل است و تغییری پیشنهاد نمی‌شود.",
        ),
        (
            result(Reason.NO_CHANGE_AFTER_ROUNDING, Outcome.HOLD, suggested_price_rial=None),
            f"{MARKET}؛ پس از گرد کردن، قیمت پیشنهادی با قیمت فعلی برابر است.",
        ),
        (
            result(
                Reason.MARKET_BELOW_FLOOR,
                Outcome.FLOOR_CONFLICT,
                market_ref_rial=82_000_000,
                suggested_price_rial=None,
            ),
            "کمترین قیمت معتبر بازار ۸٬۲۰۰٬۰۰۰ تومان از «لیون کامپیوتر» در ترب (مشاهده: ۳ آبان ۱۴۰۵، ۱۵:۳۰) است که از کف سود ۸٬۴۰۰٬۰۰۰ تومان پایین‌تر است. هیچ قیمتی پیشنهاد نمی‌شود؛ تصمیم با کارشناس است.",
        ),
        (
            result(
                Reason.ABOVE_MARKET, flags=(Flag.UNDERCUT_LOST,), suggested_price_rial=86_000_000
            ),
            f"{MARKET}؛ قیمت فعلی ما بالاتر است. پیشنهاد: کاهش به ۸٬۶۰۰٬۰۰۰ تومان؛ کف سود ۸٬۴۰۰٬۰۰۰ تومان است. توجه: پس از گرد کردن، قیمت پیشنهادی دیگر پایین‌تر از قیمت بازار نیست.",
        ),
    ],
)
def test_explanations_with_market_reference(res: RecommendationResult, expected: str) -> None:
    assert explain(res, REF) == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (Reason.MISSING_COST, "داده ناکافی: بهای تمام‌شده معتبر برای این کالا ثبت نشده است."),
        (Reason.STALE_EVIDENCE, "داده ناکافی: قیمت‌های رقبا قدیمی است؛ منبع را بررسی کنید."),
        (
            Reason.PENDING_REVIEW,
            "داده ناکافی: تطبیق پیشنهادهای رقبا هنوز تأیید نشده است؛ صف تطبیق را بررسی کنید.",
        ),
        (
            Reason.TAX_BASIS_UNSET,
            "داده ناکافی: قاعده سود پیش‌فرض با نرخ مالیات بر ارزش افزوده تعریف نشده است.",
        ),
        (Reason.NO_OFFERS, "داده ناکافی: پیشنهاد معتبر و هم‌شرایطی از رقبا یافت نشد."),
        (
            Reason.BELOW_MIN_OFFERS,
            "داده ناکافی: تعداد پیشنهادهای معتبر کمتر از حداقل تعیین‌شده است.",
        ),
        (Reason.MISSING_CURRENT_PRICE, "داده ناکافی: قیمت فعلی این کالا در فروشگاه ثبت نشده است."),
    ],
)
def test_insufficient_data_explanations(reason: Reason, expected: str) -> None:
    assert explain(RecommendationResult(Outcome.INSUFFICIENT_DATA, reason)) == expected


def test_every_reason_has_a_template() -> None:
    for reason in Reason:
        text = explain(
            result(reason, suggested_price_rial=85_500_000, ceiling_rial=115_000_000), REF
        )
        assert text
        assert "None" not in text


def test_decrease_names_competitor_price_time_and_floor() -> None:
    text = explain(result(Reason.ABOVE_MARKET), REF)
    for part in ("لیون کامپیوتر", "۸٬۶۰۰٬۰۰۰ تومان", "۳ آبان ۱۴۰۵", "کف سود ۸٬۴۰۰٬۰۰۰ تومان"):
        assert part in text
