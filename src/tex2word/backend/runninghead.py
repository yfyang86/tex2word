"""Generate a running-head header + page-number footer (V5-12).

When a document declares a running head (``\\markboth``/``\\markright``/
``\\runninghead``/``\\title[short]{…}``) and no ``--reference-doc`` supplies its
own headers/footers, we synthesise a minimal default header (the running title)
and a centred ``PAGE`` field footer. The parts are wired into the package exactly
like template-carried headers/footers (content-type override + relationship +
``sectPr`` reference), so the live page numbering renders in Word.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_HEADER_TMPL = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<w:hdr xmlns:w="{_W_NS}">'
    '<w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
    '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
    "</w:p></w:hdr>"
)

_FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<w:ftr xmlns:w="{_W_NS}">'
    '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:t>1</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p></w:ftr>"
)


def header_xml(running_head: str) -> bytes:
    return _HEADER_TMPL.format(text=escape(running_head)).encode("utf-8")


def footer_xml() -> bytes:
    return _FOOTER_XML.encode("utf-8")
