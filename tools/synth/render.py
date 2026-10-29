"""``--render``: the sentinel/KEEP tokens must show up in a LibreOffice render.

The XML oracles see what tex2word wrote; this one sees what a reader sees.
Documents are converted to PDF in batches with ``soffice --headless`` and the
PDF text is extracted with PDFium. Slow (seconds per batch): use it with
``--filter`` or ``--tier smoke``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from . import SENTINEL
from .model import Finding, Probe, Result
from .runner import convert, write_probe

_BATCH = 40


def _tokens(p: Probe) -> list[str]:
    toks = [t for t in p.expect.texts if re.fullmatch(r"K[A-Z]+\d*|KEEP\d+", t)]
    if SENTINEL in p.source and SENTINEL not in p.expect.counts:
        toks.append(SENTINEL)
    return toks


def _field_paragraphs(docx: bytes) -> list[str]:
    """Text of the body paragraphs that hold a SEQ/REF/STYLEREF field."""
    import io
    import zipfile

    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode("utf-8")
    out = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        if not re.search(r"<w:instrText[^>]*>\s*(SEQ|REF|STYLEREF)\b", para):
            continue
        text = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", para))
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if text.strip():
            out.append(text.replace("\u00a0", " "))
    return out


def render_check(probes: dict[str, Probe], results: list[Result]) -> None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if soffice is None or pdfium is None:
        for r in results:
            r.findings.append(Finding("render-unavailable", "needs soffice and pypdfium2"))
        return
    by_id = {r.probe_id: r for r in results}
    todo = [p for p in probes.values() if p.id in by_id and _tokens(p)]
    with tempfile.TemporaryDirectory(prefix="t2w-render-") as tmp:
        names: dict[str, Probe] = {}
        field_lines: dict[str, list[str]] = {}
        for i, p in enumerate(todo):
            d = os.path.join(tmp, f"src{i}")
            os.makedirs(d)
            write_probe(p, d)
            try:
                docx = convert(p, d).docx
            except Exception:  # noqa: BLE001 - the main run already reported it
                continue
            name = f"p{i}"
            with open(os.path.join(tmp, name + ".docx"), "wb") as fh:
                fh.write(docx)
            names[name] = p
            field_lines[name] = _field_paragraphs(docx)
        files = sorted(names)
        for start in range(0, len(files), _BATCH):
            batch = [os.path.join(tmp, f + ".docx") for f in files[start:start + _BATCH]]
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp,
                            *batch], capture_output=True, timeout=600, check=False)
        for name, p in names.items():
            pdf = os.path.join(tmp, name + ".pdf")
            r = by_id[p.id]
            if not os.path.exists(pdf):
                r.findings.append(Finding("render-failed", "LibreOffice produced no PDF"))
                continue
            doc = pdfium.PdfDocument(pdf)
            text = "".join(page.get_textpage().get_text_range() for page in doc)
            doc.close()
            flat = re.sub(r"\s+", "", text)
            for tok in _tokens(p):
                if tok not in flat:
                    r.findings.append(Finding("render-missing", f"{tok!r} not in the PDF text"))
            # cached field results (numbers, references) must equal what
            # LibreOffice computes when it updates the fields on load
            for line in field_lines.get(name, []):
                if re.sub(r"\s+", "", line) not in flat:
                    r.findings.append(Finding("render-field-mismatch",
                                              f"cached {line!r} differs from the render"))
                    break
