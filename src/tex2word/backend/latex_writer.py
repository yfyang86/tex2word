"""IR -> LaTeX writer (round-trip back-end, SPRINT-V3 A2/M1).

The inverse of the OOXML back-end: walks the IR and emits compilable LaTeX. It
splices each node's *retained original source* where present (figures, raw
passthroughs) and reconstructs the rest structurally, so a manifest-recovered IR
round-trips losslessly for unchanged math/figures and faithfully for the rest.

This is a structural round-trip, not byte-identical (an explicit PRD non-goal).
"""

from __future__ import annotations

import re

from .. import ir

_HEADING_CMD = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}
_HEADING_CMD_BOOK = {
    1: "chapter", 2: "section", 3: "subsection", 4: "subsubsection", 5: "paragraph",
}
_EMPH_CMD = {
    "bold": "textbf", "italic": "emph", "underline": "underline",
    "typewriter": "texttt", "smallcaps": "textsc",
    "superscript": "textsuperscript", "subscript": "textsubscript",
    "strike": "sout", "highlight": "hl",
}

# w:sz half-points -> nearest LaTeX size declaration (for round-trip).
_HP_SIZE_CMD = {
    10: "tiny", 14: "scriptsize", 16: "footnotesize", 18: "small",
    24: "large", 29: "Large", 34: "LARGE", 41: "huge", 50: "Huge",
}
_CITE_CMD = {
    "paren": "citep", "text": "citet", "foot": "footcite",
    "author": "citeauthor", "year": "citeyear", "num": "citenum",
}
_SPECIALS = re.compile(r"([&%$#_{}])")
# BCP-47 -> babel option (for the round-trip preamble); common languages.
_BABEL_NAME = {
    "en-US": "english", "en-GB": "british", "de-DE": "ngerman", "de-AT": "naustrian",
    "fr-FR": "french", "fr-CA": "canadien", "es-ES": "spanish", "it-IT": "italian",
    "pt-PT": "portuguese", "pt-BR": "brazilian", "nl-NL": "dutch", "ru-RU": "russian",
    "pl-PL": "polish", "sv-SE": "swedish", "da-DK": "danish", "nb-NO": "norsk",
    "fi-FI": "finnish", "cs-CZ": "czech", "el-GR": "greek", "tr-TR": "turkish",
    "ja-JP": "japanese", "zh-CN": "chinese",
}


def _partial_rule_latex(row: ir.TableRow) -> str:
    """`\\cmidrule` lines for the bordered (``border_bottom``) cells of a row."""
    cols: list[int] = []
    col = 1
    for cell in row.cells:
        if cell.border_bottom:
            cols.extend(range(col, col + cell.colspan))
        col += cell.colspan
    if not cols:
        return ""
    out: list[str] = []
    start = prev = cols[0]
    for c in cols[1:] + [-1]:
        if c != prev + 1:
            out.append(f"\\cmidrule{{{start}-{prev}}}")
            start = c
        prev = c
    return "".join(out)


def latex_escape(text: str) -> str:
    """Escape LaTeX specials in plain text (re-escaping de-escaped IR text)."""
    text = text.replace("\\", "\\textbackslash{}")
    text = _SPECIALS.sub(r"\\\1", text)
    text = text.replace("~", "\\textasciitilde{}").replace("^", "\\textasciicircum{}")
    return text


