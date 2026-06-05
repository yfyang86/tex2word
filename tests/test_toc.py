from __future__ import annotations

import io
import zipfile

from lxml import etree

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.frontend.docx_reader import read_docx
from latex2word.roundtrip import recover_ir, to_latex
from latex2word.validate import validate_docx

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

SRC = (
    r"\begin{document}"
    r"\tableofcontents\listoffigures\listoftables"
    r"\section{Intro}\label{s:i} Hi."
    r"\end{document}"
)


def _instrs(docx: bytes) -> list[str]:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml")
    root = etree.fromstring(xml)
    return [
        (e.text or "").strip() for e in root.iter(f"{{{NS['w']}}}instrText")
    ]


# -- parse ------------------------------------------------------------------- #


def test_toc_macros_parse_to_ir():
    doc, _ = parse_document(
        r"\tableofcontents\listoffigures\listoftables", "."
    )
    tocs = [b for b in doc.blocks if isinstance(b, ir.TableOfContents)]
    assert [b.kind for b in tocs] == ["contents", "figures", "tables"]


# -- emit -------------------------------------------------------------------- #


def test_toc_emits_field_instructions():
    instrs = [i for i in _instrs(convert_source(SRC).docx) if "TOC" in i]
    assert 'TOC \\o "1-3" \\h \\z \\u' in instrs
    assert 'TOC \\h \\z \\c "Figure"' in instrs
    assert 'TOC \\h \\z \\c "Table"' in instrs


def test_toc_output_is_valid():
    assert validate_docx(convert_source(SRC).docx) == []


def test_toc_field_is_a_complex_field():
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(SRC).docx)).read("word/document.xml")
    )
    kinds = [e.get(f"{{{NS['w']}}}fldCharType") for e in root.iter(f"{{{NS['w']}}}fldChar")]
    # each of the three TOC fields contributes begin/separate/end
    assert kinds.count("begin") >= 3 and kinds.count("end") >= 3


# -- round-trip -------------------------------------------------------------- #


def test_toc_manifest_round_trip_exact():
    res = convert_source(SRC, embed_manifest=True)
    assert recover_ir(res.docx).to_dict() == res.document.to_dict()


def test_toc_to_latex():
    latex = to_latex(convert_source(SRC, embed_manifest=True).docx)
    assert "\\tableofcontents" in latex
    assert "\\listoffigures" in latex
    assert "\\listoftables" in latex


def test_foreign_reader_recovers_toc_without_duplicate_title():
    doc = read_docx(convert_source(SRC, embed_manifest=False).docx)
    tocs = [b for b in doc.blocks if isinstance(b, ir.TableOfContents)]
    assert [b.kind for b in tocs] == ["contents", "figures", "tables"]
    texts = [
        "".join(i.value for i in b.inlines if isinstance(i, ir.Text)).strip()
        for b in doc.blocks
        if isinstance(b, ir.Paragraph)
    ]
    assert "Contents" not in texts and "List of Figures" not in texts
