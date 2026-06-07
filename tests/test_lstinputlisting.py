"""Fidelity: \\lstinputlisting / \\verbatiminput embed an external file verbatim."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _code_blocks(doc) -> list[str]:
    return [b.text for b in doc.blocks if type(b).__name__ == "CodeBlock"]


def test_lstinputlisting_embeds_file(tmp_path):
    (tmp_path / "snippet.py").write_text("def f(x):\n    return x % 2  # keep\n")
    src = r"\begin{document}\lstinputlisting[language=Python]{snippet.py}\end{document}"
    res = convert_source(src, base_dir=str(tmp_path))
    blocks = _code_blocks(res.document)
    assert blocks, "expected a CodeBlock from \\lstinputlisting"
    assert "def f(x):" in blocks[0]
    # a literal % inside source code must survive (not stripped as a comment)
    assert "x % 2  # keep" in blocks[0]
    assert validate_docx(res.docx) == []


def test_verbatiminput_embeds_file(tmp_path):
    (tmp_path / "notes.txt").write_text("line one\nline two\n")
    src = r"\begin{document}\verbatiminput{notes.txt}\end{document}"
    res = convert_source(src, base_dir=str(tmp_path))
    blocks = _code_blocks(res.document)
    assert blocks and "line one" in blocks[0] and "line two" in blocks[0]


def test_missing_listing_file_is_dropped(tmp_path):
    src = r"\begin{document}Before \lstinputlisting{nope.py} after.\end{document}"
    res = convert_source(src, base_dir=str(tmp_path))
    # no crash, no code block, document still valid
    assert _code_blocks(res.document) == []
    assert validate_docx(res.docx) == []
