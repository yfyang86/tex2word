from __future__ import annotations

from tex2word import ir
from tex2word.report import ConversionReport
from tex2word.transforms.crossref import resolve_crossrefs, sanitize_bookmark


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
