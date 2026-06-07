"""CJK support: XeLaTeX/xeCJK font selection (\\setmainfont / \\setCJK*font)."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source
from tex2word.frontend import parse_document
from tex2word.validate import validate_docx

PREAMBLE = (
    r"\documentclass{article}"
    r"\usepackage{xeCJK}"
    r"\setmainfont{Times New Roman}"
    r"\setCJKmainfont{SimSun}"
    r"\setCJKsansfont{SimHei}"
)
DOC = (
    PREAMBLE
    + r"\begin{document}"
    + "测试中文字体。Formula $\\sum E=m c^2$."
    + r"\section{中文标题 Heading}更多中文内容。"
    + r"\end{document}"
)


def _styles(docx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/styles.xml").decode()


def _document(docx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()


def _style_rfonts(styles: str, style_id: str) -> str:
    block = re.search(rf'styleId="{style_id}".*?</w:style>', styles, re.S)
    assert block, f"style {style_id} not found"
    rf = re.search(r"<w:rFonts[^/]*/>", block.group(0))
    return rf.group(0) if rf else ""


def test_fonts_detected_from_preamble():
    doc, _ = parse_document(DOC)
    assert doc.meta.main_font == "Times New Roman"
    assert doc.meta.cjk_main_font == "SimSun"
    assert doc.meta.cjk_sans_font == "SimHei"
    assert doc.meta.cjk_mono_font is None


def test_setmainfont_with_options_form():
    src = (
        r"\documentclass{article}\setmainfont[BoldFont=Arial Bold]{Arial}"
        r"\begin{document}x\end{document}"
    )
    doc, _ = parse_document(src)
    assert doc.meta.main_font == "Arial"


def test_docdefaults_get_latin_and_eastasia_fonts():
    styles = _styles(convert_source(DOC).docx)
    default = re.search(r"<w:rPrDefault>.*?</w:rPrDefault>", styles, re.S).group(0)
    rfonts = re.search(r"<w:rFonts[^/]*/>", default).group(0)
    assert 'w:ascii="Times New Roman"' in rfonts
    assert 'w:hAnsi="Times New Roman"' in rfonts
    assert 'w:eastAsia="SimSun"' in rfonts


def test_cjk_sans_applied_to_headings():
    styles = _styles(convert_source(DOC).docx)
    assert 'w:eastAsia="SimHei"' in _style_rfonts(styles, "Heading1")
    assert 'w:eastAsia="SimHei"' in _style_rfonts(styles, "Title")


def test_cjk_monofont_applied_to_source_code():
    src = (
        r"\documentclass{article}\usepackage{xeCJK}\setCJKmonofont{FangSong}"
        r"\begin{document}x\end{document}"
    )
    styles = _styles(convert_source(src).docx)
    assert 'w:eastAsia="FangSong"' in _style_rfonts(styles, "SourceCode")


def test_chinese_body_text_preserved():
    doc_xml = _document(convert_source(DOC).docx)
    assert "测试中文字体" in doc_xml
    assert "中文标题" in doc_xml


def test_cjk_output_is_valid():
    assert validate_docx(convert_source(DOC).docx) == []


def test_fonts_round_trip_to_latex():
    from tex2word.roundtrip import to_latex

    latex = to_latex(convert_source(DOC).docx)
    assert r"\usepackage{xeCJK}" in latex
    assert r"\setmainfont{Times New Roman}" in latex
    assert r"\setCJKmainfont{SimSun}" in latex
    assert r"\setCJKsansfont{SimHei}" in latex


def test_no_fonts_leaves_defaults_untouched():
    styles = _styles(convert_source(r"\begin{document}x\end{document}").docx)
    assert "eastAsia" not in styles
    assert 'w:ascii="Calibri"' in styles  # the shipped default is unchanged
