"""CJK in context: Chinese text inside tables, formulas, headings, lists, etc.

These are structural checks (they run anywhere): the CJK text must survive into
the right OOXML place (table cells, math ``m:t``, headings, …) and the document
must stay schema-valid with the CJK font applied. A separate LibreOffice render
smoke lives in ``test_cjk_render.py``.
"""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.validate import validate_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

PREAMBLE = (
    r"\documentclass{article}"
    r"\usepackage{xeCJK}"
    r"\setCJKmainfont{WenQuanYi Zen Hei}"
    r"\setCJKsansfont{WenQuanYi Zen Hei}"
)


def _doc(src: str):
    from lxml import etree

    docx = convert_source(PREAMBLE + r"\begin{document}" + src + r"\end{document}").docx
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    return docx, root


def _texts(el, tag: str, ns: str) -> list[str]:
    """Joined text per element of ``{ns}tag`` (e.g. table cells, oMath blocks)."""
    out = []
    for node in el.iter(f"{{{ns}}}{tag}"):
        out.append("".join(t.text or "" for t in node.iter(f"{{{ns}}}t")))
    return [t for t in out if t.strip()]


# -- tables ------------------------------------------------------------------ #

def test_chinese_in_table_cells():
    _, root = _doc(
        r"\begin{tabular}{ll}\hline 姓名 & 年龄 \\ 张三 & 25 \\\hline\end{tabular}"
    )
    cells = _texts(root, "tc", W)
    assert "姓名" in cells and "年龄" in cells and "张三" in cells


def test_chinese_table_caption():
    docx, root = _doc(
        r"\begin{table}\caption{中文表格标题}"
        r"\begin{tabular}{l}\hline 数据 \\\hline\end{tabular}\end{table}"
    )
    body_text = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))
    assert "中文表格标题" in body_text and "数据" in body_text


def test_chinese_multicolumn_cell():
    _, root = _doc(
        r"\begin{tabular}{ll}\hline \multicolumn{2}{c}{合并单元格} \\ 甲 & 乙 \\\hline\end{tabular}"
    )
    cells = _texts(root, "tc", W)
    assert "合并单元格" in cells


# -- formulas ---------------------------------------------------------------- #

def test_chinese_in_inline_math_text():
    _, root = _doc(r"能量 $E = mc^2 \text{（能量）}$ 公式。")
    math = _texts(root, "oMath", M)
    assert any("（能量）" in m for m in math)


def test_chinese_in_display_math():
    _, root = _doc(r"\[ \sum_{i=1}^{n} x_i = \text{总和} \]")
    math = _texts(root, "oMath", M)
    assert any("总和" in m for m in math)


def test_chinese_mbox_in_math():
    _, root = _doc(r"$a + b = c \mbox{（其中 c 为和）}$")
    math = _texts(root, "oMath", M)
    assert any("其中" in m for m in math)


# -- other contexts ---------------------------------------------------------- #

def test_chinese_section_heading():
    docx, root = _doc(r"\section{中文标题}正文内容。")
    body_text = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))
    assert "中文标题" in body_text


def test_chinese_in_lists():
    _, root = _doc(r"\begin{itemize}\item 第一项\item 第二项\end{itemize}")
    body_text = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))
    assert "第一项" in body_text and "第二项" in body_text


def test_chinese_in_footnote():
    docx, _ = _doc(r"正文\footnote{这是脚注}。")
    fn = zipfile.ZipFile(io.BytesIO(docx)).read("word/footnotes.xml").decode()
    assert "这是脚注" in fn


def test_mixed_chinese_latin_and_math_paragraph():
    _, root = _doc(r"This 是 a mixed 段落 with math $x^2$ 和中文。")
    body_text = "".join(t.text or "" for t in root.iter(f"{{{W}}}t"))
    assert "是" in body_text and "mixed" in body_text and "和中文" in body_text


# -- whole-document integration --------------------------------------------- #

_RICH = (
    r"\section{中文标题}"
    r"段落里有中文与公式 $E=mc^2$。"
    r"\begin{table}\caption{表格}"
    r"\begin{tabular}{ll}\hline 姓名 & 年龄 \\ 张三 & 25 \\\hline\end{tabular}\end{table}"
    r"\begin{itemize}\item 列表项\end{itemize}"
    r"\[ \int_0^1 f(x)\,dx = \text{积分} \]"
)


def test_rich_cjk_document_is_valid():
    docx, _ = _doc(_RICH)
    assert validate_docx(docx) == []


def test_rich_cjk_document_applies_eastasia_font():
    docx, _ = _doc(_RICH)
    styles = zipfile.ZipFile(io.BytesIO(docx)).read("word/styles.xml").decode()
    assert 'w:eastAsia="WenQuanYi Zen Hei"' in styles
