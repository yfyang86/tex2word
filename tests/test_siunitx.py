from __future__ import annotations

from latex2word import convert_source, ir
from latex2word.frontend import parse_document
from latex2word.frontend.siunitx import num_to_text, units_to_text
from latex2word.validate import validate_docx


def _text(src: str) -> str:
    doc, _ = parse_document(src, ".")
    return "".join(
        i.value
        for b in doc.blocks
        if isinstance(b, ir.Paragraph)
        for i in b.inlines
        if isinstance(i, ir.Text)
    )


def test_si_value_and_unit():
    assert _text(r"\SI{5}{\meter}") == "5 m"


def test_si_compound_unit_with_power():
    assert _text(r"\SI{9.81}{\meter\per\second\squared}") == "9.81 m/s²"


def test_qty_is_alias_for_si():
    assert _text(r"\qty{3}{\kilo\gram}") == "3 kg"


def test_prefix_attaches_without_separator():
    assert _text(r"\si{\micro\metre}") == "µm"
    assert _text(r"\si{\kilo\gram}") == "kg"


def test_separate_units_get_a_space():
    assert _text(r"\si{\newton\metre}") == "N m"


def test_cubic_and_square_prefix_powers():
    assert _text(r"\si{\kilo\gram\per\cubic\metre}") == "kg/m³"
    assert _text(r"\si{\cubic\centi\metre}") == "cm³"


def test_num_exponent():
    assert num_to_text("1.5e3") == "1.5×10³"
    assert num_to_text("6.022e23") == "6.022×10²³"
    assert num_to_text("42") == "42"


def test_ang():
    assert _text(r"\ang{30}") == "30°"
    assert _text(r"\ang{30;15;0}") == "30°15′"


def test_optional_argument_is_skipped():
    assert _text(r"\SI[per-mode=symbol]{5}{\metre\per\second}") == "5 m/s"


def test_percent_and_celsius():
    assert _text(r"\SI{100}{\percent}") == "100 %"
    assert _text(r"\SI{20}{\celsius}") == "20 °C"


def test_unit_macro_alias():
    assert units_to_text.__module__  # smoke
    assert _text(r"\unit{\joule\per\kelvin}") == "J/K"


def test_siunitx_is_valid_and_warning_free():
    res = convert_source(
        r"\begin{document}Gravity is \SI{9.81}{\meter\per\second\squared}; "
        r"density \qty{1.0e3}{\kilo\gram\per\cubic\metre}.\end{document}"
    )
    assert validate_docx(res.docx) == []
    assert res.report.warnings == []


def test_siunitx_round_trips_as_text():
    from latex2word.roundtrip import recover_ir, to_latex

    res = convert_source(
        r"\begin{document}\SI{9.81}{\meter\per\second\squared}\end{document}",
        embed_manifest=True,
    )
    assert recover_ir(res.docx).to_dict() == res.document.to_dict()
    assert "m/s²" in to_latex(res.docx)
