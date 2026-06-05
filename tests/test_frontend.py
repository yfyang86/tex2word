from __future__ import annotations

from tex2word import ir
from tex2word.frontend import parse_document
from tex2word.frontend.macros import expand_macros

SAMPLE = r"""
\title{Sample}
\author{Ada Lovelace}
\begin{document}
\maketitle
\section{Introduction}\label{sec:intro}
Hello \textbf{world}, math $x^2$ and \ref{eq:e}.

\begin{equation}\label{eq:e}
E = mc^2
\end{equation}

\begin{itemize}
\item First
\item Second
\end{itemize}
\end{document}
"""


def test_parses_title_and_authors():
    doc, _ = parse_document(SAMPLE)
    assert isinstance(doc.meta.title[0], ir.Text)
    assert doc.meta.title[0].value == "Sample"
    assert doc.meta.authors[0][0].value == "Ada Lovelace"


def test_block_structure():
    doc, _ = parse_document(SAMPLE)
    kinds = [type(b).__name__ for b in doc.blocks]
    assert "Heading" in kinds
    assert "MathBlock" in kinds
    assert "ItemList" in kinds


def test_section_label_attached():
    doc, _ = parse_document(SAMPLE)
    heading = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    assert heading.label == "sec:intro"


def test_equation_label_and_numbered():
    doc, _ = parse_document(SAMPLE)
    mb = next(b for b in doc.blocks if isinstance(b, ir.MathBlock))
    assert mb.label == "eq:e"
    assert mb.numbered is True
    assert mb.latex.strip() == "E = mc^2"


def test_inline_emphasis_and_math():
    doc, _ = parse_document(SAMPLE)
    para = next(
        b for b in doc.blocks
        if isinstance(b, ir.Paragraph) and any(isinstance(i, ir.Emphasis) for i in b.inlines)
    )
    assert any(isinstance(i, ir.Math) for i in para.inlines)
    assert any(isinstance(i, ir.Ref) for i in para.inlines)


def test_starred_equation_not_numbered():
    doc, _ = parse_document(r"\begin{document}\begin{equation*}x=1\end{equation*}\end{document}")
    mb = next(b for b in doc.blocks if isinstance(b, ir.MathBlock))
    assert mb.numbered is False


def test_unknown_macro_degrades_gracefully():
    doc, report = parse_document(r"\begin{document}Text \weirdmacro here.\end{document}")
    # no exception, and a warning recorded
    assert any("weirdmacro" in w.construct for w in report.warnings)


def test_newcommand_expansion():
    expanded = expand_macros(r"\newcommand{\foo}[1]{Hello #1!}\foo{World}")
    assert "Hello World!" in expanded


def test_def_expansion():
    expanded = expand_macros(r"\def\x{42}value is \x.")
    assert "value is 42." in expanded


def test_newcommand_optional_arg():
    assert "D-b" in expand_macros(r"\newcommand{\x}[2][D]{#1-#2}\x{b}")
    assert "a-b" in expand_macros(r"\newcommand{\x}[2][D]{#1-#2}\x[a]{b}")


def test_declare_robust_command():
    assert "Tutti is fast" in expand_macros(r"\DeclareRobustCommand{\sys}{Tutti}\sys is fast")
