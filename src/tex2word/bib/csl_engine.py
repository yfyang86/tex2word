"""Real CSL formatting via ``citeproc-py`` (the optional ``csl`` extra).

Given the document's CSL-JSON items, the in-text citations, and a user-supplied
``.csl`` style file, produce properly formatted in-text citations and an ordered,
style-sorted reference list. Falls back (returns ``None``) when ``citeproc-py``
is not installed or the style fails to load — the caller then uses the built-in
heuristic formatter.

We deliberately do *not* bundle CSL styles (they are CC-BY-SA); the user points
``--csl`` at a style file of their choice.
"""

from __future__ import annotations

from .. import ir
from ..report import ConversionReport


def _to_csl_json(item: ir.CSLItem) -> dict:
    """An ir.CSLItem -> a CSL-JSON dict citeproc can consume (drop internals)."""
    out: dict = {"id": item.id, "type": item.type or "article-journal"}
    for key, value in item.csl_fields.items():
        if not key.startswith("_"):  # _order/_label/_formatted are ours, not CSL
            out[key] = value
    return out


def render_with_csl(
    cites: list[ir.Cite],
    extra_keys: list[str],
    items: dict[str, ir.CSLItem],
    csl_path: str,
    report: ConversionReport,
) -> tuple[dict[int, str], list[tuple[str, str]]] | None:
    """Format citations + bibliography against ``csl_path``.

    Returns ``(cite_text, entries)`` where ``cite_text`` maps ``id(cite)`` to its
    formatted in-text string and ``entries`` is an ordered list of
    ``(citekey, formatted_reference)``. Returns ``None`` to signal fallback.
    """
    try:
        from citeproc import (
            Citation,
            CitationItem,
            CitationStylesBibliography,
            CitationStylesStyle,
            formatter,
        )
        from citeproc.source.json import CiteProcJSON
    except ImportError:
        report.warn("--csl", "citeproc-py not installed; run `uv sync --extra csl`")
        return None

    try:
        source = CiteProcJSON([_to_csl_json(it) for it in items.values()])
        style = CitationStylesStyle(csl_path, validate=False)
        bib = CitationStylesBibliography(style, source, formatter.plain)

        pairs: list[tuple[ir.Cite, object]] = []
        for cite in cites:
            keys = [k for k in cite.keys if k in items]
            if not keys:
                continue
            if len(keys) == 1:  # attach locators only to single-key cites
                citem = [CitationItem(
                    keys[0], prefix=cite.prefix or "", suffix=cite.suffix or "",
                )]
            else:
                citem = [CitationItem(k) for k in keys]
            citation = Citation(citem)
            bib.register(citation)
            pairs.append((cite, citation))

        for key in extra_keys:  # \nocite: in the bibliography, no in-text cite
            if key in items:
                bib.register(Citation([CitationItem(key)]))

        cite_text: dict[int, str] = {}
        for cite, citation in pairs:
            cite_text[id(cite)] = str(bib.cite(citation, lambda _ci: None))

        entries = [
            (key, str(entry))
            for key, entry in zip(bib.keys, bib.bibliography(), strict=False)
        ]
        return cite_text, entries
    except Exception as exc:  # malformed style, unsupported field, ... -> fall back
        report.warn("--csl", f"citeproc formatting failed ({exc}); using heuristic")
        return None
