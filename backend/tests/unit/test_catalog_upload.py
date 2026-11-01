import io
import zipfile

import pytest
from fastapi import UploadFile

from pricing_assistant.catalog.upload import FileFormat, detect_format
from pricing_assistant.core.errors import PayloadTooLarge, UnsupportedMediaType
from pricing_assistant.core.uploads import read_limited
from tests.support.catalog_files import csv_bytes, row, xlsx_bytes

LIMIT = 10 * 1024 * 1024


async def test_oversized_upload_is_rejected_before_full_read() -> None:
    upload = UploadFile(io.BytesIO(b"x" * 300_000), filename="big.csv")
    with pytest.raises(PayloadTooLarge):
        await read_limited(upload, max_bytes=200_000)
    assert upload.file.tell() < 300_000


async def test_upload_within_limit_is_read_completely() -> None:
    upload = UploadFile(io.BytesIO(b"abc"), filename="small.csv")
    assert await read_limited(upload, max_bytes=10) == b"abc"


def test_formats_are_detected_by_extension_and_content() -> None:
    assert (
        detect_format("c.csv", csv_bytes([row("A")]), max_uncompressed_bytes=LIMIT)
        is FileFormat.CSV
    )
    assert (
        detect_format("c.XLSX", xlsx_bytes([row("A")]), max_uncompressed_bytes=LIMIT)
        is FileFormat.XLSX
    )


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("catalog.pdf", b"%PDF-1.7"),
        ("catalog.xlsx", b"not a zip"),
        ("catalog.csv", b"\xff\xfe\x00b"),
        ("catalog.csv", "sku\nA".encode("utf-16")),
    ],
)
def test_wrong_types_are_rejected(name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedMediaType):
        detect_format(name, data, max_uncompressed_bytes=LIMIT)


def test_xlsx_archive_bomb_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 5_000_000)
    with pytest.raises(PayloadTooLarge):
        detect_format("bomb.xlsx", buffer.getvalue(), max_uncompressed_bytes=1_000_000)
