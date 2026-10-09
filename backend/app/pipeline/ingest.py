"""Stage 1: ingest. Validate, scan and fingerprint uploaded files before any processing.

The original bytes are stored unchanged and identified by SHA-256; every later citation refers to the
document by that hash, so a citation can never silently point at a different file.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from app.domain.schemas import Document

MAX_BYTES = 50 * 1024 * 1024

# media type -> predicate on leading bytes. Extension alone is never trusted.
_SIGNATURES = {
    "application/pdf": lambda b: b.startswith(b"%PDF-"),
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/tiff": lambda b: b[:4] in (b"II*\x00", b"MM\x00*"),
}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT = "text/plain"  # synthetic samples and pasted notes; disabled in production config


class IngestError(ValueError):
    pass


class MalwareScanner(Protocol):
    def scan(self, data: bytes) -> bool:
        """Return True if clean. Production: Defender for Storage on-upload scan result."""
        ...


class AllowAllScanner:
    """Local development only. Production relies on Defender for Storage scan results."""

    def scan(self, data: bytes) -> bool:
        return True


@dataclass(frozen=True)
class IngestedFile:
    document: Document
    data: bytes


def detect_media_type(data: bytes, *, allow_text: bool) -> str:
    head = data[:16]
    for media_type, matches in _SIGNATURES.items():
        if matches(head):
            return media_type
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile as exc:
            raise IngestError("corrupt archive") from exc
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            return DOCX
        raise IngestError("unsupported Office/zip file")
    if allow_text:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError("unsupported or binary file type") from exc
        return TEXT
    raise IngestError("unsupported file type")


def ingest(
    *,
    case_id: str,
    filename: str,
    data: bytes,
    uploaded_by: str,
    scanner: MalwareScanner,
    allow_text: bool = False,
) -> IngestedFile:
    if not data:
        raise IngestError("empty file")
    if len(data) > MAX_BYTES:
        raise IngestError(f"file exceeds {MAX_BYTES // (1024 * 1024)} MB limit")
    media_type = detect_media_type(data, allow_text=allow_text)
    if not scanner.scan(data):
        raise IngestError("file failed malware scan and has been quarantined")
    doc = Document(
        case_id=case_id,
        filename=filename,
        media_type=media_type,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        uploaded_by=uploaded_by,
    )
    return IngestedFile(document=doc, data=data)
