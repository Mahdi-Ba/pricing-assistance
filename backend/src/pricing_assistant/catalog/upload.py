"""Upload limits and format detection, applied before any parsing (task 3.6).

XLSX files are ZIP archives; their declared uncompressed size is checked to reject archive
bombs before openpyxl touches them. CSV files must be UTF-8 text.
"""

import io
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

from pricing_assistant.core.errors import PayloadTooLarge, UnsupportedMediaType

_ZIP_MAGIC = b"PK\x03\x04"


class FileFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


MEDIA_TYPES = {
    FileFormat.CSV: "text/csv",
    FileFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True, slots=True)
class Upload:
    file_name: str
    file_format: FileFormat
    data: bytes

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.file_format]


def detect_format(file_name: str, data: bytes, *, max_uncompressed_bytes: int) -> FileFormat:
    suffix = PurePath(file_name).suffix.lower()
    if suffix == ".xlsx":
        _check_xlsx(data, max_uncompressed_bytes)
        return FileFormat.XLSX
    if suffix == ".csv":
        _check_csv(data)
        return FileFormat.CSV
    raise UnsupportedMediaType(
        "Only .csv and .xlsx files are accepted",
        message_fa="فقط فایل‌های CSV و XLSX پذیرفته می‌شوند.",
    )


def _check_xlsx(data: bytes, max_uncompressed_bytes: int) -> None:
    if not data.startswith(_ZIP_MAGIC):
        raise UnsupportedMediaType(
            "File is not a valid XLSX workbook", message_fa="فایل XLSX معتبر نیست."
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            declared = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise UnsupportedMediaType(
            "File is not a valid XLSX workbook", message_fa="فایل XLSX معتبر نیست."
        ) from exc
    if "xl/workbook.xml" not in names:
        raise UnsupportedMediaType(
            "File is not a valid XLSX workbook", message_fa="فایل XLSX معتبر نیست."
        )
    if declared > max_uncompressed_bytes:
        raise PayloadTooLarge(
            "Workbook expands beyond the allowed size",
            message_fa="محتوای فایل بیش از حد مجاز است.",
        )


def _check_csv(data: bytes) -> None:
    if b"\x00" in data:
        raise UnsupportedMediaType("CSV must be text", message_fa="فایل CSV باید متنی باشد.")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedMediaType(
            "CSV must be UTF-8 encoded", message_fa="فایل CSV باید با کدگذاری UTF-8 ذخیره شود."
        ) from exc
