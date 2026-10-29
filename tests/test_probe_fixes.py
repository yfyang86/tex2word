"""Regression tests for defects found by the synthetic probe harness (tools/synth)."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source, ir


def _doc(body: str, preamble: str = "", cls: str = "article"):
    return convert_source(
        f"\\documentclass{{{cls}}}\n{preamble}\n\\begin{{document}}\n{body}\n\\end{{document}}\n"
    )


def _text(r, part: str = "word/document.xml") -> str:
    xml = zipfile.ZipFile(io.BytesIO(r.docx)).read(part).decode()
    runs = re.findall(r"<[wm]:t(?: [^>]*)?>([^<]*)</[wm]:t>", xml)
    return "".join(runs).replace("&amp;", "&").replace("\u00a0", " ")


def _warnings(r) -> list[str]:
    return [w.message for w in r.report.warnings]


def test_control_characters_do_not_crash():
    r = _doc("A \x0c B \x07 C \x1b D")
    assert "A" in _text(r) and "D" in _text(r)


def test_percent_inside_verbatim_and_verb_is_text():
    r = _doc("\\begin{verbatim}\nx = 1 % not a comment\n\\end{verbatim}\n\\verb|50% off| % gone")
    text = _text(r)
    assert "x = 1 % not a comment" in text
    assert "50% off" in text and "gone" not in text


def test_block_content_in_a_footnote_is_kept():
    r = _doc(r"Text\footnote{Intro. \begin{itemize}\item NOTEA\end{itemize}"
             r"\begin{quote}NOTEB\end{quote}}")
    notes = _text(r, "word/footnotes.xml")
    assert "Intro." in notes and "NOTEA" in notes and "NOTEB" in notes
    fn = next(n for n in ir.iter_nodes(r.document) if isinstance(n, ir.Footnote))
    assert fn.blocks


def test_tabular_inside_a_caption_or_box_keeps_its_text():
    r = _doc(r"\begin{figure}\caption{See \begin{tabular}{ll}CELLA & CELLB\end{tabular}}"
             r"\end{figure}\fbox{\begin{tabular}{l}CELLC\end{tabular}}", r"\usepackage{graphicx}")
    text = _text(r)
    assert "CELLA" in text and "CELLB" in text and "CELLC" in text


def test_text_in_math_keeps_its_spaces():
    r = _doc(r"$x = 1 \text{ if } y > 0$ and $\mbox{for all } z$")
    text = _text(r)
    assert " if " in text and "for all " in text


def test_newenvironment_begin_and_end_code():
    r = _doc(r"\begin{note}BODY\end{note} \begin{titled}{HEAD}TAIL\end{titled}",
             r"\newenvironment{note}{\begin{quote}\textbf{Note:} }{\end{quote}}"
             r"\newenvironment{titled}[1]{\textbf{#1}: }{.}")
    text = _text(r)
    assert "Note: BODY" in text and "HEAD: TAIL." in text
    assert not _warnings(r)


def test_pageref_resolves():
    r = _doc(r"\section{S}\label{s}See page~\pageref{s}.")
    assert "??" not in _text(r) and "s." not in _text(r).split("page")[-1][:3]
    assert not _warnings(r)


def test_cite_locator_keeps_its_tie_and_url_its_tilde():
    r = _doc(r"\citep[see][p.~3]{x} \url{https://example.org/~user/a_b}"
             r"\begin{thebibliography}{9}\bibitem{x} X. Author.\end{thebibliography}",
             r"\usepackage{natbib}")
    text = _text(r)
    assert "p. 3" in text
    assert "~user/a_b" in text


def test_text_letters_and_accented_dotless_i():
    r = _doc(r"Gro\ss e \o \aa \l \AE \oe{} na\"{\i}ve \glqq Q\grqq")
    text = _text(r)
    for s in ("Große", "ø", "å", "ł", "Æ", "œ", "naïve", "„Q“"):
        assert s in text, s
    assert not _warnings(r)


def test_make_uppercase_parbox_foreignlanguage():
    r = _doc(r"\MakeUppercase{shout} \parbox{3cm}{BOXED} \foreignlanguage{french}{FR}"
             r"\selectlanguage{english}")
    text = _text(r)
    assert "SHOUT" in text and "BOXED" in text and "FR" in text
    assert not _warnings(r)


def test_parbox_with_paragraphs_becomes_blocks():
    r = _doc("\\parbox{5cm}{First.\n\nSecond.}")
    paras = [b for b in r.document.blocks if isinstance(b, ir.Paragraph)]
    assert len(paras) == 2


def test_theorem_numbered_within_section():
    r = _doc(r"\section{S}\begin{theorem}A\end{theorem}",
             r"\newtheorem{theorem}{Theorem}[section]\newtheorem{lemma}[theorem]{Lemma}")
    xml = zipfile.ZipFile(io.BytesIO(r.docx)).read("word/document.xml").decode()
    assert "STYLEREF 1 \\n" in xml and "SEQ Theorem \\r 1 \\s 1" in xml
    thm = next(b for b in r.document.blocks if isinstance(b, ir.Theorem))
    assert thm.within == "section"


def test_class_environments():
    r = _doc(r"\begin{abstract}A\end{abstract}\begin{IEEEkeywords}kw1, kw2\end{IEEEkeywords}"
             r"\begin{acks}THANKS\end{acks}\begin{comment}HIDDEN\end{comment}"
             r"\begin{IEEEbiography}{Jane Roe}Bio.\end{IEEEbiography}"
             r"\begin{multicols}{2}COLS\end{multicols}", cls="IEEEtran")
    text = _text(r)
    assert "kw1, kw2" in text and "THANKS" in text and "Acknowledgments" in text
    assert "HIDDEN" not in text and "Jane Roe" in text and "COLS" in text
    assert "2COLS" not in text
    assert not _warnings(r)


def test_elsarticle_keyword_separators():
    r = _doc(r"\begin{frontmatter}\begin{keyword}one \sep two\end{keyword}\end{frontmatter}",
             cls="elsarticle")
    assert "one; two" in _text(r)
