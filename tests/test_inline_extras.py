"""SPRINT-V2.1: \\verb, caption spacing, \\cref type prefixes."""

from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source, ir
from tex2word.frontend import parse_document


def _para_with(doc: ir.Document, needle_type) -> ir.Paragraph:
    for b in doc.blocks:
        if isinstance(b, ir.Paragraph) and any(isinstance(i, needle_type) for i in b.inlines):
            return b
    raise AssertionError("not found")


# -- T1: \verb --------------------------------------------------------------- #


def test_verb_is_typewriter_literal():
    doc, _ = parse_document(r"\begin{document}code \verb|x_i = a&b| end\end{document}")
    para = _para_with(doc, ir.Emphasis)
    emph = next(i for i in para.inlines if isinstance(i, ir.Emphasis))
    assert emph.kind_ == "typewriter"
    assert emph.inlines[0].value == "x_i = a&b"


def test_verb_preserves_backslash_and_specials():
    doc, _ = parse_document(r"\begin{document}\verb#g\_io_ring# x\end{document}")
    emph = next(
        i for b in doc.blocks if isinstance(b, ir.Paragraph)
        for i in b.inlines if isinstance(i, ir.Emphasis)
    )
    assert emph.inlines[0].value == r"g\_io_ring"


def test_verb_star_normalised():
    doc, _ = parse_document(r"\begin{document}\verb*|a  b|\end{document}")
    emph = next(
        i for b in doc.blocks if isinstance(b, ir.Paragraph)
        for i in b.inlines if isinstance(i, ir.Emphasis)
    )
    assert "a" in emph.inlines[0].value and "b" in emph.inlines[0].value


def test_verb_renders_consolas_run():
    root = document_root(convert_source(r"\begin{document}\verb|abc|\end{document}").docx)
    fonts = root.xpath("//w:r/w:rPr/w:rFonts[@w:ascii='Consolas']", namespaces=NS)
    assert fonts


# -- T2: caption spacing ----------------------------------------------------- #


def test_caption_has_single_space_before_number():
    src = (
        r"\begin{document}\begin{table}\begin{tabular}{l}x\\\end{tabular}"
        r"\caption{C}\end{table}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    cap = next(
        p for p in root.xpath("//w:p", namespaces=NS)
        if p.xpath('./w:pPr/w:pStyle[@w:val="Caption"]', namespaces=NS)
    )
    runs = [t.text for t in cap.xpath(".//w:t", namespaces=NS)]
    assert runs[:3] == ["Table ", "1", ": "]  # no double space


# -- T3: cleveref prefixes --------------------------------------------------- #


def _ref(src: str) -> ir.Ref:
    doc, _ = parse_document(src)
    return next(
        i for b in doc.blocks if isinstance(b, ir.Paragraph)
        for i in b.inlines if isinstance(i, ir.Ref)
    )


def test_ref_styles_parsed():
    assert _ref(r"\begin{document}\ref{x}\end{document}").style == "plain"
    assert _ref(r"\begin{document}\cref{x}\end{document}").style == "abbrev"
    assert _ref(r"\begin{document}\Cref{x}\end{document}").style == "full"
    assert _ref(r"\begin{document}\autoref{x}\end{document}").style == "full"


