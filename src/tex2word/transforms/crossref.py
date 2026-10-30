"""Cross-reference resolution pass (IR -> IR).

Implements the PRD's headline differentiator plumbing: collect every labelled
target, assign it a sanitized Word bookmark name and a ``SEQ`` counter, then
rewrite each ``Ref`` to point at the matching bookmark with the right kind. The
back-end then emits live ``SEQ``/``REF``/``PAGEREF`` fields -- numbers that
auto-renumber in Word.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .. import ir
from ..report import ConversionReport

_COUNTER = {
    "equation": "Equation",
    "figure": "Figure",
    "table": "Table",
    "section": "Section",
    "algorithm": "Algorithm",
    "listing": "Listing",
}


def sanitize_bookmark(key: str) -> str:
    """Word bookmark names: start with a letter, no spaces, <= 40 chars."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", key)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "ref_" + cleaned
    return cleaned[:40]


def _inline_text(inlines: list) -> str:
    """Flatten an inline list to plain text (for \\nameref display text)."""
    out: list[str] = []
    for n in inlines:
        if isinstance(n, ir.Text):
            out.append(n.value)
        elif hasattr(n, "inlines"):
            out.append(_inline_text(n.inlines))
    return "".join(out).strip()


def _label_name(block: ir.Block) -> str | None:
    """The target's title/caption text, used by \\nameref."""
    if isinstance(block, ir.Heading):
        return _inline_text(block.inlines)
    if isinstance(block, ir.Theorem):
        return _inline_text(block.title) if block.title else block.kind
    if isinstance(block, ir.Figure | ir.Table | ir.CodeBlock) and block.caption:
        return _inline_text(block.caption)
    return None


def _label_kind(block: ir.Block) -> str:
    if isinstance(block, ir.MathBlock):
        return "equation"
    if isinstance(block, ir.Figure):
        return "figure"
    if isinstance(block, ir.Table):
        return "table"
    if isinstance(block, ir.Heading):
        return "section"
    if isinstance(block, ir.Theorem):
        return "theorem"
    if isinstance(block, ir.Algorithm):
        return "algorithm"
    if isinstance(block, ir.CodeBlock):
        return "listing"
    return "generic"


def figure_bookmark(fig: ir.Figure) -> str | None:
    """The bookmark for a figure's number (shared by parent and sub-labels)."""
    if fig.label:
        return sanitize_bookmark(fig.label)
    for sub in fig.subfigures:
        if sub.label:
            return sanitize_bookmark("fig_" + sub.label)
    return None


def _ref_type(block: ir.Block, book: bool) -> str:
    """The counter type cleveref/hyperref name a target by."""
    if isinstance(block, ir.Heading):
        if block.part:
            return "part"
        if block.appendix:
            return "appendix"
        depth = block.level - 1 if book else block.level
        return {0: "chapter", 1: "section", 2: "subsection"}.get(depth, "subsubsection")
    if isinstance(block, ir.Theorem):
        return "theorem"
    if isinstance(block, ir.Algorithm):
        return "algorithm"
    if isinstance(block, ir.CodeBlock):
        return "listing"
    return _label_kind(block)


def _register(block: ir.Block, labels: dict[str, ir.LabelInfo], book: bool = False) -> None:
    label = getattr(block, "label", None)
    if label:
        kind = _label_kind(block)
        if isinstance(block, ir.Theorem):
            counter_name = block.counter or "Item"
        else:
            counter_name = _COUNTER.get(kind, "Item")
        labels[label] = ir.LabelInfo(
            kind=kind,  # type: ignore[arg-type]
            counter_name=counter_name,
            bookmark=sanitize_bookmark(label),
            name=_label_name(block),
            ref_type=_ref_type(block, book),
            type_name=block.kind if isinstance(block, ir.Theorem) else None,
        )
    # every numbered line of an align/eqnarray that carries a \label is its
    # own referenceable equation (not just the first line).
    if isinstance(block, ir.MathBlock) and block.line_labels:
        for lab in block.line_labels:
            if lab:
                labels[lab] = ir.LabelInfo(
                    kind="equation",  # type: ignore[arg-type]
                    counter_name="Equation",
                    bookmark=sanitize_bookmark(lab),
                    ref_type="equation",
                )
    # sub-figure labels resolve to the parent figure's number.
    if isinstance(block, ir.Figure) and block.subfigures:
        bookmark = figure_bookmark(block)
        if bookmark is not None:
            if block.label:
                labels[block.label] = ir.LabelInfo(
                    kind="figure", counter_name="Figure", bookmark=bookmark, ref_type="figure"
                )
            for i, sub in enumerate(block.subfigures):
                if sub.label:
                    labels[sub.label] = ir.LabelInfo(
                        kind="figure", counter_name="Figure", bookmark=bookmark,
                        sub=chr(ord("a") + i), ref_type="figure",
                    )


