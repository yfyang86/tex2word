from __future__ import annotations

import struct
import zlib

from conftest import NS, document_root

from latex2word import convert_file, ir
from latex2word.frontend import parse_document


def _png(path, w=40, h=30, rgb=(0, 128, 255)):
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SUBCAPTION_SRC = r"""
\begin{document}
\begin{figure}
  \centering
  \begin{subfigure}[b]{0.45\textwidth}
    \includegraphics{a.png}\caption{First}\label{fig:a}
  \end{subfigure}
  \begin{subfigure}[b]{0.45\textwidth}
    \includegraphics{b.png}\caption{Second}\label{fig:b}
  \end{subfigure}
  \caption{Both}\label{fig:both}
\end{figure}
See \ref{fig:both}, \ref{fig:a}, \ref{fig:b}.
\end{document}
"""


def test_subcaption_environment_parsed():
    doc, _ = parse_document(SUBCAPTION_SRC)
    fig = next(b for b in doc.blocks if isinstance(b, ir.Figure))
    assert len(fig.subfigures) == 2
    assert [s.label for s in fig.subfigures] == ["fig:a", "fig:b"]
    assert fig.subfigures[0].caption[0].value == "First"
    assert fig.label == "fig:both"


def test_subfloat_command_parsed():
    src = (
        r"\begin{document}\begin{figure}"
        r"\subfloat[Left]{\includegraphics{a.png}\label{fig:l}}"
        r"\subfloat[Right]{\includegraphics{b.png}\label{fig:r}}"
        r"\caption{C}\label{fig:c}\end{figure}\end{document}"
    )
    doc, _ = parse_document(src)
    fig = next(b for b in doc.blocks if isinstance(b, ir.Figure))
    assert len(fig.subfigures) == 2
    assert fig.subfigures[0].caption[0].value == "Left"
    assert fig.subfigures[1].label == "fig:r"


def test_subfigure_labels_resolve_to_parent_number():
    doc, _ = parse_document(SUBCAPTION_SRC)
    from latex2word.report import ConversionReport
    from latex2word.transforms.crossref import resolve_crossrefs

    resolve_crossrefs(doc, ConversionReport())
    # parent + both sub-labels point at the same (figure number) bookmark
    bms = {doc.labels[k].bookmark for k in ("fig:both", "fig:a", "fig:b")}
    assert len(bms) == 1


def test_subfigures_render_images_and_captions(tmp_path):
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png", rgb=(255, 80, 80))
    tex = tmp_path / "main.tex"
    tex.write_text(SUBCAPTION_SRC, encoding="utf-8")
    _, result = convert_file(str(tex))
    assert result.report.errors == []
    root = document_root(result.docx)
    # two embedded images
    assert len(root.xpath("//w:drawing", namespaces=NS)) == 2
    caps = [
        "".join(p.xpath(".//w:t/text()", namespaces=NS))
        for p in root.xpath("//w:p", namespaces=NS)
        if p.xpath('./w:pPr/w:pStyle[@w:val="Caption"]', namespaces=NS)
    ]
    assert any(c.startswith("(a) First") for c in caps)
    assert any(c.startswith("(b) Second") for c in caps)
    assert any("Both" in c for c in caps)


def test_subfigures_render_side_by_side(tmp_path):
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    tex = tmp_path / "main.tex"
    tex.write_text(SUBCAPTION_SRC, encoding="utf-8")
    _, result = convert_file(str(tex))
    root = document_root(result.docx)
    # a single 1-row table with one cell per sub-figure
    tables = root.xpath("//w:tbl", namespaces=NS)
    assert len(tables) == 1
    cells = tables[0].xpath("./w:tr/w:tc", namespaces=NS)
    assert len(cells) == 2
    # each cell holds an image scaled below full text width
    extents = root.xpath(
        "//wp:extent",
        namespaces={"wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"},
    )
    from latex2word.backend.images import _MAX_WIDTH_EMU

    assert all(int(e.get("cx")) < _MAX_WIDTH_EMU for e in extents)


def test_subfigure_ref_emits_seq_figure_and_ref(tmp_path):
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png")
    tex = tmp_path / "main.tex"
    tex.write_text(SUBCAPTION_SRC, encoding="utf-8")
    _, result = convert_file(str(tex))
    root = document_root(result.docx)
    instrs = "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))
    assert "SEQ Figure" in instrs
    assert "REF fig_both" in instrs  # the \ref to a sub-figure resolves here
