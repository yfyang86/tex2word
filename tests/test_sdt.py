"""V5-4: semantic round-trip tags (w:sdt) — bibliography recovery + SDT descent."""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from latex2word import convert_file, ir
from latex2word.frontend import docx_reader as _R
from latex2word.frontend.docx_reader import read_docx
from latex2word.roundtrip import to_latex

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _bib_docx(tmp_path, embed_manifest=False) -> bytes:
    (tmp_path / "refs.bib").write_text(
        "@article{e1905, author={Einstein, A.}, title={On X}, year={1905}}\n",
        encoding="utf-8",
    )
    (tmp_path / "c.tex").write_text(
        r"\begin{document}Body \cite{e1905}."
        r"\bibliographystyle{plain}\bibliography{refs}\end{document}",
        encoding="utf-8",
    )
    _, result = convert_file(str(tmp_path / "c.tex"), embed_manifest=embed_manifest)
    return result.docx


def _part(docx: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read(name).decode()


def test_bibliography_is_wrapped_in_a_tagged_sdt(tmp_path):
    doc_xml = _part(_bib_docx(tmp_path), "word/document.xml")
    assert "latex2word:bibliography" in doc_xml
    assert "<w:sdt>" in doc_xml or "w:sdt>" in doc_xml


def test_reader_recovers_bibliography_block(tmp_path):
    doc = read_docx(_bib_docx(tmp_path))
    bib = next((b for b in doc.blocks if isinstance(b, ir.Bibliography)), None)
    assert bib is not None and bib.entries
    # no stray "References" heading leaks out of the SDT
    assert not any(
        isinstance(b, ir.Heading)
        and "".join(i.value for i in b.inlines if isinstance(i, ir.Text)).strip().lower()
        == "references"
        for b in doc.blocks
    )


def test_foreign_bibliography_text_survives_roundtrip(tmp_path):
    latex = to_latex(_bib_docx(tmp_path, embed_manifest=False))  # foreign path
    assert "thebibliography" in latex
    assert "Einstein" in latex  # the reference text is preserved as the entry note


_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f0005000100ff5ccae20000000049454e44ae426082"
)


def _figure_docx(tmp_path, embed_manifest=False) -> bytes:
    (tmp_path / "p.png").write_bytes(_PNG)
    from latex2word import convert_source

    return convert_source(
        r"\begin{document}\begin{figure}\includegraphics{p.png}"
        r"\caption{A diagram}\end{figure}\end{document}",
        base_dir=str(tmp_path), embed_manifest=embed_manifest,
    ).docx


def test_figure_is_wrapped_in_a_tagged_sdt(tmp_path):
    assert "latex2word:figure" in _part(_figure_docx(tmp_path), "word/document.xml")


def test_reader_recovers_figure_from_sdt(tmp_path):
    doc = read_docx(_figure_docx(tmp_path))
    fig = next((b for b in doc.blocks if isinstance(b, ir.Figure)), None)
    assert fig is not None and fig.image is not None and fig.image.path == "p.png"
    assert fig.caption and fig.caption[0].value == "A diagram"
    # it is recovered as a Figure, not a Table
    assert not any(isinstance(b, ir.Table) for b in doc.blocks)


def test_generic_content_control_content_is_recovered():
    # an untagged Word content control wrapping a paragraph -> its content is read
    body = etree.fromstring(
        f'<w:body xmlns:w="{_W}"><w:sdt><w:sdtPr/><w:sdtContent>'
        "<w:p><w:r><w:t>inside a control</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt></w:body>".encode()
    )
    blocks = _R._Reader(ir.DocumentMeta()).read_body(body)
    para = next((b for b in blocks if isinstance(b, ir.Paragraph)), None)
    assert para is not None
    assert "".join(i.value for i in para.inlines if isinstance(i, ir.Text)) == "inside a control"
