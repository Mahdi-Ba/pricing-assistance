"""Bounded reading of uploaded files."""

import io

from fastapi import UploadFile

from pricing_assistant.core.errors import PayloadTooLarge

_CHUNK = 64 * 1024


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most ``max_bytes``; reject larger uploads without buffering them."""
    buffer = io.BytesIO()
    while chunk := await upload.read(_CHUNK):
        if buffer.tell() + len(chunk) > max_bytes:
            raise PayloadTooLarge(
                f"Upload exceeds the limit of {max_bytes} bytes",
                message_fa=f"حجم فایل بیش از حد مجاز ({max_bytes // 1024} کیلوبایت) است.",
            )
        buffer.write(chunk)
    return buffer.getvalue()
