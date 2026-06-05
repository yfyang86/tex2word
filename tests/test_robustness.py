from __future__ import annotations

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.frontend.preprocess import strip_comments


def _blocks(src: str):
    doc, report = parse_document(src)
    return doc, report


def test_preamble_with_newenvironment_does_not_break_body():
    # \newenvironment defines an env whose body has an unbalanced \begin{itemize}
    # in one brace group -- this used to break \begin{document} matching.
    src = r"""
\documentclass{article}
\newenvironment{ul}{\begin{itemize}}{\end{itemize}}
\AtBeginDocument{\providecommand\X{{x}}}
\begin{document}
\section{Intro}
Real body text here.
\end{document}
"""
    doc, _ = _blocks(src)
    headings = [b for b in doc.blocks if isinstance(b, ir.Heading)]
    assert any(h.inlines and getattr(h.inlines[0], "value", "") == "Intro" for h in headings)
    text = " ".join(
        t.value for b in doc.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "Real body text here." in text


def test_unknown_environment_is_transparent():
    # An unknown wrapper without \item is transparent (content preserved).
    doc, report = _blocks(
        r"\begin{document}\begin{fancybox}kept content\end{fancybox}\end{document}"
    )
    text = " ".join(
        t.value for b in doc.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "kept content" in text
    assert any("transparent" in w.message for w in report.warnings)


def test_custom_list_wrapper_renders_as_list():
    # A user \newenvironment wrapping itemize (\item inside) -> a real list,
    # not leaked "\item" text.
    doc, _ = _blocks(
        r"\begin{document}\begin{ul}\item one\item two\end{ul}\end{document}"
    )
    lists = [b for b in doc.blocks if isinstance(b, ir.ItemList)]
    assert lists and len(lists[0].items) == 2
    flat = " ".join(
        t.value
        for it in lists[0].items
        for blk in it.blocks if isinstance(blk, ir.Paragraph)
        for t in blk.inlines if isinstance(t, ir.Text)
    )
    assert "one" in flat and "two" in flat
    assert "\\item" not in flat


def test_opaque_environment_becomes_placeholder():
    doc, report = _blocks(
        r"\begin{document}\begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}\end{document}"
    )
    assert any(isinstance(b, ir.Figure) and b.image is None for b in doc.blocks)
    assert any("placeholder" in w.message for w in report.warnings)


def test_title_recovered_from_preamble():
    src = r"""
\documentclass{article}
\title{A Preamble Title}
\begin{document}
\maketitle
Body.
\end{document}
"""
    doc, _ = _blocks(src)
    assert doc.meta.title is not None
    assert doc.meta.title[0].value == "A Preamble Title"


def test_xspace_inserts_space_between_words():
    doc, _ = _blocks(r"\begin{document}Cache\xspace Practical.\end{document}")
    text = "".join(
        t.value for b in doc.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "Cache Practical" in text
    assert "CachePractical" not in text


def test_xspace_suppressed_before_punctuation():
    doc, _ = _blocks(r"\begin{document}Tutti\xspace: Making.\end{document}")
    text = "".join(
        t.value for b in doc.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "Tutti:" in text
    assert "Tutti :" not in text


def test_comment_line_is_not_a_paragraph_break():
    # A full-line %comment must NOT split a paragraph: TeX eats the newline, so
    # the surrounding soft newlines keep the sentences in one paragraph.
    assert strip_comments("A\n% comment\nB") == "A\nB"
    assert "\n\n" not in strip_comments("one\n%c\ntwo\n%d\nthree")


def test_escaped_percent_preserved():
    assert strip_comments(r"100\% done") == r"100\% done"


def test_soft_newlines_and_comments_keep_one_paragraph():
    src = (
        "\\begin{document}\n"
        "First sentence on a line\n"
        "% an interspersed comment\n"
        "second sentence on the next line.\n"
        "\\end{document}"
    )
    doc, _ = parse_document(src)
    paras = [b for b in doc.blocks if isinstance(b, ir.Paragraph)]
    assert len(paras) == 1
    text = "".join(t.value for t in paras[0].inlines if isinstance(t, ir.Text))
    assert "First sentence on a line second sentence on the next line." in text


def test_blank_line_still_splits_paragraphs():
    doc, _ = parse_document("\\begin{document}Para one.\n\nPara two.\\end{document}")
    paras = [b for b in doc.blocks if isinstance(b, ir.Paragraph)]
    assert len(paras) == 2


def test_paragraph_edges_trimmed():
    doc, _ = parse_document("\\begin{document}   spaced text   \n\n\\end{document}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    assert para.inlines[0].value == "spaced text"


def test_figure_label_not_overwritten_by_trailing_label():
    # A figure's own \label must survive a stray \label after \end{figure}
    # (which in LaTeX also refers to the figure counter). Regression: the
    # trailing label used to overwrite the figure's.
    src = (
        r"\begin{document}\begin{figure}\includegraphics{a.png}"
        r"\caption{C}\label{fig:real}\end{figure}\label{fig:stray}"
        r"See \ref{fig:real}.\end{document}"
    )
    doc, report = parse_document(src)
    fig = next(b for b in doc.blocks if isinstance(b, ir.Figure))
    assert fig.label == "fig:real"
    from latex2word.transforms.crossref import resolve_crossrefs

    resolve_crossrefs(doc, report)
    assert "fig:real" in doc.labels
    assert not any("fig:real" in w.message for w in report.warnings)


def test_macro_with_xspace_expands_cleanly():
    # \sys -> "Tutti\xspace"; "\sys is fast" must become "Tutti is fast" (one
    # space, no fusion) -- a common arXiv pattern.
    src = r"""
\documentclass[sigplan]{acmart}
\setcopyright{acmlicensed}
\newcommand{\sys}{Tutti\xspace}
\begin{document}
\section{Eval}
\sys is fast and \sys scales.
\end{document}
"""
    result = convert_source(src)
    assert result.report.errors == []
    text = "".join(
        t.value for b in result.document.blocks if isinstance(b, ir.Paragraph)
        for t in b.inlines if isinstance(t, ir.Text)
    )
    assert "Tutti is fast and Tutti scales." in text
