import pytest

from pricing_assistant.matching.normalize import normalize_key, normalize_persian, normalize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("كارت گرافيك", "کارت گرافیک"),  # Arabic kaf/yeh → Persian
        ("۱۲۳ ٤٥٦", "123 456"),
        ("می‌خواهم", "می خواهم"),  # ZWNJ → space
        ("ســامسونگ", "سامسونگ"),  # tatweel removed
    ],
)
def test_normalize_persian(raw: str, expected: str) -> None:
    assert normalize_persian(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "حافظه SSD سامسونگ 990 PRO ظرفیت 1 ترابایت گارانتی ۳۶ ماهه",
            "حافظه ssd سامسونگ 990 pro ظرفیت 1TB گارانتی 36 ماهه",
        ),
        (
            "رم کینگستون DDR5 ظرفیت ۳۲ گیگ فرکانس ۵۶۰۰ مگاهرتز",
            "رم کینگستون ddr5 ظرفیت 32GB فرکانس 5600MHz",
        ),
        ("Kingston DDR5 · 32GB / 5600", "kingston ddr5 · 32GB 5600"),
        ("SSD 512 GB (NVMe)", "ssd 512GB nvme"),
        ("هارد ۲ ترا", "هارد 2TB"),
        ("کارت گرافیک RTX 4060 Ti 8 گیگابایت", "کارت گرافیک rtx 4060 ti 8GB"),
    ],
)
def test_normalize_title_units_digits_case(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_normalize_key_for_short_values() -> None:
    assert normalize_key(" Lion-Computer ") == "lioncomputer"
    assert normalize_key("لیون‌کامپیوتر") == normalize_key("لیون کامپیوتر")
    assert normalize_key(None) == ""
