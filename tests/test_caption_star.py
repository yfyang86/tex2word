"""V5-12: \\caption* (unnumbered captions)."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source, ir
from tex2word.roundtrip import to_latex

_TABLE = (
    r"\begin{{document}}\begin{{table}}\begin{{tabular}}{{ll}}a & b\\\end{{tabular}}"
    r"\caption{star}{{Unnumbered}}\end{{table}}\end{{document}}"
)


def _table(src: str) -> ir.Table:
    return next(b for b in convert_source(src).document.blocks if isinstance(b, ir.Table))


def _caption_text(docx: bytes) -> str:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    return xml


def test_table_caption_star_is_unnumbered():
    tbl = _table(_TABLE.format(star="*"))
    assert tbl.caption_numbered is False


def test_table_caption_plain_is_numbered():
    tbl = _table(_TABLE.format(star=""))
    assert tbl.caption_numbered is True


def test_caption_star_emits_no_seq_field():
    res = convert_source(_TABLE.format(star="*"))
    xml = _caption_text(res.docx)
    assert "Unnumbered" in xml
    # the unnumbered caption has no "SEQ Table" field and no "Table N:" prefix
    assert "SEQ Table" not in xml


def test_numbered_caption_keeps_seq_field():
    res = convert_source(_TABLE.format(star=""))
    assert "SEQ Table" in _caption_text(res.docx)


def test_caption_star_round_trips():
    res = convert_source(_TABLE.format(star="*"))
    latex = to_latex(res.docx)
    assert re.search(r"\\caption\*\{Unnumbered\}", latex)
