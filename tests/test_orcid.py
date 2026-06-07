"""V5-10: \\orcid -> an ORCID link in the title block."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.roundtrip import to_latex


def test_orcid_becomes_an_affiliation_link():
    src = r"\begin{document}\title{T}\author{A}\orcid{0000-0002-1825-0097}\maketitle\end{document}"
    doc, _ = parse_document(src)
    link = next(
        i for aff in doc.meta.affiliations for i in aff if isinstance(i, ir.Link)
    )
    assert link.url == "https://orcid.org/0000-0002-1825-0097"


def test_orcid_renders_and_round_trips():
    src = r"\begin{document}\title{T}\author{A}\orcid{0000-0002-1825-0097}\maketitle\end{document}"
    res = convert_source(src)
    xml = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml").decode()
    assert "0000-0002-1825-0097" in xml
    assert "orcid.org/0000-0002-1825-0097" in to_latex(res.docx)


def test_orcid_full_url_kept():
    src = r"\begin{document}\title{T}\author{A}\orcid{https://orcid.org/0000-0001-2345-6789}\maketitle\end{document}"
    doc, _ = parse_document(src)
    link = next(i for aff in doc.meta.affiliations for i in aff if isinstance(i, ir.Link))
    assert link.url == "https://orcid.org/0000-0001-2345-6789"
