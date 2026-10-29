"""Static resolution of LaTeX conditionals (found by the synthetic probes)."""

from __future__ import annotations

from tex2word.frontend.conditionals import resolve_conditionals as rc


def _norm(s: str) -> str:
    return " ".join(s.split())


def test_newif_switch_follows_assignments_in_order():
    src = r"\newif\ifdraft \ifdraft A\else B\fi \drafttrue \ifdraft C\else D\fi"
    assert _norm(rc(src)) == "B C"


def test_iftrue_iffalse_with_else():
    assert _norm(rc(r"\iftrue A\else B\fi")) == "A"
    assert _norm(rc(r"\iffalse A\else B\fi")) == "B"
    assert _norm(rc(r"x \iffalse dropped \section{y} \fi z")) == "x z"


def test_math_iff_is_not_a_conditional():
    # \iff (a relation) inside a disabled block must not unbalance the nesting
    assert _norm(rc(r"\iffalse $a \iff b$ \fi kept")) == "kept"
    assert _norm(rc(r"$a \iff b$")) == r"$a \iff b$"


def test_nested_conditionals():
    src = r"\newif\ifa\atrue \ifa X \iffalse no \else yes \fi Y\else Z\fi"
    assert _norm(rc(src)) == "X yes Y"


def test_undecidable_tests_are_left_alone_but_their_body_is_resolved():
    src = r"\ifnum\value{page}>1 A \iftrue B\fi \else C\fi"
    assert _norm(rc(src)) == r"\ifnum\value{page}>1 A B \else C\fi"
    assert _norm(rc(r"\ifx\a\b A\else B\fi")) == r"\ifx\a\b A\else B\fi"
    assert rc(r"\ifxetex A\else B\fi") == r"\ifxetex A\else B\fi"


def test_ifdefined_and_ifcsname():
    src = r"\newcommand{\foo}{x}\ifdefined\foo A\else B\fi \ifdefined\nope C\else D\fi"
    assert _norm(rc(src)).endswith("A D")
    assert _norm(rc(r"\ifcsname section\endcsname S\else T\fi")) == "S"


def test_ifthenelse_booleans_and_equal():
    src = (r"\newboolean{long}\setboolean{long}{true}"
           r"\ifthenelse{\boolean{long}}{L}{S} \ifthenelse{\not\boolean{long}}{N}{Y}"
           r" \ifthenelse{\equal{a}{a}}{E}{F}")
    assert _norm(rc(src)) == "L Y E"


def test_etoolbox_toggles_bools_and_ifdef():
    src = (r"\newtoggle{ans}\toggletrue{ans}\iftoggle{ans}{T}{F} \nottoggle{ans}{N}{Y}"
           r" \newbool{b}\ifbool{b}{B}{C} \ifdef{\section}{D}{E} \ifundef{\zzz}{U}{V}")
    assert _norm(rc(src)) == "T Y C D U"


def test_file_and_package_tests(tmp_path):
    (tmp_path / "here.tex").write_text("x", encoding="utf-8")
    src = (r"\documentclass{article}\usepackage[x]{hyperref,amsmath}"
           r"\IfFileExists{here}{F}{G} \IfFileExists{gone.tex}{H}{I}"
           r" \makeatletter\@ifpackageloaded{amsmath}{P}{Q}\@ifclassloaded{book}{R}{S}")
    out = _norm(rc(src, str(tmp_path)))
    assert out.endswith(r"F I \makeatletter PS")


def test_verbatim_is_untouched():
    src = "\\begin{verbatim}\n\\iftrue A\\else B\\fi\n\\end{verbatim} \\verb|\\iffalse| C"
    assert rc(src) == src


def test_unknown_unbalanced_input_does_not_crash():
    assert rc(r"\iftrue never closed") == r"\iftrue never closed"
    assert rc(r"\ifthenelse{\boolean{x}}{A}") == r"\ifthenelse{\boolean{x}}{A}"
