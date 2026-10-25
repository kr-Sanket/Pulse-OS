"""Text extraction for uploaded documents, so they can join local AI retrieval (M5).

**Supported: PDFs with an embedded text layer** (``application/pdf``), read with ``pypdf``.
**Not supported, deliberately:** JPEG/PNG and scanned PDFs — both need OCR, which PulseOS does
not have. A PDF whose pages yield no text is reported as ``NO_TEXT`` rather than indexed empty,
so "uploaded" is never mistaken for "searchable".

Pure and synchronous: callers run it in a worker thread (it is CPU-bound). Nothing here logs,
and no error carries document content — ``ExtractionError`` holds only a reason code.
"""

import io
import logging
import re
from enum import StrEnum
from typing import Final

from pypdf import PdfReader
from pypdf.errors import DependencyError, FileNotDecryptedError

#: The upload content types whose text can be extracted. Everything else is skipped.
INDEXABLE_CONTENT_TYPES: Final = frozenset({"application/pdf"})

#: Bounds that keep one hostile or enormous document from monopolising a worker.
MAX_PAGES: Final = 300
MAX_CHARS: Final = 500_000

_WHITESPACE = re.compile(r"\s+")

# pypdf's parser warnings quote raw document bytes (e.g. "invalid pdf header: b'...'"), which
# would put fragments of a patient's file into the worker log. Failures are reported through
# ExtractionError codes instead, so its logger is silenced below CRITICAL (docs/SECURITY.md).
logging.getLogger("pypdf").setLevel(logging.CRITICAL)


class ExtractionFailure(StrEnum):
    """Why a supported document produced no indexable text. Codes only, never content."""

    NO_TEXT = "NO_TEXT"  # no text layer — typically a scan; would need OCR
    ENCRYPTED = "ENCRYPTED"  # password-protected
    UNREADABLE = "UNREADABLE"  # not a parseable PDF (corrupt, or mislabelled content type)


class ExtractionError(Exception):
    def __init__(self, reason: ExtractionFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


def is_indexable(content_type: str) -> bool:
    return content_type in INDEXABLE_CONTENT_TYPES


def extract_pdf_text(data: bytes, *, max_pages: int = MAX_PAGES, max_chars: int = MAX_CHARS) -> str:
    """The document's text, whitespace-normalised and bounded. Raises ``ExtractionError``.

    The content type is client-declared at upload, so the bytes are not trusted to be a PDF:
    anything ``pypdf`` cannot parse is ``UNREADABLE``, never a crash.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError(ExtractionFailure.ENCRYPTED)
        parts: list[str] = []
        length = 0
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            parts.append(text)
            length += len(text)
            if length >= max_chars:
                break
    except ExtractionError:
        raise
    except (FileNotDecryptedError, DependencyError) as exc:
        # Needs a password, or an AES decryptor this install does not carry.
        raise ExtractionError(ExtractionFailure.ENCRYPTED) from exc
    except Exception as exc:
        raise ExtractionError(ExtractionFailure.UNREADABLE) from exc
    normalized = _WHITESPACE.sub(" ", " ".join(parts)).strip()[:max_chars]
    if not normalized:
        raise ExtractionError(ExtractionFailure.NO_TEXT)
    return normalized
