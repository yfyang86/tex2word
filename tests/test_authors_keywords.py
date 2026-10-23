"""V5-10: multi-author (\\and) and keywords in the title block."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.roundtrip import to_latex


def _text(inlines) -> str:
    return "".join(i.value for i in inlines if isinstance(i, ir.Text)).strip()


def _docxml(docx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()


def test_and_splits_authors_in_preamble():
    src = (
        r"\documentclass{article}\title{T}"
        r"\author{Alice Smith \and Bob Jones}\begin{document}\maketitle\end{document}"
    )
    doc, _ = parse_document(src)
    names = [_text(a) for a in doc.meta.authors]
    assert len(doc.meta.authors) == 2
    assert any("Alice" in n for n in names) and any("Bob" in n for n in names)


def test_and_splits_authors_in_body():
    src = r"\begin{document}\title{T}\author{Ada \and Grace \and Linus}\maketitle\end{document}"
    doc, _ = parse_document(src)
    assert len(doc.meta.authors) == 3


def test_each_author_is_its_own_subtitle_paragraph():
    src = r"\begin{document}\title{T}\author{Ada \and Grace}\maketitle\end{document}"
    docx = convert_source(src).docx
    xml = _docxml(docx)
    assert "Ada" in xml and "Grace" in xml
    assert xml.count('w:val="Subtitle"') >= 2  # one Subtitle paragraph per author


def test_keywords_render_and_round_trip():
    src = (
        r"\begin{document}\title{T}\author{A}\maketitle"
        r"\begin{abstract}Summary.\end{abstract}\keywords{graphs, trees}\end{document}"
    )
    res = convert_source(src)
    xml = _docxml(res.docx)
    assert "Keywords:" in xml and "graphs, trees" in xml
    latex = to_latex(res.docx)  # manifest round-trip
    assert "graphs, trees" in latex


def test_ieeekeywords_is_recognised():
    src = r"\begin{document}\title{T}\author{A}\maketitle\IEEEkeywords{deep learning}\end{document}"
    doc, _ = parse_document(src)
    assert doc.meta.keywords is not None and "deep learning" in _text(doc.meta.keywords)


# -- affiliations ------------------------------------------------------------ #


def test_institute_split_on_and():
    src = (
        r"\documentclass{llncs}\title{T}\author{Alice\inst{1} \and Bob\inst{2}}"
        r"\institute{MIT \and CMU}\begin{document}\maketitle\end{document}"
    )
    doc, _ = parse_document(src)
    affils = [_text(a) for a in doc.meta.affiliations]
    assert len(doc.meta.affiliations) == 2
    assert any("MIT" in a for a in affils) and any("CMU" in a for a in affils)


def test_inst_marker_is_superscript():
    src = r"\begin{document}\title{T}\author{Alice\inst{1}}\maketitle\end{document}"
    doc, _ = parse_document(src)
    author = doc.meta.authors[0]
    assert any(isinstance(i, ir.Emphasis) and i.kind_ == "superscript" for i in author)


def test_affiliations_render_and_round_trip():
    src = (
        r"\begin{document}\title{T}\author{A}\affiliation{Dept of CS, Example U}"
        r"\maketitle\end{document}"
    )
    res = convert_source(src)
    assert "Dept of CS, Example U" in _docxml(res.docx)
    assert "Dept of CS, Example U" in to_latex(res.docx)


def test_ieeetran_author_block_content_survives():
    src = (
        r"\begin{document}\title{T}"
        r"\author{\IEEEauthorblockN{Grace Hopper}\IEEEauthorblockA{US Navy}}"
        r"\maketitle\end{document}"
    )
    doc, _ = parse_document(src)
    joined = " ".join(_text(a) for a in doc.meta.authors)
    assert "Grace Hopper" in joined and "US Navy" in joined


def test_today_expands_in_date_block():
    # \date{\today} must expand to the current date, not emit literal "\today"
    import datetime
    t = datetime.date.today()
    exp = f"{t:%B} {t.day}, {t.year}"
    doc, _ = parse_document(
        r"\documentclass{article}\title{T}\date{\today}\begin{document}\maketitle\end{document}"
    )
    assert doc.meta.date is not None
    text = "".join(getattr(i, "value", "") for i in doc.meta.date)
    assert text == exp
    assert "\\today" not in text


def test_omitted_date_defaults_to_today_when_title_present():
    import datetime
    t = datetime.date.today()
    exp = f"{t:%B} {t.day}, {t.year}"
    doc, _ = parse_document(
        r"\documentclass{article}\title{T}\begin{document}\maketitle\end{document}"
    )
    assert doc.meta.date and "".join(getattr(i, "value", "") for i in doc.meta.date) == exp


def test_empty_date_stays_empty():
    # an explicit \date{} suppresses the date; today must not be injected
    doc, _ = parse_document(
        r"\documentclass{article}\title{T}\date{}\begin{document}\maketitle\end{document}"
    )
    assert not doc.meta.date  # None or empty, never today


def test_redefined_today_is_used_for_the_default_date():
    # \renewcommand{\today}{...} must win over the real date, both for an
    # omitted \date (the \maketitle default) and for \date{\today}.
    for src in (
        r"\renewcommand{\today}{2026-09-04}\title{T}\begin{document}\maketitle\end{document}",
        r"\renewcommand{\today}{2026-09-04}\title{T}\date{\today}"
        r"\begin{document}\maketitle\end{document}",
    ):
        doc, _ = parse_document(src)
        assert "".join(getattr(i, "value", "") for i in doc.meta.date) == "2026-09-04"
