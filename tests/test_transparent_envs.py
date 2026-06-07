"""Quality: known structural wrappers pass through without a warning."""

from __future__ import annotations

from tex2word import convert_source
from tex2word.validate import validate_docx


def _conv(src: str):
    return convert_source(r"\begin{document}" + src + r"\end{document}")


def test_subequations_no_warning_keeps_math():
    res = _conv(r"\begin{subequations}\begin{align} a &= b \\ c &= d \end{align}\end{subequations}")
    assert validate_docx(res.docx) == []
    assert not any("subequations" in (w.message or "") for w in res.report.warnings)
    assert any(type(b).__name__ == "MathBlock" for b in res.document.blocks)


def test_samepage_passthrough_no_warning():
    res = _conv(r"\begin{samepage}Kept together.\end{samepage}")
    assert not any("samepage" in (w.message or "") for w in res.report.warnings)
    paras = [b for b in res.document.blocks if type(b).__name__ == "Paragraph"]
    assert paras and "Kept together." in "".join(
        getattr(x, "value", "") for x in paras[0].inlines
    )


def test_truly_unknown_env_still_warns():
    res = _conv(r"\begin{reallymadeup}content\end{reallymadeup}")
    assert any("reallymadeup" in (w.message or "") for w in res.report.warnings)
