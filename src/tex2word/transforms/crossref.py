"""Cross-reference resolution pass (IR -> IR).

Implements the PRD's headline differentiator plumbing: collect every labelled
target, assign it a sanitized Word bookmark name and a ``SEQ`` counter, then
rewrite each ``Ref`` to point at the matching bookmark with the right kind. The
back-end then emits live ``SEQ``/``REF``/``PAGEREF`` fields -- numbers that
auto-renumber in Word.
"""

from __future__ import annotations

import re

from .. import ir
from ..report import ConversionReport

_COUNTER = {
    "equation": "Equation",
    "figure": "Figure",
    "table": "Table",
    "section": "Section",
    "algorithm": "Algorithm",
}


def sanitize_bookmark(key: str) -> str:
    """Word bookmark names: start with a letter, no spaces, <= 40 chars."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", key)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "ref_" + cleaned
    return cleaned[:40]


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
    return "generic"


def figure_bookmark(fig: ir.Figure) -> str | None:
    """The bookmark for a figure's number (shared by parent and sub-labels)."""
    if fig.label:
        return sanitize_bookmark(fig.label)
    for sub in fig.subfigures:
        if sub.label:
            return sanitize_bookmark("fig_" + sub.label)
    return None


def _collect(blocks: list[ir.Block], labels: dict[str, ir.LabelInfo]) -> None:
    for block in blocks:
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
            )
        # sub-figure labels resolve to the parent figure's number.
        if isinstance(block, ir.Figure) and block.subfigures:
            bookmark = figure_bookmark(block)
            if bookmark is not None:
                if block.label:
                    labels[block.label] = ir.LabelInfo(
                        kind="figure", counter_name="Figure", bookmark=bookmark
                    )
                for sub in block.subfigures:
                    if sub.label:
                        labels[sub.label] = ir.LabelInfo(
                            kind="figure", counter_name="Figure", bookmark=bookmark
                        )
        # recurse into nested block containers
        if isinstance(block, ir.Quote | ir.Theorem):
            _collect(block.blocks, labels)
        elif isinstance(block, ir.ItemList):
            for item in block.items:
                _collect(item.blocks, labels)


def _rewrite_refs_inlines(inlines: list[ir.Inline], labels, report) -> None:
    for node in inlines:
        if isinstance(node, ir.Ref):
            info = labels.get(node.key)
            if info is None:
                report.warn("\\ref", f"unresolved reference to '{node.key}'")
                continue
            node.bookmark = info.bookmark
            if node.ref_kind == "generic":
                node.ref_kind = info.kind  # type: ignore[assignment]
        elif isinstance(node, ir.Emphasis | ir.Link | ir.Footnote | ir.Colored | ir.FontSize):
            _rewrite_refs_inlines(node.inlines, labels, report)


def _rewrite_refs_blocks(blocks: list[ir.Block], labels, report) -> None:
    for block in blocks:
        if isinstance(block, ir.Paragraph | ir.Heading):
            _rewrite_refs_inlines(block.inlines, labels, report)
        elif isinstance(block, ir.Quote | ir.Theorem):
            _rewrite_refs_blocks(block.blocks, labels, report)
        elif isinstance(block, ir.ItemList):
            for item in block.items:
                _rewrite_refs_blocks(item.blocks, labels, report)
        elif isinstance(block, ir.Table) and block.caption:
            _rewrite_refs_inlines(block.caption, labels, report)
        elif isinstance(block, ir.Figure) and block.caption:
            _rewrite_refs_inlines(block.caption, labels, report)


def resolve_crossrefs(doc: ir.Document, report: ConversionReport) -> ir.Document:
    """Populate ``doc.labels`` and wire ``Ref`` nodes to bookmarks (in place)."""
    labels: dict[str, ir.LabelInfo] = {}
    _collect(doc.blocks, labels)
    if doc.meta.abstract:
        _collect(doc.meta.abstract, labels)
    doc.labels = labels
    _rewrite_refs_blocks(doc.blocks, labels, report)
    if doc.meta.abstract:
        _rewrite_refs_blocks(doc.meta.abstract, labels, report)
    return doc
