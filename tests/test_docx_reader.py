"""SPRINT-V3 A2/M3: foreign-docx (no-manifest) OOXML -> IR reader."""

from __future__ import annotations

from tex2word import convert_source, ir
from tex2word.frontend.docx_reader import read_docx
from tex2word.roundtrip import to_latex


def _foreign(src: str) -> ir.Document:
    # convert without the manifest, then read the docx back structurally
    docx = convert_source(src, embed_manifest=False).docx
    return read_docx(docx)


def test_reads_heading_and_paragraph():
    doc = _foreign(r"\begin{document}\section{Intro}Body text.\end{document}")
    kinds = [type(b).__name__ for b in doc.blocks]
    assert "Heading" in kinds and "Paragraph" in kinds
    h = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    assert h.level == 1


def test_reads_emphasis():
    doc = _foreign(r"\begin{document}A \textbf{bold} word.\end{document}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.Emphasis) and i.kind_ == "bold" for i in para.inlines)


def test_reads_inline_and_display_math():
    doc = _foreign(r"\begin{document}$x^2$\[ \sum_{i=1}^n i \]\end{document}")
    assert any(isinstance(b, ir.MathBlock) for b in doc.blocks)
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    math = next(i for i in para.inlines if isinstance(i, ir.Math))
    assert "x" in math.latex and "2" in math.latex


def test_reads_ref_field():
    doc = _foreign(r"\begin{document}\section{S}\label{sec:s}See \ref{sec:s}.\end{document}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    refs = [i for i in para.inlines if isinstance(i, ir.Ref)]
    assert refs and refs[0].key  # bookmark name recovered


def test_reads_hyperlink_field():
    doc = _foreign(r"\begin{document}\href{http://x.com}{site}\end{document}")
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    link = next(i for i in para.inlines if isinstance(i, ir.Link))
    assert link.url == "http://x.com"


def test_reads_zotero_citation(tmp_path):
    (tmp_path / "refs.bib").write_text(
        "@article{e1905, author={Einstein, A.}, title={T}, year={1905}}\n", encoding="utf-8"
    )
    tex = tmp_path / "c.tex"
    tex.write_text(
        r"\begin{document}\cite{e1905}\bibliographystyle{plain}\bibliography{refs}\end{document}",
        encoding="utf-8",
    )
    from tex2word import convert_file

    _, result = convert_file(str(tex), embed_manifest=False, citation_mode="zotero")
    doc = read_docx(result.docx)
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    cites = [i for i in para.inlines if isinstance(i, ir.Cite)]
    assert cites and "e1905" in cites[0].keys


def test_reads_nested_list():
    doc = _foreign(
        r"\begin{document}\begin{itemize}\item a"
        r"\begin{itemize}\item b\end{itemize}\end{itemize}\end{document}"
    )
    lst = next(b for b in doc.blocks if isinstance(b, ir.ItemList))
    # the first item contains a nested list
    assert any(isinstance(blk, ir.ItemList) for it in lst.items for blk in it.blocks)


def test_reads_table():
    doc = _foreign(
        r"\begin{document}\begin{tabular}{ll}a & b\\ c & d\\\end{tabular}\end{document}"
    )
    tbl = next(b for b in doc.blocks if isinstance(b, ir.Table))
    assert len(tbl.rows) == 2
    assert len(tbl.rows[0].cells) == 2


def test_to_latex_foreign_roundtrips_structure():
    src = (
        r"\begin{document}\section{S}\label{s}Text $x^2$ \ref{s}."
        r"\begin{itemize}\item a\item b\end{itemize}\end{document}"
    )
    docx = convert_source(src, embed_manifest=False).docx
    latex = to_latex(docx)
    from tex2word.frontend import parse_document

    recovered, _ = parse_document(latex)
    kinds = [type(b).__name__ for b in recovered.blocks]
    assert kinds == ["Heading", "Paragraph", "ItemList"]


# -- V4-16: faithful recovery of Figure / Quote / CodeBlock ------------------ #

import struct  # noqa: E402
import zlib  # noqa: E402

from lxml import etree  # noqa: E402

from tex2word.frontend import docx_reader as _R  # noqa: E402

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _png(path, w=40, h=30):
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_reader_recovers_quote():
    doc = _foreign(r"\begin{document}\begin{quote}To be.\end{quote}\end{document}")
    quote = next((b for b in doc.blocks if isinstance(b, ir.Quote)), None)
    assert quote is not None
    text = "".join(
        i.value for p in quote.blocks if isinstance(p, ir.Paragraph)
        for i in p.inlines if isinstance(i, ir.Text)
    )
    assert "To be." in text


def test_reader_recovers_table_with_caption():
    docx = convert_source(
        r"\begin{document}\begin{table}\begin{tabular}{ll}a & b\\\end{tabular}"
        r"\caption{Results matrix}\end{table}\end{document}",
        embed_manifest=False,
    ).docx
    blocks = read_docx(docx).blocks
    tbl = next((b for b in blocks if isinstance(b, ir.Table)), None)
    assert tbl is not None and tbl.caption and tbl.caption[0].value == "Results matrix"
    # the caption is attached, not left as a stray trailing paragraph
    assert not any(isinstance(b, ir.Paragraph) and _plain_text_(b) == "Results matrix"
                   for b in blocks)


def _plain_text_(b):
    return "".join(i.value for i in b.inlines if isinstance(i, ir.Text)).strip()


def test_reader_recovers_figure_with_caption(tmp_path):
    _png(tmp_path / "p.png")
    docx = convert_source(
        r"\begin{document}\begin{figure}\includegraphics{p.png}"
        r"\caption{A red square}\end{figure}\end{document}",
        base_dir=str(tmp_path), embed_manifest=False,
    ).docx
    fig = next((b for b in read_docx(docx).blocks if isinstance(b, ir.Figure)), None)
    assert fig is not None and fig.image is not None
    assert fig.image.path == "p.png"
    assert fig.caption and fig.caption[0].value == "A red square"


def _para(style: str, text: str) -> str:
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
    )


def test_reader_recovers_codeblock_from_sourcecode_runs():
    # isolate from the (separate) verbatim parser bug: craft SourceCode paragraphs
    body = etree.fromstring(
        f'<w:body xmlns:w="{_W}">{_para("SourceCode", "def f(x):")}'
        f'{_para("SourceCode", "    return x+1")}{_para("Normal", "after")}</w:body>'.encode()
    )
    blocks = _R._Reader(ir.DocumentMeta()).read_body(body)
    code = next((b for b in blocks if isinstance(b, ir.CodeBlock)), None)
    assert code is not None and code.text == "def f(x):\n    return x+1"
    # the trailing Normal paragraph is NOT swallowed into the code block
    assert any(isinstance(b, ir.Paragraph) for b in blocks)


# -- V4-16: theorem / proof recovery ----------------------------------------- #


def _deep(inlines):
    out = []
    for i in inlines:
        if isinstance(i, ir.Text):
            out.append(i.value)
        elif isinstance(i, ir.Math):
            out.append(f"${i.latex}$")
        elif hasattr(i, "inlines"):
            out.append(_deep(i.inlines))
    return "".join(out)


def test_reader_recovers_theorem_with_title_and_math():
    doc = _foreign(
        r"\begin{document}\begin{theorem}[Pythagoras]"
        r"For a right triangle $a^2+b^2=c^2$.\end{theorem}\end{document}"
    )
    thm = next(b for b in doc.blocks if isinstance(b, ir.Theorem))
    assert thm.kind == "Theorem"
    assert thm.title and thm.title[0].value == "Pythagoras"
    body = _deep(thm.blocks[0].inlines)
    assert body.startswith("For a right triangle") and "$" in body


def test_reader_recovers_proof_and_strips_qed():
    doc = _foreign(r"\begin{document}\begin{proof}It follows.\end{proof}\end{document}")
    proof = next(b for b in doc.blocks if isinstance(b, ir.Theorem))
    assert proof.kind == "Proof"
    body = _deep(proof.blocks[0].inlines)
    assert body.strip() == "It follows." and "□" not in body


def test_reader_recovers_untitled_lemma():
    doc = _foreign(r"\begin{document}\begin{lemma}A short lemma.\end{lemma}\end{document}")
    lemma = next(b for b in doc.blocks if isinstance(b, ir.Theorem))
    assert lemma.kind == "Lemma" and lemma.title is None
    assert _deep(lemma.blocks[0].inlines).strip() == "A short lemma."


def test_plain_paragraph_is_not_mistaken_for_a_theorem():
    doc = _foreign(r"\begin{document}This is ordinary text.\end{document}")
    assert all(not isinstance(b, ir.Theorem) for b in doc.blocks)


def test_theorem_round_trips_through_foreign_read():
    src = r"\begin{document}\begin{theorem}[Euclid]A point has no part.\end{theorem}\end{document}"
    latex = to_latex(convert_source(src, embed_manifest=False).docx)
    assert r"\begin{theorem}[Euclid]" in latex


# -- V4-16: algorithm-box recovery ------------------------------------------- #

_ALG = (
    r"\begin{document}\begin{algorithm}\caption{Binary search}\label{alg:bs}"
    r"\begin{algorithmic}[1]"
    r"\STATE $lo \gets 0$"
    r"\WHILE{$lo \leq hi$}"
    r"  \STATE $mid \gets (lo+hi)/2$"
    r"\ENDWHILE"
    r"\end{algorithmic}\end{algorithm}\end{document}"
)


def test_reader_recovers_algorithm_box():
    doc = _foreign(_ALG)
    alg = next((b for b in doc.blocks if isinstance(b, ir.Algorithm)), None)
    assert alg is not None
    # the caption "Algorithm N: Binary search" is recovered without the number
    assert alg.caption and alg.caption[0].value == "Binary search"
    # bookmark sanitisation is irreversible (alg:bs -> alg_bs), as elsewhere
    assert alg.label and "bs" in alg.label
    # the numbered pseudocode lines came back with their content (and a number)
    assert alg.lines and all(ln.number for ln in alg.lines)
    body = " ".join(_deep(ln.inlines) for ln in alg.lines)
    assert "lo" in body and "mid" in body
    # the line-number prefix ("1  ", "2  ", …) was peeled off, not kept as text
    assert not any(ln.inlines and isinstance(ln.inlines[0], ir.Text)
                   and ln.inlines[0].value.strip().isdigit() for ln in alg.lines)


def test_recovered_algorithm_lines_keep_relative_indent():
    doc = _foreign(_ALG)
    alg = next(b for b in doc.blocks if isinstance(b, ir.Algorithm))
    # the \STATE inside the \WHILE is indented deeper than the top-level \STATE
    assert max(ln.indent for ln in alg.lines) > min(ln.indent for ln in alg.lines)


def test_algorithm_box_round_trips_to_latex():
    latex = to_latex(convert_source(_ALG, embed_manifest=False).docx)
    assert r"\begin{algorithm}" in latex and "Binary search" in latex


def test_real_table_is_not_mistaken_for_an_algorithm():
    doc = _foreign(
        r"\begin{document}\begin{tabular}{ll}a & b\\ c & d\\\end{tabular}\end{document}"
    )
    assert any(isinstance(b, ir.Table) for b in doc.blocks)
    assert all(not isinstance(b, ir.Algorithm) for b in doc.blocks)


# -- V4-16: description-list recovery ---------------------------------------- #

_DESC = (
    r"\begin{document}\begin{description}"
    r"\item[Apple] a pome fruit"
    r"\item[Banana] a yellow berry"
    r"\end{description}\end{document}"
)


def test_reader_recovers_description_list():
    doc = _foreign(_DESC)
    dl = next((b for b in doc.blocks if isinstance(b, ir.ItemList) and b.description), None)
    assert dl is not None
    assert len(dl.items) == 2
    assert _deep(dl.items[0].term) == "Apple"
    assert _deep(dl.items[0].blocks[0].inlines).strip() == "a pome fruit"
    assert _deep(dl.items[1].term) == "Banana"


def test_description_list_round_trips_to_latex():
    latex = to_latex(convert_source(_DESC, embed_manifest=False).docx)
    assert r"\begin{description}" in latex
    assert r"\item[Apple]" in latex and "a pome fruit" in latex


def test_plain_paragraph_is_not_mistaken_for_a_description_item():
    doc = _foreign(r"\begin{document}\textbf{Note} this is a normal sentence.\end{document}")
    assert all(not (isinstance(b, ir.ItemList) and b.description) for b in doc.blocks)


def test_bullet_list_is_not_read_as_a_description_list():
    doc = _foreign(
        r"\begin{document}\begin{itemize}\item one\item two\end{itemize}\end{document}"
    )
    lst = next(b for b in doc.blocks if isinstance(b, ir.ItemList))
    assert not lst.description
