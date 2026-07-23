"""Preprocess transforms for the exam / oxmathproblems problem-sheet class.

Covers the pieces that make an Oxford-style problem sheet render like the
compiled PDF: nested numbered lists from questions/parts/subparts, a recovered
title block, plain-TeX \\halign systems -> array, and hidden solutions.
"""

from __future__ import annotations

from tex2word.frontend.preprocess import (
    _inject_exam_title,
    _rewrite_halign,
    preprocess,
)

# a minimal exam-class document (matches oxmathproblems' \LoadClass{exam} shape
# closely enough for the class detector, which also accepts \documentclass{exam})
_HEAD = r"\documentclass{exam}"


def _pp(body: str) -> str:
    return preprocess(_HEAD + r"\begin{document}" + body + r"\end{document}")


# -- questions/parts/subparts -> nested enumerate --------------------------- #


def test_questions_env_becomes_enumerate():
    out = _pp(r"\begin{questions}\question a \question b\end{questions}")
    assert r"\begin{enumerate}" in out and r"\begin{questions}" not in out
    assert out.count(r"\item") == 2


def test_part_marker_does_not_leak_as_sectioning():
    # exam's \part is a sub-item, NOT \part sectioning -> must become \item
    out = _pp(r"\begin{questions}\question\begin{parts}\part x\part y\end{parts}\end{questions}")
    assert r"\part" not in out
    assert out.count(r"\item") == 3  # one question + two parts


def test_points_argument_is_dropped():
    out = _pp(r"\begin{questions}\question[7] foo\end{questions}")
    assert "[7]" not in out and r"\item" in out


# -- solutions hidden unless \printanswers ---------------------------------- #


def test_solution_hidden_without_printanswers():
    out = _pp(r"\begin{questions}\question q\begin{solution}secret\end{solution}\end{questions}")
    assert "secret" not in out


def test_solution_shown_with_printanswers():
    out = preprocess(
        _HEAD + r"\printanswers\begin{document}"
        r"\begin{questions}\question q\begin{solution}secret\end{solution}\end{questions}"
        r"\end{document}"
    )
    assert "secret" in out


# -- \halign system of equations -> array ----------------------------------- #


def test_halign_display_becomes_array():
    src = (
        r"\[\centerline{\hbox{\vbox{\openup1.5\jot"
        r"\halign{\hss$#$\hss&&$#$\cr x&=&5\cr y&=&7\cr}}}}\]"
    )
    out = _rewrite_halign(src)
    assert r"\halign" not in out and r"\centerline" not in out
    assert r"\begin{array}" in out and r"\end{array}" in out
    # the data rows survive; the template row (before the first \cr) is dropped
    assert "x" in out and "5" in out and "7" in out


def test_halign_without_display_left_untouched():
    src = r"plain text with no display math"
    assert _rewrite_halign(src) == src


# -- recovered title block -------------------------------------------------- #


def test_inject_exam_title_builds_center_block():
    src = (
        r"\course{Impossible Maths I}\sheetnumber{3}\oxfordterm{MT18}"
        r"\sheettitle{First topic questions}\begin{document}body\end{document}"
    )
    out = _inject_exam_title(src)
    assert r"\begin{center}" in out
    assert "Impossible Maths I" in out
    assert "Sheet 3" in out and "MT18" in out
    assert "First topic questions" in out


def test_inject_exam_title_noop_without_metadata():
    src = r"\begin{document}body\end{document}"
    assert _inject_exam_title(src) == src
