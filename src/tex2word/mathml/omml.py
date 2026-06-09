"""math AST -> OMML (Office MathML) lxml elements.

This is the *direct* LaTeX->OMML path (texmath-style), the primary and only V1
math route. Output lives under the ``m:`` namespace and is embedded as native
math runs in ``document.xml`` -- editable in Word's equation editor, never an
image or an HTML AltChunk.
"""

from __future__ import annotations

import re

from lxml import etree

from ..backend.ooxml import el, preserve_space, qn, sub
from . import latex_math as L
from .latex_math import MathUnsupported

_Element = etree._Element

# strip equation-numbering / label noise before parsing a math line
_LABEL_RE = re.compile(r"\\(?:label|tag|nonumber|notag)\b\s*(?:\{[^{}]*\})?")

# CJK ranges: Unified Ideographs (+ext A), compat ideographs, kana, Hangul, and
# the CJK symbols/punctuation block (（）。… used inside \text{...}).
_CJK_RE = re.compile(
    r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]"
)


def tag_cjk_runs(root: _Element, east_asia_font: str) -> None:
    """Set an East-Asian font on math text runs (``m:r``) whose ``m:t`` holds CJK.

    OMML math runs otherwise inherit the math font (Cambria Math), so CJK inside
    ``\\text{...}`` renders with a fallback. Adding ``w:rFonts w:eastAsia`` makes
    Word use the document's CJK font for those glyphs. The ``w:rPr`` is inserted
    before ``m:t`` (after the optional ``m:rPr``), per the CT_R element order."""
    m_t, m_r = qn("m:t"), qn("m:r")
    w_rpr, w_rfonts = qn("w:rPr"), qn("w:rFonts")
    for t in list(root.iter(m_t)):
        if not (t.text and _CJK_RE.search(t.text)):
            continue
        r = t.getparent()
        if r is None or r.tag != m_r:
            continue
        wrpr = r.find(w_rpr)
        if wrpr is None:
            wrpr = el("w:rPr")
            r.insert(list(r).index(t), wrpr)  # before m:t, after any m:rPr
        rfonts = wrpr.find(w_rfonts)
        if rfonts is None:
            rfonts = el("w:rFonts")
            wrpr.insert(0, rfonts)  # rFonts is first in CT_RPr
        rfonts.set(qn("w:eastAsia"), east_asia_font)


# --------------------------------------------------------------------------- #
# Leaf runs
# --------------------------------------------------------------------------- #


def _run(
    text: str, *, upright: bool = False, bold: bool = False, script: str | None = None
) -> _Element:
    r = el("m:r")
    if upright or bold or script:
        rpr = sub(r, "m:rPr")
        if upright:
            sub(rpr, "m:nor")
        if script:
            sub(rpr, "m:scr", **{"m:val": script})
        if bold:
            sub(rpr, "m:sty", **{"m:val": "b"})
        elif script:
            sub(rpr, "m:sty", **{"m:val": "p"})
    t = sub(r, "m:t")
    t.text = text
    preserve_space(t)
    return r


# --------------------------------------------------------------------------- #
# Node emission
# --------------------------------------------------------------------------- #


def _emit(node: L.MNode) -> list[_Element]:
    """Render a node to a list of sibling OMML elements."""
    if isinstance(node, L.Lit):
        if node.text == "":
            return []
        return [_run(node.text, upright=node.upright, bold=node.bold, script=node.script)]
    if isinstance(node, L.Row):
        out: list[_Element] = []
        for item in node.items:
            out.extend(_emit(item))
        return out
    if isinstance(node, L.Group):
        return _emit(node.row)
    return [_emit_single(node)]


def _fill(tag: str, node: L.MNode | None) -> _Element:
    """Create an OMML container element filled with the rendered node."""
    container = el(tag)
    if node is not None:
        for child in _emit(node):
            container.append(child)
    return container


