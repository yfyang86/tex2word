"""LibreOffice render smoke for CJK: the generated .docx really renders Chinese.

This complements the structural checks in ``test_cjk_context.py`` by driving a
real LibreOffice (docx -> PDF) and confirming the Chinese text is extractable
from the render. It is gated:

* skipped if ``pypdfium2`` (the ``pdf`` extra) is not installed;
* skipped if no ``soffice``/``libreoffice`` is on PATH;
* skipped if soffice is present but produces no PDF (e.g. a broken sandbox).

The CI ``cjk-render`` lane installs LibreOffice + ``fonts-wqy-zenhei`` so this
actually runs there.
"""

from __future__ import annotations

import pytest

from tex2word import convert_source
from tex2word.render_check import check_docx, find_soffice

pytest.importorskip("pypdfium2")  # the `pdf` extra backend (PDFium)

CJK_SRC = (
    r"\documentclass{article}"
    r"\usepackage{xeCJK}"
    r"\setCJKmainfont{WenQuanYi Zen Hei}"
    r"\setCJKsansfont{WenQuanYi Zen Hei}"
    r"\begin{document}"
    r"测试中文字体。"
    r"\section{中文标题}"
    r"\begin{table}\caption{表格标题}"
    r"\begin{tabular}{ll}\hline 姓名 & 年龄 \\ 张三 & 25 \\\hline\end{tabular}\end{table}"
    r"公式：$E=mc^2$ 与 $\sum_{i=1}^{n} x_i = \text{总和}$。"
    r"\end{document}"
)


def test_cjk_docx_renders_chinese(tmp_path):
    if find_soffice() is None:
        pytest.skip("no LibreOffice/soffice on PATH")
    docx_path = tmp_path / "zh.docx"
    docx_path.write_bytes(convert_source(CJK_SRC).docx)
    # We assert the reliably text-extractable contexts (prose, heading, table).
    # CJK *inside math* (\text{总和}) is not checked here: OMML math is rendered as
    # a formula object whose text LibreOffice does not place in the PDF text layer,
    # and the math run doesn't carry the eastAsia font. That CJK-in-math content is
    # verified structurally (in m:t) by test_cjk_context.py instead.
    problems = check_docx(
        docx_path,
        expect=["测试中文字体", "中文标题", "表格标题", "姓名", "张三"],
    )
    if problems is None:
        pytest.skip("LibreOffice present but could not render in this environment")
    assert problems == []
