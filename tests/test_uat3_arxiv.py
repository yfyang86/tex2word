"""UAT-3: arXiv:2605.23904v2 (a Microsoft tech-report-class paper).

A trimmed, self-contained excerpt that locks in the fixes the full paper drove:
the ``\\dvalp``/``\\dvaln`` delta-cell macros (which expand to ``\\hphantom{...}``
and used to leak it as raw text in 311 cells), the title-page box/font plumbing
(``\\mbox``/``\\raisebox``/``\\rule``/``\\fontsize``/``\\selectfont``), and an
appendix prompt printed as ``{\\footnotesize \\begin{verbatim}...}`` (which used
to come back empty).
"""

from __future__ import annotations

import os

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.validate import validate_docx

UAT_DIR = os.path.join(os.path.dirname(__file__), "uat", "arXiv-2605.23904v2")


def _source() -> str:
    with open(os.path.join(UAT_DIR, "main.tex"), encoding="utf-8") as fh:
        return fh.read()


def _result():
    return convert_source(_source(), base_dir=UAT_DIR)


def _doc() -> ir.Document:
    doc, _ = parse_document(_source(), UAT_DIR)
    return doc


def _all_text(inlines) -> str:
    out = []
    for i in inlines:
        if isinstance(i, ir.Text):
            out.append(i.value)
        elif hasattr(i, "inlines"):
            out.append(_all_text(i.inlines))
    return "".join(out)


# -- end to end -------------------------------------------------------------- #


def test_uat3_converts_clean_and_valid():
    res = _result()
    assert res.report.errors == []
    assert validate_docx(res.docx) == []
    # the \hphantom leak was 311 warnings; keep a tight ceiling so it can't creep back
    assert len(res.report.warnings) <= 2, [w.construct for w in res.report.warnings]


def test_uat3_no_phantom_leaks_anywhere():
    full = str(_doc().to_dict())
    assert "hphantom" not in full and "phantom" not in full


# -- the \dvalp delta cells -------------------------------------------------- #


def test_uat3_dvalp_cells_render_the_value():
    table = next(b for b in _doc().blocks if isinstance(b, ir.Table))
    # row "1 example": cell 1 is \dvalp{81.0}{4.1} -> "81.0+4.1", no \hphantom
    cell = _all_text(table.rows[1].cells[1].blocks[0].inlines)
    assert cell.startswith("81.0") and "hphantom" not in cell


# -- the appendix verbatim prompt -------------------------------------------- #


def test_uat3_verbatim_prompt_is_recovered():
    code = [b for b in _doc().blocks if isinstance(b, ir.CodeBlock)]
    assert code, "the {\\footnotesize \\begin{verbatim}...} prompt was dropped"
    text = "\n".join(c.text for c in code)
    assert "failure-analysis agent" in text
    assert "valid JSON object" in text
    assert len(text) > 200


# -- box / font plumbing is silent ------------------------------------------- #


def test_uat3_mbox_keeps_its_content():
    paras = " ".join(
        _all_text(b.inlines) for b in _doc().blocks if isinstance(b, ir.Paragraph)
    )
    assert "best_skill.md" in paras  # \mbox{\texttt{best\_skill.md}} survived