class LatexWriter:
    def __init__(self) -> None:
        self._theorem_kinds: dict[str, str] = {}  # envname -> display
        self.book = False
        self._appendix_emitted = False

    # -- public ----------------------------------------------------------- #

    def write(self, doc: ir.Document) -> str:
        self.book = doc.book
        body = self._blocks(doc.blocks)
        preamble = self._preamble(doc)
        meta = self._frontmatter(doc.meta)
        parts = [preamble, "\\begin{document}", meta, body, "\\end{document}", ""]
        return "\n".join(p for p in parts if p)

    # -- preamble --------------------------------------------------------- #

    def _preamble(self, doc: ir.Document) -> str:
        feat = _Features()
        _scan(doc.blocks, feat)
        if doc.meta.abstract:
            _scan(doc.meta.abstract, feat)
        cls = "report" if doc.book else "article"
        lines = [f"\\documentclass{{{cls}}}", "\\usepackage[utf8]{inputenc}"]
        babel = _BABEL_NAME.get(doc.meta.language or "")
        if babel:
            lines.append(f"\\usepackage[{babel}]{{babel}}")
        m = doc.meta
        if m.cjk_main_font or m.cjk_sans_font or m.cjk_mono_font:
            lines.append("\\usepackage{xeCJK}")  # also loads fontspec
        elif m.main_font:
            lines.append("\\usepackage{fontspec}")
        if m.main_font:
            lines.append(f"\\setmainfont{{{m.main_font}}}")
        if m.cjk_main_font:
            lines.append(f"\\setCJKmainfont{{{m.cjk_main_font}}}")
        if m.cjk_sans_font:
            lines.append(f"\\setCJKsansfont{{{m.cjk_sans_font}}}")
        if m.cjk_mono_font:
            lines.append(f"\\setCJKmonofont{{{m.cjk_mono_font}}}")
        if feat.math:
            lines += ["\\usepackage{amsmath}", "\\usepackage{amssymb}"]
        if feat.graphics:
            lines.append("\\usepackage{graphicx}")
        if feat.subfig:
            lines.append("\\usepackage{subcaption}")
        if feat.booktabs:
            lines.append("\\usepackage{booktabs}")
        if feat.multirow:
            lines.append("\\usepackage{multirow}")
        if feat.algorithm:
            lines += ["\\usepackage{algorithm}", "\\usepackage{algpseudocode}"]
        if feat.links or feat.refs:
            lines.append("\\usepackage{hyperref}")
        if feat.cleveref:
            lines.append("\\usepackage{cleveref}")
        if feat.cites:
            lines.append("\\usepackage{natbib}")
        if feat.index:
            lines += ["\\usepackage{makeidx}", "\\makeindex"]
        for env, display in sorted(feat.theorem_kinds.items()):
            if env != "proof":
                lines.append(f"\\newtheorem{{{env}}}{{{display}}}")
        return "\n".join(lines)

    def _frontmatter(self, meta: ir.DocumentMeta) -> str:
        out: list[str] = []
        if meta.title:
            head = f"[{latex_escape(meta.running_head)}]" if meta.running_head else ""
            out.append(f"\\title{head}{{{self._inlines(meta.title)}}}")
        elif meta.running_head:
            out.append(f"\\markright{{{latex_escape(meta.running_head)}}}")
        for author in meta.authors:
            out.append(f"\\author{{{self._inlines(author)}}}")
        for affil in meta.affiliations:
            out.append(f"\\affiliation{{{self._inlines(affil)}}}")
        if meta.date:
            out.append(f"\\date{{{self._inlines(meta.date)}}}")
        if meta.title:
            out.append("\\maketitle")
        if meta.abstract:
            out.append("\\begin{abstract}")
            out.append(self._blocks(meta.abstract))
            out.append("\\end{abstract}")
        if meta.keywords:
            out.append(f"\\keywords{{{self._inlines(meta.keywords)}}}")
        return "\n".join(out)

    # -- blocks ----------------------------------------------------------- #

    def _blocks(self, blocks: list[ir.Block]) -> str:
        return "\n\n".join(self._block(b) for b in blocks if b is not None)

    def _block(self, block: ir.Block) -> str:  # noqa: C901
        if isinstance(block, ir.Heading):
            cmd_map = _HEADING_CMD_BOOK if self.book else _HEADING_CMD
            cmd = "part" if block.part else cmd_map.get(block.level, "section")
            star = "" if block.numbered else "*"
            label = f"\\label{{{block.label}}}" if block.label else ""
            prefix = ""
            if block.appendix and not self._appendix_emitted:
                prefix = "\\appendix\n"
                self._appendix_emitted = True
            return f"{prefix}\\{cmd}{star}{{{self._inlines(block.inlines)}}}{label}"
        if isinstance(block, ir.Paragraph):
            body = self._inlines(block.inlines)
            env = {"center": "center", "left": "flushleft", "right": "flushright"}.get(
                block.align or ""
            )
            if env:
                return f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}"
            return body
        if isinstance(block, ir.MathBlock):
            return self._math_block(block)
        if isinstance(block, ir.ItemList):
            return self._list(block)
        if isinstance(block, ir.Table):
            return self._table(block)
        if isinstance(block, ir.Figure):
            return block.source or self._figure(block)
        if isinstance(block, ir.CodeBlock):
            return f"\\begin{{verbatim}}\n{block.text}\n\\end{{verbatim}}"
        if isinstance(block, ir.Quote):
            return f"\\begin{{quote}}\n{self._blocks(block.blocks)}\n\\end{{quote}}"
        if isinstance(block, ir.Theorem):
            return self._theorem(block)
        if isinstance(block, ir.Algorithm):
            return self._algorithm(block)
        if isinstance(block, ir.Bibliography):
            return self._bibliography(block)
        if isinstance(block, ir.TableOfContents):
            return {
                "contents": "\\tableofcontents",
                "figures": "\\listoffigures",
                "tables": "\\listoftables",
            }[block.kind]
        if isinstance(block, ir.Index):
            return "\\printindex"
        if isinstance(block, ir.RawPassthrough):
            return block.latex
        return ""

    def _math_block(self, block: ir.MathBlock) -> str:
        latex = block.latex.strip()
        if block.label:
            latex = f"{latex}\n\\label{{{block.label}}}"
        env = block.env
        if env in ("displaymath", "math"):
            return f"\\[\n{latex}\n\\]"
        name = env if block.numbered else f"{env}*"
        return f"\\begin{{{name}}}\n{latex}\n\\end{{{name}}}"

    def _list(self, block: ir.ItemList) -> str:
        env = "description" if block.description else ("enumerate" if block.ordered else "itemize")
        rows = []
        for item in block.items:
            term = f"[{self._inlines(item.term)}]" if item.term else ""
            rows.append(f"\\item{term} {self._blocks(item.blocks)}".rstrip())
        body = "\n".join(rows)
        return f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}"

    def _table(self, block: ir.Table) -> str:
        def _col(i: int, align: str) -> str:
            w = block.colwidths[i] if i < len(block.colwidths) else None
            if w:
                return f"p{{{w * 72.27 / 914400:.1f}pt}}"  # EMU -> pt
            return {"left": "l", "center": "c", "right": "r"}[align]

        colspec = "".join(_col(i, a) for i, a in enumerate(block.colspec))
        if not colspec:
            ncols = max((sum(c.colspan for c in r.cells) for r in block.rows), default=1)
            colspec = "l" * ncols
        lines = [f"\\begin{{tabular}}{{{colspec}}}"]
        if block.booktabs:
            lines.append("\\toprule")
        for row in block.rows:
            cells = [self._cell(c) for c in row.cells]
            lines.append(" & ".join(cells) + " \\\\")
            rule = _partial_rule_latex(row)
            if rule:
                lines.append(rule)
            if block.booktabs and row.is_header:
                lines.append("\\midrule")
        if block.booktabs:
            lines.append("\\bottomrule")
        lines.append("\\end{tabular}")
        table = "\n".join(lines)
        if block.caption is None and block.label is None:
            return table
        star = "" if block.caption_numbered else "*"
        cap = f"\\caption{star}{{{self._inlines(block.caption or [])}}}"
        label = f"\\label{{{block.label}}}" if block.label else ""
        return f"\\begin{{table}}\n\\centering\n{table}\n{cap}{label}\n\\end{{table}}"

    def _cell(self, cell: ir.TableCell) -> str:
        content = self._blocks(cell.blocks)
        if cell.shade:
            content = f"\\cellcolor[HTML]{{{cell.shade}}}{content}"
        if cell.colspan > 1:
            a = {"left": "l", "center": "c", "right": "r"}[cell.align]
            content = f"\\multicolumn{{{cell.colspan}}}{{{a}}}{{{content}}}"
        if cell.rowspan > 1:
            content = f"\\multirow{{{cell.rowspan}}}{{*}}{{{content}}}"
        return content

    def _figure(self, block: ir.Figure) -> str:
        lines = ["\\begin{figure}", "\\centering"]
        if block.image is not None:
            lines.append(f"\\includegraphics{{{block.image.path}}}")
        for sub in block.subfigures:
            lines.append("\\begin{subfigure}{0.45\\linewidth}")
            if sub.image is not None:
                lines.append(f"\\includegraphics{{{sub.image.path}}}")
            if sub.caption:
                lines.append(f"\\caption{{{self._inlines(sub.caption)}}}")
            if sub.label:
                lines.append(f"\\label{{{sub.label}}}")
            lines.append("\\end{subfigure}")
        if block.caption:
            star = "" if block.caption_numbered else "*"
            lines.append(f"\\caption{star}{{{self._inlines(block.caption)}}}")
        if block.label:
            lines.append(f"\\label{{{block.label}}}")
        lines.append("\\end{figure}")
        return "\n".join(lines)

    def _theorem(self, block: ir.Theorem) -> str:
        env = "proof" if block.kind == "Proof" else block.kind.lower()
        title = f"[{self._inlines(block.title)}]" if block.title else ""
        label = f"\\label{{{block.label}}}\n" if block.label else ""
        return (
            f"\\begin{{{env}}}{title}\n{label}{self._blocks(block.blocks)}\n\\end{{{env}}}"
        )

    def _algorithm(self, block: ir.Algorithm) -> str:
        lines = ["\\begin{algorithm}"]
        if block.caption:
            lines.append(f"\\caption{{{self._inlines(block.caption)}}}")
        if block.label:
            lines.append(f"\\label{{{block.label}}}")
        lines.append("\\begin{algorithmic}[1]")
        for aline in block.lines:
            indent = "  " * aline.indent
            lines.append(f"{indent}\\State {self._inlines(aline.inlines)}")
        lines += ["\\end{algorithmic}", "\\end{algorithm}"]
        return "\n".join(lines)

    def _bibliography(self, block: ir.Bibliography) -> str:
        lines = [f"\\begin{{thebibliography}}{{{len(block.entries)}}}"]
        for item in block.entries:
            note = item.csl_fields.get("note", "")
            lines.append(f"\\bibitem{{{item.id}}} {note}")
        lines.append("\\end{thebibliography}")
        return "\n".join(lines)

    # -- inline ----------------------------------------------------------- #

    def _inlines(self, inlines: list[ir.Inline]) -> str:
        return "".join(self._inline(n) for n in inlines)

    def _inline(self, node: ir.Inline) -> str:  # noqa: C901
        if isinstance(node, ir.Text):
            return latex_escape(node.value)
        if isinstance(node, ir.Emphasis):
            cmd = _EMPH_CMD.get(node.kind_, "emph")
            return f"\\{cmd}{{{self._inlines(node.inlines)}}}"
        if isinstance(node, ir.Math):
            return f"${node.latex}$"
        if isinstance(node, ir.Ref):
            return self._ref(node)
        if isinstance(node, ir.Cite):
            return self._cite(node)
        if isinstance(node, ir.Link):
            text = self._inlines(node.inlines)
            if node.anchor:
                return f"\\hyperref[{node.anchor}]{{{text}}}"
            return f"\\href{{{node.url}}}{{{text}}}"
        if isinstance(node, ir.LineBreak):
            return "\\\\"
        if isinstance(node, ir.Footnote):
            return f"\\footnote{{{self._inlines(node.inlines)}}}"
        if isinstance(node, ir.Endnote):
            return f"\\endnote{{{self._inlines(node.inlines)}}}"
        if isinstance(node, ir.IndexEntry):
            return f"\\index{{{node.term}}}"
        if isinstance(node, ir.Colored):
            inner = self._inlines(node.inlines)
            if node.bg is not None:
                return f"\\colorbox[HTML]{{{node.bg}}}{{{inner}}}"
            if node.fg is not None:
                return f"\\textcolor[HTML]{{{node.fg}}}{{{inner}}}"
            return inner
        if isinstance(node, ir.FontSize):
            # our own sizes are always table keys (exact round-trip); a foreign
            # docx may carry an arbitrary half-point value near the body default,
            # for which rendering at the document default is safest.
            size_cmd = _HP_SIZE_CMD.get(node.half_points)
            inner = self._inlines(node.inlines)
            return f"{{\\{size_cmd} {inner}}}" if size_cmd else inner
        if isinstance(node, ir.Image):
            return f"\\includegraphics{{{node.path}}}"
        if isinstance(node, ir.RawInline):
            return node.latex
        if isinstance(node, ir.Comment):
            # a reviewer's note -> a LaTeX % line (no visible body); newline-
            # wrapped and whitespace-collapsed so it never comments out real text.
            note = " ".join(node.text.split())
            who = f"[{node.author}] " if node.author else ""
            return f"\n% comment: {who}{note}\n"
        return ""

    def _ref(self, node: ir.Ref) -> str:
        if node.style == "abbrev":
            return f"\\cref{{{node.key}}}"
        if node.style == "full":
            return f"\\Cref{{{node.key}}}"
        if node.ref_kind == "equation":
            return f"\\eqref{{{node.key}}}"
        if node.ref_kind == "page":
            return f"\\pageref{{{node.key}}}"
        return f"\\ref{{{node.key}}}"

    def _cite(self, node: ir.Cite) -> str:
        cmd = _CITE_CMD.get(node.mode, "cite")
        opts = ""
        if node.prefix:
            opts = f"[{node.prefix}][{node.suffix or ''}]"
        elif node.suffix:
            opts = f"[{node.suffix}]"
        return f"\\{cmd}{opts}{{{','.join(node.keys)}}}"


