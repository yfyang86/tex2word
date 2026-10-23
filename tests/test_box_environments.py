"""Fidelity: boxed environments (framed/mdframed/tcolorbox/...) -> Quote blocks."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def _quote_text(doc) -> str | None:
    q = next((b for b in doc.blocks if type(b).__name__ == "Quote"), None)
    if q is None:
        return None
    out = []
    for bb in q.blocks:
        for x in getattr(bb, "inlines", []):
            out.append(getattr(x, "value", "") or "".join(
                getattr(y, "value", "") for y in getattr(x, "inlines", [])
            ))
    return "".join(out)


def test_framed_and_shaded_become_quote():
    for env in ("framed", "shaded", "boxedminipage"):
        doc = _conv(rf"\begin{{{env}}} Boxed text. \end{{{env}}}").document
        assert _quote_text(doc) == "Boxed text.", env


def test_mdframed_consumes_options():
    doc = _conv(r"\begin{mdframed}[linewidth=2pt] Inside. \end{mdframed}").document
    # the [options] must not leak into the body
    assert _quote_text(doc) == "Inside."


def test_tcolorbox_consumes_options():
    doc = _conv(r"\begin{tcolorbox}[colback=red!5] Note. \end{tcolorbox}").document
    assert _quote_text(doc) == "Note."


def test_box_content_keeps_formatting():
    doc = _conv(r"\begin{framed}A \textbf{bold} word.\end{framed}").document
    q = next(b for b in doc.blocks if type(b).__name__ == "Quote")
    para = q.blocks[0]
    assert any(type(n).__name__ == "Emphasis" for n in para.inlines)


def test_newmdenv_defines_a_callout_environment():
    # \newmdenv[...]{name} in the preamble makes `name` a boxed environment,
    # and \newcommand wrappers around it expand to it.
    src = (
        r"\definecolor{Amber}{HTML}{B07D2B}\definecolor{AmberLight}{HTML}{FAF0DC}"
        r"\newmdenv[backgroundcolor=AmberLight,linecolor=Amber]{obox}"
        r"\newcommand{\open}[2]{\begin{obox}\textbf{Open item #1.}\ #2\end{obox}}"
        r"\begin{document}\open{7}{The note body.}\end{document}"
    )
    doc = convert_source(src).document
    q = next((b for b in doc.blocks if type(b).__name__ == "Quote"), None)
    assert q is not None, "obox not recognised as a boxed environment"
    # coloured callout: background + border captured from the \newmdenv options
    assert q.shade == "FAF0DC" and q.border == "B07D2B"


def test_newmdenv_callout_renders_as_shaded_box():
    src = (
        r"\definecolor{NavyDark}{HTML}{1F3864}\definecolor{NavyLight}{HTML}{DCE4F2}"
        r"\newmdenv[backgroundcolor=NavyLight,linecolor=NavyDark]{positionbox}"
        r"\begin{document}\begin{positionbox}Reserve the word.\end{positionbox}\end{document}"
    )
    conv = convert_source(src)
    assert validate_docx(conv.docx) == []
    import re
    import zipfile
    from io import BytesIO

    d = zipfile.ZipFile(BytesIO(conv.docx)).read("word/document.xml").decode()
    assert 'w:fill="DCE4F2"' in d          # background shading
    assert 'w:color="1F3864"' in d          # border colour
    assert "Reserve the word." in " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", d))


def test_valid():
    assert validate_docx(_conv(r"\begin{tcolorbox}[title=X]Body.\end{tcolorbox}").docx) == []


# -- tcolorbox styling: \newtcolorbox args, \tcbset styles, defaults ---------- #


def _quote(src):
    return next(b for b in convert_source(src).document.blocks if type(b).__name__ == "Quote")


def _title_text(q):
    def walk(inls):
        return "".join(getattr(i, "value", "") or walk(getattr(i, "inlines", [])) for i in inls)
    return walk(q.title or [])


def test_newtcolorbox_argument_becomes_title():
    # \newtcolorbox{box}[1]{title={#1},...}: the \begin{box}{...} argument is
    # consumed (not leaked as a body paragraph) and substituted into the title.
    src = (
        r"\definecolor{hd}{HTML}{1F2A6E}"
        r"\newtcolorbox{tplbox}[1]{colback=white,colframe=hd,colbacktitle=hd,"
        r"coltitle=white,fonttitle=\bfseries,title={#1}}"
        r"\begin{document}\begin{tplbox}{(a) Base template}Body text\end{tplbox}\end{document}"
    )
    q = _quote(src)
    assert _title_text(q) == "(a) Base template"
    assert (q.shade, q.border, q.title_shade) == ("FFFFFF", "1F2A6E", "1F2A6E")
    body = "".join(getattr(i, "value", "") for i in q.blocks[0].inlines)
    assert "Base template" not in body and "Body text" in body


def test_tcbset_style_and_override():
    src = (
        r"\definecolor{lo}{HTML}{faa755}"
        r"\tcbset{ex/.style={colback=orange!6,colframe=lo,title=Example}}"
        r"\begin{document}\begin{tcolorbox}[ex, title=Worked]X\end{tcolorbox}\end{document}"
    )
    q = _quote(src)
    assert q.border == "FAA755" and q.shade == "FFF7F0"
    assert _title_text(q) == "Worked"  # a later key overrides the style's title


def test_plain_tcolorbox_uses_tcolorbox_defaults():
    q = _quote(r"\begin{document}\begin{tcolorbox}Plain\end{tcolorbox}\end{document}")
    assert (q.shade, q.border) == ("F2F2F2", "404040")


def test_boxrule_zero_hides_the_frame():
    src = (
        r"\definecolor{bg}{HTML}{EEEFF9}"
        r"\newtcolorbox{inp}{colback=bg,colframe=black,boxrule=0pt}"
        r"\begin{document}\begin{inp}x\end{inp}\end{document}"
    )
    q = _quote(src)
    assert q.border == q.shade == "EEEFF9"


def test_titled_callout_renders_title_bar():
    src = (
        r"\newtcolorbox{tb}[1]{colframe=black,colbacktitle=black,title={#1}}"
        r"\begin{document}\begin{tb}{Takeaways}Body\end{tb}\end{document}"
    )
    conv = convert_source(src)
    assert validate_docx(conv.docx) == []
    import zipfile
    from io import BytesIO

    d = zipfile.ZipFile(BytesIO(conv.docx)).read("word/document.xml").decode()
    tbl = d[d.find("<w:tbl>"):d.find("</w:tbl>")]
    assert tbl.count("<w:tr>") == 2            # title row + body row
    assert 'w:fill="000000"' in tbl and "Takeaways" in tbl
