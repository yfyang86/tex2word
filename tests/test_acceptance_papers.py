"""Acceptance tests on two synthetic papers (issue #44).

The fixtures come from rstex2word (MIT, ``crates/tex2word/tests/fixtures``):

* ``tikz_paper`` mirrors arXiv:2610.32813: TikZ figures kept in ``\\input``
  files, two pictures stacked in one ``figure*``, captions built with
  ``\\protect\\input``, nested ``\\input`` paths relative to the main file, a
  heading with two ``\\label``s, ``\\path``, natbib ``[numbers]`` with
  ``plainnat``, and ``\\nobalance``/``\\typeout``/``\\onecolumn`` end matter.
* ``amsart_paper`` mirrors an amsart economics manuscript: ``\\paragraph``
  redefined through ``\\@startsection``, ``\\subjclass[JEL]``, citations and
  ``\\ref`` in table cells, captions and theorem-like blocks, a landscape table
  built from ``\\rotatebox{90}{minipage + \\captionof{table}}`` with
  ``\\makecell`` headers, and display math with sums, ``\\\\[2pt]`` row spacing,
  ``\\DeclareMathOperator``, ``\\mathrm{Beta}`` and minus signs.

Rendering TikZ needs a TeX engine and pypdfium2; without them the TikZ test
checks the graceful path. Set ``T2W_REQUIRE_TIKZ=1`` to fail instead.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path

import pytest

from tex2word import convert_source
from tex2word.backend import raster, tikz
from tex2word.validate import validate_docx

FIXTURES = Path(__file__).parent / "fixtures"


def _listing(d: Path) -> set[Path]:
    return {p.relative_to(d) for p in d.rglob("*") if p.is_file()}


def _convert(name: str):
    d = FIXTURES / name
    before = _listing(d)
    r = convert_source((d / "main.tex").read_text(encoding="utf-8"), base_dir=str(d))
    assert _listing(d) == before, "conversion wrote into the source tree"
    assert validate_docx(r.docx) == []
    return r


def _parts(docx: bytes) -> tuple[list[str], list[int], str]:
    """(media part names, drawing widths in EMU, document.xml)."""
    z = zipfile.ZipFile(io.BytesIO(docx))
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    xml = z.read("word/document.xml").decode()
    widths = [int(w) for w in re.findall(r'<wp:extent cx="(\d+)"', xml)]
    return media, widths, xml


def _text(xml: str) -> str:
    runs = re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml)
    return " ".join(runs).replace("&amp;", "&")


def _ir(r) -> str:
    return json.dumps(r.document.to_dict(), ensure_ascii=False)


def _warnings(r) -> list[str]:
    return [f"{w.construct}: {w.message}" for w in r.report.warnings]


def _tikz_tools() -> bool:
    ok = bool(tikz.available_engines()) and raster.has_pdf_support()
    if not ok and os.environ.get("T2W_REQUIRE_TIKZ"):
        pytest.fail("T2W_REQUIRE_TIKZ is set but no TeX engine + pypdfium2 was found")
    return ok


def _bib_keys(d: Path) -> list[str]:
    bib = (d / "refs.bib").read_text(encoding="utf-8")
    return re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib)


@pytest.mark.parametrize("engines", ["installed", "none"])
def test_tikz_paper(engines, monkeypatch):
    if engines == "none":  # the graceful path, whatever this machine has
        monkeypatch.setattr(tikz, "available_engines", lambda: [])
    r = _convert("tikz_paper")
    ir = _ir(r)
    media, widths, xml = _parts(r.docx)

    # nothing degraded to raw LaTeX: \path, \typeout, \onecolumn, ...
    assert "RawInline" not in ir
    # \protect\input in captions inlines the file's text, not \protectText
    assert "Pipeline overview. Each stage is one crate" in ir
    assert "Quality and cost of the three variants" in ir
    assert "protectEach" not in ir and "protectQuality" not in ir
    # nested \input{generated/...} from generated/*.tex: the table arrives
    assert '"tab:results"' in ir
    # the figure keeps its own \label, not the \foreach variable \label
    assert '"fig:bars"' in ir
    # \path renders as monospace text
    assert "generated/results_raw.json" in xml
    # natbib [numbers] beats plainnat's author-year default
    assert "[1]" in _text(xml)

    w = _warnings(r)
    if engines == "installed" and _tikz_tools():
        # every reference resolves (incl. the second \label of a heading) and
        # both figures render: 1 + 2 stacked pictures, none wider than the
        # text column (letter paper, 0.75in margins: 7in = 6400800 EMU)
        assert w == []
        assert len(media) == 3, media
        assert len(widths) == 3
        assert all(0 < cx <= 6_400_800 for cx in widths), widths
    else:
        # graceful degradation: only the TikZ notes, never a dropped ref
        assert media == []
        assert all(m.startswith("figure: ") for m in w), w
        assert any("TikZ figure not rendered" in m for m in w), w


def test_amsart_paper():
    d = FIXTURES / "amsart_paper"
    r = _convert("amsart_paper")
    ir = _ir(r)
    media, _, xml = _parts(r.docx)
    text = _text(xml)

    assert "RawInline" not in ir, "raw LaTeX left in the IR"
    assert r.report.math_raw == 0, "equations fell back to raw LaTeX"
    # citations and references resolve everywhere, tables and captions too
    for key in _bib_keys(d):
        assert key not in text, f"raw citation key {key!r} in the text"
    assert "??" not in text, "unresolved reference rendered as ??"
    # layout macros never leak as text
    for junk in ("startsection", "baselineskip", "makecell", "rotatebox", "captionof"):
        assert junk not in text, f"{junk} leaked into the text"
    # every n-ary operator has its operand, and \\[2pt] stays out of the math
    assert "<m:e/>" not in xml, "n-ary operator with an empty body"
    assert "pt</m:t>" not in xml, "row spacing leaked into math"

    # \subjclass[JEL] prints with the label from \@namedef{subjclassname@JEL}
    assert "JEL classification:" in text
    assert "D91, E21, J63" in text
    # the redefined \paragraph is still a run-in heading, with its citation
    assert "Reference-dependent adoption" in text
    # citations in cells, captions and the design rule render as author-year
    assert text.count("Tversky") >= 4, text
    assert text.count("Laibson") >= 4, text
    # the landscape table keeps its \captionof caption and \label
    assert '"tab:results"' in ir, "rotated table lost its label"
    assert "Stress-test results" in text
    # \makecell headers break lines inside the cell
    cell = xml[xml.index("Peak junior"):]
    assert "<w:br/>" in cell[:200], "makecell line break missing"
    # math: minus signs, operator names as words, sums own their operands
    assert ">−<" in xml, "minus rendered as a hyphen"
    assert ">Beta<" in xml and ">rel<" in xml
    assert xml.count("<m:nary>") >= 3

    w = _warnings(r)
    if raster.has_pdf_support():
        assert w == []
        assert len(media) == 1, "the PDF figure is embedded"
    else:
        # only the PDF figure degrades
        assert len(w) == 1, w
