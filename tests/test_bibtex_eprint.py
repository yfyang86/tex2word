"""V5-11 tail: richer bibtex->CSL field mapping (eprint/arXiv, ISSN, chapter)."""

from __future__ import annotations

from tex2word.bib.bibtex import parse_bibtex
from tex2word.bib.render import format_reference

ARXIV = r"""
@article{vaswani2017,
  author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention Is All You Need},
  year = {2017},
  eprint = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass = {cs.CL}
}
@article{withdoi,
  author = {Doe, Jane},
  title = {A Paper}, journal = {J}, year = {2020},
  doi = {10.1/x}, eprint = {2001.00001}, archivePrefix = {arXiv}
}
@book{withissn,
  author = {Roe, R.}, title = {Vol}, year = {1999},
  issn = {1234-5678}, chapter = {3}
}
"""


def test_arxiv_eprint_becomes_abs_url():
    items = parse_bibtex(ARXIV)
    f = items["vaswani2017"].csl_fields
    assert f["URL"] == "https://arxiv.org/abs/1706.03762"
    assert f["note"] == "arXiv:1706.03762"


def test_existing_doi_wins_over_eprint_url():
    items = parse_bibtex(ARXIV)
    f = items["withdoi"].csl_fields
    assert f["DOI"] == "10.1/x"
    # eprint must not clobber a real DOI's URL slot
    assert f.get("URL") != "https://arxiv.org/abs/2001.00001"
    assert f["note"] == "arXiv:2001.00001"


def test_issn_and_chapter_mapped():
    items = parse_bibtex(ARXIV)
    f = items["withissn"].csl_fields
    assert f["ISSN"] == "1234-5678"
    assert f["chapter-number"] == "3"


def test_eprint_url_renders():
    items = parse_bibtex(ARXIV)
    assert "arxiv.org/abs/1706.03762" in format_reference(items["vaswani2017"])