def _collect(root: object, labels: dict[str, ir.LabelInfo], book: bool = False) -> None:
    """Register every labelled target below ``root`` (table cells, captions,
    theorem and figure bodies, list items included)."""
    for node in ir.iter_nodes(root):
        if isinstance(node, ir.ListItem):
            if node.label:
                # \item\label{} -> the item's (Word auto-numbered) list number;
                # the back-end references it with a REF \r field.
                labels[node.label] = ir.LabelInfo(
                    kind="listitem",
                    counter_name="Item",
                    bookmark=sanitize_bookmark(node.label),
                    ref_type="enumi",
                )
        elif isinstance(node, ir.SubFigure):
            continue  # registered with its parent figure
        elif isinstance(node, _TARGETS):
            _register(node, labels, book)


_TARGETS = (ir.Heading, ir.MathBlock, ir.Table, ir.Figure, ir.Theorem, ir.Algorithm,
            ir.CodeBlock)


def _rewrite_refs(root: object, labels: dict[str, ir.LabelInfo], report) -> None:
    """Point every ``Ref`` (and ``\\hyperref`` link) below ``root`` at its bookmark."""
    for inlines in ir.node_lists(root):
        letters: list[tuple[int, str]] = []  # (index, letter) to insert after a Ref
        for i, node in enumerate(inlines):
            if isinstance(node, ir.Ref):
                for extra in node.more:
                    if extra not in labels:
                        report.warn("\\ref", f"unresolved reference to '{extra}'")
                info = labels.get(node.key)
                if info is None:
                    report.warn("\\ref", f"unresolved reference to '{node.key}'")
                    continue
                if node.ref_kind == "subref":
                    # \subref -> the sub-figure's own letter, "(a)"
                    inlines[i] = ir.Text(f"({info.sub})" if info.sub else "")
                    continue
                if info.sub and node.ref_kind in ("generic", "figure", "table"):
                    letters.append((i, info.sub))  # \ref to a panel -> "1a"
                if node.ref_kind == "name":
                    # \nameref -> the target's title as an internal hyperlink
                    text = info.name or node.key
                    inlines[i] = ir.Link([ir.Text(text)], "", anchor=info.bookmark)
                    continue
                node.bookmark = info.bookmark
                if node.ref_kind == "generic":
                    node.ref_kind = info.kind  # type: ignore[assignment]
            elif isinstance(node, ir.Link) and node.anchor is not None:
                # \hyperref[label] -> sanitized bookmark
                info = labels.get(node.anchor)
                if info is None:
                    report.warn("\\hyperref", f"unresolved \\hyperref to '{node.anchor}'")
                else:
                    node.anchor = info.bookmark
        for i, letter in reversed(letters):
            inlines.insert(i + 1, ir.Text(letter))


def resolve_crossrefs(doc: ir.Document, report: ConversionReport) -> ir.Document:
    """Populate ``doc.labels`` and wire ``Ref`` nodes to bookmarks (in place)."""
    labels: dict[str, ir.LabelInfo] = {}
    _collect(doc.blocks, labels, doc.book)
    _collect(doc.meta, labels, doc.book)
    # a target's extra \label{}s share the kept label's bookmark
    for alias, kept in doc.label_aliases.items():
        if alias not in labels and kept in labels:
            labels[alias] = labels[kept]
    # a subtable panel: the overall table's number plus the panel's letter
    for sub_label, (kept, letter) in doc.sub_labels.items():
        if sub_label not in labels and kept in labels:
            labels[sub_label] = replace(labels[kept], sub=letter)
    doc.labels = labels
    _rewrite_refs(doc.blocks, labels, report)
    _rewrite_refs(doc.meta, labels, report)
    return doc
