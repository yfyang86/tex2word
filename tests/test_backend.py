from __future__ import annotations

from conftest import NS, document_root, part_names

from latex2word import convert_source


def _xpath(root, expr):
    return root.xpath(expr, namespaces=NS)


def test_package_has_required_parts():
    docx = convert_source(r"\begin{document}Hi\end{document}").docx
    names = part_names(docx)
    for required in (
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/settings.xml",
        "word/_rels/document.xml.rels",
    ):
        assert required in names


def test_headings_get_styles():
    src = r"\begin{document}\section{A}\subsection{B}\end{document}"
    root = document_root(convert_source(src).docx)
    styles = [e.get(f"{{{NS['w']}}}val") for e in _xpath(root, "//w:pStyle")]
    assert "Heading1" in styles
    assert "Heading2" in styles


def test_inline_math_produces_omath():
    root = document_root(convert_source(r"\begin{document}$x^2$\end{document}").docx)
    assert len(_xpath(root, "//m:oMath")) == 1
    assert len(_xpath(root, "//m:sSup")) == 1


def test_numbered_equation_has_seq_and_bookmark():
    src = r"\begin{document}\begin{equation}\label{eq:e}E=mc^2\end{equation}\end{document}"
    root = document_root(convert_source(src).docx)
    instrs = "".join(t.text or "" for t in _xpath(root, "//w:instrText"))
    assert "SEQ Equation" in instrs
    assert len(_xpath(root, "//w:bookmarkStart")) >= 1


def test_eqref_emits_ref_field():
    src = (
        r"\begin{document}\begin{equation}\label{eq:e}E=mc^2\end{equation}"
        r"See \eqref{eq:e}.\end{document}"
    )
    root = document_root(convert_source(src).docx)
    instrs = "".join(t.text or "" for t in _xpath(root, "//w:instrText"))
    assert "REF ref_eq_e" in instrs or "REF eq_e" in instrs


def test_bold_run_has_b_property():
    root = document_root(convert_source(r"\begin{document}\textbf{x}\end{document}").docx)
    assert len(_xpath(root, "//w:r/w:rPr/w:b")) == 1


def test_table_gridspan_for_multicolumn():
    src = (
        r"\begin{document}\begin{tabular}{ll}"
        r"\multicolumn{2}{c}{Head}\\ a & b\\"
        r"\end{tabular}\end{document}"
    )
    root = document_root(convert_source(src).docx)
    spans = [e.get(f"{{{NS['w']}}}val") for e in _xpath(root, "//w:gridSpan")]
    assert "2" in spans


def test_deterministic_output():
    # The document content is reproducible; the round-trip manifest carries a
    # wall-clock timestamp by design, so compare with it disabled.
    src = r"\begin{document}\section{A}$x^2$\end{document}"
    a = convert_source(src, embed_manifest=False).docx
    b = convert_source(src, embed_manifest=False).docx
    assert a == b
