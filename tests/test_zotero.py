"""SPRINT-V2 A4: live Zotero/Mendeley citation fields."""

from __future__ import annotations

import json

from conftest import NS, document_root

from tex2word import convert_file

BIB = r"""
@article{e1905, author={Einstein, Albert}, title={Zur Elektrodynamik},
  journal={Ann. Phys.}, volume={17}, year={1905}}
@book{k1984, author={Knuth, Donald E.}, title={The TeXbook}, year={1984}}
"""


def _convert(body: str, tmp_path, mode: str):
    (tmp_path / "z.bib").write_text(BIB, encoding="utf-8")
    tex = tmp_path / "z.tex"
    tex.write_text(
        rf"\begin{{document}}{body}\bibliographystyle{{plainnat}}"
        rf"\bibliography{{z}}\end{{document}}",
        encoding="utf-8",
    )
    _, result = convert_file(str(tex), citation_mode=mode)
    return result


def _instrs(docx):
    root = document_root(docx)
    return [t.text or "" for t in root.xpath("//w:instrText", namespaces=NS)]


def test_static_mode_has_no_zotero_fields(tmp_path):
    result = _convert(r"Text \citep{e1905}.", tmp_path, "static")
    assert not any("ZOTERO" in i for i in _instrs(result.docx))


def test_zotero_mode_emits_citation_field(tmp_path):
    result = _convert(r"Text \citep{e1905}.", tmp_path, "zotero")
    cits = [i for i in _instrs(result.docx) if "ZOTERO_ITEM CSL_CITATION" in i]
    assert len(cits) == 1


def test_zotero_citation_json_valid(tmp_path):
    result = _convert(r"\citep[p.~5]{e1905}.", tmp_path, "zotero")
    cit = next(i for i in _instrs(result.docx) if "ZOTERO_ITEM" in i)
    payload = json.loads(cit.split("CSL_CITATION ", 1)[1])
    item = payload["citationItems"][0]
    assert item["itemData"]["title"] == "Zur Elektrodynamik"
    assert item["itemData"]["type"] == "article-journal"
    assert item["locator"] == "p.5"
    assert payload["properties"]["formattedCitation"].startswith("(Einstein")


def test_zotero_bibliography_field(tmp_path):
    result = _convert(r"\citep{e1905}.", tmp_path, "zotero")
    assert any("ZOTERO_BIBL" in i and "CSL_BIBLIOGRAPHY" in i for i in _instrs(result.docx))


def test_zotero_cached_text_matches_static(tmp_path):
    # the field's cached result should be the same formatted text as static mode
    static = _convert(r"\citet{k1984}.", tmp_path, "static")
    zot = _convert(r"\citet{k1984}.", tmp_path, "zotero")
    static_text = " ".join(
        t.text or "" for t in document_root(static.docx).xpath("//w:t", namespaces=NS)
    )
    zot_text = " ".join(
        t.text or "" for t in document_root(zot.docx).xpath("//w:t", namespaces=NS)
    )
    assert "Knuth (1984)" in static_text
    assert "Knuth (1984)" in zot_text


def test_zotero_output_valid(tmp_path):
    from tex2word.validate import validate_docx

    result = _convert(r"\citep[see][p.~5]{e1905} and \citet{k1984}.", tmp_path, "zotero")
    assert validate_docx(result.docx) == []
