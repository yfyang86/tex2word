"""V5-3 (back): recover Word review comments into LaTeX."""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source, ir
from tex2word.backend.latex_writer import write_latex
from tex2word.frontend.docx_reader import read_docx
from tex2word.roundtrip import to_latex

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _comments_xml(cid: str, author: str, text: str) -> bytes:
    return (
        f'<?xml version="1.0"?><w:comments xmlns:w="{_W}">'
        f'<w:comment w:id="{cid}" w:author="{author}"><w:p><w:r><w:t>{text}</w:t>'
        f"</w:r></w:p></w:comment></w:comments>"
    ).encode()


def _foreign_docx_with_comment() -> bytes:
    doc = (
        f'<?xml version="1.0"?><w:document xmlns:w="{_W}"><w:body>'
        '<w:p><w:r><w:t>The claim holds.</w:t></w:r>'
        '<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
        '<w:r><w:commentReference w:id="1"/></w:r></w:p>'
        "</w:body></w:document>"
    ).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/comments.xml", _comments_xml("1", "Alice", "Please clarify"))
    return buf.getvalue()


def test_reader_recovers_comment():
    doc = read_docx(_foreign_docx_with_comment())
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    note = next((i for i in para.inlines if isinstance(i, ir.Comment)), None)
    assert note is not None and note.author == "Alice" and note.text == "Please clarify"
    # the visible body text is untouched
    assert "".join(i.value for i in para.inlines if isinstance(i, ir.Text)) == "The claim holds."


def test_comment_renders_as_latex_percent_line():
    latex = write_latex(read_docx(_foreign_docx_with_comment()))
    assert "% comment: [Alice] Please clarify" in latex
    assert "The claim holds." in latex


def test_comment_does_not_comment_out_following_text():
    doc = ir.Document(blocks=[ir.Paragraph([
        ir.Text("before "), ir.Comment("a note", "Bob"), ir.Text("after"),
    ])])
    latex = write_latex(doc)
    # the note is on its own % line; "after" survives on a fresh line
    assert "before " in latex and "after" in latex
    assert "% comment: [Bob] a note" in latex
    line_with_after = next(ln for ln in latex.splitlines() if "after" in ln)
    assert not line_with_after.lstrip().startswith("%")


def _add_comment(docx: bytes, anchor: str, cid: str, author: str, text: str) -> bytes:
    """Attach a Word comment to the paragraph containing ``anchor`` (manifest left as-is)."""
    zin = zipfile.ZipFile(io.BytesIO(docx))
    parts = {n: zin.read(n) for n in zin.namelist()}
    root = etree.fromstring(parts["word/document.xml"])
    for p in root.iter(f"{{{_W}}}p"):
        if anchor in "".join(t.text or "" for t in p.iter(f"{{{_W}}}t")):
            r = etree.SubElement(p, f"{{{_W}}}r")
            ref = etree.SubElement(r, f"{{{_W}}}commentReference")
            ref.set(f"{{{_W}}}id", cid)
            break
    parts["word/document.xml"] = etree.tostring(root)
    parts["word/comments.xml"] = _comments_xml(cid, author, text)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_todo_becomes_a_word_comment():
    res = convert_source(r"\begin{document}The proof is short.\todo{expand this}\end{document}")
    z = zipfile.ZipFile(io.BytesIO(res.docx))
    assert "word/comments.xml" in z.namelist()
    assert "expand this" in z.read("word/comments.xml").decode()
    assert "commentReference" in z.read("word/document.xml").decode()
    from tex2word.validate import validate_docx

    assert validate_docx(res.docx) == []


def test_todo_round_trips_to_a_comment_line_without_duplication():
    res = convert_source(r"\begin{document}The proof is short.\todo{expand this}\end{document}")
    latex = to_latex(res.docx)  # manifest + reconcile
    assert "The proof is short." in latex
    assert latex.count("expand this") == 1  # not duplicated by reconcile grafting
    assert "% comment:" in latex


def test_no_comments_means_no_comments_part():
    res = convert_source(r"\begin{document}Plain text.\end{document}")
    assert "word/comments.xml" not in zipfile.ZipFile(io.BytesIO(res.docx)).namelist()


def test_comment_survives_reconcile_on_unchanged_paragraph():
    # our own output (has the manifest) reviewed in Word with a comment added
    src = r"\begin{document}\section{S}The first paragraph is unchanged.\end{document}"
    docx = convert_source(src).docx
    commented = _add_comment(
        docx, "The first paragraph is unchanged.", "1", "Bob", "check this",
    )
    latex = to_latex(commented)  # reconcile is on by default
    assert "The first paragraph is unchanged." in latex  # exact manifest text kept
    assert "% comment: [Bob] check this" in latex  # the note is grafted on
