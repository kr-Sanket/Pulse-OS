"""Synthetic PDFs for indexing tests — built in memory, no binary fixtures in the repo."""

import io

from pypdf import PdfWriter


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (Helvetica), assembled by hand."""
    content = (
        "BT /F1 12 Tf 72 720 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        " /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def blank_pdf() -> bytes:
    """A valid PDF with no text layer — what a scan looks like to a text extractor."""
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def encrypted_pdf() -> bytes:
    """A password-protected PDF (RC4, so no optional crypto dependency is needed)."""
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    writer.encrypt("not-the-empty-password", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
