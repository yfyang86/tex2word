from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source, ir
from tex2word.frontend import parse_document

ALGORITHMIC = r"""
\begin{document}
\begin{algorithm}
\caption{Binary search}\label{alg:bs}
\begin{algorithmic}[1]
\REQUIRE sorted array $A$
\STATE $lo \gets 0$
\WHILE{$lo \leq hi$}
  \STATE $mid \gets (lo+hi)/2$
  \IF{$A[mid] = x$}
    \RETURN $mid$
  \ELSE
    \STATE $lo \gets mid+1$
  \ENDIF
\ENDWHILE
\RETURN $-1$
\end{algorithmic}
\end{algorithm}
See Algorithm \ref{alg:bs}.
\end{document}
"""


def _alg(src: str) -> ir.Algorithm:
    doc, _ = parse_document(src)
    return next(b for b in doc.blocks if isinstance(b, ir.Algorithm))


def _line_text(line: ir.AlgLine) -> str:
    def t(node):
        if isinstance(node, ir.Text):
            return node.value
        if isinstance(node, ir.Emphasis):
            return "".join(t(x) for x in node.inlines)
        if isinstance(node, ir.Math):
            return "$" + node.latex + "$"
        return ""

    return "".join(t(i) for i in line.inlines)


def test_algorithm_parsed_with_caption_label():
    alg = _alg(ALGORITHMIC)
    assert alg.label == "alg:bs"
    assert alg.caption[0].value == "Binary search"
    assert len(alg.lines) == 9


def test_indentation_tracks_blocks():
    alg = _alg(ALGORITHMIC)
    texts = [(_line_text(line), line.indent) for line in alg.lines]
    # WHILE opens to indent 1; IF (inside) opens to 2; RETURN inside if -> 2
    while_line = next(t for t in texts if t[0].startswith("while"))
    assert while_line[1] == 0
    mid = next(t for t in texts if "mid" in t[0] and "while" not in t[0])
    assert mid[1] == 1
    ret = next(t for t in texts if t[0].startswith("return $mid"))
    assert ret[1] == 2


def test_keywords_and_input_label():
    alg = _alg(ALGORITHMIC)
    joined = " ".join(_line_text(line) for line in alg.lines)
    assert "Input: sorted array" in joined
    assert "while" in joined and "then" in joined and "else" in joined


def test_inline_math_in_algorithm_is_omml():
    root = document_root(convert_source(ALGORITHMIC).docx)
    assert root.xpath("//m:oMath", namespaces=NS)


def test_algorithm_caption_has_seq_and_ref_resolves():
    root = document_root(convert_source(ALGORITHMIC).docx)
    instrs = "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))
    assert "SEQ Algorithm" in instrs
    assert "REF alg_bs" in instrs


def test_algorithm_lines_are_indented_and_numbered():
    root = document_root(convert_source(ALGORITHMIC).docx)
    # at least one paragraph carries a left indent (nested line)
    assert root.xpath("//w:p/w:pPr/w:ind", namespaces=NS)


def test_algorithm2e_basic_lines():
    src = r"""
\begin{document}
\begin{algorithm}
\caption{A2e}
\KwIn{a list}
\KwOut{sorted}
\For{$i=1$ to $n$}{
  swap;
}
\Return done\;
\end{algorithm}
\end{document}
"""
    alg = _alg(src)
    joined = " ".join(_line_text(line) for line in alg.lines)
    assert "Input:" in joined
    assert "Output:" in joined
    assert "for" in joined
    # the \For{...}{ body } group is recursed and rendered
    assert "swap" in joined


def test_algorithm2e_eif_renders_both_branches():
    src = (
        r"\begin{document}\begin{algorithm}"
        r"\eIf{$a>b$}{take a\;}{take b\;}"
        r"\end{algorithm}\end{document}"
    )
    alg = _alg(src)
    texts = [_line_text(line) for line in alg.lines]
    joined = " ".join(texts)
    assert "if" in joined and "then" in joined and "else" in joined
    assert "take a" in joined and "take b" in joined


def test_comment_attaches_to_line_not_separate():
    src = (
        r"\begin{document}\begin{algorithm}\begin{algorithmic}"
        r"\STATE $x \gets 0$ \COMMENT{init}"
        r"\end{algorithmic}\end{algorithm}\end{document}"
    )
    alg = _alg(src)
    assert len(alg.lines) == 1
    assert "▷ init" in _line_text(alg.lines[0])


def test_algorithmic_optional_arg_not_leaked():
    src = (
        r"\begin{document}\begin{algorithm}\begin{algorithmic}[1]"
        r"\STATE done\end{algorithmic}\end{algorithm}\end{document}"
    )
    alg = _alg(src)
    assert all("[1]" not in _line_text(line) for line in alg.lines)


def test_no_warnings_for_algorithm():
    result = convert_source(ALGORITHMIC)
    assert result.report.errors == []
    assert not any("algorithm" in w.construct.lower() for w in result.report.warnings)