def _emit_single(node: L.MNode) -> _Element:  # noqa: C901 - structural dispatch
    if isinstance(node, L.Frac):
        f = el("m:f")
        f.append(_fill("m:num", node.num))
        f.append(_fill("m:den", node.den))
        return f

    if isinstance(node, L.Sup):
        e = el("m:sSup")
        e.append(_fill("m:e", node.base))
        e.append(_fill("m:sup", node.sup))
        return e

    if isinstance(node, L.Sub):
        e = el("m:sSub")
        e.append(_fill("m:e", node.base))
        e.append(_fill("m:sub", node.sub))
        return e

    if isinstance(node, L.SubSup):
        e = el("m:sSubSup")
        e.append(_fill("m:e", node.base))
        e.append(_fill("m:sub", node.sub))
        e.append(_fill("m:sup", node.sup))
        return e

    if isinstance(node, L.Sqrt):
        r = el("m:rad")
        rpr = sub(r, "m:radPr")
        sub(rpr, "m:degHide", **{"m:val": "1"})
        r.append(_fill("m:deg", None))
        r.append(_fill("m:e", node.radicand))
        return r

    if isinstance(node, L.Root):
        r = el("m:rad")
        r.append(_fill("m:deg", node.index))
        r.append(_fill("m:e", node.radicand))
        return r

    if isinstance(node, L.Nary):
        n = el("m:nary")
        npr = sub(n, "m:naryPr")
        sub(npr, "m:chr", **{"m:val": node.op})
        sub(npr, "m:limLoc", **{"m:val": node.limloc})
        if node.sub is None:
            sub(npr, "m:subHide", **{"m:val": "1"})
        if node.sup is None:
            sub(npr, "m:supHide", **{"m:val": "1"})
        n.append(_fill("m:sub", node.sub))
        n.append(_fill("m:sup", node.sup))
        n.append(_fill("m:e", node.body))
        return n

    if isinstance(node, L.Accent):
        a = el("m:acc")
        apr = sub(a, "m:accPr")
        sub(apr, "m:chr", **{"m:val": node.char})
        a.append(_fill("m:e", node.base))
        return a

    if isinstance(node, L.Fenced):
        d = el("m:d")
        dpr = sub(d, "m:dPr")
        sub(dpr, "m:begChr", **{"m:val": node.open})
        sub(dpr, "m:endChr", **{"m:val": node.close})
        d.append(_fill("m:e", node.body))
        return d

    if isinstance(node, L.LimLow):
        ll = el("m:limLow")
        ll.append(_fill("m:e", node.base))
        ll.append(_fill("m:lim", node.lim))
        return ll

    if isinstance(node, L.GroupChr):
        g = el("m:groupChr")
        gpr = sub(g, "m:groupChrPr")
        sub(gpr, "m:chr", **{"m:val": node.char})
        sub(gpr, "m:pos", **{"m:val": node.pos})
        sub(gpr, "m:vertJc", **{"m:val": "bot" if node.pos == "top" else "top"})
        g.append(_fill("m:e", node.body))
        return g

    if isinstance(node, L.Matrix):
        m = el("m:m")
        if node.aligned and node.rows:
            _add_alignment_mcs(m, max(len(r) for r in node.rows))
        for row in node.rows:
            mr = sub(m, "m:mr")
            for cell in row:
                mr.append(_fill("m:e", cell))
        return m

    # Lit/Row/Group are handled by _emit; reaching here is a bug.
    raise MathUnsupported(type(node).__name__)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _omath(row: L.Row) -> _Element:
    o = el("m:oMath")
    for child in _emit(row):
        o.append(child)
    return o


def render_inline(latex: str) -> _Element:
    """Render inline math to a single ``m:oMath`` element. May raise."""
    row = L.parse(_LABEL_RE.sub("", latex).strip())
    return _omath(row)


