from __future__ import annotations

from conftest import NS, document_root

from tex2word import convert_source, ir
from tex2word.frontend import parse_document
from tex2word.report import ConversionReport
from tex2word.transforms.crossref import resolve_crossrefs


def _theorems(src: str) -> list[ir.Theorem]:
    doc, _ = parse_document(src)
    return [b for b in doc.blocks if isinstance(b, ir.Theorem)]


def test_theorem_parsed_with_title_and_counter():
    [t] = _theorems(
        r"\begin{document}\begin{theorem}[Pythagoras]$a^2+b^2=c^2$\end{theorem}\end{document}"
    )
    assert t.kind == "Theorem"
    assert t.counter == "Theorem"
    assert t.title is not None
    assert isinstance(t.title[0], ir.Text) and t.title[0].value == "Pythagoras"


def test_lemma_maps_to_lemma_counter():
    [t] = _theorems(r"\begin{document}\begin{lemma}X\end{lemma}\end{document}")
    assert t.kind == "Lemma"
    assert t.counter == "Lemma"


def test_proof_is_unnumbered():
    [t] = _theorems(r"\begin{document}\begin{proof}done\end{proof}\end{document}")
    assert t.kind == "Proof"
    assert t.counter is None


def test_starred_theorem_unnumbered():
    [t] = _theorems(r"\begin{document}\begin{theorem*}X\end{theorem*}\end{document}")
    assert t.counter is None


def test_label_inside_theorem_attaches_to_theorem_not_section():
    src = (
        r"\begin{document}\section{S}\label{sec:s}"
        r"\begin{theorem}\label{thm:a}X\end{theorem}\end{document}"
    )
    doc, _ = parse_document(src)
    heading = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    theorem = next(b for b in doc.blocks if isinstance(b, ir.Theorem))
    assert heading.label == "sec:s"
    assert theorem.label == "thm:a"


def test_crossref_uses_per_kind_counter():
    src = r"\begin{document}\begin{lemma}\label{l:1}X\end{lemma}\end{document}"
    doc, _ = parse_document(src)
    resolve_crossrefs(doc, ConversionReport())
    assert doc.labels["l:1"].counter_name == "Lemma"
    assert doc.labels["l:1"].kind == "theorem"


def test_backend_emits_seq_counter_and_bookmark():
    src = r"\begin{document}\begin{theorem}\label{t:1}X\end{theorem}\end{document}"
    root = document_root(convert_source(src).docx)
    instrs = "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))
    assert "SEQ Theorem" in instrs
    names = {e.get(f"{{{NS['w']}}}name") for e in root.xpath("//w:bookmarkStart", namespaces=NS)}
    assert "t_1" in names


def test_proof_has_qed():
    root = document_root(convert_source(
        r"\begin{document}\begin{proof}done\end{proof}\end{document}"
    ).docx)
    texts = "".join(t.text or "" for t in root.xpath("//w:t", namespaces=NS))
    assert "□" in texts
    assert "Proof" in texts


def test_theorem_ref_is_plain_seq_reference():
    src = (
        r"\begin{document}\begin{theorem}\label{t:1}X\end{theorem}"
        r"See \ref{t:1}.\end{document}"
    )
    root = document_root(convert_source(src).docx)
    instrs = "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))
    assert "REF t_1 \\h" in instrs
    assert "REF t_1 \\r" not in instrs  # not a paragraph-number ref
