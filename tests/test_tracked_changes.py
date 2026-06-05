"""V5-3 (back): accept Word tracked changes when reading a .docx."""

from __future__ import annotations

from lxml import etree

from tex2word import ir
from tex2word.frontend import docx_reader as _R

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _body(inner: str) -> etree._Element:
    return etree.fromstring(f'<w:body xmlns:w="{_W}">{inner}</w:body>'.encode())


def _read(inner: str) -> list[ir.Block]:
    return _R._Reader(ir.DocumentMeta()).read_body(_body(inner))


def _text(blocks: list[ir.Block]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, ir.Paragraph):
            out.append("".join(i.value for i in b.inlines if isinstance(i, ir.Text)))
    return "".join(out)


def _run(text: str) -> str:
    return f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r>"


def test_inserted_run_is_kept():
    blocks = _read(f"<w:p>{_run('Keep ')}<w:ins>{_run('added')}</w:ins></w:p>")
    assert _text(blocks) == "Keep added"


def test_deleted_run_is_dropped():
    # deleted text uses w:delText and sits inside w:del -> accepted as a deletion
    deleted = "<w:del><w:r><w:delText>removed </w:delText></w:r></w:del>"
    blocks = _read(f"<w:p>{deleted}{_run('stays')}</w:p>")
    assert _text(blocks) == "stays"


def test_mixed_insert_and_delete():
    deleted = "<w:del><w:r><w:delText>old</w:delText></w:r></w:del>"
    blocks = _read(f"<w:p>{_run('A ')}<w:ins>{_run('new')}</w:ins>{deleted}</w:p>")
    assert _text(blocks) == "A new"


def test_move_from_dropped_move_to_kept():
    mv = f"<w:moveFrom>{_run('here')}</w:moveFrom>"
    blocks = _read(f"<w:p>{_run('X ')}{mv}<w:moveTo>{_run('there')}</w:moveTo></w:p>")
    assert _text(blocks) == "X there"


def test_fully_deleted_paragraph_is_dropped():
    deleted = "<w:del><w:r><w:delText>gone</w:delText></w:r></w:del>"
    blocks = _read(f"<w:p>{deleted}</w:p>{_run('') and ''}<w:p>{_run('kept')}</w:p>")
    assert _text(blocks) == "kept"
    assert sum(isinstance(b, ir.Paragraph) for b in blocks) == 1


def test_inserted_math_is_kept():
    omath = '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"/>'
    blocks = _read(f"<w:p>{_run('see ')}<w:ins>{omath}</w:ins></w:p>")
    para = next(b for b in blocks if isinstance(b, ir.Paragraph))
    assert any(isinstance(i, ir.Math) for i in para.inlines)
