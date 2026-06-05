"""CSL-JSON -> formatted reference strings + in-text citation resolution.

A pragmatic static formatter supporting two styles: ``numeric`` ([1], [2], ...)
and ``author-year`` ((Author, 2020)). It is *not* a full CSL processor (that is
the post-V1 citeproc upgrade) but produces clean, editable Word text and a
formatted reference list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import ir
from ..report import ConversionReport

# bibliographystyle -> our two supported style families
_STYLE_FAMILY = {
    "plain": "numeric", "unsrt": "numeric", "abbrv": "numeric",
    "ieeetr": "numeric", "acm": "numeric", "siam": "numeric",
    "plainnat": "author-year", "apalike": "author-year", "abbrvnat": "author-year",
    "agsm": "author-year", "harvard": "author-year", "chicago": "author-year",
    "apa": "author-year",
}


def style_family(bibstyle: str) -> str:
    name = bibstyle.strip().lower()
    if name in ("numeric", "author-year"):  # already a family (idempotent)
        return name
    return _STYLE_FAMILY.get(name, "numeric")


@dataclass
class Bibliography:
    entries: list[ir.CSLItem] = field(default_factory=list)
    style: str = "numeric"
    #: citekey -> in-text label (e.g. "1" or "Smith, 2020")
    labels: dict[str, str] = field(default_factory=dict)
    #: citekey -> 1-based position (numeric ordering)
    numbers: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Name / field helpers
# --------------------------------------------------------------------------- #


def _names(item: ir.CSLItem, role: str = "author") -> list[dict[str, str]]:
    value = item.csl_fields.get(role)
    return value if isinstance(value, list) else []


def _year(item: ir.CSLItem) -> str:
    issued = item.csl_fields.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if parts and parts[0]:
            return str(parts[0][0])
    return "n.d."


def _family(name: dict[str, str]) -> str:
    return name.get("family", "").strip()


def _initials(given: str) -> str:
    return " ".join(f"{p[0]}." for p in given.split() if p)


def _author_label(item: ir.CSLItem) -> str:
    names = _names(item)
    if not names:
        return item.id
    if len(names) == 1:
        return _family(names[0])
    if len(names) == 2:
        return f"{_family(names[0])} & {_family(names[1])}"
    return f"{_family(names[0])} et al."


def _format_authors(item: ir.CSLItem) -> str:
    names = _names(item)
    rendered = []
    for n in names:
        fam = _family(n)
        given = n.get("given", "")
        rendered.append(f"{fam}, {_initials(given)}".strip().rstrip(",") if given else fam)
    if not rendered:
        return ""
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + " & " + rendered[-1]


# --------------------------------------------------------------------------- #
# Reference list formatting
# --------------------------------------------------------------------------- #


def format_reference(item: ir.CSLItem) -> str:
    """Render a single CSL item as a formatted reference string."""
    f: dict[str, Any] = item.csl_fields
    # a real CSL engine (citeproc-py) may have pre-formatted this entry
    if f.get("_formatted"):
        return str(f["_formatted"]).strip()
    # thebibliography \bibitem entries carry only free-text 'note'.
    if not _names(item) and "title" not in f and "note" in f:
        return str(f["note"]).strip()
    parts: list[str] = []
    authors = _format_authors(item)
    if authors:
        parts.append(f"{authors} ({_year(item)}).")
    else:
        parts.append(f"({_year(item)}).")

    title = f.get("title")
    if title:
        parts.append(f"{title}.")

    container = f.get("container-title")
    if container:
        detail = str(container)
        if f.get("volume"):
            detail += f", {f['volume']}"
        if f.get("issue"):
            detail += f"({f['issue']})"
        if f.get("page"):
            detail += f", {f['page']}"
        parts.append(f"{detail}.")
    else:
        if f.get("publisher"):
            parts.append(f"{f['publisher']}.")

    if f.get("DOI"):
        parts.append(f"https://doi.org/{f['DOI']}")
    elif f.get("URL"):
        parts.append(str(f["URL"]))

    return " ".join(p for p in parts if p).strip()


# --------------------------------------------------------------------------- #
# In-text citation rendering
# --------------------------------------------------------------------------- #


def _cite_one(key: str, biblio: Bibliography) -> str:
    return biblio.labels.get(key, key)


def render_citation(cite: ir.Cite, biblio: Bibliography) -> str:
    """Render an in-text marker for a ``Cite`` node against the bibliography."""
    index = biblio_index(biblio)

    # author-/year-only modes are style-independent
    if cite.mode == "author":
        return ", ".join(
            _author_label(index[k]) if k in index else k for k in cite.keys
        )
    if cite.mode == "year":
        return ", ".join(_year(index[k]) if k in index else k for k in cite.keys)
    if cite.mode == "num":
        return ", ".join(biblio.numbers.get(k, "?").__str__() for k in cite.keys)

    pre = f"{cite.prefix} " if cite.prefix else ""
    post = f", {cite.suffix}" if cite.suffix else ""

    if biblio.style == "numeric":
        inner = ", ".join(_cite_one(k, biblio) for k in cite.keys)
        return f"[{pre}{inner}{post}]"

    # author-year
    if cite.mode == "text":
        rendered = []
        for k in cite.keys:
            item = index.get(k)
            if item is None:
                rendered.append(k)
            else:
                rendered.append(f"{_author_label(item)} ({_year(item)}{post})")
        return ", ".join(rendered)
    inner = ", ".join(_cite_one(k, biblio) for k in cite.keys)
    return f"({pre}{inner}{post})"


def biblio_index(biblio: Bibliography) -> dict[str, ir.CSLItem]:
    return {e.id: e for e in biblio.entries}


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def build_bibliography(
    items: dict[str, ir.CSLItem], cited_keys: list[str], style: str
) -> Bibliography:
    """Build the bibliography for the cited keys in the chosen style.

    When entries carry a ``_order`` (from a ``.bbl`` or ``thebibliography``) that
    canonical order wins; a ``_label`` (the ``.bst``-formatted in-text marker)
    overrides the computed numeric/author-year label.
    """
    numeric = style == "numeric"
    known = [k for k in cited_keys if k in items]

    has_order = any("_order" in items[k].csl_fields for k in known)
    if has_order:
        ordered_keys = sorted(known, key=lambda k: items[k].csl_fields.get("_order", 1 << 30))
    elif numeric:
        ordered_keys = known  # citation order
    else:
        ordered_keys = sorted(
            known, key=lambda k: (_author_label(items[k]).lower(), _year(items[k]))
        )

    biblio = Bibliography(style=style)
    for i, key in enumerate(ordered_keys, start=1):
        item = items[key]
        biblio.entries.append(item)
        biblio.numbers[key] = i
        explicit = item.csl_fields.get("_label")
        if explicit:
            biblio.labels[key] = str(explicit)
        elif numeric:
            biblio.labels[key] = str(i)
        else:
            biblio.labels[key] = f"{_author_label(item)}, {_year(item)}"
    return biblio


def _walk_cites(blocks: list[ir.Block], out: list[ir.Cite]) -> None:
    def inl(inlines: list[ir.Inline]) -> None:
        for n in inlines:
            if isinstance(n, ir.Cite):
                out.append(n)
            elif isinstance(n, ir.Emphasis | ir.Link | ir.Footnote):
                inl(n.inlines)

    for block in blocks:
        if isinstance(block, ir.Paragraph | ir.Heading):
            inl(block.inlines)
        elif isinstance(block, ir.Quote):
            _walk_cites(block.blocks, out)
        elif isinstance(block, ir.ItemList):
            for item in block.items:
                _walk_cites(item.blocks, out)


def resolve_citations(
    doc: ir.Document,
    items: dict[str, ir.CSLItem],
    bibstyle: str,
    report: ConversionReport,
    *,
    csl_path: str | None = None,
    nocite_keys: list[str] | None = None,
) -> Bibliography:
    """Resolve cites, fill ``Cite.rendered``, and populate the Bibliography block."""
    style = style_family(bibstyle)
    cites: list[ir.Cite] = []
    _walk_cites(doc.blocks, cites)

    cited_order: list[str] = []
    for cite in cites:
        for key in cite.keys:
            if key not in cited_order:
                cited_order.append(key)
            if key not in items:
                report.warn("\\cite", f"unknown citation key '{key}'")
    # \nocite{key} / \nocite{*}: include in the reference list, no in-text cite
    extra_keys: list[str] = []
    for key in nocite_keys or []:
        targets = list(items) if key == "*" else [key]
        for k in targets:
            if k in items and k not in cited_order:
                cited_order.append(k)
                extra_keys.append(k)

    if csl_path:
        csl = _resolve_with_csl(doc, items, cites, extra_keys, style, csl_path, report)
        if csl is not None:
            return csl

    biblio = build_bibliography(items, cited_order, style)
    for cite in cites:
        cite.rendered = render_citation(cite, biblio)
    _fill_biblio_block(doc, biblio.entries, style)
    return biblio


def _fill_biblio_block(doc: ir.Document, entries: list[ir.CSLItem], style: str) -> None:
    """Fill a ``\\bibliography`` placeholder block, else append one at the end."""
    placeholder = next((b for b in doc.blocks if isinstance(b, ir.Bibliography)), None)
    if placeholder is not None:
        placeholder.entries = entries
        placeholder.style = style
    elif entries:
        doc.blocks.append(ir.Bibliography(entries=entries, style=style))


def _resolve_with_csl(
    doc: ir.Document,
    items: dict[str, ir.CSLItem],
    cites: list[ir.Cite],
    extra_keys: list[str],
    style: str,
    csl_path: str,
    report: ConversionReport,
) -> Bibliography | None:
    """Format citations + references with citeproc-py; None to fall back."""
    from .csl_engine import render_with_csl

    result = render_with_csl(cites, extra_keys, items, csl_path, report)
    if result is None:
        return None
    cite_text, entries = result
    for cite in cites:
        cite.rendered = cite_text.get(id(cite), cite.rendered)
    biblio = Bibliography(style="csl")
    for i, (key, formatted) in enumerate(entries, start=1):
        item = items[key]
        item.csl_fields["_formatted"] = formatted  # consumed by format_reference
        biblio.entries.append(item)
        biblio.numbers[key] = i
    # style "csl": the formatted entry already carries the style's own label, so
    # the backend must not prepend its own "[i]".
    _fill_biblio_block(doc, biblio.entries, "csl")
    return biblio
