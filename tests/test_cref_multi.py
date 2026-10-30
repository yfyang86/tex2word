"""Fidelity: multi-label \\cref{a,b,c} and \\crefrange{a}{b} (cleveref)."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source
from tex2word.validate import validate_docx

PRE = r"""
\section{A}\label{s:a}
\section{B}\label{s:b}
\section{C}\label{s:c}
\begin{equation}x\label{e:x}\end{equation}
\begin{figure}\caption{F}\label{f:x}\end{figure}
"""


def _conv(body: str, preamble: str = ""):
    return convert_source(r"\documentclass{article}\usepackage{amsmath}" + preamble
                          + r"\usepackage{cleveref}\begin{document}" + PRE + body
                          + r"\end{document}")


def _last(res) -> str:
    xml = zipfile.ZipFile(io.BytesIO(res.docx)).read("word/document.xml").decode()
    paras = [re.sub(r"\s+", " ", "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p)))
             for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    return [p for p in paras if p.strip()][-1].strip()


def test_one_ref_holds_every_label():
    res = _conv(r"See \cref{s:a,s:b}.")
    assert not any("unresolved" in (w.message or "") for w in res.report.warnings)
    para = [b for b in res.document.blocks if type(b).__name__ == "Paragraph"][-1]
    refs = [n for n in para.inlines if type(n).__name__ == "Ref"]
    assert len(refs) == 1 and refs[0].key == "s:a" and refs[0].more == ["s:b"]


def test_plural_names_and_conjunctions():
    assert _last(_conv(r"See \cref{s:a,s:b}.")) == "See sections 1 and 2."
    assert _last(_conv(r"See \cref{s:a,s:b,s:c}.")) == "See sections 1, 2 and 3."
    assert _last(_conv(r"See \cref{s:a,f:x,e:x}.")) == "See section 1, fig. 1 and eq. (1)."
    assert _last(_conv(r"See \Cref{s:a,s:b}.")) == "See Sections 1 and 2."


def test_crefrange_both_endpoints():
    assert _last(_conv(r"See \crefrange{s:a}{s:c}.")) == "See sections 1 to 3."


def test_cleveref_default_names_and_options():
    assert _last(_conv(r"\cref{s:a} \Cref{s:a} \cref{e:x} \cref{f:x}")) == (
        "section 1 Section 1 eq. (1) fig. 1")
    capital = _conv(r"\cref{e:x} \cref{f:x}", r"\usepackage[capitalise,noabbrev]{cleveref}")
    assert _last(capital) == "Equation (1) Figure 1"
    renamed = _conv(r"\cref{s:a,s:b}", r"\crefname{section}{sect.}{sects.}")
    assert _last(renamed) == "sects. 1 and 2"


def test_ref_eqref_autoref():
    assert _last(_conv(r"\ref{e:x} \eqref{e:x} \autoref{e:x} \autoref{s:a} \labelcref{e:x}")) \
        == "1 (1) Equation 1 section 1 (1)"


def test_valid():
    assert validate_docx(_conv(r"\cref{s:a,s:b} and \crefrange{s:a}{s:c}.").docx) == []
