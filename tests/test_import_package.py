"""Fidelity: import package \\import{dir}{file} / \\subimport flattening."""

from __future__ import annotations

from tex2word import convert_file
from tex2word.validate import validate_docx


def _text(doc) -> str:
    out = []

    def walk(inlines):
        for n in inlines:
            if type(n).__name__ == "Text":
                out.append(n.value)
            elif hasattr(n, "inlines"):
                walk(n.inlines)

    for b in doc.blocks:
        if hasattr(b, "inlines"):
            walk(b.inlines)
    return " ".join(out)


def test_import_inlines_file_from_dir(tmp_path):
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "ch1.tex").write_text("Chapter one body.\n")
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\import{chapters/}{ch1.tex}\end{document}"
    )
    _, res = convert_file(str(tmp_path / "main.tex"), str(tmp_path / "out.docx"),
                          embed_manifest=False)
    t = _text(res.document)
    assert "Chapter one body." in t
    assert "import" not in t  # the macro must not leak as text
    assert validate_docx(res.docx) == []


def test_subimport_and_nested_input(tmp_path):
    sub = tmp_path / "parts"
    sub.mkdir()
    (sub / "a.tex").write_text(r"Part A then \input{b}.")
    (sub / "b.tex").write_text("nested B.")
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\subimport{parts/}{a.tex}\end{document}"
    )
    _, res = convert_file(str(tmp_path / "main.tex"), str(tmp_path / "out.docx"),
                          embed_manifest=False)
    t = _text(res.document)
    assert "Part A" in t and "nested B." in t


def test_missing_import_is_dropped(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Before \import{x/}{gone.tex} after."
        r"\end{document}"
    )
    _, res = convert_file(str(tmp_path / "main.tex"), str(tmp_path / "out.docx"),
                          embed_manifest=False)
    assert validate_docx(res.docx) == []
    assert "gone" not in _text(res.document)
