"""Declaration-form font switches: ``{\\bfseries ...}`` / ``{\\bf ...}`` etc.

These take no argument and apply to the rest of the enclosing group (like
``\\color``). Previously the long forms silently dropped their effect and the
short plain-TeX forms (``\\bf``/``\\tt``/...) leaked literally (``\\bf1.``).
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


def _run_with(src: str, needle: str):
    return next(r for r in _runs(src) if needle in r[0])


def test_bfseries_declaration_is_bold():
    assert "b" in _run_with(r"\begin{document}x {\bfseries hi} y\end{document}", "hi")[1]


def test_short_bf_is_bold():
    assert "b" in _run_with(r"\begin{document}x {\bf hi} y\end{document}", "hi")[1]


def test_short_it_is_italic():
    assert "i" in _run_with(r"\begin{document}x {\it hi} y\end{document}", "hi")[1]


def test_short_tt_is_typewriter():
    assert "rFonts" in _run_with(r"\begin{document}x {\tt code} y\end{document}", "code")[1]


def test_scope_ends_at_group():
    runs = _runs(r"\begin{document}a {\bf b} c\end{document}")
    after = next(r for r in runs if "c" in r[0])
    assert "b" not in after[1]  # 'c' is outside the group -> not bold


def test_short_forms_do_not_leak_literally():
    txt = _alltext(r"\begin{document}{\bf A}{\tt B}{\it C}{\sc D}{\rm E}\end{document}")
    for tok in (r"\bf", r"\tt", r"\it", r"\sc", r"\rm"):
        assert tok not in txt


def test_itemize_label_bold_no_leak():
    txt = _alltext(
        r"\begin{document}\begin{itemize}\item[{\bf 1.}] item one\end{itemize}\end{document}"
    )
    assert r"\bf" not in txt and "1." in txt


def test_rm_reset_passes_content_through():
    txt = _alltext(r"\begin{document}x {\rm plain} y\end{document}")
    assert "plain" in txt and r"\rm" not in txt
