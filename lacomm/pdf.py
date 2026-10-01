import io
import re
import subprocess

import pypdf


def pdf_text(data: bytes) -> str:
    """Layout-preserving text via poppler's pdftotext; pypdf garbles spacing on some agendas."""
    result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True)
    return result.stdout.decode("utf-8")


def pdf_links(data: bytes) -> list[str]:
    """All hyperlink URIs in the PDF, in document order, deduplicated."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    links = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            uri = annot.get_object().get("/A", {}).get("/URI")
            if uri and uri not in links:
                links.append(str(uri))
    return links


def normalize_space(text: str) -> str:
    """Collapse runs of spaces and blank lines left over from layout extraction."""
    lines = [re.sub(r"[ \t]{2,}", "  ", line).rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
