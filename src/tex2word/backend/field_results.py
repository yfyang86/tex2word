"""Compute the cached results of the fields tex2word writes.

Numbers in the document are live Word fields (``SEQ`` for figures, tables,
equations and theorems; ``STYLEREF`` for the section part of "2.1"; ``REF``
for cross-references). Word and LibreOffice recompute them, but Protected
View, previews, Google Docs import and text extractors show the cached
result, which used to be a placeholder ("1" for every number, "0" for every
reference).

This pass walks the finished XML in reading order, the way Word's field update
does:

1. it emulates list numbering from ``numbering.xml`` (headings and ordered
   lists), so ``STYLEREF`` and ``REF \\r`` know the paragraph numbers;
2. it counts ``SEQ`` fields (``\\s N`` resets at each heading of level <= N);
3. it records the text inside each bookmark (and its paragraph number);
4. it fills each ``REF`` result from the bookmark, in the body and in notes.

``PAGEREF`` results are left alone (page numbers need layout).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_w = f"{{{W}}}"
_HEADING_RE = re.compile(r"^Heading([1-9])$")


def _qn(tag: str) -> str:
    return _w + tag


# --------------------------------------------------------------------------- #
# list numbering
# --------------------------------------------------------------------------- #


class _Numbering:
    """Paragraph numbers from ``numbering.xml`` (decimal/letter/roman formats,
    ``%n`` level text, per-instance start overrides, deeper levels restarting)."""

    def __init__(self, numbering_xml: bytes) -> None:
        root = etree.fromstring(numbering_xml)
        self.levels: dict[str, dict[int, tuple[int, str, str]]] = {}
        for an in root.iter(_qn("abstractNum")):
            lv: dict[int, tuple[int, str, str]] = {}
            for lvl in an.iter(_qn("lvl")):
                ilvl = int(lvl.get(_qn("ilvl"), "0"))
                start = lvl.find(_qn("start"))
                fmt = lvl.find(_qn("numFmt"))
                text = lvl.find(_qn("lvlText"))
                lv[ilvl] = (
                    int(start.get(_qn("val"), "1")) if start is not None else 1,
                    fmt.get(_qn("val"), "decimal") if fmt is not None else "decimal",
                    text.get(_qn("val"), "") if text is not None else "",
                )
            self.levels[an.get(_qn("abstractNumId"), "")] = lv
        #: numId -> (abstractNumId, {ilvl: start override})
        self.nums: dict[str, tuple[str, dict[int, int]]] = {}
        for num in root.iter(_qn("num")):
            aid = num.find(_qn("abstractNumId"))
            overrides = {}
            for ov in num.iter(_qn("lvlOverride")):
                so = ov.find(_qn("startOverride"))
                if so is not None:
                    overrides[int(ov.get(_qn("ilvl"), "0"))] = int(so.get(_qn("val"), "1"))
            if aid is not None:
                self.nums[num.get(_qn("numId"), "")] = (aid.get(_qn("val"), ""), overrides)
        #: running counters per numId (Word counts each w:num instance)
        self.counters: dict[str, list[int | None]] = {}

    def advance(self, num_id: str, ilvl: int) -> tuple[str, str] | None:
        """Number the next paragraph of ``num_id`` at ``ilvl``; returns
        ``(full text, this level's own number)``, e.g. ``("2.1", "1")``."""
        if num_id not in self.nums:
            return None
        aid, overrides = self.nums[num_id]
        levels = self.levels.get(aid, {})
        counts = self.counters.setdefault(num_id, [None] * 9)
        start = overrides.get(ilvl, levels.get(ilvl, (1, "decimal", ""))[0])
        counts[ilvl] = start if counts[ilvl] is None else (counts[ilvl] or 0) + 1
        for deeper in range(ilvl + 1, 9):
            counts[deeper] = None
        for upper in range(ilvl):  # an unnumbered upper level counts as its start
            if counts[upper] is None:
                counts[upper] = levels.get(upper, (1, "decimal", ""))[0]
        _, fmt, text = levels.get(ilvl, (1, "decimal", f"%{ilvl + 1}"))
        if fmt in ("bullet", "none"):
            return None

        def sub(m: re.Match[str]) -> str:
            k = int(m.group(1)) - 1
            f = levels.get(k, (1, "decimal", ""))[1]
            return _format(counts[k] or 0, f)

        full = re.sub(r"%([1-9])", sub, text)
        return full, _format(counts[ilvl] or 0, fmt)


def _format(n: int, fmt: str) -> str:
    if fmt == "lowerLetter":
        return _letters(n).lower()
    if fmt == "upperLetter":
        return _letters(n)
    if fmt == "lowerRoman":
        return _roman(n).lower()
    if fmt == "upperRoman":
        return _roman(n)
    return str(n)


def _letters(n: int) -> str:
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out or "A"


def _roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out or "0"


# --------------------------------------------------------------------------- #
# fields
# --------------------------------------------------------------------------- #


class _Field:
    def __init__(self, code: str, result_t: etree._Element | None) -> None:
        self.code = code.strip()
        self.result_t = result_t
        parts = self.code.split()
        self.kind = parts[0].upper() if parts else ""
        self.args = parts[1:]


def _paragraph_fields(p: etree._Element) -> list[_Field]:
    """The complex fields of a paragraph, each with its first result ``w:t``."""
    out: list[_Field] = []
    state = None  # None | "code" | "result"
    code: list[str] = []
    result_t: etree._Element | None = None
    for el in p.iter(_qn("fldChar"), _qn("instrText"), _qn("t")):
        if el.tag == _qn("fldChar"):
            kind = el.get(_qn("fldCharType"))
            if kind == "begin":
                state, code, result_t = "code", [], None
            elif kind == "separate" and state == "code":
                state = "result"
            elif kind == "end" and state is not None:
                out.append(_Field("".join(code), result_t))
                state = None
        elif el.tag == _qn("instrText") and state == "code":
            code.append(el.text or "")
        elif el.tag == _qn("t") and state == "result" and result_t is None:
            result_t = el
    return out


def _style_of(p: etree._Element) -> str:
    ps = p.find(f"{_qn('pPr')}/{_qn('pStyle')}")
    return ps.get(_qn("val"), "") if ps is not None else ""


def _num_of(p: etree._Element) -> tuple[str, int] | None:
    numpr = p.find(f"{_qn('pPr')}/{_qn('numPr')}")
    if numpr is None:
        return None
    nid = numpr.find(_qn("numId"))
    ilvl = numpr.find(_qn("ilvl"))
    if nid is None:
        return None
    return nid.get(_qn("val"), ""), int(ilvl.get(_qn("val"), "0")) if ilvl is not None else 0


def fill_field_results(
    body: etree._Element, numbering_xml: bytes, notes: Iterable[etree._Element] = ()
) -> None:
    """Set the cached result of every SEQ/STYLEREF/REF field (in place)."""
    numbering = _Numbering(numbering_xml)
    seq: dict[str, int] = {}
    seq_reset: dict[str, int] = {}  # counter -> heading level that resets it (\s N)
    heading_numbers: dict[int, str] = {}  # level -> latest heading's number text
    bookmark_text: dict[str, list[str]] = {}
    bookmark_number: dict[str, str] = {}
    refs: list[_Field] = []

    for p in body.iter(_qn("p")):
        number: tuple[str, str] | None = None
        num = _num_of(p)
        if num is not None:
            number = numbering.advance(*num)
        hm = _HEADING_RE.match(_style_of(p))
        if hm:
            level = int(hm.group(1))
            for counter, reset_level in seq_reset.items():
                if level <= reset_level:
                    seq[counter] = 0
            for deeper in [k for k in heading_numbers if k > level]:
                del heading_numbers[deeper]
            if number is not None:
                heading_numbers[level] = number[0]
        for f in _paragraph_fields(p):
            if f.kind == "SEQ" and f.args:
                name = f.args[0]
                if "\\s" in f.args:
                    i = f.args.index("\\s")
                    if i + 1 < len(f.args) and f.args[i + 1].isdigit():
                        seq_reset[name] = int(f.args[i + 1])
                if "\\r" in f.args and f.args.index("\\r") + 1 < len(f.args) \
                        and f.args[f.args.index("\\r") + 1].isdigit():
                    seq[name] = int(f.args[f.args.index("\\r") + 1])  # explicit reset
                elif "\\c" not in f.args:
                    seq[name] = seq.get(name, 0) + 1
                _set(f, str(seq.get(name, 0)))
            elif f.kind == "STYLEREF" and f.args:
                level = int(f.args[0]) if f.args[0].isdigit() else 1
                _set(f, heading_numbers.get(level, "0").rstrip("."))
            elif f.kind == "REF" and f.args:
                refs.append(f)
        # bookmarks: their text (after this paragraph's fields are filled) and
        # the paragraph's own number (for REF \r)
        open_marks: dict[str, str] = {}
        for el in p.iter(_qn("bookmarkStart"), _qn("bookmarkEnd"), _qn("t"), _qn("instrText")):
            if el.tag == _qn("bookmarkStart"):
                name = el.get(_qn("name"), "")
                open_marks[el.get(_qn("id"), "")] = name
                bookmark_text.setdefault(name, [])
                if number is not None:
                    bookmark_number[name] = number[0]
            elif el.tag == _qn("bookmarkEnd"):
                open_marks.pop(el.get(_qn("id"), ""), None)
            elif el.tag == _qn("t"):
                for name in open_marks.values():
                    bookmark_text[name].append(el.text or "")
    for note in notes:
        for p in note.iter(_qn("p")):
            refs.extend(f for f in _paragraph_fields(p) if f.kind == "REF" and f.args)
    for f in refs:
        mark = f.args[0]
        if "\\r" in f.args or "\\n" in f.args or "\\w" in f.args:
            value = bookmark_number.get(mark)
            if value is not None:
                _set(f, value.rstrip("."))
            continue
        text = "".join(bookmark_text.get(mark, [])).strip()
        if text:
            _set(f, text)


def _set(f: _Field, value: str) -> None:
    if f.result_t is not None and value:
        f.result_t.text = value
