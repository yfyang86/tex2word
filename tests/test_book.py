from __future__ import annotations

import io
import zipfile

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.roundtrip import recover_ir, to_latex
from latex2word.validate import validate_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _headings(docx: bytes) -> list[tuple[str, str | None, str | None, str]]:
    root = etree_fromstring(docx)
    out = []
    for p in root.iter(f"{{{W}}}p"):
        st = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        if st is None or not st.get(f"{{{W}}}val", "").startswith("Heading"):
            continue
        numpr = p.find(f"{{{W}}}pPr/{{{W}}}numPr")
        ilvl = nid = None
        if numpr is not None:
            ilvl = numpr.find(f"{{{W}}}ilvl").get(f"{{{W}}}val")
            nid = numpr.find(f"{{{W}}}numId").get(f"{{{W}}}val")
        txt = "".join(t.text or "" for t in p.iter(f"{{{W}}}t"))
        out.append((st.get(f"{{{W}}}val"), ilvl, nid, txt))
    return out


def etree_fromstring(docx: bytes):
    from lxml import etree
    return etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))


_BOOK = r"""\documentclass{report}
\begin{document}
\chapter{Intro}\label{c:i}
\section{Background}
\subsection{Detail}
\appendix
\chapter{Extra}\label{a:x}
\section{More}
\end{document}"""


# -- parsing / levels -------------------------------------------------------- #


def test_book_mode_detected_and_chapter_is_top_level():
    doc, _ = parse_document(_BOOK, ".")
    assert doc.book is True
    headings = [b for b in doc.blocks if isinstance(b, ir.Heading)]
    levels = {h.inlines[0].value: h.level for h in headings if h.inlines}
    assert levels["Intro"] == 1 and levels["Background"] == 2 and levels["Detail"] == 3


def test_article_section_stays_level_1():
    src = r"\documentclass{article}\begin{document}\section{S}\end{document}"
    doc, _ = parse_document(src, ".")
    assert doc.book is False
    h = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    assert h.level == 1


def test_chapter_presence_triggers_book_mode_without_class():
    # even with article class, a \chapter switches to book sectioning
    doc, _ = parse_document(r"\begin{document}\chapter{C}\section{S}\end{document}", ".")
    assert doc.book is True


def test_appendix_flag_on_later_headings():
    doc, _ = parse_document(_BOOK, ".")
    headings = {h.inlines[0].value: h for h in doc.blocks if isinstance(h, ir.Heading)}
    assert headings["Intro"].appendix is False
    assert headings["Extra"].appendix is True and headings["More"].appendix is True


# -- backend numbering ------------------------------------------------------- #


def test_book_headings_use_nested_numbering():
    rows = _headings(convert_source(_BOOK).docx)
    # chapter / section / subsection -> Heading1/2/3 at ilvl 0/1/2, list numId 3
    assert rows[0] == ("Heading1", "0", "3", "Intro")
    assert rows[1] == ("Heading2", "1", "3", "Background")
    assert rows[2] == ("Heading3", "2", "3", "Detail")


def test_appendix_uses_letter_numbering_list():
    rows = _headings(convert_source(_BOOK).docx)
    extra = next(r for r in rows if r[3] == "Extra")
    more = next(r for r in rows if r[3] == "More")
    assert extra == ("Heading1", "0", "4", "Extra")  # numId 4 = lettered list
    assert more == ("Heading2", "1", "4", "More")


def test_book_output_is_valid():
    assert validate_docx(convert_source(_BOOK).docx) == []


def test_article_numbering_unchanged():
    rows = _headings(
        convert_source(
            r"\documentclass{article}\begin{document}\section{S}\subsection{T}\end{document}"
        ).docx
    )
    assert rows[0] == ("Heading1", "0", "3", "S")
    assert rows[1] == ("Heading2", "1", "3", "T")


# -- round-trip -------------------------------------------------------------- #


def test_book_round_trips():
    res = convert_source(_BOOK, embed_manifest=True)
    assert recover_ir(res.docx).to_dict() == res.document.to_dict()
    latex = to_latex(res.docx)
    assert "\\documentclass{report}" in latex
    assert "\\chapter{Intro}" in latex
    assert "\\appendix" in latex
