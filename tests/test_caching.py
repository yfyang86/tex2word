"""V4-19: content-hash media dedup + image-math render memoisation."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

from latex2word import convert_source
from latex2word.mathml.cascade import MathCascade
from latex2word.report import ConversionReport
from latex2word.validate import validate_docx


def _png(path, w=20, h=20):
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# -- media dedup ------------------------------------------------------------- #


def test_identical_images_share_one_media_part(tmp_path):
    _png(tmp_path / "a.png")
    src = (
        r"\begin{document}icon \includegraphics{a.png} x"
        r"\begin{figure}\includegraphics{a.png}\caption{1}\end{figure}"
        r"\begin{figure}\includegraphics{a.png}\caption{2}\end{figure}\end{document}"
    )
    res = convert_source(src, base_dir=str(tmp_path))
    zf = zipfile.ZipFile(io.BytesIO(res.docx))
    media = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert len(media) == 1  # three uses, one part
    assert validate_docx(res.docx) == []


def test_dedup_keeps_docpr_ids_unique(tmp_path):
    import re

    _png(tmp_path / "a.png")
    src = (
        r"\begin{document}a \includegraphics{a.png} b \includegraphics{a.png} c"
        r"\end{document}"
    )
    res = convert_source(src, base_dir=str(tmp_path))
    xml = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml").decode()
    embeds = re.findall(r'r:embed="([^"]+)"', xml)
    ids = re.findall(r'<wp:docPr id="(\d+)"', xml)
    assert len(set(embeds)) == 1            # same image -> same relationship
    assert len(set(ids)) == len(ids) == 2   # but distinct drawing ids


def test_distinct_images_get_distinct_parts(tmp_path):
    _png(tmp_path / "a.png", 20, 20)
    _png(tmp_path / "b.png", 30, 10)  # different bytes
    src = (
        r"\begin{document}\includegraphics{a.png}\includegraphics{b.png}"
        r"\includegraphics{a.png}\end{document}"
    )
    res = convert_source(src, base_dir=str(tmp_path))
    media = [n for n in zipfile.ZipFile(io.BytesIO(res.docx)).namelist()
             if n.startswith("word/media/")]
    assert len(media) == 2  # a and b, with a deduped


# -- image-math memoisation -------------------------------------------------- #


class _CountingRenderer:
    def __init__(self):
        self.calls = 0

    def render(self, latex, display):
        self.calls += 1
        return (b"PNGBYTES", "png")


def test_image_math_render_is_memoised():
    r = _CountingRenderer()
    casc = MathCascade(ConversionReport(), image_renderer=r, enable_pmml=False)
    for _ in range(3):
        casc.inline(r"\thisisnotrealmath")  # forces the image fallback each time
    assert r.calls == 1  # rendered once, then cached
