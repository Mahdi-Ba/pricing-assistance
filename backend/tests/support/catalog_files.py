"""Builders for catalog import files used in tests."""

import csv
import io

from openpyxl import Workbook

from pricing_assistant.catalog.template import TEMPLATE_COLUMNS


def csv_bytes(rows: list[dict[str, str]], columns: tuple[str, ...] = TEMPLATE_COLUMNS) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def xlsx_bytes(rows: list[dict[str, str]], columns: tuple[str, ...] = TEMPLATE_COLUMNS) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(columns))
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def row(sku_value: str, **overrides: str) -> dict[str, str]:
    base = {
        "sku": sku_value,
        "product_name": "Samsung 990 PRO",
        "category": "ssd",
        "brand": "Samsung",
        "model": "990 PRO 1TB",
        "current_price": "8,900,000",
        "purchase_cost": "7,500,000",
        "currency": "TOMAN",
        "importance": "A",
        "stock_quantity": "4",
        "mpn": "MZ-V9P1T0BW",
        "capacity": "1TB",
        "warranty_provider": "آواژنگ",
        "warranty_months": "36",
    }
    base.update(overrides)
    return base
