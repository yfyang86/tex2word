from __future__ import annotations

from latex2word import ir


def test_json_round_trip():
    doc = ir.Document(
        blocks=[
            ir.Heading(1, [ir.Text("Intro")], label="sec:1"),
            ir.Paragraph([ir.Text("Hello "), ir.Emphasis([ir.Text("world")], "bold")]),
            ir.MathBlock("E=mc^2", numbered=True, label="eq:e", env="equation"),
        ],
        meta=ir.DocumentMeta(title=[ir.Text("T")], authors=[[ir.Text("A")]]),
    )
    data = doc.to_dict()
    again = ir.Document.from_dict(data)
    assert again.to_dict() == data


def test_node_kind_discriminator_does_not_shadow_fields():
    # LabelInfo has a field literally named ``kind`` -- regression guard.
    info = ir.LabelInfo(kind="equation", counter_name="Equation", bookmark="eq_e")
    assert info.kind == "equation"
    assert info.node_kind == "LabelInfo"


def test_to_dict_carries_type_tag():
    data = ir.Document(blocks=[ir.Paragraph([ir.Text("x")])]).to_dict()
    assert data["blocks"][0]["@type"] == "Paragraph"
    assert data["blocks"][0]["inlines"][0]["@type"] == "Text"


def test_theorem_field_named_kind_round_trips():
    # Theorem has a field literally named ``kind`` -- collision regression guard.
    doc = ir.Document(blocks=[ir.Theorem(kind="Proof", blocks=[ir.Paragraph([ir.Text("x")])])])
    again = ir.Document.from_dict(doc.to_dict())
    assert isinstance(again.blocks[0], ir.Theorem)
    assert again.blocks[0].kind == "Proof"
