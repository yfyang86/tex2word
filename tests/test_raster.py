from __future__ import annotations

import io
import zipfile

import pytest
from conftest import NS, document_root

from latex2word import convert_file
from latex2word.backend import raster


def _make_pdf(path) -> None:
    """Write a minimal 1-page PDF (matplotlib's PDF backend; permissive)."""
    plt = pytest.importorskip("matplotlib.pyplot")
    fig = plt.figure(figsize=(2, 1.5))
    fig.text(0.1, 0.5, "sample")
    fig.savefig(str(path), format="pdf")
    plt.close(fig)


def test_has_pdf_support_reflects_backend():
    import importlib.util

    expected = (
        importlib.util.find_spec("pypdfium2") is not None
        and importlib.util.find_spec("PIL") is not None
    )
    assert raster.has_pdf_support() == expected


@pytest.mark.skipif(not raster.has_pdf_support(), reason="PDF backend not installed")
def test_rasterize_pdf_returns_png(tmp_path):
    pdf = tmp_path / "f.pdf"
    _make_pdf(pdf)
    result = raster.rasterize_pdf(str(pdf), dpi=100)
    assert result is not None
    data, w, h = result
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert w > 0 and h > 0


def test_rasterize_unsupported_format_returns_none():
    assert raster.rasterize("/x/y.eps", "eps") is None


@pytest.mark.skipif(not raster.has_pdf_support(), reason="PDF backend not installed")
def test_includegraphics_pdf_is_embedded(tmp_path):
    _make_pdf(tmp_path / "fig.pdf")
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"\begin{document}\begin{figure}\includegraphics{fig.pdf}"
        r"\caption{C}\end{figure}\end{document}",
        encoding="utf-8",
    )
    out, result = convert_file(str(tex))
    zf = zipfile.ZipFile(io.BytesIO(result.docx))
    media = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert media and media[0].endswith(".png")
    root = document_root(result.docx)
    assert root.xpath("//w:drawing", namespaces=NS)


def test_extension_resolution_finds_pdf(tmp_path):
    # \includegraphics{fig} (no extension) should find fig.pdf on disk.
    _make_pdf(tmp_path / "fig.pdf") if raster.has_pdf_support() else (
        tmp_path / "fig.pdf"
    ).write_bytes(b"%PDF-1.4 fake")
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"\begin{document}\includegraphics{fig}\end{document}", encoding="utf-8"
    )
    _, result = convert_file(str(tex))
    # Either embedded (backend present) or a 'not found' is NOT raised -- the file
    # was resolved; with the backend it embeds, without it warns about the backend.
    msgs = " ".join(w.message for w in result.report.warnings)
    if raster.has_pdf_support():
        zf = zipfile.ZipFile(io.BytesIO(result.docx))
        assert any(n.startswith("word/media/") for n in zf.namelist())
    else:
        assert "fig" in msgs
        assert "not found" not in msgs  # resolution succeeded, backend missing


def test_missing_image_still_degrades(tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"\begin{document}\includegraphics{nope.pdf}\end{document}", encoding="utf-8"
    )
    _, result = convert_file(str(tex))
    assert any("not found" in w.message for w in result.report.warnings)
