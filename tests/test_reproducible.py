"""V4-18: reproducible builds via SOURCE_DATE_EPOCH."""

from __future__ import annotations

import io
import json
import zipfile

from latex2word import convert_source

SRC = (
    r"\begin{document}\section{S}Hello $x^2$. \cite{a}"
    r"\begin{figure}\caption{C}\label{f}\end{figure}\end{document}"
)


def _manifest(docx: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(docx))
    name = next(n for n in zf.namelist() if "manifest" in n)
    return json.loads(zf.read(name).decode())


def test_output_is_byte_identical_with_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    a = convert_source(SRC).docx
    b = convert_source(SRC).docx
    assert a == b  # fully deterministic


def test_manifest_timestamp_follows_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    gen = _manifest(convert_source(SRC).docx)["generated"]
    assert gen == "2023-11-14T22:13:20+00:00"


def test_invalid_source_date_epoch_falls_back(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "not-a-number")
    # must not crash; just uses the current time
    assert convert_source(SRC).docx
