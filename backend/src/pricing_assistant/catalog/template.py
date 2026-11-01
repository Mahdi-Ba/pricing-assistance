"""The catalog import template: columns, table parsing and row validation (tasks 3.3, 3.4).

Rows are numbered from 1 for the first data row (the header row is not counted). Validation
collects every problem in a row and reports it with row number, column and a Persian message.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from openpyxl import load_workbook

from pricing_assistant.catalog.models import ImportanceTier
from pricing_assistant.catalog.upload import FileFormat
from pricing_assistant.core.money import (
    CurrencyUnit,
    MoneyParseError,
    parse_amount,
    parse_currency_unit,
    to_rial,
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "sku",
    "product_name",
    "category",
    "brand",
    "model",
    "current_price",
    "purchase_cost",
)
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "currency",
    "importance",
    "stock_quantity",
    "mpn",
    "gtin",
    "capacity",
    "generation",
    "colour_edition",
    "warranty_provider",
    "warranty_months",
)
TEMPLATE_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
ATTRIBUTE_COLUMNS = ("capacity", "generation", "colour_edition", "warranty_provider")

_LABELS_FA = {
    "sku": "کد کالا (SKU)",
    "product_name": "نام محصول",
    "category": "دسته",
    "brand": "برند",
    "model": "مدل",
    "current_price": "قیمت فعلی",
    "purchase_cost": "هزینه خرید",
    "currency": "واحد پول",
    "importance": "سطح اهمیت",
    "stock_quantity": "موجودی",
    "gtin": "GTIN",
    "warranty_months": "مدت گارانتی (ماه)",
}
_TIER_ALIASES = {"a": "A", "b": "B", "c": "C", "الف": "A", "ب": "B", "ج": "C"}
_SKU = re.compile(r"^[\w.\-/]{1,64}$")
_CATEGORY = re.compile(r"^[a-z0-9_\-]{1,40}$")
_GTIN = re.compile(r"^(\d{8}|\d{12}|\d{13}|\d{14})$")
_MAX_TEXT = 200


@dataclass(frozen=True, slots=True)
class RowError:
    row: int | None
    column: str | None
    message_fa: str

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "message_fa": self.message_fa}


@dataclass(frozen=True, slots=True)
class CatalogRow:
    row: int
    sku: str
    product_name: str
    category: str
    brand: str
    model: str
    mpn: str | None
    gtin: str | None
    attributes: dict[str, Any]
    importance_tier: ImportanceTier
    stock_quantity: int | None
    current_price_rial: int | None
    purchase_cost_rial: int | None


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)


class TemplateMismatchError(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"missing required columns: {', '.join(missing)}")
        self.missing = missing


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lstrip("﻿").strip().lower()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_table(data: bytes, file_format: FileFormat, *, max_rows: int) -> ParsedTable:
    if file_format is FileFormat.CSV:
        records: Iterator[list[str]] = csv.reader(io.StringIO(data.decode("utf-8-sig")))
    else:
        records = _xlsx_records(data)
    try:
        headers = [_normalize_header(h) for h in next(records)]
    except StopIteration:
        return ParsedTable(headers=[])
    table = ParsedTable(headers=headers)
    for index, record in enumerate(records, start=1):
        values = [_cell_text(v) for v in record]
        if not any(values):
            continue
        if len(table.rows) >= max_rows:
            raise ValueError(f"more than {max_rows} rows")
        table.rows.append((index, dict(zip(headers, values, strict=False))))
    return table


def _xlsx_records(data: bytes) -> Iterator[list[str]]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        for row in sheet.iter_rows(values_only=True):
            yield [_cell_text(v) for v in row]
    finally:
        workbook.close()


def check_headers(headers: list[str]) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise TemplateMismatchError(missing)


def _label(column: str) -> str:
    return _LABELS_FA.get(column, column)


class _RowValidator:
    """Validates one data row, collecting every error rather than stopping at the first."""

    def __init__(self, row: int, values: dict[str, str], default_currency: CurrencyUnit | None):
        self.row = row
        self.values = values
        self.errors: list[RowError] = []
        self.currency_raw = values.get("currency", "")
        self.unit: CurrencyUnit | None = default_currency
        try:
            self.unit = parse_currency_unit(self.currency_raw) or default_currency
        except MoneyParseError:
            self.fail("currency", "واحد پول باید ریال یا تومان باشد.")
            self.unit = None

    def fail(self, column: str, message: str) -> None:
        error = RowError(self.row, column, message)
        if error not in self.errors:
            self.errors.append(error)

    def raw(self, column: str) -> str:
        return self.values.get(column, "").strip()

    def required(self, column: str) -> str:
        value = self.raw(column)
        if not value:
            self.fail(column, f"{_label(column)} خالی است.")
        elif len(value) > _MAX_TEXT:
            self.fail(column, f"{_label(column)} بیش از حد طولانی است.")
        return value

    def optional_text(self, column: str) -> str | None:
        value = self.raw(column)
        if len(value) > _MAX_TEXT:
            self.fail(column, f"{_label(column)} بیش از حد طولانی است.")
        return value or None

    def optional_int(self, column: str, message: str) -> int | None:
        value = self.raw(column)
        if not value:
            return None
        try:
            return parse_amount(value)
        except MoneyParseError:
            self.fail(column, message)
            return None

    def money(self, column: str) -> int | None:
        value = self.raw(column)
        if not value:
            return None
        try:
            amount = parse_amount(value)
        except MoneyParseError:
            self.fail(column, f"{_label(column)} باید عدد باشد.")
            return None
        if amount <= 0:
            self.fail(column, f"{_label(column)} باید بیشتر از صفر باشد.")
            return None
        if self.unit is None:
            if not self.currency_raw.strip():
                self.fail(
                    "currency", "واحد پول مشخص نیست؛ ستون currency یا واحد پیش‌فرض را تعیین کنید."
                )
            return None
        return to_rial(amount, self.unit)

    def tier(self) -> ImportanceTier:
        value = self.raw("importance").lower()
        if not value:
            return ImportanceTier.B
        if value not in _TIER_ALIASES:
            self.fail("importance", "سطح اهمیت باید A، B یا C باشد.")
            return ImportanceTier.B
        return ImportanceTier(_TIER_ALIASES[value])

    def matching(self, column: str, value: str, pattern: re.Pattern[str], message: str) -> None:
        if value and not pattern.fullmatch(value):
            self.fail(column, message)


def validate_row(
    row: int, values: dict[str, str], default_currency: CurrencyUnit | None
) -> CatalogRow | list[RowError]:
    v = _RowValidator(row, values, default_currency)
    sku = v.required("sku")
    v.matching("sku", sku, _SKU, "کد کالا (SKU) فقط می‌تواند شامل حروف، عدد و - _ . / باشد.")
    product_name = v.required("product_name")
    category = v.required("category").lower()
    v.matching("category", category, _CATEGORY, "کد دسته فقط حروف لاتین کوچک، عدد، - و _ می‌پذیرد.")
    brand = v.required("brand")
    model = v.required("model")
    tier = v.tier()
    stock = v.optional_int("stock_quantity", "موجودی باید عدد صحیح نامنفی باشد.")
    warranty_months = v.optional_int("warranty_months", "مدت گارانتی باید عدد صحیح ماه باشد.")
    gtin = v.optional_text("gtin")
    v.matching("gtin", gtin or "", _GTIN, "GTIN باید ۸، ۱۲، ۱۳ یا ۱۴ رقم باشد.")
    mpn = v.optional_text("mpn")
    attributes: dict[str, Any] = {
        column: value for column in ATTRIBUTE_COLUMNS if (value := v.optional_text(column))
    }
    current_price = v.money("current_price")
    purchase_cost = v.money("purchase_cost")
    if v.errors:
        return v.errors
    if warranty_months is not None:
        attributes["warranty_months"] = warranty_months
    return CatalogRow(
        row=row,
        sku=sku,
        product_name=product_name,
        category=category,
        brand=brand,
        model=model,
        mpn=mpn,
        gtin=gtin,
        attributes=attributes,
        importance_tier=tier,
        stock_quantity=stock,
        current_price_rial=current_price,
        purchase_cost_rial=purchase_cost,
    )
