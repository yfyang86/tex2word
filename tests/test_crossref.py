from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source, ir
from tex2word.report import ConversionReport
from tex2word.transforms.crossref import resolve_crossrefs, sanitize_bookmark

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_sanitize_bookmark():
    assert sanitize_bookmark("eq:e") == "eq_e"
    assert sanitize_bookmark("1bad").startswith("ref_")
    assert " " not in sanitize_bookmark("a b c")
    assert len(sanitize_bookmark("x" * 100)) <= 40


def test_collects_labels_and_wires_refs():
    ref = ir.Ref("eq:e", "equation")
    doc = ir.Document(
        blocks=[
            ir.MathBlock("E=mc^2", numbered=True, label="eq:e", env="equation"),
            ir.Paragraph([ir.Text("See "), ref]),
        ]
    )
    report = ConversionReport()
    resolve_crossrefs(doc, report)
    assert "eq:e" in doc.labels
    assert doc.labels["eq:e"].kind == "equation"
    assert ref.bookmark == "eq_e"


def test_enumerate_item_label_is_collected_as_listitem():
    item = ir.ListItem([ir.Paragraph([ir.Text("Q")])], label="rq:a")
    ref = ir.Ref("rq:a", "generic")
    doc = ir.Document(
        blocks=[ir.ItemList(ordered=True, items=[item]), ir.Paragraph([ref])]
    )
    resolve_crossrefs(doc, ConversionReport())
    assert doc.labels["rq:a"].kind == "listitem"
    assert ref.bookmark == "rq_a"
    assert ref.ref_kind == "listitem"  # generic inherits the target kind


def test_enumerate_item_ref_end_to_end():
    # \item\label{} attaches to the item; \ref renders a REF \r field that returns
    # the item's auto-numbered list number, with a bookmark on the item paragraph.
    src = (
        r"\documentclass{article}\begin{document}\begin{enumerate}"
        r"\item\label{rq:base}A \item\label{rq:prod}B \item\label{rq:abla}C"
        r"\end{enumerate}See RQ\ref{rq:base}, RQ\ref{rq:prod}, RQ\ref{rq:abla}."
        r"\end{document}"
    )
    res = convert_source(src)
    assert not res.report.warnings  # all three refs resolve
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml")
    )
    names = {b.get(f"{{{_W}}}name") for b in root.iter(f"{{{_W}}}bookmarkStart")}
    assert {"rq_base", "rq_prod", "rq_abla"} <= names
    instrs = [i.text.strip() for i in root.iter(f"{{{_W}}}instrText")]
    assert "REF rq_prod \\r \\h" in instrs  # list-number reference


def test_unresolved_ref_warns_not_raises():
    ref = ir.Ref("missing", "generic")
    doc = ir.Document(blocks=[ir.Paragraph([ref])])
    report = ConversionReport()
    resolve_crossrefs(doc, report)
    assert ref.bookmark is None
    assert any("missing" in w.message for w in report.warnings)


def test_ref_kind_inherited_from_target():
    ref = ir.Ref("fig:1", "generic")
    doc = ir.Document(
        blocks=[
            ir.Figure(image=None, caption=[ir.Text("c")], label="fig:1"),
            ir.Paragraph([ref]),
        ]
    )
    resolve_crossrefs(doc, ConversionReport())
    assert ref.ref_kind == "figure"
