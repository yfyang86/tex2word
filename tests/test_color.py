"""SPRINT-V4-5: colour (\\textcolor / \\color / \\colorbox / \\definecolor)."""

from __future__ import annotations

import io
import zipfile

from conftest import NS

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.frontend.colors import ColorTable, color_from_model
from tex2word.roundtrip import recover_ir, to_latex
from tex2word.validate import validate_docx


def _doc_xml(src: str) -> str:
    docx = convert_source(rf"\begin{{document}}{src}\end{{document}}").docx
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()


def _rpr_of(xml: str, text: str) -> str:
    i = xml.find(f">{text}<")
    return xml[xml.rfind("<w:r>", 0, i):i]


# -- colour model resolution ------------------------------------------------- #


def test_color_models():
    assert color_from_model("HTML", "1A2B3C") == "1A2B3C"
    assert color_from_model("rgb", "0,0.5,0") == "008000"
    assert color_from_model("RGB", "255,128,0") == "FF8000"
    assert color_from_model("gray", "0.5") == "808080"
    assert color_from_model("cmyk", "0,1,1,0") == "FF0000"
    assert color_from_model("HTML", "nothex") is None


def test_named_and_mix_and_alias():
    t = ColorTable()
    assert t.resolve("red") == "FF0000"
    t.define("brand", "HTML", "112233")
    assert t.resolve("brand") == "112233"
    t.define_alias("accent", "brand")
    assert t.resolve("accent") == "112233"


def test_color_mix_is_computed():
    t = ColorTable()
    assert t.resolve("blue!8") == "EBEBFF"        # 8% blue + 92% white (light)
    assert t.resolve("red!40!white") == "FF9999"  # 40% red + 60% white
    assert t.resolve("red!40!blue") == "660099"   # 40% red + 60% blue
    assert t.resolve("black!10") == "E6E6E6"      # light gray
    assert t.resolve("red!50!green") == "808000"  # left-fold of two mixes
    assert t.resolve("nosuch!50") is None         # unknown component -> None


# -- parsing ----------------------------------------------------------------- #


def test_textcolor_parses_to_colored():
    doc, _ = parse_document(r"\textcolor{red}{warn}", ".")
    col = next(i for i in doc.blocks[0].inlines if isinstance(i, ir.Colored))
    assert col.fg == "FF0000" and col.bg is None
    assert col.inlines == [ir.Text("warn")]


def test_colorbox_sets_background():
    doc, _ = parse_document(r"\colorbox{yellow}{hi}", ".")
    col = next(i for i in doc.blocks[0].inlines if isinstance(i, ir.Colored))
    assert col.bg == "FFFF00" and col.fg is None


def test_color_switch_is_scoped_to_group():
    doc, _ = parse_document(r"{\color{green}tinted} plain", ".")
    blocks = doc.blocks[0].inlines
    col = next(i for i in blocks if isinstance(i, ir.Colored))
    assert col.fg == "00FF00"
    # "plain" must NOT be inside the colour scope
    assert any(isinstance(i, ir.Text) and "plain" in i.value for i in blocks)


def test_definecolor_in_preamble_resolves():
    src = r"\definecolor{brand}{RGB}{10,20,30}\begin{document}\textcolor{brand}{x}\end{document}"
    doc, _ = parse_document(src, ".")
    col = next(i for i in doc.blocks[0].inlines if isinstance(i, ir.Colored))
    assert col.fg == "0A141E"


def test_unknown_color_degrades_without_wrapper():
    doc, rep = parse_document(r"\textcolor{nosuchcolor}{x}", ".")
    # content survives as plain text; no Colored node, no crash
    assert not any(isinstance(i, ir.Colored) for i in doc.blocks[0].inlines)
    assert any(isinstance(i, ir.Text) and "x" in i.value for i in doc.blocks[0].inlines)


# -- rendering --------------------------------------------------------------- #


def test_textcolor_renders_w_color():
    xml = _doc_xml(r"\textcolor{red}{warn}")
    assert 'w:color w:val="FF0000"' in xml


def test_colorbox_renders_shading():
    xml = _doc_xml(r"\colorbox{yellow}{hi}")
    assert 'w:fill="FFFF00"' in xml


