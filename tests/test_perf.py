"""V5-14: book-scale performance — a regression guard against pathological blowups."""

from __future__ import annotations

import time

from tex2word import convert_source
from tex2word.validate import validate_docx


def _book(n_sections: int) -> str:
    parts = [r"\begin{document}"]
    for i in range(n_sections):
        parts.append(rf"\section{{Section {i}}}\label{{sec:{i}}}")
        parts.append(
            rf"Body {i} with math $x_{{{i}}}^2 + {i}$ and \textbf{{bold}}, see \ref{{sec:{i}}}."
        )
        parts.append(r"\begin{equation}E_" + str(i) + r" = m c^2\end{equation}")
        parts.append(r"\begin{tabular}{ll}a & b\\ c & d\\\end{tabular}")
    parts.append(r"\end{document}")
    return "\n".join(parts)


def _timed(n: int) -> tuple[float, object]:
    src = _book(n)
    t0 = time.perf_counter()
    res = convert_source(src, embed_manifest=False)
    return time.perf_counter() - t0, res


def test_book_scale_converts_validly():
    dt, res = _timed(400)  # ~1600 blocks
    assert validate_docx(res.docx) == []
    assert len(res.report.errors) == 0
    headings = sum(1 for b in res.document.blocks if type(b).__name__ == "Heading")
    assert headings == 400
    assert dt < 30.0, f"book-scale conversion too slow: {dt:.1f}s"  # generous; catches O(n^2)


def test_conversion_does_not_blow_up_quadratically():
    t_small, _ = _timed(200)
    t_big, _ = _timed(400)
    # doubling the input must not quintuple the time (very loose; quadratic -> ~4x)
    assert t_big < t_small * 5 + 1.0, f"super-linear: {t_small:.2f}s -> {t_big:.2f}s"