def _split_top_level(latex: str, sep: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    env = 0  # \begin..\end nesting: a separator inside an environment isn't top-level
    i, n = 0, len(latex)
    buf: list[str] = []
    while i < n:
        if latex.startswith("\\begin", i) and not latex[i + 6 : i + 7].isalpha():
            env += 1
            buf.append(latex[i : i + 6])
            i += 6
            continue
        if latex.startswith("\\end", i) and not latex[i + 4 : i + 5].isalpha():
            env = max(0, env - 1)
            buf.append(latex[i : i + 4])
            i += 4
            continue
        c = latex[i]
        if c == "{":
            depth += 1
            buf.append(c)
        elif c == "}":
            depth -= 1
            buf.append(c)
        elif depth == 0 and env == 0 and latex.startswith(sep, i):
            parts.append("".join(buf))
            buf = []
            i += len(sep)
            continue
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _strip_align_markers(line: str) -> str:
    """Remove top-level ``&`` alignment markers from an align/aligned line.

    A ``&`` inside a ``\\begin``…``\\end`` environment (e.g. a wrapped ``aligned``
    or a nested ``array``) belongs to that environment's own column parsing and
    must be left intact, so we skip markers while inside one."""
    out: list[str] = []
    depth = 0
    env = 0
    i, n = 0, len(line)
    while i < n:
        if line.startswith("\\begin", i) and not line[i + 6 : i + 7].isalpha():
            env += 1
            out.append(line[i : i + 6])
            i += 6
            continue
        if line.startswith("\\end", i) and not line[i + 4 : i + 5].isalpha():
            env = max(0, env - 1)
            out.append(line[i : i + 4])
            i += 4
            continue
        c = line[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == "&" and depth == 0 and env == 0:
            out.append(" ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _has_top_amp(line: str) -> bool:
    """True if ``line`` has a top-level ``&`` alignment marker (outside ``{}`` and
    outside any ``\\begin``…``\\end`` environment, e.g. a nested ``array``)."""
    depth = 0
    env = 0
    i, n = 0, len(line)
    while i < n:
        if line.startswith("\\begin", i) and not line[i + 6 : i + 7].isalpha():
            env += 1
            i += 6
            continue
        if line.startswith("\\end", i) and not line[i + 4 : i + 5].isalpha():
            env = max(0, env - 1)
            i += 4
            continue
        c = line[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "&" and depth == 0 and env == 0:
            return True
        i += 1
    return False


def _add_alignment_mcs(m: _Element, ncols: int) -> None:
    """Add ``m:mPr/m:mcs`` column properties giving the classic ``array{rl}`` look
    (right | left | right | …), so relation signs line up at the ``&``."""
    mpr = sub(m, "m:mPr")
    mcs = sub(mpr, "m:mcs")
    for i in range(ncols):
        mcpr = sub(sub(mcs, "m:mc"), "m:mcPr")
        sub(mcpr, "m:count", **{"m:val": "1"})
        sub(mcpr, "m:mcJc", **{"m:val": "right" if i % 2 == 0 else "left"})


def _aligned_matrix(lines: list[str]) -> _Element:
    """Render ``&``-aligned lines as one ``m:oMath`` holding a column-justified
    matrix (the classic ``array{rl}`` look: right | left | right | …), so the
    relation signs line up at the ``&``."""
    rows = [[c.strip() for c in _split_top_level(line, "&")] for line in lines]
    ncols = max(len(r) for r in rows)
    m = el("m:m")
    _add_alignment_mcs(m, ncols)
    for cells in rows:
        mr = sub(m, "m:mr")
        for i in range(ncols):
            cell = cells[i] if i < len(cells) else ""
            mr.append(_fill("m:e", L.parse(cell) if cell else None))
    o = el("m:oMath")
    o.append(m)
    return o


def render_block_lines(latex: str, collapse_align: bool = True) -> list[_Element]:
    """Render display math (possibly multi-line) to a list of ``m:oMath``.

    Each ``\\\\``-separated line becomes its own ``m:oMath`` so the writer can
    stack them in ``m:oMathPara`` paragraphs. With ``collapse_align`` (the
    default), a block whose lines carry ``&`` markers is instead rendered as a
    *single* column-aligned matrix so the equations line up at the ``&`` — used
    for ``align*``/``aligned`` and single-numbered ``equation`` blocks. Callers
    that need per-line numbering (top-level numbered ``align``) pass
    ``collapse_align=False``.
    """
    cleaned = _LABEL_RE.sub("", latex).strip()
    lines = [s.strip() for s in _split_top_level(cleaned, "\\\\")]
    lines = [line for line in lines if line]
    if not lines:
        raise MathUnsupported("empty", "no math content")
    if collapse_align and any(_has_top_amp(line) for line in lines):
        return [_aligned_matrix(lines)]
    return [_omath(L.parse(_strip_align_markers(line).strip())) for line in lines]


# Back-compat alias used by the package __init__.
def latex_to_omml(latex: str, display: bool = False) -> _Element:
    if display:
        lines = render_block_lines(latex)
        para = el("m:oMathPara")
        for line in lines:
            para.append(line)
        return para
    return render_inline(latex)
