"""Persian presentation helpers: digits, Toman amounts and Jalali (solar hijri) dates."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pricing_assistant.core.money import rial_to_toman

TEHRAN = ZoneInfo("Asia/Tehran")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def fa_digits(text: str | int) -> str:
    return str(text).translate(_FA_DIGITS)


def toman(amount_rial: int) -> str:
    """«۸٬۶۰۰٬۰۰۰ تومان» — Persian digits, Arabic thousands separator, explicit unit."""
    grouped = f"{rial_to_toman(amount_rial):,}".replace(",", "٬")
    return f"{fa_digits(grouped)} تومان"


def percent_bp(value_bp: int) -> str:
    whole, rest = divmod(value_bp, 100)
    text = f"{whole}" if rest == 0 else f"{whole}.{rest:02d}".rstrip("0")
    return f"{fa_digits(text.replace('.', '٫'))}٪"


def to_jalali(day: date) -> tuple[int, int, int]:
    """Gregorian → Jalali (algorithm of Borkowski / jdf.scr.ir, valid 1800–2200)."""
    gy, gm, gd = day.year, day.month, day.day
    g_days_in_month = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy  # noqa: PLR2004
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + g_days_in_month[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:  # noqa: PLR2004
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:  # noqa: PLR2004
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def jalali_datetime(moment: datetime) -> str:
    """«۳ آبان ۱۴۰۵، ۱۲:۰۰» in Tehran time."""
    local = moment.astimezone(TEHRAN)
    jy, jm, jd = to_jalali(local.date())
    return (
        f"{fa_digits(jd)} {_MONTHS[jm - 1]} {fa_digits(jy)}، {fa_digits(local.strftime('%H:%M'))}"
    )
