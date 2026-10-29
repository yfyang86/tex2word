"""Listing captions/labels and sub-figure references (issue #45)."""

from __future__ import annotations

from tex2word import convert_source, ir


def _doc(body: str, pre: str = "", base_dir: str = "."):
    r = convert_source("\\documentclass{article}\n" + pre + "\n\\begin{document}\n" + body
                       + "\n\\end{document}\n", base_dir=base_dir)
    assert [w.message for w in r.report.warnings] == []
    return r.document


def _code(doc) -> list[ir.CodeBlock]:
    return [b for b in doc.blocks if isinstance(b, ir.CodeBlock)]


def _txt(inl) -> str:
    return "".join(n.value if isinstance(n, ir.Text) else _txt(getattr(n, "inlines", []))
                   for n in inl or [])


def test_lstlisting_caption_label_and_title():
    doc = _doc("\\begin{lstlisting}[language=C,caption={Main loop},label=lst:m]\nint x;\n"
               "\\end{lstlisting}\n\\begin{lstlisting}[title=Untitled]\ny\n\\end{lstlisting}\n"
               "See Listing~\\ref{lst:m}.", r"\usepackage{listings}")
    first, second = _code(doc)
    assert _txt(first.caption) == "Main loop" and first.label == "lst:m"
    assert first.caption_numbered and not second.caption_numbered
    assert doc.labels["lst:m"].kind == "listing"


def test_lstinputlisting_caption(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    doc = _doc(r"\lstinputlisting[caption=Script,label=lst:a]{a.py} \ref{lst:a}",
               r"\usepackage{listings}", base_dir=str(tmp_path))
    (code,) = _code(doc)
    assert _txt(code.caption) == "Script" and "lst:a" in doc.labels


def test_minted_listing_float():
    doc = _doc("\\begin{listing}\\begin{minted}{python}\nx = 1\n\\end{minted}"
               "\\caption{Example}\\label{lst:e}\\end{listing}\\ref{lst:e}",
               r"\usepackage{minted}")
    (code,) = _code(doc)
    assert _txt(code.caption) == "Example" and code.label == "lst:e"


def test_subref_and_panel_refs():
    doc = _doc(r"\begin{figure}\begin{subfigure}{.4\textwidth}\caption{A}\label{f:a}"
               r"\end{subfigure}\begin{subfigure}{.4\textwidth}\caption{B}\label{f:b}"
               r"\end{subfigure}\caption{Both}\label{f}\end{figure}"
               r"See \ref{f:a}, \subref{f:b}, \ref{f}.", r"\usepackage{subcaption}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    assert "(b)" in _txt(para.inlines)
    texts = [i.value for i in para.inlines if isinstance(i, ir.Text)]
    assert "a" in texts  # \ref to a panel: the figure number then its letter


def test_subfloat_label_in_the_caption():
    doc = _doc(r"\begin{figure}\subfloat[Left\label{s:l}]{x}\subfloat[Right]{y}"
               r"\caption{C}\end{figure}\ref{s:l}", r"\usepackage{subfig}")
    assert doc.labels["s:l"].sub == "a"
