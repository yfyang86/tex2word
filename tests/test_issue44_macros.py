"""Issue #44: structural redefinitions, rotated tables and layout macros."""

from __future__ import annotations

import io
import re
import zipfile

from tex2word import convert_source, ir


def _convert(body: str, preamble: str = "", cls: str = "article"):
    src = (
        f"\\documentclass{{{cls}}}\n" + preamble
        + "\\begin{document}\n" + body + "\n\\end{document}\n"
    )
    return convert_source(src)


def _text(docx: bytes) -> str:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    return "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml))


def _warned(r) -> list[str]:
    return [w.message for w in r.report.warnings]


def test_startsection_redefinition_is_not_expanded():
    r = _convert(
        "\\paragraph{Head.} Body.",
        preamble=(
            "\\makeatletter\n\\def\\paragraph{\\@startsection{paragraph}{4}\\z@"
            "{0.6\\baselineskip}{-\\fontdimen2\\font}{\\normalfont\\bfseries}}\n"
            "\\makeatother\n"
        ),
    )
    text = _text(r.docx)
    assert "startsection" not in text and "baselineskip" not in text
    assert any(
        isinstance(b, ir.Heading) and b.inlines and "Head" in b.inlines[0].value
        for b in r.document.blocks
    )
    assert not _warned(r)


def test_plain_redefinition_of_structural_name_still_expands():
    # a body without LaTeX internals is a real user macro: keep expanding it
    r = _convert("\\newcommand{\\today}{1 May 2020}\\today")
    assert "1 May 2020" in _text(r.docx)


def test_rotated_minipage_table_keeps_caption_label_and_rows():
    r = _convert(
        "\\begin{table}\\rotatebox{90}{\\begin{minipage}{5cm}"
        "\\captionof{table}{Rotated.}\\label{tab:r}\n"
        "\\begin{tabular}{l} \\makecell{a\\\\b} \\\\ c \\\\ \\end{tabular}"
        "\\end{minipage}}\\end{table}\nSee Table~\\ref{tab:r}.",
        preamble="\\usepackage{caption,makecell,graphicx}\n",
    )
    tables = [b for b in r.document.blocks if isinstance(b, ir.Table)]
    assert len(tables) == 1
    t = tables[0]
    assert t.label == "tab:r"
    assert t.caption and t.caption[0].value.startswith("Rotated")
    assert len(t.rows) == 2
    # \makecell{a\\b} -> a line break inside the cell
    cell = t.rows[0].cells[0].blocks[0]
    assert any(isinstance(i, ir.LineBreak) for i in cell.inlines)
    assert not _warned(r)
    text = _text(r.docx)
    assert "rotatebox" not in text and "captionof" not in text and "makecell" not in text


def test_makecell_alignment_option_is_consumed():
    r = _convert(
        "\\begin{tabular}{l} \\makecell[r]{Peak\\\\rate} & \\thead{H} \\\\ \\end{tabular}",
        preamble="\\usepackage{makecell}\n",
    )
    text = _text(r.docx)
    assert "[r]" not in text and "Peak" in text and "H" in text
    assert not _warned(r)


def test_path_and_nolinkurl_render_as_monospace():
    r = _convert("Data in \\path{generated/results_raw.json} and \\nolinkurl{a/b}.")
    para = r.document.blocks[0]
    mono = [i for i in para.inlines if isinstance(i, ir.Emphasis) and i.kind_ == "typewriter"]
    assert [m.inlines[0].value for m in mono] == ["generated/results_raw.json", "a/b"]
    assert not _warned(r)


def test_column_and_console_macros_are_silent():
    r = _convert(
        "Text.\\nobalance\n\\typeout{PAGE=\\thepage}\n\\onecolumn\n"
        "\\twocolumn[\\section{Wide}]\nMore."
    )
    assert not _warned(r)
    text = _text(r.docx)
    assert "PAGE" not in text and "nobalance" not in text
    # \twocolumn's optional argument is full-width content, not dropped
    assert any(isinstance(b, ir.Heading) for b in r.document.blocks)


def test_subjclass_uses_namedef_label():
    r = _convert(
        "\\subjclass[JEL]{D91, E21}\n\\subjclass[2010]{91B16}\n\\subjclass{00A00}",
        preamble="\\makeatletter\n\\@namedef{subjclassname@JEL}{JEL codes}\n\\makeatother\n",
        cls="amsart",
    )
    text = _text(r.docx)
    assert "JEL codes: D91, E21" in text
    assert "2010 Mathematics Subject Classification: 91B16" in text
    assert "Mathematics Subject Classification: 00A00" in text
    assert not _warned(r)


def test_amsart_thanks_before_maketitle_goes_on_the_title():
    r = _convert(
        "\\title{T}\\author{A}\\thanks{Funded.}\\subjclass[2010]{91B16}\n"
        "\\maketitle\nBody\\thanks{Later.}",
        cls="amsart",
    )
    title = r.document.meta.title
    assert title and isinstance(title[-1], ir.Footnote)
    # no paragraph holding nothing but the note mark
    assert not any(
        isinstance(b, ir.Paragraph) and all(isinstance(i, ir.Footnote) for i in b.inlines)
        for b in r.document.blocks
    )
    # after \maketitle, \thanks is an ordinary footnote in the text
    body = [b for b in r.document.blocks if isinstance(b, ir.Paragraph)][-1]
    assert any(isinstance(i, ir.Footnote) for i in body.inlines)
