"""Presentation MathML -> OMML (the cascade's secondary math path, A3).

When the direct LaTeX->OMML writer can't parse a construct, the cascade converts
LaTeX -> presentation MathML (via the optional ``latex2mathml`` dependency) and
maps that MathML to OMML here -- reusing the OMML element builders. This lifts
the math-coverage ceiling for the hard 20% (e.g. ``\\overset``, ``\\xrightarrow``,
``\\genfrac``) the direct writer rejects, keeping them editable rather than raw.
"""

from __future__ import annotations

from lxml import etree

from ..backend.ooxml import el, preserve_space, sub

_MML = "http://www.w3.org/1998/Math/MathML"
_Element = etree._Element

# MathML wrappers that carry no layout of their own -> process children inline.
_TRANSPARENT = {"mrow", "mstyle", "mpadded", "mphantom", "menclose", "merror", "semantics"}


def _localname(e: _Element) -> str:
    return etree.QName(e).localname


def _run(text: str, *, upright: bool = False) -> _Element:
    r = el("m:r")
    if upright:
        sub(sub(r, "m:rPr"), "m:nor")
    t = sub(r, "m:t")
    t.text = text
    preserve_space(t)
    return r


def _box(tag: str, e: _Element | None) -> _Element:
    container = el(tag)
    if e is not None:
        _emit(e, container)
    return container


def _children(e: _Element) -> list[_Element]:
    return [c for c in e if isinstance(c.tag, str)]


def _emit(e: _Element, parent: _Element) -> None:  # noqa: C901
    tag = _localname(e)
    text = (e.text or "").strip()

    if tag in _TRANSPARENT:
        for c in _children(e):
            _emit(c, parent)
        return
    if tag in ("mi", "mn", "mo", "mtext", "ms"):
        # numbers/operators/text/multi-letter identifiers are upright
        upright = tag in ("mn", "mo", "mtext", "ms") or (tag == "mi" and len(text) > 1)
        if text:
            parent.append(_run(text, upright=upright))
        return
    if tag == "mspace":
        parent.append(_run(" "))
        return

    kids = _children(e)
    if tag == "mfrac":
        f = el("m:f")
        if e.get("linethickness") in ("0", "0pt", "0em"):  # \binom-style, no bar
            sub(sub(f, "m:fPr"), "m:type", **{"m:val": "noBar"})
        f.append(_box("m:num", kids[0] if kids else None))
        f.append(_box("m:den", kids[1] if len(kids) > 1 else None))
        parent.append(f)
        return
    if tag == "msup" and len(kids) >= 2:
        s = el("m:sSup")
        s.append(_box("m:e", kids[0]))
        s.append(_box("m:sup", kids[1]))
        parent.append(s)
        return
    if tag == "msub" and len(kids) >= 2:
        s = el("m:sSub")
        s.append(_box("m:e", kids[0]))
        s.append(_box("m:sub", kids[1]))
        parent.append(s)
        return
    if tag == "msubsup" and len(kids) >= 3:
        s = el("m:sSubSup")
        s.append(_box("m:e", kids[0]))
        s.append(_box("m:sub", kids[1]))
        s.append(_box("m:sup", kids[2]))
        parent.append(s)
        return
    if tag == "msqrt":
        rad = el("m:rad")
        sub(sub(rad, "m:radPr"), "m:degHide", **{"m:val": "1"})
        rad.append(_box("m:deg", None))
        e_box = _box("m:e", None)
        for c in kids:
            _emit(c, e_box)
        rad.append(e_box)
        parent.append(rad)
        return
    if tag == "mroot" and len(kids) >= 2:
        rad = el("m:rad")
        rad.append(_box("m:deg", kids[1]))
        rad.append(_box("m:e", kids[0]))
        parent.append(rad)
        return
    if tag == "mover" and len(kids) >= 2:
        ll = el("m:limUpp")
        ll.append(_box("m:e", kids[0]))
        ll.append(_box("m:lim", kids[1]))
        parent.append(ll)
        return
    if tag == "munder" and len(kids) >= 2:
        ll = el("m:limLow")
        ll.append(_box("m:e", kids[0]))
        ll.append(_box("m:lim", kids[1]))
        parent.append(ll)
        return
    if tag == "munderover" and len(kids) >= 3:
        low = el("m:limLow")
        low.append(_box("m:e", kids[0]))
        low.append(_box("m:lim", kids[1]))
        upp = el("m:limUpp")
        upp.append(_wrap(low))
        upp.append(_box("m:lim", kids[2]))
        parent.append(upp)
        return
    if tag == "mfenced":
        d = el("m:d")
        dpr = sub(d, "m:dPr")
        sub(dpr, "m:begChr", **{"m:val": e.get("open", "(")})
        sub(dpr, "m:endChr", **{"m:val": e.get("close", ")")})
        box = _box("m:e", None)
        for c in kids:
            _emit(c, box)
        d.append(box)
        parent.append(d)
        return
    if tag in ("mtable", "mtr", "mtd"):
        if tag == "mtable":
            m = el("m:m")
            for row in [c for c in kids if _localname(c) == "mtr"]:
                mr = sub(m, "m:mr")
                for cell in [c for c in _children(row) if _localname(c) == "mtd"]:
                    mr.append(_box("m:e", cell))
            parent.append(m)
        return

    # unknown element: recurse over its children (graceful)
    for c in kids:
        _emit(c, parent)
    if not kids and text:
        parent.append(_run(text))


def _wrap(child: _Element) -> _Element:
    box = el("m:e")
    box.append(child)
    return box


def mathml_to_omath(math: _Element) -> _Element:
    """Convert a presentation-MathML ``<math>`` element to an ``m:oMath``."""
    o = el("m:oMath")
    for child in _children(math):
        _emit(child, o)
    return o


def latex_via_mathml(latex: str) -> _Element | None:
    """LaTeX -> presentation MathML -> OMML; ``None`` if unavailable/failed."""
    try:
        import latex2mathml.converter as converter
    except Exception:
        return None
    try:
        mml = converter.convert(latex)
        math = etree.fromstring(mml.encode("utf-8"))
        return mathml_to_omath(math)
    except Exception:
        return None
