from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source, ir
from tex2word.frontend import parse_document


def _table(src: str) -> ir.Table:
    doc, _ = parse_document(src)
    return next(b for b in doc.blocks if isinstance(b, ir.Table))


BOOKTABS = r"""\begin{document}
\begin{tabular}{lll}
\toprule
Group & A & B \\
\midrule
\multirow{2}{*}{Pair} & 1 & 2 \\
 & 3 & 4 \\
\bottomrule
\end{tabular}
\end{document}"""


def test_multirow_sets_rowspan():
    table = _table(BOOKTABS)
    first_data_row = table.rows[1]
    assert first_data_row.cells[0].rowspan == 2


def test_multirow_unbraced_star_width():
    # \multirow{6}*{X} writes the width as a bare ``*`` (only two brace groups);
    # the span/content must still be recognised, not dropped to an unsupported
    # inline macro. (Real arXiv table idiom.)
    src = (
        r"\begin{document}\begin{tabular}{cl}"
        r"\multirow{3}*{Beauty} & Recall \\ & NDCG \\ & MRR \\"
        r"\end{tabular}\end{document}"
    )
    table = _table(src)
    assert table.rows[0].cells[0].rowspan == 3
    body = "".join(
        getattr(x, "value", "")
        for blk in table.rows[0].cells[0].blocks
        for x in getattr(blk, "inlines", [])
    )
    assert "Beauty" in body
    res = convert_source(src)
    assert not any("multirow" in (w.message or "") for w in res.report.warnings)


def test_header_row_detected_with_midrule():
    table = _table(BOOKTABS)
    assert table.rows[0].is_header is True
    assert table.rows[1].is_header is False


def test_plain_table_has_no_header():
    table = _table(
        r"\begin{document}\begin{tabular}{ll}a & b\\ c & d\\\end{tabular}\end{document}"
    )
    assert all(not r.is_header for r in table.rows)


def test_backend_emits_vmerge_restart_and_continue():
    root = document_root(convert_source(BOOKTABS).docx)
    vmerges = root.xpath("//w:vMerge", namespaces=NS)
    vals = [v.get(f"{{{NS['w']}}}val") for v in vmerges]
    assert "restart" in vals
    assert None in vals  # a continue cell (no w:val)


def test_backend_marks_repeating_header():
    root = document_root(convert_source(BOOKTABS).docx)
    assert len(root.xpath("//w:tblHeader", namespaces=NS)) == 1


def test_longtable_endhead_marks_header():
    src = (
        r"\begin{document}\begin{longtable}{ll}H1 & H2\\ \endhead a & b\\"
        r"\end{longtable}\end{document}"
    )
    table = _table(src)
    assert table.rows[0].is_header is True
    assert table.rows[1].is_header is False


# -- SPRINT-V4-13: cell/row colour + p{} column widths ----------------------- #


def _doc_root(src: str):
    return document_root(convert_source(rf"\begin{{document}}{src}\end{{document}}").docx)


def test_cellcolor_sets_cell_shade():
    table = _table(r"\begin{document}\begin{tabular}{ll}"
                   r"a & \cellcolor{yellow} b \\\end{tabular}\end{document}")
    assert table.rows[0].cells[1].shade == "FFFF00"
    assert table.rows[0].cells[0].shade is None
    # the \cellcolor macro must not leak into the cell text
    para = table.rows[0].cells[1].blocks[0]
    assert all("cellcolor" not in getattr(i, "value", "") for i in para.inlines)


def test_rowcolor_applies_to_whole_row():
    table = _table(r"\begin{document}\begin{tabular}{lll}"
                   r"\rowcolor{gray} a & b & c \\\end{tabular}\end{document}")
    assert [cell.shade for cell in table.rows[0].cells] == ["808080"] * 3


def test_cellcolor_overrides_rowcolor():
    table = _table(r"\begin{document}\begin{tabular}{ll}"
                   r"\rowcolor{gray} a & \cellcolor{red} b \\\end{tabular}\end{document}")
    assert table.rows[0].cells[0].shade == "808080"
    assert table.rows[0].cells[1].shade == "FF0000"


