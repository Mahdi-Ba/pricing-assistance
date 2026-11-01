import pytest

from pricing_assistant.catalog.models import ImportanceTier
from pricing_assistant.catalog.template import (
    CatalogRow,
    RowError,
    TemplateMismatchError,
    check_headers,
    parse_table,
    validate_row,
)
from pricing_assistant.catalog.upload import FileFormat
from pricing_assistant.core.money import CurrencyUnit
from tests.support.catalog_files import csv_bytes, row, xlsx_bytes


def test_valid_row_is_normalized_to_rial() -> None:
    result = validate_row(1, row("SSD-1"), None)
    assert isinstance(result, CatalogRow)
    assert result.current_price_rial == 89_000_000
    assert result.purchase_cost_rial == 75_000_000
    assert result.importance_tier is ImportanceTier.A
    assert result.attributes == {
        "capacity": "1TB",
        "warranty_provider": "آواژنگ",
        "warranty_months": 36,
    }


def test_missing_unit_without_default_rejects_row() -> None:
    result = validate_row(3, row("SSD-1", currency=""), None)
    assert result == [
        RowError(3, "currency", "واحد پول مشخص نیست؛ ستون currency یا واحد پیش‌فرض را تعیین کنید.")
    ]


def test_default_currency_applies_when_row_has_none() -> None:
    result = validate_row(1, row("SSD-1", currency=""), CurrencyUnit.RIAL)
    assert isinstance(result, CatalogRow)
    assert result.purchase_cost_rial == 7_500_000


def test_tier_defaults_to_b_and_accepts_persian_letters() -> None:
    default = validate_row(1, row("X", importance=""), None)
    persian = validate_row(1, row("X", importance="الف"), None)
    assert isinstance(default, CatalogRow)
    assert isinstance(persian, CatalogRow)
    assert default.importance_tier is ImportanceTier.B
    assert persian.importance_tier is ImportanceTier.A


@pytest.mark.parametrize(
    ("overrides", "column"),
    [
        ({"sku": ""}, "sku"),
        ({"purchase_cost": "abc"}, "purchase_cost"),
        ({"current_price": "0"}, "current_price"),
        ({"importance": "Z"}, "importance"),
        ({"stock_quantity": "-1"}, "stock_quantity"),
        ({"gtin": "123"}, "gtin"),
        ({"currency": "USD"}, "currency"),
        ({"category": "SSD Drives"}, "category"),
    ],
)
def test_invalid_values_are_reported_per_column(overrides: dict[str, str], column: str) -> None:
    result = validate_row(5, row("SSD-1", **overrides), None)
    assert isinstance(result, list)
    assert [e.column for e in result] == [column]
    assert all(e.row == 5 and e.message_fa for e in result)


def test_missing_cost_value_is_allowed() -> None:
    result = validate_row(1, row("SSD-1", purchase_cost=""), None)
    assert isinstance(result, CatalogRow)
    assert result.purchase_cost_rial is None


def test_header_check_names_missing_columns() -> None:
    with pytest.raises(TemplateMismatchError) as exc:
        check_headers(["sku", "product_name", "category", "brand", "model", "current_price"])
    assert exc.value.missing == ["purchase_cost"]


@pytest.mark.parametrize("builder", [csv_bytes, xlsx_bytes])
def test_csv_and_xlsx_parse_to_the_same_table(builder: object) -> None:
    data = builder([row("SSD-1"), row("SSD-2", purchase_cost="")])  # type: ignore[operator]
    fmt = FileFormat.CSV if builder is csv_bytes else FileFormat.XLSX
    table = parse_table(data, fmt, max_rows=100)
    assert table.headers[:3] == ["sku", "product_name", "category"]
    assert [number for number, _ in table.rows] == [1, 2]
    assert table.rows[0][1]["purchase_cost"] == "7,500,000"
    assert table.rows[1][1]["purchase_cost"] == ""


def test_blank_rows_are_skipped_and_row_limit_enforced() -> None:
    data = csv_bytes([row("A"), {}, row("B")])
    table = parse_table(data, FileFormat.CSV, max_rows=100)
    assert [number for number, _ in table.rows] == [1, 3]
    with pytest.raises(ValueError, match="more than 1 rows"):
        parse_table(data, FileFormat.CSV, max_rows=1)