# --------------------------------------------------------------------------- #
# Feature detection for the preamble
# --------------------------------------------------------------------------- #


class _Features:
    def __init__(self) -> None:
        self.math = self.graphics = self.subfig = self.booktabs = False
        self.multirow = self.algorithm = self.links = self.refs = False
        self.cleveref = self.cites = self.index = False
        self.theorem_kinds: dict[str, str] = {}


def _scan(blocks: list[ir.Block], feat: _Features) -> None:  # noqa: C901
    for block in blocks:
        if isinstance(block, ir.MathBlock):
            feat.math = True
        elif isinstance(block, ir.Figure):
            feat.graphics = True
            if block.subfigures:
                feat.subfig = True
        elif isinstance(block, ir.Table):
            feat.booktabs = feat.booktabs or block.booktabs
            if any(c.rowspan > 1 for r in block.rows for c in r.cells):
                feat.multirow = True
            _scan_inlines([c for r in block.rows for cell in r.cells for c in cell.blocks], feat)
        elif isinstance(block, ir.Algorithm):
            feat.algorithm = True
        elif isinstance(block, ir.Theorem):
            env = "proof" if block.kind == "Proof" else block.kind.lower()
            feat.theorem_kinds[env] = block.kind
            _scan(block.blocks, feat)
        elif isinstance(block, ir.Quote):
            _scan(block.blocks, feat)
        elif isinstance(block, ir.ItemList):
            for item in block.items:
                _scan(item.blocks, feat)
        elif isinstance(block, ir.Index):
            feat.index = True
        elif isinstance(block, ir.Paragraph | ir.Heading):
            _scan_inlines(block.inlines, feat)


def _scan_inlines(inlines: list, feat: _Features) -> None:
    for node in inlines:
        if isinstance(node, ir.Math):
            feat.math = True
        elif isinstance(node, ir.Link):
            feat.links = True
        elif isinstance(node, ir.Ref):
            feat.refs = True
            if node.style in ("abbrev", "full"):
                feat.cleveref = True
        elif isinstance(node, ir.Cite):
            feat.cites = True
        elif isinstance(node, ir.Image):
            feat.graphics = True
        elif isinstance(node, ir.IndexEntry):
            feat.index = True
        elif isinstance(node, ir.Emphasis | ir.Footnote | ir.Endnote | ir.Colored | ir.FontSize):
            _scan_inlines(node.inlines, feat)


def write_latex(doc: ir.Document) -> str:
    """Serialise an IR document to LaTeX."""
    return LatexWriter().write(doc)
