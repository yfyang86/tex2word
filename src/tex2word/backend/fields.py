"""Word field codes and bookmarks (SEQ / REF / PAGEREF).

These are the primitives ``python-docx`` cannot create and that the PRD
identifies as the universal failure point of existing tools. A complex field is
a sequence of runs: ``fldChar begin`` -> ``instrText`` (the field code) ->
``fldChar separate`` -> a cached result run -> ``fldChar end``. Word recomputes
the result on field-refresh, giving live numbering.
"""

from __future__ import annotations

import itertools

from lxml import etree

from .ooxml import el, preserve_space, sub, text_el

_Element = etree._Element
_bookmark_ids = itertools.count(1)


def bookmark_start(name: str) -> _Element:
    bid = next(_bookmark_ids)
    return el("w:bookmarkStart", **{"w:id": bid, "w:name": name})


def bookmark_end_for(start: _Element) -> _Element:
    bid = start.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id")
    return el("w:bookmarkEnd", **{"w:id": bid})


def reset_bookmark_ids() -> None:
    """Reset the bookmark-id counter (call per-document for deterministic ids)."""
    global _bookmark_ids
    _bookmark_ids = itertools.count(1)


def _instr_run(code: str) -> _Element:
    r = el("w:r")
    instr = sub(r, "w:instrText")
    preserve_space(instr)
    instr.text = code
    return r


def _fldchar(kind: str) -> _Element:
    r = el("w:r")
    sub(r, "w:fldChar", **{"w:fldCharType": kind})
    return r


def field(code: str, cached: str = "") -> list[_Element]:
    """Build a complex field as a list of runs.

    ``code`` is the field instruction (e.g. ``SEQ Equation \\* ARABIC``);
    ``cached`` is the placeholder result shown until Word refreshes fields.
    """
    runs = [_fldchar("begin"), _instr_run(code), _fldchar("separate")]
    result = el("w:r")
    t = text_el("w:t", cached or " ")
    preserve_space(t)
    result.append(t)
    runs.append(result)
    runs.append(_fldchar("end"))
    return runs


def seq_field(counter: str, cached: str = "") -> list[_Element]:
    return field(f"SEQ {counter} \\* ARABIC", cached)


def number_field(counter: str, by_section: bool = False) -> list[_Element]:
    """Runs for a live number: flat ``SEQ`` or per-section ``N.M``.

    With ``by_section`` the number is ``STYLEREF 1 \\s`` (the nearest numbered
    Heading 1) + ``.`` + ``SEQ counter \\s 1`` (a counter that resets at each
    Heading 1) -- the standard Word "include chapter number" caption scheme.
    """
    if not by_section:
        return seq_field(counter, "1")
    runs = field("STYLEREF 1 \\s", "1")
    dot = el("w:r")
    dot.append(text_el("w:t", "."))
    runs.append(dot)
    runs += field(f"SEQ {counter} \\s 1 \\* ARABIC", "1")
    return runs


def ref_field(bookmark: str, cached: str = "", *, paragraph_number: bool = False) -> list[_Element]:
    # \h = hyperlink to the bookmark. \r inserts the paragraph (list) number of
    # the bookmark in relative context -- used for numbered-section references.
    switches = "\\r \\h" if paragraph_number else "\\h"
    return field(f"REF {bookmark} {switches}", cached)


def pageref_field(bookmark: str, cached: str = "") -> list[_Element]:
    return field(f"PAGEREF {bookmark} \\h", cached)