def test_cref_renders_type_prefix():
    src = (
        r"\begin{document}\begin{figure}\includegraphics{a.png}"
        r"\caption{C}\label{fig:x}\end{figure}"
        r"\cref{fig:x} \Cref{fig:x} \ref{fig:x}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    text = " ".join(t.text or "" for t in root.xpath("//w:t", namespaces=NS))
    assert "fig. " in text
    assert "Figure " in text  # \Cref


def test_plain_ref_has_no_prefix():
    src = (
        r"\begin{document}\begin{figure}\includegraphics{a.png}\caption{C}"
        r"\label{fig:x}\end{figure}\ref{fig:x}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    # the paragraph containing the lone \ref has no "fig." / "Figure" prefix text
    paras = [
        " ".join(p.xpath(".//w:t/text()", namespaces=NS))
        for p in root.xpath("//w:p", namespaces=NS)
        if p.xpath(".//w:instrText[contains(., 'REF fig_x')]", namespaces=NS)
        and not p.xpath('./w:pPr/w:pStyle[@w:val="Caption"]', namespaces=NS)
    ]
    assert paras and "fig." not in paras[0] and "Figure" not in paras[0]


# -- \textsuperscript / \textsubscript (UAT-2 follow-up) --------------------- #


def test_superscript_parses_with_argument():
    doc, _ = parse_document(r"E=mc\textsuperscript{2}", ".")
    para = doc.blocks[0]
    emph = next(i for i in para.inlines if isinstance(i, ir.Emphasis))
    assert emph.kind_ == "superscript"
    assert emph.inlines == [ir.Text("2")]  # the argument is captured, not leaked


def test_subscript_parses_with_argument():
    doc, _ = parse_document(r"H\textsubscript{2}O", ".")
    para = doc.blocks[0]
    emph = next(i for i in para.inlines if isinstance(i, ir.Emphasis))
    assert emph.kind_ == "subscript"
    assert emph.inlines == [ir.Text("2")]


def test_superscript_renders_vertalign():
    docx = convert_source(r"\begin{document}x\textsuperscript{2}\end{document}").docx
    root = document_root(docx)
    va = root.findall(f".//{{{NS['w']}}}vertAlign")
    assert any(e.get(f"{{{NS['w']}}}val") == "superscript" for e in va)


def test_subscript_renders_vertalign():
    docx = convert_source(r"\begin{document}x\textsubscript{i}\end{document}").docx
    root = document_root(docx)
    va = root.findall(f".//{{{NS['w']}}}vertAlign")
    assert any(e.get(f"{{{NS['w']}}}val") == "subscript" for e in va)


def test_superscript_no_warning():
    result = convert_source(r"\begin{document}1\textsuperscript{st}\end{document}")
    assert result.report.warnings == []


# -- V4-8: strike / highlight / underline / font-size spans ------------------ #


def _xml(src):
    return convert_source(rf"\begin{{document}}{src}\end{{document}}").docx


def test_sout_is_strike():
    doc, _ = parse_document(r"\sout{gone}", ".")
    emph = next(i for i in doc.blocks[0].inlines if isinstance(i, ir.Emphasis))
    assert emph.kind_ == "strike" and emph.inlines == [ir.Text("gone")]


def test_strike_renders_w_strike():
    root = document_root(_xml(r"\sout{x}"))
    assert root.findall(f".//{{{NS['w']}}}strike")


def test_hl_renders_highlight():
    root = document_root(_xml(r"\hl{x}"))
    hi = root.findall(f".//{{{NS['w']}}}highlight")
    assert hi and hi[0].get(f"{{{NS['w']}}}val") == "yellow"


def test_font_size_group_scoped():
    doc, _ = parse_document(r"{\large big} small", ".")
    inlines = doc.blocks[0].inlines
    fs = next(i for i in inlines if isinstance(i, ir.FontSize))
    assert fs.half_points == 24
    # "small" text stays outside the size span
    assert any(isinstance(i, ir.Text) and "small" in i.value for i in inlines)


def test_normalsize_is_no_span():
    doc, _ = parse_document(r"{\normalsize plain}", ".")
    assert not any(isinstance(i, ir.FontSize) for i in doc.blocks[0].inlines)


def test_font_size_renders_w_sz():
    root = document_root(_xml(r"{\Large big}"))
    sz = root.findall(f".//{{{NS['w']}}}sz")
    assert any(e.get(f"{{{NS['w']}}}val") == "29" for e in sz)


def test_text_spans_roundtrip():
    from tex2word.roundtrip import to_latex

    latex = to_latex(_xml(r"\sout{a} \hl{b} {\large c}"))
    assert r"\sout{a}" in latex and r"\hl{b}" in latex and r"\large" in latex


def test_text_spans_no_warning():
    res = convert_source(r"\begin{document}\sout{a} \hl{b} {\small c}\end{document}")
    assert res.report.warnings == []
