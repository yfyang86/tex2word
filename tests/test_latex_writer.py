"""SPRINT-V3 A2/M1: IR -> LaTeX writer + manifest-only round-trip."""

from __future__ import annotations

from tex2word import convert_source, ir
from tex2word.backend.latex_writer import latex_escape, write_latex
from tex2word.cli import main
from tex2word.frontend import parse_document
from tex2word.roundtrip import to_latex

K = "@type"


def _kinds(doc: ir.Document) -> list[str]:
    return [b[K] for b in doc.to_dict()["blocks"]]


def test_latex_escape():
    assert latex_escape("a & b % c") == r"a \& b \% c"
    assert latex_escape("x_1") == r"x\_1"


def test_writer_emits_preamble_and_body():
    doc, _ = parse_document(r"\begin{document}\section{S}$x^2$\end{document}")
    tex = write_latex(doc)
    assert "\\documentclass{article}" in tex
    assert "\\usepackage{amsmath}" in tex
    assert "\\begin{document}" in tex and "\\end{document}" in tex
    assert "\\section{S}" in tex


def test_to_latex_prefers_manifest_then_reader():
    # with the manifest -> exact IR; without -> the foreign-docx reader (M3).
    with_manifest = convert_source(r"\begin{document}x\end{document}").docx
    assert to_latex(with_manifest) is not None
    no_manifest = convert_source(r"\begin{document}x\end{document}", embed_manifest=False).docx
    recovered = to_latex(no_manifest)
    assert recovered is not None and "\\begin{document}" in recovered


def _roundtrip(src: str) -> tuple[ir.Document, ir.Document]:
    docx = convert_source(src).docx
    latex = to_latex(docx)
    assert latex is not None
    original, _ = parse_document(src)
    recovered, _ = parse_document(latex)
    return original, recovered


def test_roundtrip_block_structure():
    src = (
        r"\begin{document}\section{Intro}\label{s:i}"
        r"Text \textbf{bold} and $x^2$ and \eqref{eq:e}."
        r"\begin{equation}\label{eq:e}E=mc^2\end{equation}"
        r"\begin{itemize}\item one\item two\end{itemize}\end{document}"
    )
    original, recovered = _roundtrip(src)
    assert _kinds(original) == _kinds(recovered)


def test_roundtrip_preserves_math_source():
    src = r"\begin{document}\begin{align}a &= b \\ c &= d\end{align}\end{document}"
    _, recovered = _roundtrip(src)
    mb = next(b for b in recovered.blocks if isinstance(b, ir.MathBlock))
    assert "a &= b" in mb.latex and "c &= d" in mb.latex


def test_roundtrip_list_has_no_empty_leading_item():
    _, recovered = _roundtrip(
        "\\begin{document}\\begin{itemize}\n\\item a\\item b\\end{itemize}\\end{document}"
    )
    lst = next(b for b in recovered.blocks if isinstance(b, ir.ItemList))
    assert len(lst.items) == 2


def test_roundtrip_description_term():
    _, recovered = _roundtrip(
        r"\begin{document}\begin{description}\item[Key] val\end{description}\end{document}"
    )
    lst = next(b for b in recovered.blocks if isinstance(b, ir.ItemList))
    assert lst.description and lst.items[0].term[0].value == "Key"


def test_roundtrip_table_and_theorem():
    src = (
        r"\newtheorem{theorem}{Theorem}\begin{document}"
        r"\begin{theorem}[T]$a=b$\end{theorem}"
        r"\begin{tabular}{ll}\toprule a & b\\\midrule c & d\\\bottomrule\end{tabular}"
        r"\end{document}"
    )
    original, recovered = _roundtrip(src)
    assert _kinds(original) == _kinds(recovered)


def test_to_latex_cli(tmp_path):
    tex = tmp_path / "in.tex"
    tex.write_text(r"\begin{document}\section{Hi}$x^2$\end{document}", encoding="utf-8")
    docx = tmp_path / "in.docx"
    assert main(["convert", str(tex), "-o", str(docx)]) == 0
    out = tmp_path / "back.tex"
    assert main(["to-latex", str(docx), "-o", str(out)]) == 0
    recovered = out.read_text(encoding="utf-8")
    assert "\\section{Hi}" in recovered and "$x^2$" in recovered
