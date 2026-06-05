from __future__ import annotations

from tex2word import convert_source
from tex2word.backend.package import MANIFEST_PART
from tex2word.roundtrip import read_manifest, recover_ir

SRC = r"""
\title{RT}
\begin{document}
\section{S}\label{sec:s}
Text with $x^2$ and \eqref{eq:e}.
\begin{equation}\label{eq:e}E=mc^2\end{equation}
\end{document}
"""


def test_manifest_is_embedded():
    result = convert_source(SRC)
    assert MANIFEST_PART in _names(result.docx)
    payload = read_manifest(result.docx)
    assert payload is not None
    assert payload["tool"] == "tex2word"
    assert "ir" in payload
    assert payload["labels"]["eq:e"]["bookmark"] == "eq_e"


def test_manifest_can_be_disabled():
    result = convert_source(SRC, embed_manifest=False)
    assert MANIFEST_PART not in _names(result.docx)
    assert read_manifest(result.docx) is None


def test_recover_ir_round_trips():
    result = convert_source(SRC)
    recovered = recover_ir(result.docx)
    assert recovered is not None
    # original LaTeX is preserved on math nodes for round-trip
    assert recovered.to_dict() == result.document.to_dict()


def _names(docx: bytes):
    import io
    import zipfile

    return set(zipfile.ZipFile(io.BytesIO(docx)).namelist())
