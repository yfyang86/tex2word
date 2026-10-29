"""Table floats found broken by the synthetic probes (issue #45)."""

from __future__ import annotations

from tex2word import convert_source, ir


def _convert(body: str):
    r = convert_source("\\documentclass{article}\\usepackage{threeparttable,subcaption,rotating}"
                       "\\begin{document}\n" + body + "\n\\end{document}")
    assert [w.message for w in r.report.warnings] == []
    return r.document


def _tables(doc) -> list[ir.Table]:
    return [b for b in doc.blocks if isinstance(b, ir.Table)]


def _txt(inlines) -> str:
    return "".join(n.value if isinstance(n, ir.Text) else _txt(getattr(n, "inlines", []))
                   for n in inlines or [])


def test_threeparttable_caption_label_and_notes():
    doc = _convert(r"\begin{table}\begin{threeparttable}\caption{Results}\label{tab:r}"
                   r"\begin{tabular}{l} a\tnote{a}\\\end{tabular}"
                   r"\begin{tablenotes}\item[a] A note.\end{tablenotes}"
                   r"\end{threeparttable}\end{table}See \ref{tab:r}.")
    (t,) = _tables(doc)
    assert _txt(t.caption) == "Results" and t.label == "tab:r"
    cell = t.rows[0].cells[0].blocks[0]
    assert any(isinstance(i, ir.Emphasis) and i.kind_ == "superscript" for i in cell.inlines)
    assert "tab:r" in doc.labels


def test_sidewaystable_is_a_table_float():
    (t,) = _tables(_convert(r"\begin{sidewaystable}\caption{Wide}\label{w}"
                            r"\begin{tabular}{ll}a&b\\\end{tabular}\end{sidewaystable}"))
    assert _txt(t.caption) == "Wide" and t.label == "w"


def test_side_by_side_tables_keep_their_captions_and_labels():
    doc = _convert(r"\begin{table}\begin{minipage}{.45\linewidth}\caption{Left}\label{l}"
                   r"\begin{tabular}{l}x\\\end{tabular}\end{minipage}\hfill"
                   r"\begin{minipage}{.45\linewidth}\caption{Right}\label{r}"
                   r"\begin{tabular}{l}y\\\end{tabular}\end{minipage}\end{table}")
    left, right = _tables(doc)
    assert (_txt(left.caption), left.label) == ("Left", "l")
    assert (_txt(right.caption), right.label) == ("Right", "r")


def test_subtables_with_a_main_caption():
    doc = _convert(r"\begin{table}\caption{Main}\label{m}"
                   r"\begin{subtable}{.4\textwidth}\caption{One}\label{s}"
                   r"\begin{tabular}{l}x\\\end{tabular}\end{subtable}"
                   r"\begin{subtable}{.4\textwidth}\caption{Two}"
                   r"\begin{tabular}{l}y\\\end{tabular}\end{subtable}\end{table}\ref{s}")
    first, second = _tables(doc)
    assert _txt(first.caption) == "Main" and first.label == "m" and second.caption is None
    lines = [_txt(b.inlines) for b in doc.blocks if isinstance(b, ir.Paragraph)]
    assert "(a) One" in lines and "(b) Two" in lines
    assert doc.labels["s"].bookmark == doc.labels["m"].bookmark
