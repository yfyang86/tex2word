"""UAT: arXiv:2507.17026v2 (ICML 2026), a recent real paper.

The paper splits its custom commands into a local ``style.sty`` pulled in with
``\\usepackage{style}`` -- including the ``\\@for ... \\do{...}`` generator idiom
that synthesises ``\\cA..\\cZ`` (calligraphic) and ``\\bA..\\bZ`` (blackboard)
families. It exercises local-package macro loading, the run-in ``\\paragraph``
headings pylatexenc's defaults drop, and the math constructs (``\\{`` / ``\\}``,
``\\Big``, ``\\xrightarrow``, ``\\overset``) the full paper sent down the lossy
fallback path before these fixes.
"""

from __future__ import annotations

import os

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.frontend.macros import (
    Macro,
    _is_safe_macro,
    _load_local_package_macros,
    expand_macros,
)
from tex2word.roundtrip import recover_ir
from tex2word.validate import validate_docx

UAT_DIR = os.path.join(os.path.dirname(__file__), "uat", "arXiv-2507.17026v2")


def _main_source() -> str:
    with open(os.path.join(UAT_DIR, "main.tex"), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #


def test_uat_converts_without_errors():
    result = convert_source(_main_source(), base_dir=UAT_DIR)
    assert result.report.errors == [], result.report.errors


def test_uat_output_is_valid_ooxml():
    result = convert_source(_main_source(), base_dir=UAT_DIR)
    assert validate_docx(result.docx) == []


def test_uat_all_math_is_native_omml():
    # the whole point of the local-package + math-construct fixes: nothing
    # should fall through to the lossy raw path.
    result = convert_source(_main_source(), base_dir=UAT_DIR)
    cov = result.report.coverage()
    assert cov["math_total"] > 0
    assert cov["math_raw"] == 0, "math fell back to raw LaTeX"
    assert cov["math_image"] == 0


def test_uat_roundtrips_to_same_ir():
    result = convert_source(_main_source(), base_dir=UAT_DIR)
    recovered = recover_ir(result.docx)
    assert recovered is not None
    assert recovered.to_dict() == result.document.to_dict()


def test_uat_headings_recovered():
    doc, _ = parse_document(_main_source(), UAT_DIR)
    headings = [b for b in doc.blocks if isinstance(b, ir.Heading)]
    titles = {"".join(getattr(i, "value", "") for i in h.inlines) for h in headings}
    # the run-in \paragraph titles must survive (they used to leak into the body)
    assert "Summary of contributions." in titles
    assert "A toy example." in titles
    assert "Introduction" in titles


# --------------------------------------------------------------------------- #
# Local-package (.sty) macro loading
# --------------------------------------------------------------------------- #


def test_local_sty_simple_macros_loaded():
    macros = _load_local_package_macros(_main_source(), UAT_DIR)
    # plain \newcommand definitions from style.sty
    assert "EE" in macros and macros["EE"].body == r"\mathbb{E}"
    assert "RR" in macros and macros["RR"].body == r"\mathbb{R}"
    assert "var" in macros and macros["var"].body == r"\text{Var}"
    assert "inv" in macros and macros["inv"].body == "^{-1}"


def test_generator_idiom_synthesises_letter_families():
    # \@for\i:=\LatinUpper\do{\expandafter\genCal\i} -> \cA..\cZ etc.
    macros = _load_local_package_macros(_main_source(), UAT_DIR)
    assert macros["cM"].body == r"{\mathcal M}"
    assert macros["cO"].body == r"{\mathcal O}"
    assert macros["bI"].body == r"{\mathbb I}"
    assert macros["bP"].body == r"{\mathbb P}"


def _mk(name: str, body: str) -> Macro:
    return Macro(name, 0, None, body)


def test_unsafe_package_internals_are_rejected():
    # \section is structural (rebuilt via \@startsection in icml2026.sty);
    # harvesting that would clobber the heading. Recursive \ifx generators
    # and self-referential macros must be dropped too. Plain bodies pass.
    assert not _is_safe_macro(_mk("section", r"\@startsection{}{}{}"))
    assert not _is_safe_macro(_mk("foo", r"\ifx\foo X\else Y\fi"))
    assert not _is_safe_macro(_mk("rec", r"\rec next"))  # self-reference
    assert _is_safe_macro(_mk("EE", r"\mathbb{E}"))


def test_recursive_stylesheet_does_not_hang():
    # style.sty's \mydefallgreek is \ifx tail-recursion; expansion must still
    # terminate quickly (this used to blow up to a timeout).
    out = expand_macros(r"\usepackage{style} $\EE[X]$ and $\cM$", UAT_DIR)
    assert r"\mathbb{E}" in out
    assert r"{\mathcal M}" in out
