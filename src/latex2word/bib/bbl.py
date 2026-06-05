"""Parsing a BibTeX ``.bbl`` file (the formatted ``.bst`` output).

When a ``.bbl`` sits next to the ``.tex``, it carries the *exact* reference
formatting, ordering, and labels produced by the chosen ``.bst`` style -- far
better than our heuristic ``.bib``->CSL rendering. We parse its ``\\bibitem``
entries into note-bearing :class:`~latex2word.ir.CSLItem`s (``_order`` preserves
the order; ``_label`` carries the author-year marker when present).
"""

from __future__ import annotations

import re

from pylatexenc.latex2text import LatexNodes2Text

from .. import ir

_L2T = LatexNodes2Text(keep_comments=False, strict_latex_spaces=False)

# \bibitem[label]{key}  (label optional, for author-year styles)
_BIBITEM_RE = re.compile(
    r"\\bibitem\s*(?:\[(?P<label>(?:[^\[\]]|\[[^\]]*\])*)\])?\s*\{(?P<key>[^}]*)\}"
)
# noise commands inside .bbl entries that should become a space / drop
_NEWBLOCK_RE = re.compile(r"\\(?:newblock|bibinfo|natexlab|urlprefix|doibase)\b")
_PROVIDE_RE = re.compile(r"\\(?:providecommand|expandafter|def|begingroup|endgroup)\b.*")


def _clean(text: str) -> str:
    text = _NEWBLOCK_RE.sub(" ", text)
    try:
        out = _L2T.latex_to_text(text)
    except Exception:
        out = re.sub(r"\\[A-Za-z]+", "", text).replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", out).strip(" .,") + ("." if out.strip() else "")


def _thebib_body(text: str) -> str:
    m = re.search(r"\\begin\{thebibliography\}.*?\}", text, re.DOTALL)
    start = m.end() if m else 0
    end = text.find(r"\end{thebibliography}")
    return text[start : end if end != -1 else len(text)]


def parse_bbl(text: str) -> dict[str, ir.CSLItem]:
    """Parse a ``.bbl`` (or inline ``thebibliography``) into ``{key: CSLItem}``."""
    body = _thebib_body(text)
    items: dict[str, ir.CSLItem] = {}
    matches = list(_BIBITEM_RE.finditer(body))
    for order, m in enumerate(matches, start=1):
        key = m.group("key").strip()
        if not key:
            continue
        chunk_end = matches[order].start() if order < len(matches) else len(body)
        raw = body[m.end() : chunk_end]
        note = _clean(raw)
        fields: dict[str, object] = {"note": note, "_order": order}
        label = m.group("label")
        if label:
            fields["_label"] = _clean(label).rstrip(".")
        items[key] = ir.CSLItem(id=key, type="document", csl_fields=fields)
    return items


def bbl_style(items: dict[str, ir.CSLItem]) -> str:
    """Infer numeric vs author-year from whether entries carry ``_label``."""
    if any("_label" in it.csl_fields for it in items.values()):
        return "author-year"
    return "numeric"
