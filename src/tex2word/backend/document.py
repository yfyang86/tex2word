"""IR -> ``word/document.xml``.

Walks the IR and emits OOXML, dropping to raw math (OMML) and field plumbing as
needed. Math uses the direct LaTeX->OMML path; on failure it degrades to a raw
text run and records the fallback in the :class:`ConversionReport` (never an
abort).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import replace as _replace
from typing import Any

from lxml import etree

from .. import ir
from ..mathml.cascade import ImageMathRenderer, MathCascade
from ..report import ConversionReport
from . import fields, images, raster
from .numbering import (
    BULLET_NUM_ID,
    FIRST_LIST_NUM_ID,
    HEADING_ABSTRACT_ID,
    HEADING_APPENDIX_NUM_ID,
    HEADING_NUM_ID,
    PART_NUM_ID,
)
from .ooxml import el, preserve_space, serialize, sub, text_el

_Element = etree._Element

_HEADING_STYLE = {
    0: "Title", 1: "Heading1", 2: "Heading2", 3: "Heading3", 4: "Heading4",
    5: "Heading5",
}
# multi-line display envs that number each line -> keep per-line, don't collapse
_MULTILINE_NUMBERED_ENVS = {"align", "alignat", "flalign", "eqnarray"}
# Word TOC field instructions per \tableofcontents / \listoffigures / \listoftables.
# \o "1-3" = outline levels; \h = hyperlinks; \z = hide leaders in web view;
# \u = use applied outline levels; \c "Figure" = build from the SEQ Figure captions.
_TOC_SPEC = {
    "contents": ("Contents", 'TOC \\o "1-3" \\h \\z \\u'),
    "figures": ("List of Figures", 'TOC \\h \\z \\c "Figure"'),
    "tables": ("List of Tables", 'TOC \\h \\z \\c "Table"'),
}
_PIC_URI = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
#: w:sdt tags marking regions for faithful round-trip recovery.
BIB_SDT_TAG = "tex2word:bibliography"
FIG_SDT_TAG = "tex2word:figure"


class DocumentWriter:
    def __init__(
        self,
        report: ConversionReport,
        base_dir: str = ".",
        image_math_renderer: ImageMathRenderer | None = None,
        number_by_section: bool = False,
        citation_mode: str = "static",
        columns: int = 1,
        page_pgsz: dict[str, str] | None = None,
        page_pgmar: dict[str, str] | None = None,
        header_footer_refs: list[tuple[str, str, str]] | None = None,
        preamble: str = "",
    ) -> None:
        self.report = report
        self.base_dir = base_dir
        #: document preamble (for compiling TikZ pictures to images)
        self.preamble = preamble
        self.number_by_section = number_by_section
        self.citation_mode = citation_mode
        self.columns = max(columns, 1)
        #: page geometry (from a --reference-doc), or None for the built-in default.
        self.page_pgsz = page_pgsz
        self.page_pgmar = page_pgmar
        #: the output page's text column (EMU), from the reference-doc geometry or
        #: the built-in default (US-Letter, 1in margins -> 6.5in). Images size and
        #: clamp against this, so relative widths and the cap track the real page.
        self.text_width_emu, self.text_height_emu = self._text_box_emu()
        #: (element, w:type, r:id) header/footer references from a --reference-doc.
        self.header_footer_refs = header_footer_refs or []
        #: citekey -> CSLItem, populated from the Bibliography block in build().
        self._cite_items: dict[str, ir.CSLItem] = {}
        #: archive path -> bytes, e.g. "word/media/image1.png".
        self.media: dict[str, bytes] = {}
        #: relationship XML strings for word/_rels/document.xml.rels.
        self.document_rels: list[str] = []
        self._image_counter = 0   # distinct media parts written
        self._drawing_counter = 0  # drawing instances (unique wp:docPr ids)
        #: content-hash -> (rel_id, media ext-index) so identical images are
        #: embedded once and merely re-referenced.
        self._media_by_hash: dict[str, tuple[str, int]] = {}
        #: rendered <w:footnote> elements (excluding the separator pair)
        self._footnotes: list[_Element] = []
        self._footnote_counter = 0
        #: rendered <w:endnote> elements (\endnote -> endnotes.xml)
        self._endnotes: list[_Element] = []
        self._endnote_counter = 0
        #: rendered <w:comment> elements (review annotations -> comments.xml)
        self._comments: list[_Element] = []
        self._comment_counter = 0
        self.math = MathCascade(report, image_renderer=image_math_renderer)
        fields.reset_bookmark_ids()
        #: (numId, ilvl, start) of every ordered list's own numbering instance
        self.list_restarts: list[tuple[int, ...]] = []
        #: the heading numbering instance in use (a \setcounter{section} starts a new one)
        self._heading_num_id = HEADING_NUM_ID
        #: number of Heading 1 paragraphs so far, and per SEQ counter the value it
        #: had at that counter's last section-relative number
        self._section_epoch = 0
        self._seq_epoch: dict[str, int] = {}

    # -- public ----------------------------------------------------------- #

    def build(self, doc: ir.Document) -> bytes:
        from ..bib import zotero

        zotero.reset_ids()
        self._labels = doc.labels
        self._cref = doc.cref or {}
        # CJK glyphs inside math get the document's East-Asian font (xeCJK).
        self.math.cjk_font = doc.meta.cjk_main_font or doc.meta.cjk_sans_font
        for block in doc.blocks:
            if isinstance(block, ir.Bibliography):
                self._cite_items = {e.id: e for e in block.entries}
        body = el("w:body")
        self._emit_body(doc, body)
        # real cached numbers for SEQ/STYLEREF/REF (viewers that don't update
        # fields would otherwise show "Figure 1" everywhere and "see 0")
        from .field_results import fill_field_results
        from .numbering import numbering_xml

        fill_field_results(body, numbering_xml(self.list_restarts),
                           notes=[*self._footnotes, *self._endnotes])
        document = el("w:document", body)
        return serialize(document)

    def _emit_body(self, doc: ir.Document, body: _Element) -> None:
        """Emit the title block and body blocks, inserting continuous section
        breaks so ``figure*``/``table*`` (and, in a multi-column paper, the
        title/abstract) span the full page width while text flows in N columns."""
        n = self.columns
        # (columns, emitter) for each top-level region, in order.
        regions: list[tuple[int, Any]] = []
        has_title = bool(
            doc.meta.title or doc.meta.authors or doc.meta.affiliations
            or doc.meta.date or doc.meta.abstract or doc.meta.keywords
            or doc.meta.subtitle or doc.meta.front_notes
        )
        if has_title:
            # the title/authors/abstract are set full-width above the columns.
            regions.append((1 if n > 1 else n, lambda: self._title_block(doc.meta, body)))
        for block in doc.blocks:
            cols = 1 if (n > 1 and getattr(block, "spanning", False)) else n
            regions.append((cols, lambda b=block: self._block(b, body)))

        prev: int | None = None
        for cols, emit in regions:
            if prev is not None and cols != prev:
                # a continuous section break closes the previous region: its
                # sectPr (carried on this empty paragraph) describes that region.
                body.append(self._column_break_para(prev))
            emit()
            prev = cols
        body.append(self._sect_pr(columns=prev if prev is not None else n))

    def _column_break_para(self, columns: int) -> _Element:
        """An empty paragraph whose pPr carries a continuous section break, used to
        end a region with the given column count."""
        p = el("w:p")
        ppr = sub(p, "w:pPr")
        ppr.append(self._sect_pr(columns=columns, continuous=True))
        return p

    # -- title / meta ----------------------------------------------------- #

    def _title_block(self, meta: ir.DocumentMeta, body: _Element) -> None:
        if meta.title:
            p = self._styled_paragraph("Title")
            self._inlines(meta.title, p)
            body.append(p)
        if meta.subtitle:
            p = self._styled_paragraph("Subtitle")
            self._inlines([ir.Emphasis(list(meta.subtitle), "bold")], p)
            body.append(p)
        for author in meta.authors:
            p = self._styled_paragraph("Subtitle")
            self._inlines(author, p)
            body.append(p)
        for affil in meta.affiliations:
            p = self._styled_paragraph("Subtitle")
            self._inlines([ir.Emphasis(list(affil), "italic")], p)
            body.append(p)
        for note in meta.front_notes:
            p = self._styled_paragraph("Subtitle")
            self._inlines(note, p)
            body.append(p)
        if meta.date:
            p = self._styled_paragraph("Subtitle")
            self._inlines(meta.date, p)
            body.append(p)
        if meta.abstract:
            self._abstract(meta, body)
        if meta.keywords:
            p = self._styled_paragraph("Abstract")
            p.append(self._run("Keywords: ", bold=True))
            self._inlines(meta.keywords, p)
            body.append(p)

    def _abstract(self, meta: ir.DocumentMeta, body: _Element) -> None:
        """The abstract with the heading its class prints: a line above it
        ("Abstract"), run-in ("Abstract." / IEEEtran's "Abstract—"), or none."""
        name, form = meta.abstract_name or "Abstract", meta.abstract_form
        if form == "block":
            p = self._styled_paragraph("Abstract")
            self._set_align(p, "center")
            p.append(self._run(name, bold=True))
            body.append(p)
        start = len(body)
        for block in meta.abstract or []:
            self._block(block, body, default_style="Abstract")
        if form not in ("runin", "dash"):
            return
        first = body[start] if len(body) > start else None
        if first is None or first.tag != _qn("w:p"):
            first = self._styled_paragraph("Abstract")
            body.insert(start, first)
        ppr = first.find(_qn("w:pPr"))
        at = 0 if ppr is None else first.index(ppr) + 1
        if form == "dash":
            label = self._run(f"{name}—", bold=True, italic=True)
        else:
            label = self._run(f"{name}. ", bold=True)
        first.insert(at, label)

    # -- blocks ----------------------------------------------------------- #

    def _block(self, block: ir.Block, body: _Element, default_style: str = "Normal") -> None:
        if isinstance(block, ir.Heading):
            self._heading(block, body)
        elif isinstance(block, ir.Paragraph):
            p = self._styled_paragraph(default_style)
            if block.align:
                self._set_align(p, block.align)
            self._inlines(block.inlines, p)
            body.append(p)
        elif isinstance(block, ir.MathBlock):
            self._math_block(block, body)
        elif isinstance(block, ir.ItemList):
            self._list(block, body)
        elif isinstance(block, ir.Table):
            self._table(block, body)
        elif isinstance(block, ir.Figure):
            self._figure(block, body)
        elif isinstance(block, ir.CodeBlock):
            self._code_block(block, body)
        elif isinstance(block, ir.Quote):
            if block.shade or block.border or block.title:
                self._callout(block, body)
            else:
                for inner in block.blocks:
                    self._block(inner, body, default_style="Quote")
        elif isinstance(block, ir.Theorem):
            self._theorem(block, body)
        elif isinstance(block, ir.Algorithm):
            self._algorithm(block, body)
        elif isinstance(block, ir.Bibliography):
            self._bibliography(block, body)
        elif isinstance(block, ir.TableOfContents):
            self._toc(block, body)
        elif isinstance(block, ir.Index):
            p = self._styled_paragraph("Normal")
            for run in fields.field('INDEX \\c "2" \\z "1033"'):
                p.append(run)
            body.append(p)
        elif isinstance(block, ir.RawPassthrough):
            p = self._styled_paragraph("SourceCode")
            p.append(self._run(block.latex))
            body.append(p)

    def _heading(self, block: ir.Heading, body: _Element) -> None:
        style = _HEADING_STYLE.get(block.level, "Heading5")
        if style == "Heading1":
            self._section_epoch += 1
        p = self._styled_paragraph(style)
        if block.part and block.numbered:
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            numpr = sub(ppr, "w:numPr")
            sub(numpr, "w:ilvl", **{"w:val": "0"})
            sub(numpr, "w:numId", **{"w:val": str(PART_NUM_ID)})
        elif block.numbered and 1 <= block.level <= 4:
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            numpr = sub(ppr, "w:numPr")
            sub(numpr, "w:ilvl", **{"w:val": str(block.level - 1)})
            if block.number_start and not block.appendix:
                # \setcounter{section}{n}: a new instance of the heading scheme
                # starting at the new values; later headings continue in it
                self._heading_num_id = FIRST_LIST_NUM_ID + len(self.list_restarts)
                for ilvl, value in enumerate(block.number_start):
                    self.list_restarts.append(
                        (self._heading_num_id, ilvl, value, HEADING_ABSTRACT_ID))
            num_id = HEADING_APPENDIX_NUM_ID if block.appendix else self._heading_num_id
            sub(numpr, "w:numId", **{"w:val": str(num_id)})
        start = None
        if block.label:
            start = fields.bookmark_start(_bookmark_for(block.label))
            p.append(start)
        self._inlines(block.inlines, p)
        if start is not None:
            p.append(fields.bookmark_end_for(start))
        body.append(p)

    def _math_block(self, block: ir.MathBlock, body: _Element) -> None:
        # top-level numbered align/eqnarray keep per-line numbers; everything
        # else (align*, aligned, single-numbered equation) collapses to one
        # column-aligned matrix so the lines line up at the & relation.
        collapse = not (block.numbered and block.env in _MULTILINE_NUMBERED_ENVS)
        result = self.math.block(block.latex, collapse_align=collapse)
        if result.path == "image" and result.image is not None:
            data, fmt = result.image
            p = self._styled_paragraph("Normal")
            self._set_align(p, "center")
            r = el("w:r")
            r.append(self._embed_image_bytes(data, fmt, "equation"))
            p.append(r)
            body.append(p)
            return
        if result.path == "raw" or result.omath is None:
            p = self._styled_paragraph("Normal")
            p.append(self._run(f"\\[{block.latex}\\]", italic=True))
            body.append(p)
            return

        tags = block.line_tags
        # a block that carries one number (equation, a collapsed align, every
        # line of a multline) takes the tag of whichever line has one
        lines = len(result.omath)
        multline = block.env.startswith("multline") and lines > 1
        whole_tag = next((t for t in tags if t), None)
        if whole_tag is None and "" in tags:
            whole_tag = ""
        for idx, omath in enumerate(result.omath):
            label = None
            if multline:
                # multline numbers its last line only, and that line takes the label
                last = idx == lines - 1
                tag = whole_tag if last else ""
                label = (block.label or next((x for x in block.line_labels if x), None)
                         if last else None)
            elif lines == 1 and len(tags) > 1:
                tag = whole_tag
            else:
                tag = tags[idx] if idx < len(tags) else None
            if tag or (block.numbered and tag is None):
                body.append(self._numbered_equation(omath, block, idx, tag,
                                                    label_override=label if multline else None,
                                                    no_label=multline and label is None))
            else:
                p = self._styled_paragraph("Normal")
                para = el("m:oMathPara")
                para.append(omath)
                p.append(para)
                body.append(p)

    def _numbered_equation(self, omath: _Element, block: ir.MathBlock, idx: int,
                           tag: str | None = None, label_override: str | None = None,
                           no_label: bool = False) -> _Element:
        p = el("w:p")
        ppr = sub(p, "w:pPr")
        tabs = sub(ppr, "w:tabs")
        sub(tabs, "w:tab", **{"w:val": "center", "w:pos": "4680"})
        sub(tabs, "w:tab", **{"w:val": "right", "w:pos": "9360"})
        # tab -> equation -> tab -> (SEQ)
        p.append(self._tab_run())
        p.append(omath)
        p.append(self._tab_run())
        # \tag{A} prints "(A)", \tag*{A} prints "A"; the bookmark holds what
        # \ref prints ("A"), and \eqref adds the parentheses
        tagged = tag is not None and tag.startswith("(") and tag.endswith(")")
        if tag is None or tagged:
            p.append(self._run("("))
        # each numbered line bookmarks its own \label (so \ref to any line
        # resolves); a single equation / external \label falls back to block.label.
        if label_override or no_label:
            line_label = label_override
        elif idx < len(block.line_labels):
            line_label = block.line_labels[idx]
        else:
            line_label = block.label if idx == 0 and not block.line_labels else None
        start = None
        if line_label:
            start = fields.bookmark_start(_bookmark_for(line_label))
            p.append(start)
        if tag is None:
            for run in self._number_runs("Equation", self.number_by_section):
                p.append(run)
        else:
            p.append(self._run(tag[1:-1] if tagged else tag))
        if start is not None:
            p.append(fields.bookmark_end_for(start))
        if tag is None or tagged:
            p.append(self._run(")"))
        return p

    def _list(
        self, block: ir.ItemList, body: _Element, level: int = 0,
        parent_num: int | None = None,
    ) -> None:
        if block.description:
            for item in block.items:
                self._description_item(item, body, level)
            return
        if not block.ordered:
            num_id = BULLET_NUM_ID
        elif parent_num is not None and block.start == 1:
            # nested in an ordered list: the parent's instance, whose deeper
            # level restarts at each parent item -- (a), (b) under every item
            num_id = parent_num
        else:
            # its own instance, so the list restarts at 1 (or at its start=)
            num_id = FIRST_LIST_NUM_ID + len(self.list_restarts)
            self.list_restarts.append((num_id, level, block.start))
        for item in block.items:
            self._list_item(item, body, level, num_id)

    def _list_item(self, item: ir.ListItem, body: _Element, level: int, num_id: int) -> None:
        if item.term:  # a custom \item[label] -> show the label, suppress the bullet
            self._description_item(item, body, level)
            return
        marked = False
        # If the item leads with a nested list (no leading text of its own — e.g.
        # an exam question whose \parts follow immediately), emit an empty
        # numbered paragraph first so the item's own number ("1.") renders ABOVE
        # the nested (a)/(b)/(c), rather than being deferred onto a later
        # trailing paragraph (which left the sub-list looking unnumbered).
        first_structural = next(
            (b for b in item.blocks if isinstance(b, (ir.Paragraph, ir.ItemList))), None
        )
        if isinstance(first_structural, ir.ItemList):
            p = self._styled_paragraph("Normal")
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            numpr = sub(ppr, "w:numPr")
            sub(numpr, "w:ilvl", **{"w:val": str(level)})
            sub(numpr, "w:numId", **{"w:val": str(num_id)})
            self._bookmark_list_item(item, p)
            body.append(p)
            marked = True
        ordered_parent = num_id != BULLET_NUM_ID
        for inner in item.blocks:
            if isinstance(inner, ir.ItemList):
                self._list(inner, body, level + 1,
                           parent_num=num_id if ordered_parent else None)
                continue
            if not isinstance(inner, ir.Paragraph):
                self._block(inner, body)
                continue
            p = self._styled_paragraph("Normal")
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            if not marked:
                numpr = sub(ppr, "w:numPr")
                sub(numpr, "w:ilvl", **{"w:val": str(level)})
                sub(numpr, "w:numId", **{"w:val": str(num_id)})
                # bookmark the numbered paragraph so \ref to \item\label{} resolves
                # to its list number (a REF \r field).
                self._bookmark_list_item(item, p)
                marked = True
            else:
                sub(ppr, "w:ind", **{"w:left": str((level + 1) * 360)})
            self._inlines(inner.inlines, p)
            body.append(p)
        if not marked:
            p = self._styled_paragraph("Normal")
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            numpr = sub(ppr, "w:numPr")
            sub(numpr, "w:ilvl", **{"w:val": str(level)})
            sub(numpr, "w:numId", **{"w:val": str(num_id)})
            self._bookmark_list_item(item, p)
            body.append(p)

    def _bookmark_list_item(self, item: ir.ListItem, p: _Element) -> None:
        """Wrap a numbered list-item paragraph in its label bookmark, if any."""
        if not item.label:
            return
        start = fields.bookmark_start(_bookmark_for(item.label))
        p.append(start)
        p.append(fields.bookmark_end_for(start))

    def _description_item(self, item: ir.ListItem, body: _Element, level: int) -> None:
        p = self._styled_paragraph("Normal")
        ppr = p.find(_qn("w:pPr"))
        assert ppr is not None
        sub(ppr, "w:ind", **{"w:left": str((level + 1) * 360)})
        if item.term:
            for t in item.term:
                self._inline_styled(t, p, "bold")
            p.append(self._run("  "))
        first_para = next((b for b in item.blocks if isinstance(b, ir.Paragraph)), None)
        if first_para is not None:
            self._inlines(first_para.inlines, p)
        body.append(p)
        for inner in item.blocks:
            if inner is first_para:
                continue
            if isinstance(inner, ir.ItemList):
                self._list(inner, body, level + 1)
            else:
                self._block(inner, body)

    def _table(self, block: ir.Table, body: _Element) -> None:
        # a caption (and a panel's "(a) ..." line) written above the tabular
        if block.caption is not None and block.caption_above:
            body.append(self._caption("Table", block.caption, block.label,
                                      numbered=block.caption_numbered))
        if block.subcaption and block.subcaption_above:
            sp = self._styled_paragraph("Caption")
            self._set_align(sp, "center")
            self._inlines(block.subcaption, sp)
            body.append(sp)
        tbl = el("w:tbl")
        tpr = sub(tbl, "w:tblPr")
        ncols = max((sum(c.colspan for c in r.cells) for r in block.rows), default=1)
        if block.layout:
            # side-by-side minipages: a borderless grid spanning the text column
            sub(tpr, "w:tblW", **{"w:w": "5000", "w:type": "pct"})
            borders = sub(tpr, "w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                sub(borders, f"w:{side}", **{"w:val": "nil"})
            col_tw = int(self.text_width_emu / 635 / max(ncols, 1))
            widths: list[int | None] = [col_tw] * ncols
        else:
            sub(tpr, "w:tblW", **{"w:w": "0", "w:type": "auto"})
            borders = sub(tpr, "w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                sub(borders, f"w:{side}", **{"w:val": "single", "w:sz": "4", "w:color": "auto"})
            # p{width} column widths -> twips (dxa); 914400 EMU = 1440 twips.
            widths = [int(w / 635) if w else None for w in block.colwidths]
        grid = sub(tbl, "w:tblGrid")
        for i in range(ncols):
            w = widths[i] if i < len(widths) else None
            sub(grid, "w:gridCol", **({"w:w": str(w)} if w else {}))

        # remaining vertical-merge continuations keyed by starting column index ->
        # (rows still to merge, colspan of the merged cell). The colspan must come
        # from the originating cell, not the current row's cell, so a cell that is
        # both \multicolumn and \multirow continues with the right grid width.
        vmerge_pending: dict[int, tuple[int, int]] = {}
        for row in block.rows:
            tr = sub(tbl, "w:tr")
            if row.is_header:
                trpr = sub(tr, "w:trPr")
                sub(trpr, "w:tblHeader")  # repeat header on each page
            col = 0
            for cell in row.cells:
                pending = vmerge_pending.get(col)
                if pending and pending[0] > 0:
                    remaining, merged_colspan = pending
                    self._merge_continue_cell(tr, merged_colspan)
                    vmerge_pending[col] = (remaining - 1, merged_colspan)
                    col += merged_colspan
                    continue
                span_w = sum(
                    widths[c] or 0 for c in range(col, col + cell.colspan) if c < len(widths)
                )
                self._table_cell(tr, cell, width=span_w or None)
                if cell.rowspan > 1:
                    vmerge_pending[col] = (cell.rowspan - 1, cell.colspan)
                col += cell.colspan
        body.append(tbl)
        if block.subcaption and not block.subcaption_above:
            sp = self._styled_paragraph("Caption")
            self._set_align(sp, "center")
            self._inlines(block.subcaption, sp)
            body.append(sp)
        if block.caption is not None and not block.caption_above:
            body.append(self._caption("Table", block.caption, block.label,
                                      numbered=block.caption_numbered))

    def _table_cell(self, tr: _Element, cell: ir.TableCell, width: int | None = None) -> None:
        tc = sub(tr, "w:tc")
        tcpr = sub(tc, "w:tcPr")
        # CT_TcPr child order: tcW, gridSpan, vMerge, ..., shd
        if width:
            sub(tcpr, "w:tcW", **{"w:w": str(width), "w:type": "dxa"})
        if cell.colspan > 1:
            sub(tcpr, "w:gridSpan", **{"w:val": str(cell.colspan)})
        if cell.rowspan > 1:
            sub(tcpr, "w:vMerge", **{"w:val": "restart"})
        if cell.border_bottom:  # partial \cmidrule/\cline rule under this cell
            borders = sub(tcpr, "w:tcBorders")
            sub(borders, "w:bottom",
                **{"w:val": "single", "w:sz": "4", "w:space": "0", "w:color": "auto"})
        if cell.shade:
            sub(tcpr, "w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": cell.shade})
        last_is_para = False
        for cb in cell.blocks:
            if isinstance(cb, ir.Paragraph):
                p = self._styled_paragraph("Normal")
                self._set_align(p, cell.align)
                self._inlines(cb.inlines, p)
                tc.append(p)
                last_is_para = True
            else:  # nested tables and other block content
                self._block(cb, tc)
                last_is_para = False
        # a table cell must end with a paragraph (Word/ECMA-376 requirement)
        if not last_is_para:
            tc.append(self._styled_paragraph("Normal"))

    def _merge_continue_cell(self, tr: _Element, colspan: int) -> None:
        tc = sub(tr, "w:tc")
        tcpr = sub(tc, "w:tcPr")
        if colspan > 1:
            sub(tcpr, "w:gridSpan", **{"w:val": str(colspan)})
        sub(tcpr, "w:vMerge")  # continue the merge
        tc.append(self._styled_paragraph("Normal"))

    def _figure(self, block: ir.Figure, body: _Element) -> None:
        # wrap in a tagged block SDT so the round-trip reader recovers one
        # ir.Figure even when sub-figures render as a table grid (else they read
        # back as a Table + paragraphs).
        sdt = el("w:sdt")
        sub(sub(sdt, "w:sdtPr"), "w:tag", **{"w:val": FIG_SDT_TAG})
        content = sub(sdt, "w:sdtContent")
        if block.subfigures:
            self._subfigures(block, content)
        elif block.image is None and block.blocks:
            # a graphic-less figure (boxes, text, a tabular, …): its body *is*
            # the figure content, rendered above the caption.
            for inner in block.blocks:
                self._block(inner, content)
        elif block.image is None:
            # No convertible graphic (e.g. a TikZ picture): compile it to an image
            # if a TeX engine is available, else fall back to a caption-only figure
            # (no developer-facing placeholder text in the document).
            for rendered in self._render_tikz(block):
                content.append(rendered)
        else:
            content.append(self._image_paragraph(block.image))
        if block.caption is not None:
            bookmark = _figure_bookmark(block)
            content.append(
                self._caption("Figure", block.caption, block.label, bookmark=bookmark,
                              numbered=block.caption_numbered)
            )
        body.append(sdt)

    def _render_tikz(self, block: ir.Figure) -> list[_Element]:
        """Compile each of a figure's TikZ/PGF pictures to an embedded PNG.

        A figure may stack several pictures (two ``\\input`` TikZ files in one
        ``figure*``): each becomes its own centred image paragraph, in order.
        """
        if not block.source:
            return []
        try:
            from . import raster, tikz

            pictures = tikz.extract_pictures(block.source)
            results = [
                tikz.render_picture(pic, block.source, self.preamble) for pic in pictures
            ]
        except Exception:  # never let a render bug abort the conversion
            return []
        if not pictures and not any(f"\\begin{{{env}}}" in block.source
                                    for env in tikz.DRAWING_ENVS):
            return []  # no drawing at all: the parser already reported the figure
        if not pictures or any(r is None for r in results):
            # Be specific about why so the user can fix their setup.
            if not pictures:
                reason = "no recognised TikZ/PGF picture in the figure"
            elif not tikz.available_engines():
                reason = "no TeX engine on PATH (install e.g. xelatex/pdflatex)"
            elif not raster.has_pdf_support():
                reason = "install tex2word[pdf] (pypdfium2) to rasterise the compiled figure"
            else:
                reason = "the TikZ compile failed (set TEX2WORD_TIKZ_DEBUG=1 to see the log)"
            self.report.warn("figure", f"TikZ figure not rendered: {reason}")
        out: list[_Element] = []
        for result in results:
            if result is None:
                continue
            data, w, h = result
            self.report.info("figure", "rendered TikZ figure to an image")
            p = self._styled_paragraph("Normal")
            self._set_align(p, "center")
            r = el("w:r")
            r.append(self._register_and_draw(data, images.ImageInfo("png", w, h), "tikz.png"))
            p.append(r)
            out.append(p)
        return out

    def _subfigures(self, block: ir.Figure, body: _Element) -> None:
        # Sub-figures sit side by side in a borderless 1-row table; each cell
        # holds the (width-scaled) image and its "(a)" sub-caption.
        subs = block.subfigures
        ncols = max(len(subs), 1)
        col_emu = int(self.text_width_emu / ncols) - 90000  # small inter-cell gap
        tbl = el("w:tbl")
        tpr = sub(tbl, "w:tblPr")
        sub(tpr, "w:tblW", **{"w:w": "0", "w:type": "auto"})
        sub(tpr, "w:jc", **{"w:val": "center"})
        grid = sub(tbl, "w:tblGrid")
        for _ in range(ncols):
            sub(grid, "w:gridCol")
        tr = sub(tbl, "w:tr")
        for idx, subfig in enumerate(subs):
            letter = chr(ord("a") + idx)
            tc = sub(tr, "w:tc")
            sub(sub(tc, "w:tcPr"), "w:tcW", **{"w:w": "0", "w:type": "auto"})
            if subfig.image is not None:
                tc.append(self._image_paragraph(subfig.image, max_width_emu=col_emu))
            else:
                ph = self._styled_paragraph("Normal")
                self._set_align(ph, "center")
                ph.append(self._run("[sub-figure omitted]", italic=True))
                tc.append(ph)
            cap = self._styled_paragraph("Caption")
            cap.append(self._run(f"({letter}) ", bold=True))
            if subfig.caption:
                self._inlines(subfig.caption, cap)
            tc.append(cap)
        body.append(tbl)

    def _image_paragraph(self, image: ir.Image, max_width_emu: int | None = None) -> _Element:
        p = self._styled_paragraph("Normal")
        self._set_align(p, "center")
        drawing = self._embed_image(image, max_width_emu)
        if drawing is None:
            p.append(self._run(f"[image: {image.path}]", italic=True))
            return p
        r = el("w:r")
        r.append(drawing)
        p.append(r)
        return p

    def _embed_image(self, image: ir.Image, max_width_emu: int | None = None) -> _Element | None:
        import os

        path = self._resolve_image_path(image.path)
        if path is None:
            self.report.warn("includegraphics", f"image file not found: {image.path}")
            return None
        fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        name = os.path.basename(path)

        info = images.probe(path)
        if info is not None and info.embeddable:
            with open(path, "rb") as fh:
                data = fh.read()
            return self._register_and_draw(data, info, name, max_width_emu, image)

        # vector formats (PDF/EPS): rasterise to PNG when a backend is available.
        if fmt in ("pdf", "eps", "ps"):
            result = raster.rasterize(path, fmt)
            if result is not None:
                data, w, h = result
                self.report.info("includegraphics", f"rasterised {fmt} -> png: {image.path}")
                return self._register_and_draw(
                    data, images.ImageInfo("png", w, h), name, max_width_emu, image
                )
            hint = (
                "install tex2word[pdf]" if fmt == "pdf" and not raster.has_pdf_support()
                else f"{fmt} rasterisation not supported"
            )
            self.report.warn("includegraphics", f"image not embedded ({hint}): {image.path}")
            return None

        self.report.warn("includegraphics", f"unsupported image format '{fmt}': {image.path}")
        return None

    def _resolve_image_path(self, rel: str) -> str | None:
        import os

        path = rel if os.path.isabs(rel) else os.path.join(self.base_dir, rel)
        if os.path.isfile(path):
            return path
        # graphicx resolves a missing extension against known formats.
        base = os.path.splitext(path)[0]
        for candidate in (path, base):
            for ext in (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps"):
                if os.path.isfile(candidate + ext):
                    return candidate + ext
        return None

    def _embed_image_bytes(self, data: bytes, fmt: str, name: str) -> _Element:
        info = images.probe_bytes(data, fmt)
        return self._register_and_draw(data, info, name)

    def _register_and_draw(
        self, data: bytes, info: images.ImageInfo, name: str,
        max_width_emu: int | None = None, image: ir.Image | None = None,
    ) -> _Element:
        # dedup identical image bytes -> one media part + one relationship,
        # referenced by every drawing that uses it.
        key = hashlib.sha1(data).hexdigest()
        cached = self._media_by_hash.get(key)
        if cached is not None:
            rel_id, _ = cached
        else:
            self._image_counter += 1
            n = self._image_counter
            ext = info.fmt if info.fmt != "jpg" else "jpeg"
            rel_id = f"rIdImg{n}"
            self.media[f"word/media/image{n}.{ext}"] = data
            self.document_rels.append(
                f'<Relationship Id="{rel_id}" Type="{_IMAGE_REL_TYPE}" '
                f'Target="media/image{n}.{ext}"/>'
            )
            self._media_by_hash[key] = (rel_id, n)
        # each drawing instance needs a unique wp:docPr id
        self._drawing_counter += 1
        draw_id = self._drawing_counter
        cx, cy = self._image_extent(info, image, max_width_emu)
        rot = self._rotation(image)
        src_rect = self._src_rect(info, image)
        alt = (image.alt if image and image.alt else name)
        return self._drawing(rel_id, cx, cy, draw_id, name, rot=rot, src_rect=src_rect, alt=alt)

    def _text_box_emu(self) -> tuple[int, int]:
        """The output page's text column (width, height) in EMU, from the
        reference-doc / default page size and margins (twips -> EMU)."""
        _EMU_PER_TWIP = 635
        pgsz = self.page_pgsz or {"w:w": "12240", "w:h": "15840"}
        pgmar = self.page_pgmar or {
            "w:top": "1440", "w:right": "1440", "w:bottom": "1440", "w:left": "1440",
        }

        def tw(d: dict, key: str) -> int:
            try:
                return int(d.get(key, "0"))
            except (TypeError, ValueError):
                return 0

        w = tw(pgsz, "w:w") - tw(pgmar, "w:left") - tw(pgmar, "w:right")
        h = tw(pgsz, "w:h") - tw(pgmar, "w:top") - tw(pgmar, "w:bottom")
        return max(w, 1440) * _EMU_PER_TWIP, max(h, 1440) * _EMU_PER_TWIP

    def _image_extent(
        self, info: images.ImageInfo, image: ir.Image | None, max_width_emu: int | None
    ) -> tuple[int, int]:
        """Final (cx, cy) in EMU. Resolves relative widths/heights against the
        page's text box, honours ``keepaspectratio`` for a width+height box, then
        clamps to the text column (or ``max_width_emu`` for a sub-figure cell)."""
        nat_cx = info.width_px * images.EMU_PER_PX
        nat_cy = info.height_px * images.EMU_PER_PX
        w = image.width if image else None
        h = image.height if image else None
        if image and image.rel_width:
            w = image.rel_width * self.text_width_emu
        if image and image.rel_height:
            h = image.rel_height * self.text_height_emu
        scale = image.scale if image else None
        keep = bool(image and image.keep_aspect)
        if w and h:
            if keep and nat_cx and nat_cy:
                f = min(w / nat_cx, h / nat_cy)  # fit inside the box, aspect kept
                cx, cy = nat_cx * f, nat_cy * f
            else:
                cx, cy = w, h
        elif w:
            cx, cy = w, (nat_cy * w / nat_cx if nat_cx else nat_cy)
        elif h:
            cx, cy = (nat_cx * h / nat_cy if nat_cy else nat_cx), h
        elif scale:
            cx, cy = nat_cx * scale, nat_cy * scale
        else:
            limit = max_width_emu if max_width_emu is not None else self.text_width_emu
            return images.emu_size(info, limit)
        limit = max_width_emu if max_width_emu is not None else self.text_width_emu
        if cx > limit:
            cy *= limit / cx
            cx = limit
        return int(cx), int(cy)

    @staticmethod
    def _rotation(image: ir.Image | None) -> int | None:
        if not image or not image.angle:
            return None
        # OOXML rot is 1/60000 deg, clockwise; LaTeX angle is counter-clockwise.
        return int(round((-image.angle % 360) * 60000))

    @staticmethod
    def _src_rect(info: images.ImageInfo, image: ir.Image | None) -> dict[str, str] | None:
        # graphicx only actually crops the trimmed region when `clip` is given;
        # trim alone shifts the box. srcRect always crops, so gate it on clip.
        if not image or not image.trim or not image.clip:
            return None
        nat_cx = info.width_px * images.EMU_PER_PX or 1
        nat_cy = info.height_px * images.EMU_PER_PX or 1
        left, bottom, right, top = image.trim  # graphicx order: l b r t
        # a:srcRect insets are in 1000ths of a percent of the natural dimension.
        return {
            "l": str(int(left / nat_cx * 100000)),
            "t": str(int(top / nat_cy * 100000)),
            "r": str(int(right / nat_cx * 100000)),
            "b": str(int(bottom / nat_cy * 100000)),
        }

    def _drawing(self, rel_id: str, cx: int, cy: int, n: int, name: str, *,
                 rot: int | None = None, src_rect: dict[str, str] | None = None,
                 alt: str = "") -> _Element:
        drawing = el("w:drawing")
        inline = sub(drawing, "wp:inline", **{
            "distT": "0", "distB": "0", "distL": "0", "distR": "0",
        })
        sub(inline, "wp:extent", cx=str(cx), cy=str(cy))
        sub(inline, "wp:docPr", id=str(n), name=f"Picture {n}", descr=alt)
        frame = sub(inline, "wp:cNvGraphicFramePr")
        sub(frame, "a:graphicFrameLocks", noChangeAspect="1")
        graphic = sub(inline, "a:graphic")
        gdata = sub(graphic, "a:graphicData", uri=_PIC_URI)
        pic = sub(gdata, "pic:pic")
        nv = sub(pic, "pic:nvPicPr")
        sub(nv, "pic:cNvPr", id="0", name=name, descr=alt)
        sub(nv, "pic:cNvPicPr")
        blipfill = sub(pic, "pic:blipFill")
        sub(blipfill, "a:blip", **{"r:embed": rel_id})
        if src_rect is not None:
            sub(blipfill, "a:srcRect", **src_rect)
        stretch = sub(blipfill, "a:stretch")
        sub(stretch, "a:fillRect")
        sppr = sub(pic, "pic:spPr")
        xfrm = sub(sppr, "a:xfrm", **({"rot": str(rot)} if rot else {}))
        sub(xfrm, "a:off", x="0", y="0")
        sub(xfrm, "a:ext", cx=str(cx), cy=str(cy))
        geom = sub(sppr, "a:prstGeom", prst="rect")
        sub(geom, "a:avLst")
        return drawing

    def _toc(self, block: ir.TableOfContents, body: _Element) -> None:
        title, code = _TOC_SPEC[block.kind]
        heading = self._styled_paragraph("Normal")
        heading.append(self._run(title, bold=True))
        body.append(heading)
        p = self._styled_paragraph("Normal")
        for run in fields.field(code, "Right-click and Update Field to build this list."):
            p.append(run)
        body.append(p)

    def _number_runs(self, counter: str, by_section: bool) -> list[_Element]:
        """``fields.number_field`` plus an explicit restart on the first
        section-relative number of each counter after a new Heading 1."""
        restart = by_section and self._seq_epoch.get(counter) != self._section_epoch
        if by_section:
            self._seq_epoch[counter] = self._section_epoch
        return fields.number_field(counter, by_section, restart=restart)

    def _caption(
        self,
        counter: str,
        caption: list[ir.Inline],
        label: str | None,
        bookmark: str | None = None,
        numbered: bool = True,
    ) -> _Element:
        p = self._styled_paragraph("Caption")
        if not numbered:
            # \caption*: no counter/SEQ, no "Figure N:" prefix -- just the text.
            self._inlines(caption, p)
            return p
        p.append(self._run(f"{counter} "))
        name = bookmark or (_bookmark_for(label) if label else None)
        start = None
        if name:
            start = fields.bookmark_start(name)
            p.append(start)
        for run in self._number_runs(counter, self.number_by_section):
            p.append(run)
        if start is not None:
            p.append(fields.bookmark_end_for(start))
        p.append(self._run(": "))
        self._inlines(caption, p)
        return p

    def _bibliography(self, block: ir.Bibliography, body: _Element) -> None:
        from ..bib.render import format_reference

        if not block.entries:
            return
        # wrap the whole reference list in a tagged block SDT so the round-trip
        # reader recovers it as one ir.Bibliography (not heading + paragraphs).
        sdt = el("w:sdt")
        sdtpr = sub(sdt, "w:sdtPr")
        sub(sdtpr, "w:tag", **{"w:val": BIB_SDT_TAG})
        content = sub(sdt, "w:sdtContent")
        heading = self._styled_paragraph("Heading1")
        heading.append(self._run("References"))
        content.append(heading)
        zotero = self.citation_mode == "zotero"
        for i, item in enumerate(block.entries, start=1):
            p = self._styled_paragraph("Bibliography")
            start = fields.bookmark_start(_bookmark_for("bib_" + item.id))
            p.append(start)
            if i == 1 and zotero:
                from ..bib.zotero import bibliography_field_runs

                for run in bibliography_field_runs([]):
                    p.append(run)
            if block.style == "numeric":
                p.append(self._run(f"[{i}]\t"))
            p.append(self._run(format_reference(item)))
            p.append(fields.bookmark_end_for(start))
            content.append(p)
        body.append(sdt)

    def _code_block(self, block: ir.CodeBlock, body: _Element) -> None:
        if block.caption or block.label:
            # lstlisting caption=/label=: "Listing N: ..." above the code
            body.append(self._caption("Listing", block.caption or [], block.label,
                                      numbered=block.caption_numbered))
        for line in block.text.split("\n"):
            p = self._styled_paragraph("SourceCode")
            p.append(self._run(line))
            body.append(p)

    def _callout(self, block: ir.Quote, body: _Element) -> None:
        """A coloured callout box (a `\\newmdenv`): a full-width single-cell table
        with a coloured border and background fill holding the box's content."""
        tbl = el("w:tbl")
        tpr = sub(tbl, "w:tblPr")
        sub(tpr, "w:tblW", **{"w:w": "5000", "w:type": "pct"})
        # CT_TblPr order: tblW -> tblBorders -> tblCellMar.
        borders = sub(tpr, "w:tblBorders")
        color = block.border or "auto"
        for side in ("top", "bottom", "left", "right"):
            sub(borders, f"w:{side}", **{"w:val": "single", "w:sz": "8", "w:color": color})
        for side in ("insideH", "insideV"):
            sub(borders, f"w:{side}", **{"w:val": "nil"})
        cellmar = sub(tpr, "w:tblCellMar")
        for side, w in (("top", "60"), ("bottom", "60"), ("left", "108"), ("right", "108")):
            sub(cellmar, f"w:{side}", **{"w:w": w, "w:type": "dxa"})
        sub(sub(tbl, "w:tblGrid"), "w:gridCol")
        if block.title:
            # tcolorbox title bar: its own shaded row above the body
            ttc = sub(sub(tbl, "w:tr"), "w:tc")
            if block.title_shade:
                ttcpr = sub(ttc, "w:tcPr")
                sub(ttcpr, "w:shd", **{"w:val": "clear", "w:color": "auto",
                                        "w:fill": block.title_shade})
            tp = self._styled_paragraph("Normal")
            self._inlines(block.title, tp)
            ttc.append(tp)
        tc = sub(sub(tbl, "w:tr"), "w:tc")
        if block.shade:
            tcpr = sub(tc, "w:tcPr")
            sub(tcpr, "w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": block.shade})
        for inner in block.blocks:
            self._block(inner, tc, default_style="Normal")
        # a table cell must end with a paragraph (not a table or nothing)
        if tc.find(_qn("w:p")) is None or not len(tc):
            tc.append(self._styled_paragraph("Normal"))
        elif tc[-1].tag != _qn("w:p"):
            tc.append(self._styled_paragraph("Normal"))
        body.append(tbl)

    def _algorithm(self, block: ir.Algorithm, body: _Element) -> None:
        # Render in a "ruled" box: a full-width single-cell table with only top
        # and bottom borders, the caption ruled off from the body.
        tbl = el("w:tbl")
        tpr = sub(tbl, "w:tblPr")
        sub(tpr, "w:tblW", **{"w:w": "5000", "w:type": "pct"})
        borders = sub(tpr, "w:tblBorders")
        for side in ("top", "bottom"):
            sub(borders, f"w:{side}", **{"w:val": "single", "w:sz": "12", "w:color": "auto"})
        for side in ("left", "right", "insideH", "insideV"):
            sub(borders, f"w:{side}", **{"w:val": "nil"})
        sub(sub(tbl, "w:tblGrid"), "w:gridCol")
        tc = sub(sub(tbl, "w:tr"), "w:tc")

        if block.caption is not None or block.label:
            cap = self._styled_paragraph("Caption")
            # a rule under the caption
            cap_ppr = cap.find(_qn("w:pPr"))
            assert cap_ppr is not None
            pbdr = sub(cap_ppr, "w:pBdr")
            sub(pbdr, "w:bottom", **{
                "w:val": "single", "w:sz": "6", "w:space": "2", "w:color": "auto",
            })
            cap.append(self._run("Algorithm ", bold=True))
            start = None
            if block.label:
                start = fields.bookmark_start(_bookmark_for(block.label))
                cap.append(start)
            for run in self._number_runs("Algorithm", self.number_by_section):
                cap.append(run)
            if start is not None:
                cap.append(fields.bookmark_end_for(start))
            cap.append(self._run(": ", bold=True))
            if block.caption:
                self._inlines(block.caption, cap)
            tc.append(cap)
        # numbered, indented pseudocode lines
        line_no = 0
        every = block.line_numbers  # 0: none; n: every n-th line shows its number
        for aline in block.lines:
            p = self._styled_paragraph("SourceCode")
            ppr = p.find(_qn("w:pPr"))
            assert ppr is not None
            sub(ppr, "w:ind", **{"w:left": str(360 + aline.indent * 360)})
            if every and aline.number:
                line_no += 1
                p.append(self._run(f"{line_no:>2}: " if line_no % every == 0 else "    "))
            self._inlines(aline.inlines, p)
            tc.append(p)
        if not block.lines:
            tc.append(self._styled_paragraph("SourceCode"))
        body.append(tbl)

    def _theorem(self, block: ir.Theorem, body: _Element) -> None:
        blocks = block.blocks or [ir.Paragraph([])]
        p = self._styled_paragraph("Normal")
        self._write_theorem_prefix(block, p)
        if isinstance(blocks[0], ir.Paragraph):
            self._inlines(blocks[0].inlines, p)
            rest = blocks[1:]
        else:
            rest = blocks
        body.append(p)
        for inner in rest:
            self._block(inner, body)
        if block.kind == "Proof":
            self._append_qed(body)

    def _write_theorem_prefix(self, block: ir.Theorem, p: _Element) -> None:
        is_proof = block.kind == "Proof"
        emphasis = "italic" if is_proof else "bold"
        flag = {emphasis: True}
        p.append(self._run(block.kind, **flag))  # type: ignore[arg-type]
        if block.counter:
            p.append(self._run(" ", **flag))  # type: ignore[arg-type]
            start = None
            if block.label:
                start = fields.bookmark_start(_bookmark_for(block.label))
                p.append(start)
            # \newtheorem{thm}{Theorem}[section] numbers "section.n" even
            # when the document's figures/equations are numbered flat
            by_section = self.number_by_section or block.within in ("section", "chapter")
            for run in self._number_runs(block.counter, by_section):
                p.append(run)
            if start is not None:
                p.append(fields.bookmark_end_for(start))
        if block.title:
            p.append(self._run(" ("))
            for t in block.title:
                self._inline_styled(t, p, emphasis)
            p.append(self._run(")"))
        p.append(self._run(". ", **flag))  # type: ignore[arg-type]

    def _append_qed(self, body: _Element) -> None:
        last = body[-1]
        if last.tag == _qn("w:p"):
            last.append(self._run(" □"))  # em-space + QED box
        else:
            q = self._styled_paragraph("Normal")
            self._set_align(q, "right")
            q.append(self._run("□"))
            body.append(q)

    # -- inline ----------------------------------------------------------- #

    def _inlines(self, inlines: list[ir.Inline], p: _Element) -> None:
        for node in inlines:
            self._inline(node, p)

    def _inline(self, node: ir.Inline, p: _Element) -> None:
        self._emit(node, p, _RunStyle())

    def _inline_styled(self, node: ir.Inline, p: _Element, kind: str) -> None:
        self._emit(node, p, _RunStyle().with_flag(_STYLE_FLAG[kind]))

    def _emit(self, node: ir.Inline, p: _Element, st: _RunStyle) -> None:  # noqa: C901
        # leaf + style-carrying nodes thread the accumulated run style; the rest
        # (math, refs, links, ...) render once and ignore inline styling.
        if isinstance(node, ir.Text):
            p.append(self._run(node.value, **st.kwargs()))
        elif isinstance(node, ir.Emphasis):
            st2 = st.with_flag(_STYLE_FLAG[node.kind_])
            for child in node.inlines:
                self._emit(child, p, st2)
        elif isinstance(node, ir.Colored):
            st2 = _replace(st, color=node.fg or st.color, shade=node.bg or st.shade)
            for child in node.inlines:
                self._emit(child, p, st2)
        elif isinstance(node, ir.FontSize):
            st2 = _replace(st, size=node.half_points)
            for child in node.inlines:
                self._emit(child, p, st2)
        elif isinstance(node, ir.RawInline):
            p.append(self._run(node.latex, **_replace(st, italic=True).kwargs()))
        elif isinstance(node, ir.LineBreak):
            r = el("w:r")
            sub(r, "w:br")
            p.append(r)
        elif isinstance(node, ir.Image):
            drawing = self._embed_image(node)
            if drawing is not None:
                r = el("w:r")
                r.append(drawing)
                p.append(r)
        elif isinstance(node, ir.Math):
            self._inline_math(node, p, st)
        elif isinstance(node, ir.Ref):
            self._ref(node, p)
        elif isinstance(node, ir.Cite):
            self._cite(node, p)
        elif isinstance(node, ir.Link):
            self._link(node, p)
        elif isinstance(node, ir.Footnote):
            self._footnote(node, p)
        elif isinstance(node, ir.Endnote):
            self._endnote(node, p)
        elif isinstance(node, ir.Comment):
            self._comment(node, p)
        elif isinstance(node, ir.IndexEntry):
            for run in fields.index_entry(node.term):
                p.append(run)

    def _comment(self, node: ir.Comment, p: _Element) -> None:
        self._comment_counter += 1
        cid = str(self._comment_counter)
        # a point anchor in the body: empty range + a reference mark
        sub(p, "w:commentRangeStart", **{"w:id": cid})
        sub(p, "w:commentRangeEnd", **{"w:id": cid})
        sub(sub(p, "w:r"), "w:commentReference", **{"w:id": cid})
        # the comment body (lives in comments.xml)
        cp = self._styled_paragraph("Normal")
        self._inlines([ir.Text(node.text)], cp)
        attrs = {"w:id": cid, "w:author": node.author or "tex2word",
                 "w:date": "2026-01-01T00:00:00Z"}
        self._comments.append(el("w:comment", cp, **attrs))

    def comments_xml(self) -> bytes | None:
        """Return ``word/comments.xml`` bytes, or None if there are no comments."""
        if not self._comments:
            return None
        root = el("w:comments")
        for c in self._comments:
            root.append(c)
        return serialize(root)

    def _inline_math(self, node: ir.Math, p: _Element, st: _RunStyle | None = None) -> None:
        result = self.math.inline(node.latex)
        if result.path == "omml" and result.omath:
            omath = result.omath[0]
            if st is not None and (st.color or st.size):
                _style_math_runs(omath, st.color, st.size)
            p.append(omath)
        elif result.path == "image" and result.image is not None:
            data, fmt = result.image
            p.append(self._embed_image_bytes(data, fmt, "math"))
        else:
            kw = st.kwargs() if st is not None else {}
            kw["italic"] = True
            p.append(self._run(f"${node.latex}$", **kw))

    def _ref(self, node: ir.Ref, p: _Element) -> None:
        if node.bookmark is None:
            p.append(self._run("??"))
            return
        if node.style in ("abbrev", "full", "auto") or node.more:
            self._named_ref(node, p)
            return
        self._ref_number(node.bookmark, node.ref_kind, node.style == "eqref", p)

    def _ref_number(self, bookmark: str, kind: str, parens: bool, p: _Element) -> None:
        """The number of one target as a field ("(3)" for an equation in parens)."""
        if kind == "page":
            runs = fields.pageref_field(bookmark, "0")
        elif kind in ("section", "listitem"):
            # \r inserts the paragraph's (list) number -- section numbers and the
            # auto-numbered list item that an \item\label{} sits on.
            runs = fields.ref_field(bookmark, "0", paragraph_number=True)
        else:
            runs = fields.ref_field(bookmark, "0")
        parens = parens and kind == "equation"
        if parens:
            p.append(self._run("("))
        for run in runs:
            p.append(run)
        if parens:
            p.append(self._run(")"))

    def _named_ref(self, node: ir.Ref, p: _Element) -> None:
        """cleveref's ``\\cref``/``\\Cref``/``\\crefrange``/``\\labelcref`` and
        hyperref's ``\\autoref``: type names (singular or plural per group of
        consecutive same-type targets) and the numbers, equations in parens."""
        named = node.style in ("abbrev", "full", "auto")
        parens = node.style != "auto"  # cleveref formats equations as "(1)"
        keys = [node.key, *node.more]
        targets = [(k, self._labels.get(k)) for k in keys]

        def number(key: str, info: ir.LabelInfo | None) -> None:
            if info is None:
                p.append(self._run("??"))
                return
            kind = "page" if node.ref_kind == "page" else info.kind
            self._ref_number(info.bookmark, kind, parens, p)
            if info.sub and kind in ("figure", "table"):
                p.append(self._run(info.sub))

        if node.is_range and len(targets) == 2:
            if named:
                p.append(self._run(self._ref_name(node, targets[0][1], plural=True) + " "))
            number(*targets[0])
            p.append(self._run(" to "))
            number(*targets[1])
            return
        groups: list[list[tuple[str, ir.LabelInfo | None]]] = []
        for key, info in targets:
            t = self._type_key(node, info)
            if groups and self._type_key(node, groups[-1][0][1]) == t:
                groups[-1].append((key, info))
            else:
                groups.append([(key, info)])
        for gi, group in enumerate(groups):
            if gi:
                p.append(self._run(" and " if gi == len(groups) - 1 else ", "))
            if named:
                p.append(self._run(self._ref_name(node, group[0][1], len(group) > 1) + " "))
            for i, (key, info) in enumerate(group):
                if i:
                    p.append(self._run(" and " if i == len(group) - 1 else ", "))
                number(key, info)

    @staticmethod
    def _type_key(node: ir.Ref, info: ir.LabelInfo | None) -> str:
        if node.ref_kind == "page":
            return "page"
        if info is None:
            return "?"
        if info.ref_type == "theorem":
            return "theorem:" + (info.type_name or "")
        return info.ref_type or info.kind

    def _ref_name(self, node: ir.Ref, info: ir.LabelInfo | None, plural: bool) -> str:
        """The type name cleveref (or hyperref's \\autoref) prints."""
        t = self._type_key(node, info)
        theorem = t.startswith("theorem:")
        tname = t.split(":", 1)[1] if theorem else ""
        if node.style == "auto":
            if theorem:
                return tname or "Theorem"
            return _AUTOREF_NAMES.get(t, t.capitalize())
        options = set(self._cref.get("options", []))
        full = node.style == "full"
        # \crefname{type}{..}{..} / \Crefname overrides: the exact type first,
        # then the type it is named after (a subsection is a "section")
        lookup = [tname.lower()] if theorem else [t, _CREF_BASE.get(t, t)]
        table = self._cref.get("Crefname" if full else "crefname", {})
        for key in lookup:
            if key in table:
                return table[key][1 if plural else 0]
        if full:
            for key in lookup:
                if key in self._cref.get("crefname", {}):
                    name = self._cref["crefname"][key][1 if plural else 0]
                    return name[:1].upper() + name[1:]
        if theorem:
            base = tname or "Theorem"
            names = (base.lower(), base.lower() + "s", base, base + "s")
        else:
            names = _CREF_NAMES.get(_CREF_BASE.get(t, t), (t, t + "s", t.capitalize(),
                                                           t.capitalize() + "s"))
            if "noabbrev" in options and t in _CREF_UNABBREV:
                names = _CREF_UNABBREV[t]
        name = names[2 + plural] if full else names[plural]
        if not full and ({"capitalise", "capitalize"} & options):
            name = name[:1].upper() + name[1:]
        return name

    def _cite(self, node: ir.Cite, p: _Element) -> None:
        rendered = node.rendered
        if (
            self.citation_mode == "zotero"
            and rendered is not None
            and any(k in self._cite_items for k in node.keys)
        ):
            from ..bib import zotero

            for run in zotero.citation_field(node, self._cite_items, rendered):
                p.append(run)
            return
        if rendered is not None:
            p.append(self._run(rendered))
            return
        # Fallback when no bibliography is present.
        text = ", ".join(node.keys)
        p.append(self._run(f"[{text}]" if node.mode == "paren" else text))

    def _link(self, node: ir.Link, p: _Element) -> None:
        instr = f'HYPERLINK \\l "{node.anchor}"' if node.anchor else f'HYPERLINK "{node.url}"'
        p.append(fields._fldchar("begin"))
        p.append(fields._instr_run(instr))
        p.append(fields._fldchar("separate"))
        for child in node.inlines:
            self._inline_styled(child, p, "hyperlink")
        p.append(fields._fldchar("end"))

    def _footnote(self, node: ir.Footnote, p: _Element) -> None:
        self._footnote_counter += 1
        note_id = self._footnote_counter
        # reference mark in the body
        r = el("w:r")
        rpr = sub(r, "w:rPr")
        sub(rpr, "w:rStyle", **{"w:val": "FootnoteReference"})
        sub(r, "w:footnoteReference", **{"w:id": str(note_id)})
        p.append(r)
        # the footnote content (lives in footnotes.xml)
        mark = el("w:r")
        mark_rpr = sub(mark, "w:rPr")
        sub(mark_rpr, "w:rStyle", **{"w:val": "FootnoteReference"})
        sub(mark, "w:footnoteRef")
        if node.blocks:
            footnote = el("w:footnote", **{"w:id": str(note_id)})
            for block in node.blocks:
                self._block(block, footnote, default_style="FootnoteText")
            first = footnote.find(_qn("w:p"))
            if first is None or footnote.index(first) != 0:
                first = self._styled_paragraph("FootnoteText")
                footnote.insert(0, first)
            ppr = first.find(_qn("w:pPr"))
            at = 0 if ppr is None else first.index(ppr) + 1
            first.insert(at, mark)
            first.insert(at + 1, self._run(" "))
            self._footnotes.append(footnote)
            return
        fp = self._styled_paragraph("FootnoteText")
        fp.append(mark)
        fp.append(self._run(" "))
        self._inlines(node.inlines, fp)
        footnote = el("w:footnote", fp, **{"w:id": str(note_id)})
        self._footnotes.append(footnote)

    def footnotes_xml(self) -> bytes | None:
        """Return ``word/footnotes.xml`` bytes, or None if there are no notes."""
        if not self._footnotes:
            return None
        root = el("w:footnotes")
        root.append(self._special_footnote("separator", -1, "w:separator"))
        root.append(self._special_footnote("continuationSeparator", 0, "w:continuationSeparator"))
        for footnote in self._footnotes:
            root.append(footnote)
        return serialize(root)

    def _special_footnote(self, kind: str, note_id: int, mark_tag: str) -> _Element:
        p = el("w:p")
        r = el("w:r")
        sub(r, mark_tag)
        p.append(r)
        return el("w:footnote", p, **{"w:type": kind, "w:id": str(note_id)})

    def _endnote(self, node: ir.Endnote, p: _Element) -> None:
        self._endnote_counter += 1
        note_id = self._endnote_counter
        r = el("w:r")
        sub(sub(r, "w:rPr"), "w:rStyle", **{"w:val": "FootnoteReference"})
        sub(r, "w:endnoteReference", **{"w:id": str(note_id)})
        p.append(r)
        ep = self._styled_paragraph("FootnoteText")
        mark = el("w:r")
        sub(sub(mark, "w:rPr"), "w:rStyle", **{"w:val": "FootnoteReference"})
        sub(mark, "w:endnoteRef")
        ep.append(mark)
        ep.append(self._run(" "))
        self._inlines(node.inlines, ep)
        self._endnotes.append(el("w:endnote", ep, **{"w:id": str(note_id)}))

    def endnotes_xml(self) -> bytes | None:
        """Return ``word/endnotes.xml`` bytes, or None if there are no endnotes."""
        if not self._endnotes:
            return None
        root = el("w:endnotes")
        for kind, nid, tag in (
            ("separator", -1, "w:separator"),
            ("continuationSeparator", 0, "w:continuationSeparator"),
        ):
            r = el("w:r")
            sub(r, tag)
            root.append(el("w:endnote", el("w:p", r), **{"w:type": kind, "w:id": str(nid)}))
        for endnote in self._endnotes:
            root.append(endnote)
        return serialize(root)

    # -- run / paragraph primitives -------------------------------------- #

    def _run(self, text: str, *, bold: bool = False, italic: bool = False,
             underline: bool = False, typewriter: bool = False, smallcaps: bool = False,
             hyperlink: bool = False, superscript: bool = False,
             subscript: bool = False, color: str | None = None,
             shade: str | None = None, strike: bool = False,
             highlight: bool = False, size: int | None = None) -> _Element:
        r = el("w:r")
        if any([bold, italic, underline, typewriter, smallcaps, hyperlink,
                superscript, subscript, color, shade, strike, highlight, size]):
            rpr = sub(r, "w:rPr")
            # children must follow the ECMA-376 CT_RPr sequence, else strict
            # validators reject the run: rStyle, rFonts, b, i, smallCaps, strike,
            # color, sz, szCs, highlight, u, shd, vertAlign.
            if hyperlink:
                sub(rpr, "w:rStyle", **{"w:val": "Hyperlink"})
            if typewriter:
                sub(rpr, "w:rFonts", **{"w:ascii": "Consolas", "w:hAnsi": "Consolas"})
            if bold:
                sub(rpr, "w:b")
            if italic:
                sub(rpr, "w:i")
            if smallcaps:
                sub(rpr, "w:smallCaps")
            if strike:
                sub(rpr, "w:strike")
            if color:
                sub(rpr, "w:color", **{"w:val": color})
            if size:
                sub(rpr, "w:sz", **{"w:val": str(size)})
                sub(rpr, "w:szCs", **{"w:val": str(size)})
            if highlight:
                sub(rpr, "w:highlight", **{"w:val": "yellow"})
            if underline:
                sub(rpr, "w:u", **{"w:val": "single"})
            if shade:
                sub(rpr, "w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": shade})
            if superscript:
                sub(rpr, "w:vertAlign", **{"w:val": "superscript"})
            if subscript:
                sub(rpr, "w:vertAlign", **{"w:val": "subscript"})
        t = text_el("w:t", text)
        preserve_space(t)
        r.append(t)
        return r

    def _tab_run(self) -> _Element:
        r = el("w:r")
        sub(r, "w:tab")
        return r

    def _styled_paragraph(self, style: str) -> _Element:
        p = el("w:p")
        ppr = sub(p, "w:pPr")
        sub(ppr, "w:pStyle", **{"w:val": style})
        return p

    def _set_align(self, p: _Element, align: str) -> None:
        if align == "left":
            return
        ppr = p.find(_qn("w:pPr"))
        assert ppr is not None
        jc = {"center": "center", "right": "end"}.get(align, "start")
        sub(ppr, "w:jc", **{"w:val": jc})

    def _sect_pr(self, columns: int | None = None, continuous: bool = False) -> _Element:
        cols = self.columns if columns is None else max(columns, 1)
        sect = el("w:sectPr")
        # CT_SectPr child order: hdr/ftr refs, type, pgSz, pgMar, cols, …, titlePg.
        # Same page size + header/footer refs on every section so continuous breaks
        # (used for full-width figure*/table*) don't force a page break or drop the
        # running head.
        for tag, w_type, rid in self.header_footer_refs:
            sub(sect, f"w:{tag}", **{"w:type": w_type, "r:id": rid})
        if continuous:
            sub(sect, "w:type", **{"w:val": "continuous"})
        pgsz = self.page_pgsz or {"w:w": "12240", "w:h": "15840"}
        pgmar = self.page_pgmar or {
            "w:top": "1440", "w:right": "1440", "w:bottom": "1440",
            "w:left": "1440", "w:header": "720", "w:footer": "720",
        }
        sub(sect, "w:pgSz", **pgsz)
        sub(sect, "w:pgMar", **pgmar)
        # A section with no w:cols is single-column (the schema default), so only a
        # multi-column section needs one; a 1-col region after a break resets to a
        # single column simply by omitting it.
        if cols > 1:
            sub(sect, "w:cols", **{"w:num": str(cols), "w:space": "720"})
        if any(w_type == "first" for _, w_type, _ in self.header_footer_refs):
            sub(sect, "w:titlePg")
        return sect


_STYLE_FLAG = {
    "bold": "bold", "italic": "italic", "underline": "underline",
    "typewriter": "typewriter", "smallcaps": "smallcaps", "hyperlink": "hyperlink",
    "superscript": "superscript", "subscript": "subscript",
    "strike": "strike", "highlight": "highlight",
}


@dataclass(frozen=True)
class _RunStyle:
    """Accumulated character formatting, applied at the text leaf."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    typewriter: bool = False
    smallcaps: bool = False
    hyperlink: bool = False
    superscript: bool = False
    subscript: bool = False
    strike: bool = False
    highlight: bool = False
    color: str | None = None
    shade: str | None = None
    size: int | None = None

    def kwargs(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if v}

    def with_flag(self, flag: str) -> _RunStyle:
        return _replace(self, **{flag: True})  # type: ignore[arg-type]

# cleveref's default names: (\cref singular, plural, \Cref singular, plural).
# Only equations and figures are abbreviated; the noabbrev option spells
# them out too.
_CREF_NAMES = {
    "equation": ("eq.", "eqs.", "Equation", "Equations"),
    "figure": ("fig.", "figs.", "Figure", "Figures"),
    "table": ("table", "tables", "Table", "Tables"),
    "section": ("section", "sections", "Section", "Sections"),
    "chapter": ("chapter", "chapters", "Chapter", "Chapters"),
    "part": ("part", "parts", "Part", "Parts"),
    "appendix": ("appendix", "appendices", "Appendix", "Appendices"),
    "algorithm": ("algorithm", "algorithms", "Algorithm", "Algorithms"),
    "listing": ("listing", "listings", "Listing", "Listings"),
    "enumi": ("item", "items", "Item", "Items"),
    "page": ("page", "pages", "Page", "Pages"),
}
_CREF_UNABBREV = {
    "equation": ("equation", "equations", "Equation", "Equations"),
    "figure": ("figure", "figures", "Figure", "Figures"),
}
#: cleveref names subsections after sections
_CREF_BASE = {"subsection": "section", "subsubsection": "section", "listitem": "enumi"}
#: hyperref's \autoref names
_AUTOREF_NAMES = {
    "equation": "Equation", "figure": "Figure", "table": "Table", "section": "section",
    "subsection": "subsection", "subsubsection": "subsubsection", "chapter": "chapter",
    "part": "Part", "appendix": "Appendix", "algorithm": "Algorithm", "listing": "Listing",
    "enumi": "item", "page": "page",
}


def _bookmark_for(label: str) -> str:
    from ..transforms.crossref import sanitize_bookmark

    return sanitize_bookmark(label)


def _figure_bookmark(fig: ir.Figure) -> str | None:
    from ..transforms.crossref import figure_bookmark

    return figure_bookmark(fig)


def _qn(tag: str) -> str:
    from .ooxml import qn

    return qn(tag)


def _style_math_runs(omath: _Element, color: str | None, size: int | None) -> None:
    """Apply ``w:color``/``w:sz`` to every math run (``m:r``) of an OMML tree.

    A math run may carry a ``w:rPr`` (WordprocessingML run properties) alongside
    its ``m:rPr`` (math run properties); it goes after ``m:rPr`` and before the
    run content. This lets ``\\textcolor{red}{$x$}`` / ``{\\large $x$}`` colour
    and resize an equation.
    """
    for mr in omath.iter(_qn("m:r")):
        wrpr = el("w:rPr")
        if color:
            sub(wrpr, "w:color", **{"w:val": color})
        if size:
            sub(wrpr, "w:sz", **{"w:val": str(size)})
            sub(wrpr, "w:szCs", **{"w:val": str(size)})
        mrpr = mr.find(_qn("m:rPr"))
        if mrpr is not None:
            mrpr.addnext(wrpr)
        else:
            mr.insert(0, wrpr)
