"""V5-11: biblatex \\addbibresource + \\printbibliography support."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_file, ir

_BIB = "@article{e1905, author={Einstein, A.}, title={On X}, year={1905}}\n"


def _convert(tmp_path, body: str, preamble: str = "") -> tuple:
    (tmp_path / "refs.bib").write_text(_BIB, encoding="utf-8")
    (tmp_path / "p.tex").write_text(
        rf"\documentclass{{article}}{preamble}\begin{{document}}{body}\end{{document}}",
        encoding="utf-8",
    )
    return convert_file(str(tmp_path / "p.tex"), embed_manifest=False)


def test_biblatex_preamble_resource_and_printbibliography(tmp_path):
    _, res = _convert(
        tmp_path,
        body=r"Text \cite{e1905}.\printbibliography",
        preamble=r"\usepackage{biblatex}\addbibresource{refs.bib}",
    )
    bib = next(b for b in res.document.blocks if isinstance(b, ir.Bibliography))
    assert any(it.id == "e1905" for it in bib.entries)
    xml = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml").decode()
    assert "Einstein" in xml


def test_printbibliography_without_resource_still_emits_block(tmp_path):
    # even with no resolvable entries, \printbibliography yields a Bibliography block
    _, res = _convert(tmp_path, body=r"Body.\printbibliography")
    assert any(isinstance(b, ir.Bibliography) for b in res.document.blocks)


def test_addbibresource_in_body_is_recognised(tmp_path):
    _, res = _convert(
        tmp_path,
        body=r"\addbibresource{refs.bib}Text \cite{e1905}.\printbibliography",
    )
    bib = next(b for b in res.document.blocks if isinstance(b, ir.Bibliography))
    assert any(it.id == "e1905" for it in bib.entries)
