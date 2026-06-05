"""SPRINT-V3: xparse \\NewDocumentCommand argspec expansion."""

from __future__ import annotations

from tex2word.frontend.macros import expand_macros, parse_argspec


def test_parse_argspec_kinds():
    assert parse_argspec("m") == [("m", None)]
    assert parse_argspec("o m") == [("o", None), ("m", None)]
    assert parse_argspec("s m") == [("s", None), ("m", None)]
    assert parse_argspec("O{d} m") == [("O", "d"), ("m", None)]
    # + (long), ! and >{proc} are skipped; r/d delimited collapse to m/o
    assert parse_argspec("+m") == [("m", None)]
    assert parse_argspec(">{\\TrimSpaces}m") == [("m", None)]
    assert parse_argspec("r() m") == [("m", None), ("m", None)]


def test_mandatory():
    assert "Hello World!" in expand_macros(r"\NewDocumentCommand{\hi}{m}{Hello #1!}\hi{World}")


def test_two_mandatory():
    assert "a+b" in expand_macros(r"\NewDocumentCommand{\f}{m m}{#1+#2}\f{a}{b}")


def test_optional_ifnovalue():
    src = r"\NewDocumentCommand{\f}{o m}{\IfNoValueTF{#1}{none}{#1}-#2}"
    assert "none-X" in expand_macros(src + r"\f{X}")
    assert "opt-X" in expand_macros(src + r"\f[opt]{X}")


def test_optional_with_default():
    src = r"\NewDocumentCommand{\f}{O{def} m}{[#1] #2}"
    assert "[def] Z" in expand_macros(src + r"\f{Z}")
    assert "[custom] Z" in expand_macros(src + r"\f[custom]{Z}")


def test_star_ifboolean():
    src = r"\NewDocumentCommand{\f}{s m}{\IfBooleanTF{#1}{STAR}{plain}-#2}"
    assert "STAR-X" in expand_macros(src + r"\f*{X}")
    assert "plain-Y" in expand_macros(src + r"\f{Y}")


def test_combined_star_optional_mandatory():
    src = (
        r"\NewDocumentCommand{\note}{s o m}"
        r"{\IfBooleanTF{#1}{!}{}\IfValueTF{#2}{(#2) }{}#3}"
    )
    assert expand_macros(src + r"\note*[p.5]{body}").strip() == "!(p.5) body"
    assert expand_macros(src + r"\note{body}").strip() == "body"


def test_single_branch_conditionals():
    src = r"\NewDocumentCommand{\f}{o}{\IfValueT{#1}{[#1]}\IfNoValueT{#1}{empty}}"
    assert expand_macros(src + r"\f[x]").strip() == "[x]"
    assert expand_macros(src + r"\f").strip() == "empty"


def test_declare_and_renew_document_command():
    assert "A" in expand_macros(r"\DeclareDocumentCommand{\g}{m}{#1}\g{A}")
    assert "B" in expand_macros(r"\RenewDocumentCommand{\g}{m}{#1}\g{B}")


def test_xparse_used_in_document():
    from tex2word import ir
    from tex2word.frontend import parse_document

    src = (
        r"\NewDocumentCommand{\kw}{s m}{\IfBooleanTF{#1}{\textbf{#2}}{\emph{#2}}}"
        r"\begin{document}A \kw*{bold} and \kw{soft} word.\end{document}"
    )
    doc, _ = parse_document(src)
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    kinds = [i.kind_ for i in para.inlines if isinstance(i, ir.Emphasis)]
    assert "bold" in kinds and "italic" in kinds  # \textbf -> bold, \emph -> italic
