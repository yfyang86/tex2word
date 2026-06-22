"""Code-listing environments must capture verbatim, not parse as LaTeX.

Regression for the bug where a ``$`` inside a ``lstlisting`` (e.g. R's ``df$col``)
opened math mode in pylatexenc -- with an odd count it swallowed ``\\end{lstlisting}``
and turned the rest of the document into code. ``lstlisting``/``minted``/``Verbatim``
are now normalised to ``verbatim`` (which pylatexenc captures literally), and the
``[options]`` / minted ``{lang}`` are dropped instead of leaking as a code line.
"""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _paras(src: str):
    from lxml import etree

    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read("word/document.xml")
    )
    out = []
    for p in root.findall(f"{{{W}}}body/{{{W}}}p"):
        pst = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        st = pst.get(f"{{{W}}}val") if pst is not None else "Normal"
        txt = "".join(t.text or "" for t in p.iter(f"{{{W}}}t"))
        if txt.strip():
            out.append((st, txt))
    return out


def test_odd_dollar_in_listing_does_not_eat_the_document():
    src = (
        r"\begin{document}\begin{lstlisting}[language=R]"
        + "\nx <- lung$time\n"
        + r"\end{lstlisting}"
        + "\nprose after \\textsf{R} 函数。\n"
        + r"\end{document}"
    )
    paras = _paras(src)
    # the prose after the listing must be normal text (not swallowed as code)
    assert paras[-1][0] == "Normal"
    assert "prose after" in paras[-1][1] and "R 函数" in paras[-1][1]
    assert "\\textsf" not in paras[-1][1]  # the macro was actually processed


def test_listing_options_not_rendered_as_code_line():
    src = (
        r"\begin{document}\begin{lstlisting}[language=R, escapeinside={(*}{*)}]"
        + "\na <- 1\n"
        + r"\end{lstlisting}"
        + r"\end{document}"
    )
    code = [t for st, t in _paras(src) if st == "SourceCode"]
    assert any("a <- 1" in t for t in code)
    assert not any("language=R" in t for t in code)  # the [options] are dropped


def test_listing_options_with_braced_brackets_not_leaked():
    # [caption={[Fig.1]}] has a ``]`` nested inside a braced value; the [options]
    # matcher must consume the whole thing rather than truncating at the inner ``]``
    # and leaking ``}]`` (plus the code) as a runaway listing.
    src = (
        r"\begin{document}\begin{lstlisting}[language=R, caption={[Fig.1] demo}]"
        + "\nz <- 1\n"
        + r"\end{lstlisting}"
        + "\nprose after.\n"
        + r"\end{document}"
    )
    paras = _paras(src)
    assert paras[-1] == ("Normal", "prose after.")
    code = [t for st, t in paras if st == "SourceCode"]
    assert any("z <- 1" in t for t in code)
    assert not any("caption" in t or "Fig.1" in t for t in code)  # options dropped


def test_listing_code_with_dollars_preserved_literally():
    src = (
        r"\begin{document}\begin{lstlisting}[language=R]"
        + "\ny <- a$b + temp$jump\n"
        + r"\end{lstlisting}"
        + r"\end{document}"
    )
    code = [t for st, t in _paras(src) if st == "SourceCode"]
    assert any("a$b + temp$jump" in t for t in code)


def test_minted_with_lang_and_options():
    src = (
        r"\begin{document}\begin{minted}[linenos]{python}"
        + "\nd = obj.attr\n"
        + r"\end{minted}"
        + "\nprose after.\n"
        + r"\end{document}"
    )
    paras = _paras(src)
    assert any(st == "SourceCode" and "d = obj.attr" in t for st, t in paras)
    assert paras[-1] == ("Normal", "prose after.")
    assert not any("python" in t for st, t in paras if st == "SourceCode")


def test_two_listings_with_prose_between_and_after():
    src = (
        r"\begin{document}"
        r"\begin{lstlisting}[language=R, escapeinside={(*}{*)}]"
        + "\nKMfun(1)\n(* $x$ *) note\n"
        + r"\end{lstlisting}"
        + "\n中间散文 $g(t)=1$ 定义：\n"
        + r"\begin{lstlisting}[language=R]"
        + "\nSUR <- temp$surv\n"
        + r"\end{lstlisting}"
        + "\n结尾散文。\n"
        + r"\end{document}"
    )
    paras = _paras(src)
    # both prose paragraphs are Normal, not code
    assert ("Normal", "结尾散文。") in [(s, t) for s, t in paras]
    assert any(s == "Normal" and "中间散文" in t for s, t in paras)


def test_listing_via_input_is_normalized(tmp_path):
    # A code listing pulled in via \input must be normalised too -- otherwise an
    # odd number of $ in the code (R's df$col) breaks parsing of everything after.
    from tex2word import convert_source

    (tmp_path / "inc.tex").write_text(
        r"\begin{lstlisting}[language=R]"
        + "\ntemp <- WKM(x=lung$time2, d=lung$death2)\ninde <- (temp$jump > 0)\n"
        + r"\end{lstlisting}"
        + "\nprose after the input \\textsf{R} 函数。\n",
        encoding="utf-8",
    )
    main = r"\documentclass{book}\begin{document}\input{inc.tex}\end{document}"
    from lxml import etree

    docx = convert_source(main, base_dir=str(tmp_path)).docx
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml")
    )
    paras = []
    for p in root.findall(f"{{{W}}}body/{{{W}}}p"):
        pst = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        st = pst.get(f"{{{W}}}val") if pst is not None else "Normal"
        txt = "".join(t.text or "" for t in p.iter(f"{{{W}}}t"))
        if txt.strip():
            paras.append((st, txt))
    after = next((s, t) for s, t in paras if "prose after" in t)
    assert after[0] == "Normal"
    assert "\\textsf" not in after[1] and "\\end{lstlisting}" not in after[1]
    # the options line is not leaked as code
    assert not any("language=R" in t for s, t in paras if s == "SourceCode")