def test_pwidth_column_captured():
    table = _table(r"\begin{document}\begin{tabular}{l p{3cm} c}"
                   r"a & b & c \\\end{tabular}\end{document}")
    assert table.colwidths[0] is None
    assert table.colwidths[2] is None
    assert table.colwidths[1] is not None
    assert round(table.colwidths[1]) == round(3 * 914400 / 2.54)  # 3cm in EMU


def test_cell_shade_renders_w_shd():
    root = _doc_root(r"\begin{tabular}{ll}a & \cellcolor{yellow} b \\\end{tabular}")
    shd = root.findall(f".//{{{NS['w']}}}tc/{{{NS['w']}}}tcPr/{{{NS['w']}}}shd")
    assert any(e.get(f"{{{NS['w']}}}fill") == "FFFF00" for e in shd)


def test_pwidth_renders_gridcol_and_tcw():
    root = _doc_root(r"\begin{tabular}{l p{3cm} c}a & b & c \\\end{tabular}")
    widths = [e.get(f"{{{NS['w']}}}w")
              for e in root.findall(f".//{{{NS['w']}}}tblGrid/{{{NS['w']}}}gridCol")]
    assert any(w and int(w) > 1000 for w in widths)  # the p{3cm} column has a width


def test_table_colour_roundtrips():
    from tex2word.roundtrip import recover_ir, to_latex

    docx = convert_source(
        r"\begin{document}\begin{tabular}{ll}a & \cellcolor{yellow} b \\\end{tabular}\end{document}"
    ).docx
    rec = recover_ir(docx)
    assert rec is not None and rec.to_dict() == ir.Document.from_dict(rec.to_dict()).to_dict()
    assert r"\cellcolor[HTML]{FFFF00}" in to_latex(docx)


def test_cellcolor_inside_multicolumn():
    # \cellcolor nested in a \multicolumn content group is still captured
    table = _table(r"\begin{document}\begin{tabular}{ll}"
                   r"\multicolumn{2}{c}{\cellcolor{red}X} \\\end{tabular}\end{document}")
    assert table.rows[0].cells[0].shade == "FF0000"
    assert table.rows[0].cells[0].colspan == 2


# -- V4-13: partial rules (\cmidrule/\cline) + >{} column processors --------- #


def test_cmidrule_sets_partial_bottom_borders():
    table = _table(
        r"\begin{document}\begin{tabular}{lll}"
        r"A & B & C \\ \cmidrule{2-3} 1 & 2 & 3 \\\end{tabular}\end{document}"
    )
    assert [c.border_bottom for c in table.rows[0].cells] == [False, True, True]


def test_cmidrule_trim_form_is_stripped():
    # \cmidrule(lr){2-3} must not leak "lr)" into the next cell
    table = _table(
        r"\begin{document}\begin{tabular}{lll}"
        r"A & B & C \\ \cmidrule(lr){2-3} 1 & 2 & 3 \\\end{tabular}\end{document}"
    )
    assert [c.border_bottom for c in table.rows[0].cells] == [False, True, True]
    first = table.rows[1].cells[0].blocks[0]
    assert "".join(i.value for i in first.inlines if isinstance(i, ir.Text)).strip() == "1"


def test_cline_partial_border():
    table = _table(
        r"\begin{document}\begin{tabular}{lll}"
        r"A & B & C \\ \cline{1-2} 1 & 2 & 3 \\\end{tabular}\end{document}"
    )
    assert [c.border_bottom for c in table.rows[0].cells] == [True, True, False]


def test_cmidrule_emits_tcborders():
    root = document_root(
        convert_source(
            r"\begin{document}\begin{tabular}{lll}"
            r"A & B & C \\ \cmidrule{2-3} 1 & 2 & 3 \\\end{tabular}\end{document}"
        ).docx
    )
    bottoms = root.findall(f".//{{{NS['w']}}}tcBorders/{{{NS['w']}}}bottom")
    assert len(bottoms) == 2


