from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from latex2word import convert_file

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CSL = str(Path(__file__).parent / "fixtures" / "numeric.csl")

_BIB = """\
@article{smith2020, title={On Things}, author={Smith, Jane}, year={2020}}
@book{jones2019, title={More Stuff}, author={Jones, Albert}, year={2019}}
@article{uncited2021, title={Unread}, author={Doe, John}, year={2021}}
"""
_TEX = r"""\documentclass{article}
\bibliographystyle{plain}
\begin{document}
We cite \cite{jones2019} and \cite{smith2020}.
\nocite{uncited2021}
\bibliography{refs}
\end{document}
"""


def _project(tmp_path) -> str:
    (tmp_path / "refs.bib").write_text(_BIB, encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(_TEX, encoding="utf-8")
    return str(main)


def _texts(docx: bytes) -> str:
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    return "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def _bib_entries(docx: bytes) -> list[str]:
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    out = []
    for p in root.iter(f"{{{W}}}p"):
        st = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        if st is not None and st.get(f"{{{W}}}val") == "Bibliography":
            out.append("".join(t.text or "" for t in p.iter(f"{{{W}}}t")))
    return out


# -- \nocite (citeproc-independent: works with the heuristic too) ------------- #


def test_nocite_includes_uncited_entry(tmp_path):
    _, result = convert_file(_project(tmp_path), str(tmp_path / "out.docx"))
    assert "Unread" in _texts(result.docx)  # uncited2021 pulled in by \nocite


# -- real CSL engine (needs the `csl` extra) ---------------------------------- #

pytest.importorskip("citeproc")


def test_csl_formats_citations_and_bibliography(tmp_path):
    _, result = convert_file(_project(tmp_path), str(tmp_path / "out.docx"), csl=_CSL)
    body = _texts(result.docx)
    assert "[1]" in body and "[2]" in body          # in-text numeric cites
    assert result.report.warnings == []


def test_csl_bibliography_not_double_numbered(tmp_path):
    _, result = convert_file(_project(tmp_path), str(tmp_path / "out.docx"), csl=_CSL)
    entries = _bib_entries(result.docx)
    assert entries and entries[0].startswith("[1] ")    # one label, not "[1]\t[1]"
    assert not entries[0].startswith("[1]\t[1]")
    assert any("Unread" in e for e in entries)          # \nocite entry present


def test_csl_output_is_valid(tmp_path):
    from latex2word.validate import validate_docx

    _, result = convert_file(_project(tmp_path), str(tmp_path / "out.docx"), csl=_CSL)
    assert validate_docx(result.docx) == []


def test_bad_csl_path_falls_back_to_heuristic(tmp_path):
    _, result = convert_file(
        _project(tmp_path), str(tmp_path / "out.docx"), csl=str(tmp_path / "nope.csl")
    )
    # graceful: a warning is logged and the heuristic still produces references
    assert any("csl" in w.construct.lower() for w in result.report.warnings)
    assert "On Things" in _texts(result.docx)
