"""Layout / front-matter commands and \\text outside math should not leak.

Real documents sprinkle grouping and shipout commands in the body (cover pages
via ``\\AddToShipoutPicture{\\put...}``, ``\\begingroup``/``\\endgroup``,
``\\newcounter``) and use ``\\text``/``\\mbox`` outside math. Left unspecced,
pylatexenc leaked the macro name and its arguments as literal text.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from tex2word import convert_source

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _text(src: str) -> str:
    root = etree.fromstring(
        zipfile.ZipFile(io.BytesIO(convert_source(src).docx)).read("word/document.xml")
    )
    return "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))


def test_text_outside_math_renders_its_argument():
    out = _text(r"\begin{document}周报表(\text{bills of mortality})说。\end{document}")
    assert "bills of mortality" in out and r"\text" not in out


def test_mbox_outside_math_renders_its_argument():
    out = _text(r"\begin{document}见 \mbox{参数真值} 。\end{document}")
    assert "参数真值" in out and r"\mbox" not in out


def test_begingroup_endgroup_dropped():
    out = _text(r"\begin{document}\begingroup A 文字 \endgroup B\end{document}")
    assert "A 文字" in out and "B" in out
    assert r"\begingroup" not in out and r"\endgroup" not in out


def test_addtoshipoutpicture_cover_dropped():
    src = (
        r"\begin{document}"
        r"\AddToShipoutPicture*{\put(0,0){\includegraphics[width=\paperwidth]{cover.png}}}"
        r"正文内容。\end{document}"
    )
    out = _text(src)
    assert "正文内容" in out
    for tok in (r"\AddToShipoutPicture", r"\put", r"\includegraphics", "cover.png"):
        assert tok not in out


def test_newcounter_dropped_with_optional_arg():
    out = _text(r"\begin{document}\newcounter{ExCnt}[section]正文。\end{document}")
    assert "正文" in out
    assert r"\newcounter" not in out and "ExCnt" not in out and "section" not in out