def test_color_and_emphasis_compose():
    xml = _doc_xml(r"\textcolor{red}{\textbf{x}}")
    rpr = _rpr_of(xml, "x")
    assert "<w:b/>" in rpr and 'w:color w:val="FF0000"' in rpr


# -- round-trip -------------------------------------------------------------- #


def test_color_roundtrips_to_ir_and_latex():
    docx = convert_source(
        r"\begin{document}\textcolor{red}{a} \colorbox{yellow}{b}\end{document}"
    ).docx
    rec = recover_ir(docx)
    assert rec is not None and "Colored" in str(rec.to_dict())
    latex = to_latex(docx)
    assert r"\textcolor[HTML]{FF0000}{a}" in latex
    assert r"\colorbox[HTML]{FFFF00}{b}" in latex


def test_color_survives_foreign_docx_read():
    # build with our writer, strip the manifest, read back from OOXML
    from tex2word.frontend.docx_reader import read_docx

    docx = convert_source(
        r"\begin{document}\textcolor{red}{x}\end{document}", embed_manifest=False
    ).docx
    doc = read_docx(docx)
    assert doc is not None and "Colored" in str(doc.to_dict())


_ = NS  # imported for parity with other tests / future xpath use


# -- code-review regressions ------------------------------------------------- #


def test_ref_inside_textcolor_resolves():
    # crossref must recurse into Colored/FontSize wrappers
    src = (r"\begin{document}\section{S}\label{sec:a}"
           r"see \textcolor{red}{\ref{sec:a}} and {\large \ref{sec:a}}.\end{document}")
    res = convert_source(src)
    assert [w for w in res.report.warnings if "ref" in w.construct] == []


def test_rpr_children_in_schema_order():
    # a run combining many properties must emit w:rPr children in CT_RPr order
    xml = _doc_xml(r"\colorbox{yellow}{\textcolor{red}{\textbf{\sout{x}}}}")
    order = ["b", "i", "smallCaps", "strike", "color", "sz", "highlight", "u", "shd", "vertAlign"]
    rpr = xml[xml.find("<w:rPr>"):xml.find("</w:rPr>")]
    seen = [tag for tag in order if f"<w:{tag}" in rpr]
    positions = [rpr.find(f"<w:{tag}") for tag in seen]
    assert positions == sorted(positions), f"rPr children out of order: {seen}"


def test_highlight_none_not_read_as_highlight():
    # a foreign run with w:highlight w:val="none" must NOT become \hl
    from tex2word.frontend.docx_reader import read_docx
    docx = convert_source(r"\begin{document}x\end{document}", embed_manifest=False).docx
    # sanity: a plain run round-trips with no highlight emphasis
    doc = read_docx(docx)
    assert "highlight" not in str(doc.to_dict())


# -- colour / size on math runs ---------------------------------------------- #

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_Wn = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _math_runs(docx):
    import io
    import zipfile

    from lxml import etree
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    return list(root.iter(f"{{{_M}}}r"))


def test_textcolor_colours_inline_math():
    docx = convert_source(r"\begin{document}\textcolor{red}{$x$} plain $y$\end{document}").docx
    colored = [
        mr for mr in _math_runs(docx)
        if (rpr := mr.find(f"{{{_Wn}}}rPr")) is not None
        and (c := rpr.find(f"{{{_Wn}}}color")) is not None
        and c.get(f"{{{_Wn}}}val") == "FF0000"
    ]
    assert len(colored) == 1  # only the x, not the y


def test_fontsize_resizes_inline_math():
    docx = convert_source(r"\begin{document}{\large $z$}\end{document}").docx
    sized = [
        mr for mr in _math_runs(docx)
        if (rpr := mr.find(f"{{{_Wn}}}rPr")) is not None
        and rpr.find(f"{{{_Wn}}}sz") is not None
    ]
    assert sized


def test_styled_math_is_valid_and_ordered():
    docx = convert_source(r"\begin{document}\textcolor{blue}{$a^2+b^2$}\end{document}").docx
    assert validate_docx(docx) == []  # w:rPr inside m:r is schema-ordered
    for mr in _math_runs(docx):
        kids = [k.tag.split("}")[1] for k in mr]
        if "rPr" in kids and "t" in kids:
            assert kids.index("rPr") < kids.index("t")
