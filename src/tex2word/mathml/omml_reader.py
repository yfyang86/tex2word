"""OMML -> LaTeX (round-trip math reader, SPRINT-V3 A2/M2).

Parses an ``m:oMath`` element back into the math AST (reusing
:mod:`tex2word.mathml.latex_math`) and serialises that AST to LaTeX. This is
the inverse of :mod:`tex2word.mathml.omml` and covers the constructs that
writer emits, so a forward+reverse pass round-trips the common math core.
"""

from __future__ import annotations

from lxml import etree

from ..backend.ooxml import NS
from . import latex_math as L
from . import symbols as S

_M = NS["m"]


def _tag(e: etree._Element) -> str:
    return etree.QName(e).localname


def _mq(name: str) -> str:
    return f"{{{_M}}}{name}"


# --------------------------------------------------------------------------- #
# Reverse symbol tables (unicode glyph -> LaTeX command), first definition wins
# --------------------------------------------------------------------------- #


def _reverse(table: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for cmd, glyph in table.items():
        out.setdefault(glyph, cmd)
    return out


_REV_SYMBOL = _reverse(S.SYMBOLS)
_REV_NARY = _reverse(S.NARY)
_REV_ACCENT = _reverse(S.ACCENTS)


# --------------------------------------------------------------------------- #
# OMML element -> math AST
# --------------------------------------------------------------------------- #


def _children_to_row(parent: etree._Element | None) -> L.Row:
    items: list[L.MNode] = []
    if parent is not None:
        for child in parent:
            node = _parse(child)
            if node is not None:
                items.append(node)
    return L.Row(items)


def _flat(parent: etree._Element | None) -> L.MNode:
    row = _children_to_row(parent)
    return row.items[0] if len(row.items) == 1 else L.Group(row)


def _find(e: etree._Element, name: str) -> etree._Element | None:
    return e.find(_mq(name))


def _chr_val(pr: etree._Element | None, name: str, default: str = "") -> str:
    if pr is None:
        return default
    el = pr.find(_mq(name))
    return el.get(f"{{{_M}}}val", default) if el is not None else default


def _parse(e: etree._Element) -> L.MNode | None:  # noqa: C901
    tag = _tag(e)
    if tag == "r":
        return _parse_run(e)
    if tag == "f":
        return L.Frac(_children_to_row(_find(e, "num")), _children_to_row(_find(e, "den")))
    if tag == "sSup":
        return L.Sup(_flat(_find(e, "e")), _flat(_find(e, "sup")))
    if tag == "sSub":
        return L.Sub(_flat(_find(e, "e")), _flat(_find(e, "sub")))
    if tag == "sSubSup":
        return L.SubSup(_flat(_find(e, "e")), _flat(_find(e, "sub")), _flat(_find(e, "sup")))
    if tag == "rad":
        pr = _find(e, "radPr")
        deg_hidden = _chr_val(pr, "degHide") == "1" if pr is not None else False
        deg = _find(e, "deg")
        if deg_hidden or deg is None or len(deg) == 0:
            return L.Sqrt(_children_to_row(_find(e, "e")))
        return L.Root(_children_to_row(deg), _children_to_row(_find(e, "e")))
    if tag == "nary":
        pr = _find(e, "naryPr")
        op = _chr_val(pr, "chr", "∫")
        sub_el, sup_el = _find(e, "sub"), _find(e, "sup")
        body = _find(e, "e")
        node = L.Nary(op)
        node.sub = _flat(sub_el) if sub_el is not None and len(sub_el) else None
        node.sup = _flat(sup_el) if sup_el is not None and len(sup_el) else None
        node.body = _flat(body) if body is not None and len(body) else None
        return node
    if tag == "acc":
        return L.Accent(_children_to_row(_find(e, "e")), _chr_val(_find(e, "accPr"), "chr", "̂"))
    if tag == "d":
        pr = _find(e, "dPr")
        return L.Fenced(_chr_val(pr, "begChr", "("), _chr_val(pr, "endChr", ")"),
                        _children_to_row(_find(e, "e")))
    if tag == "limLow":
        return L.LimLow(_flat(_find(e, "e")), _flat(_find(e, "lim")))
    if tag == "groupChr":
        pr = _find(e, "groupChrPr")
        return L.GroupChr(_children_to_row(_find(e, "e")),
                          _chr_val(pr, "chr", "⏞"), _chr_val(pr, "pos", "top"))
    if tag == "m":
        rows = [[_children_to_row(cell) for cell in mr.findall(_mq("e"))]
                for mr in e.findall(_mq("mr"))]
        return L.Matrix(rows)
    if tag in ("oMath", "oMathPara"):
        return L.Group(_children_to_row(e))
    return None


def _parse_run(e: etree._Element) -> L.Lit:
    t = e.find(_mq("t"))
    text = t.text if t is not None and t.text is not None else ""
    rpr = e.find(_mq("rPr"))
    upright = rpr is not None and rpr.find(_mq("nor")) is not None
    script = None
    bold = False
    if rpr is not None:
        scr = rpr.find(_mq("scr"))
        if scr is not None:
            script = scr.get(f"{{{_M}}}val")
        sty = rpr.find(_mq("sty"))
        if sty is not None and sty.get(f"{{{_M}}}val") in ("b", "bi"):
            bold = True
    return L.Lit(text, upright=upright, bold=bold, script=script)


# --------------------------------------------------------------------------- #
# math AST -> LaTeX
# --------------------------------------------------------------------------- #


def _glyphs_to_latex(text: str) -> str:
    out: list[str] = []
    for ch in text:
        out.append(f"\\{_REV_SYMBOL[ch]} " if ch in _REV_SYMBOL else ch)
    return "".join(out)


_SCRIPT_CMD = {"double-struck": "mathbb", "script": "mathcal", "fraktur": "mathfrak",
               "sans-serif": "mathsf", "monospace": "mathtt"}


def _lit_latex(lit: L.Lit) -> str:
    text = lit.text
    if not text:
        return ""
    if lit.script in _SCRIPT_CMD:
        return f"\\{_SCRIPT_CMD[lit.script]}{{{text}}}"
    # genuine multi-letter upright text -> a function name or \mathrm{...}
    if lit.upright and len(text) > 1 and text.isalpha():
        if text in S.FUNCTIONS:
            return f"\\{text} "
        return f"\\mathrm{{{text}}}"
    # numbers, operators, single letters, symbol glyphs: reverse-map symbols,
    # keep the rest as-is (they are naturally upright in math mode).
    body = _glyphs_to_latex(text)
    if lit.bold:
        return f"\\mathbf{{{body}}}"
    return body


def _arg(node: L.MNode) -> str:
    """A braced argument for sub/sup/frac/etc."""
    return f"{{{ast_to_latex(node)}}}"


def ast_to_latex(node: L.MNode) -> str:  # noqa: C901
    if isinstance(node, L.Lit):
        return _lit_latex(node)
    if isinstance(node, L.Row):
        return "".join(ast_to_latex(i) for i in node.items)
    if isinstance(node, L.Group):
        return ast_to_latex(node.row)
    if isinstance(node, L.Frac):
        return f"\\frac{{{ast_to_latex(node.num)}}}{{{ast_to_latex(node.den)}}}"
    if isinstance(node, L.Sup):
        return f"{_arg(node.base)}^{_arg(node.sup)}"
    if isinstance(node, L.Sub):
        return f"{_arg(node.base)}_{_arg(node.sub)}"
    if isinstance(node, L.SubSup):
        return f"{_arg(node.base)}_{_arg(node.sub)}^{_arg(node.sup)}"
    if isinstance(node, L.Sqrt):
        return f"\\sqrt{{{ast_to_latex(node.radicand)}}}"
    if isinstance(node, L.Root):
        return f"\\sqrt[{ast_to_latex(node.index)}]{{{ast_to_latex(node.radicand)}}}"
    if isinstance(node, L.Nary):
        op = "\\" + _REV_NARY.get(node.op, "int") + " "
        if node.sub is not None:
            op += f"_{_arg(node.sub)}"
        if node.sup is not None:
            op += f"^{_arg(node.sup)}"
        if node.body is not None:
            op += " " + ast_to_latex(node.body)
        return op
    if isinstance(node, L.Accent):
        cmd = _REV_ACCENT.get(node.char, "hat")
        return f"\\{cmd}{{{ast_to_latex(node.base)}}}"
    if isinstance(node, L.Fenced):
        op = node.open or "."
        cl = node.close or "."
        return f"\\left{_delim(op)} {ast_to_latex(node.body)} \\right{_delim(cl)}"
    if isinstance(node, L.LimLow):
        return f"{ast_to_latex(node.base)}_{_arg(node.lim)}"
    if isinstance(node, L.GroupChr):
        cmd = "overbrace" if node.pos == "top" else "underbrace"
        return f"\\{cmd}{{{ast_to_latex(node.body)}}}"
    if isinstance(node, L.Matrix):
        rows = " \\\\ ".join(" & ".join(ast_to_latex(c) for c in row) for row in node.rows)
        return f"\\begin{{matrix}} {rows} \\end{{matrix}}"
    return ""


_REV_DELIM = _reverse(S.SYMBOLS)


def _delim(ch: str) -> str:
    if ch in "()[]|/.":
        return ch
    if ch in ("{", "}"):
        return "\\" + ch
    return "\\" + _REV_SYMBOL.get(ch, ch)


def omath_to_latex(element: etree._Element) -> str:
    """Convert an ``m:oMath`` element to a LaTeX math string."""
    return ast_to_latex(_children_to_row(element)).strip()
