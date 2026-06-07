"""Block-level (unbraced) declaration scopes: ``\\color{c} ...`` / ``\\bfseries ...``.

The braced forms (``{\\color{c} ...}``) already scope via _scoped_inlines, but a
declaration used bare at block level (a whole colored/bold paragraph, common on
cover pages) skipped the scope handler and leaked the macro literally. blocks()
now records a scope mark and wraps the following run of inlines at flush.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _runs(src: str):
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read("word/document.xml")
    )
    out = []
    for r in root.iter(f"{{{W}}}r"):
        text = "".join(x.text or "" for x in r.iter(f"{{{W}}}t"))
        rpr = r.find(f"{{{W}}}rPr")
        tags = [etree.QName(c).localname for c in rpr] if rpr is not None else []
        if text.strip():
            out.append((text, tags))
    return out


def _alltext(src: str) -> str:
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read("word/document.xml")
    )
    return "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def test_block_level_color_applies_and_does_not_leak():
    runs = _runs(r"\begin{document}\color{red} hello world\end{document}")
    run = next(r for r in runs if "hello" in r[0])
    assert "color" in run[1]
    assert r"\color" not in _alltext(r"\begin{document}\color{red} hi\end{document}")


def test_block_level_bfseries_applies_and_does_not_leak():
    runs = _runs(r"\begin{document}\bfseries hello world\end{document}")
    run = next(r for r in runs if "hello" in r[0])
    assert "b" in run[1]
    assert r"\bfseries" not in _alltext(r"\begin{document}\bfseries hi\end{document}")


def test_block_level_color_only_tints_text_after_it():
    runs = _runs(r"\begin{document}plain \color{red} tinted\end{document}")
    plain = next(r for r in runs if "plain" in r[0])
    tinted = next(r for r in runs if "tinted" in r[0])
    assert "color" not in plain[1]
    assert "color" in tinted[1]


def test_block_level_unresolved_color_no_leak():
    # an unknown colour name still must not leak the macro
    txt = _alltext(r"\begin{document}\color{white} content here\end{document}")
    assert "content here" in txt and r"\color" not in txt


def test_normalcolor_does_not_leak():
    txt = _alltext(r"\begin{document}\normalcolor text body\end{document}")
    assert "text body" in txt and r"\normalcolor" not in txt


def test_braced_color_still_works():
    # regression guard: the braced form keeps scoping correctly
    runs = _runs(r"\begin{document}{\color{red} hi} after\end{document}")
    assert "color" in next(r for r in runs if "hi" in r[0])[1]
    assert "color" not in next(r for r in runs if "after" in r[0])[1]