def test_column_processor_alignment():
    table = _table(
        r"\begin{document}\begin{tabular}"
        r"{>{\centering}p{2cm}>{\raggedleft}l r}a & b & c \\\end{tabular}\end{document}"
    )
    assert table.colspec == ["center", "right", "right"]


def test_cmidrule_round_trips():
    from tex2word.roundtrip import recover_ir, to_latex

    src = (
        r"\begin{document}\begin{tabular}{lll}"
        r"A & B & C \\ \cmidrule(lr){2-3} 1 & 2 & 3 \\\end{tabular}\end{document}"
    )
    res = convert_source(src, embed_manifest=True)
    assert recover_ir(res.docx).to_dict() == res.document.to_dict()
    assert r"\cmidrule{2-3}" in to_latex(res.docx)


def test_nested_table_renders_and_is_valid():
    from tex2word.validate import validate_docx

    src = (
        r"\begin{document}\begin{tabular}{ll}"
        r"outer & \begin{tabular}{cc} a & b \\ c & d \end{tabular} \\"
        r"\end{tabular}\end{document}"
    )
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    root = document_root(res.docx)
    assert root.findall(f".//{{{NS['w']}}}tc/{{{NS['w']}}}tbl")  # nested table present
    for tc in root.findall(f".//{{{NS['w']}}}tc"):
        assert list(tc)[-1].tag == f"{{{NS['w']}}}p"  # cell ends in a paragraph


# -- nested tables: \resizebox / minipage transparency ----------------------- #


def test_resizebox_wrapped_table_is_recovered():
    # \resizebox{w}{h}{\begin{tabular}...} must yield a real table, not raw LaTeX
    doc, rep = parse_document(
        r"\begin{document}\begin{table}\resizebox{0.9\textwidth}{!}{"
        "\n"
        r"\begin{tabular}{ll}a & b \\ c & d \\\end{tabular}}"
        r"\caption{Cap}\label{t:x}\end{table}\end{document}",
    )
    tables = [b for b in doc.blocks if isinstance(b, ir.Table)]
    assert len(tables) == 1 and len(tables[0].rows) == 2
    assert not any(isinstance(b, ir.RawPassthrough) for b in doc.blocks)
    assert "".join(i.value for i in (tables[0].caption or []) if isinstance(i, ir.Text)) == "Cap"


def test_minipage_grid_of_subtables_recovered():
    # the failing case: a table* with nested minipages each holding a tabular
    src = (
        r"\begin{document}\begin{table}\centering"
        r"\resizebox{\textwidth}{!}{\begin{minipage}{\textwidth}"
        r"\begin{minipage}{0.5\textwidth}\textbf{(a)}\\"
        r"\begin{tabular}{ll}1 & 2 \\\end{tabular}\end{minipage}\hfill"
        r"\begin{minipage}{0.5\textwidth}\textbf{(b)}\\"
        r"\begin{tabular}{ll}3 & 4 \\\end{tabular}\end{minipage}"
        r"\end{minipage}}\caption{Grid}\end{table}\end{document}"
    )
    doc, rep = parse_document(src)
    tables = [b for b in doc.blocks if isinstance(b, ir.Table)]
    assert len(tables) == 2  # both sub-tables survive
    assert not any(isinstance(b, ir.RawPassthrough) for b in doc.blocks)
    assert rep.warnings == []


def test_resizebox_table_renders_valid_docx():
    from tex2word.validate import validate_docx

    src = (
        r"\begin{document}\begin{table}\resizebox{\textwidth}{!}{"
        "\n"
        r"\begin{tabular}{lll}\toprule a & b & c \\\midrule"
        r"\rowcolor{red}1 & 2 & 3 \\ \cmidrule(lr){1-3} 4 & 5 & 6 \\\bottomrule"
        r"\end{tabular}}\end{table}\end{document}"
    )
    res = convert_source(src)
    assert validate_docx(res.docx) == []
    from conftest import document_root
    root = document_root(res.docx)
    assert root.findall(f".//{{{NS['w']}}}tbl")  # a real table, plus shd/borders survive
    assert root.findall(f".//{{{NS['w']}}}shd") and root.findall(f".//{{{NS['w']}}}tcBorders")
