"""OOXML document.xml -> IR (round-trip reader, SPRINT-V3 A2/M3).

Best-effort reader for a *foreign* ``.docx`` (or one whose tex2word manifest
was stripped): maps Word styles back to sectioning/blocks, runs to text/
emphasis, ``m:oMath`` to math (via the OMML->LaTeX reader), complex fields to
``\\ref``/``\\cite``/links, and tables/lists to their IR nodes. The result feeds
the IR->LaTeX writer, so ``to_latex`` works without our manifest.

This is structural recovery, not byte-identical (an explicit PRD non-goal).
"""

from __future__ import annotations

import io
import json
import re
import zipfile

from lxml import etree

from .. import ir
from ..backend.ooxml import NS
from ..mathml.omml_reader import omath_to_latex

_W = NS["w"]
_M = NS["m"]

_HEADING_LEVEL = {
    "Heading1": 1, "Heading2": 2, "Heading3": 3, "Heading4": 4, "Heading5": 5,
}
_TOC_TITLES = {"Contents", "List of Figures", "List of Tables"}
#: must match tex2word.backend.document.{BIB,FIG}_SDT_TAG
_BIB_SDT_TAG = "tex2word:bibliography"
_FIG_SDT_TAG = "tex2word:figure"


def _plain_text(inlines: list[ir.Inline]) -> str:
    return "".join(i.value for i in inlines if isinstance(i, ir.Text)).strip()


def _theorem_block(inlines: list[ir.Inline]) -> ir.Theorem | None:
    """Recover a theorem/proof from its bold (italic for proof) lead paragraph.

    Our writer emits ``**Kind** [N] [(title)]**. ** content``; this reverses the
    common single-paragraph case (the number is re-derived on re-export).
    """
    if not inlines or not isinstance(inlines[0], ir.Emphasis):
        return None
    if inlines[0].kind_ not in ("bold", "italic"):
        return None
    kind = _all_text([inlines[0]]).strip()
    if kind not in _THEOREM_KINDS:
        return None
    # the lead runs end at the bold/italic ". " separator
    sep = next(
        (i for i in range(1, len(inlines))
         if isinstance(inlines[i], ir.Emphasis) and _all_text([inlines[i]]).strip() == "."),
        None,
    )
    if sep is None:
        return None
    lead, content = inlines[1:sep], inlines[sep + 1:]
    title = _paren_title(lead)
    if kind == "Proof":
        content = _strip_qed(content)
    return ir.Theorem(kind=kind, blocks=[ir.Paragraph(content)], title=title)


def _paren_title(lead: list[ir.Inline]) -> list[ir.Inline] | None:
    """The ``(title)`` text from a theorem lead, if any."""
    text = _all_text(lead)
    start, end = text.find("("), text.rfind(")")
    if 0 <= start < end:
        inner = text[start + 1:end].strip()
        return [ir.Text(inner)] if inner else None
    return None


def _strip_qed(content: list[ir.Inline]) -> list[ir.Inline]:
    """Drop a trailing QED mark (``□`` / em-space + ``□``) from a proof body."""
    out = list(content)
    while out and isinstance(out[-1], ir.Text) and not out[-1].value.strip("  □"):
        out.pop()
    if out and isinstance(out[-1], ir.Text):
        stripped = out[-1].value.rstrip("  □")
        if stripped != out[-1].value:
            out[-1] = ir.Text(stripped) if stripped else None  # type: ignore[assignment]
            if out[-1] is None:
                out.pop()
    return out


def _drawing_descr(el: etree._Element) -> str:
    """The alt-text (image source path) from a drawing's docPr/cNvPr @descr."""
    for e in el.iter():
        if _local(e) in ("docPr", "cNvPr") and e.get("descr"):
            return e.get("descr") or ""
    return ""


_THEOREM_KINDS = {
    "Theorem", "Lemma", "Corollary", "Proposition", "Definition", "Remark",
    "Example", "Conjecture", "Claim", "Fact", "Observation", "Notation",
    "Assumption", "Axiom", "Exercise", "Problem", "Question", "Proof",
}


def _all_text(inlines: list[ir.Inline]) -> str:
    """All text, recursing into Emphasis/Colored/FontSize wrappers (e.g. code)."""
    out: list[str] = []
    for i in inlines:
        if isinstance(i, ir.Text):
            out.append(i.value)
        elif isinstance(i, ir.Emphasis | ir.Colored | ir.FontSize):
            out.append(_all_text(i.inlines))
    return "".join(out)
_EMPH_FROM_RPR = [  # (rPr child localname, emphasis kind)
    ("b", "bold"), ("i", "italic"), ("u", "underline"), ("smallCaps", "smallcaps"),
    ("strike", "strike"), ("highlight", "highlight"),
]


def _w(name: str) -> str:
    return f"{{{_W}}}{name}"


def _m(name: str) -> str:
    return f"{{{_M}}}{name}"


def _local(e: etree._Element) -> str:
    return etree.QName(e).localname


def read_docx(docx_bytes: bytes, label_map: dict[str, str] | None = None) -> ir.Document:
    """Read a foreign ``.docx`` to the IR.

    ``label_map`` maps sanitised Word bookmark names back to the original label
    keys (built from a manifest, when one is present), so recovered ``\\ref``s and
    labels use the source names instead of the sanitised ``eq_e`` form.
    """
    zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    root = etree.fromstring(zf.read("word/document.xml"))
    body = root.find(_w("body"))
    meta = ir.DocumentMeta()
    comments = (
        _read_comments(zf.read("word/comments.xml"))
        if "word/comments.xml" in zf.namelist() else {}
    )
    reader = _Reader(meta, comments, label_map)
    blocks = reader.read_body(body if body is not None else root)
    return ir.Document(blocks=blocks, meta=meta)


def _read_comments(comments_xml: bytes) -> dict[str, tuple[str, str]]:
    """{comment id -> (author, plain text)} from word/comments.xml."""
    out: dict[str, tuple[str, str]] = {}
    try:
        root = etree.fromstring(comments_xml)
    except Exception:
        return out
    for c in root.findall(_w("comment")):
        cid = c.get(_w("id"))
        if cid is None:
            continue
        text = "".join(t.text or "" for t in c.iter(_w("t"))).strip()
        out[cid] = (c.get(_w("author")) or "", text)
    return out


class _Reader:
    def __init__(
        self, meta: ir.DocumentMeta, comments: dict[str, tuple[str, str]] | None = None,
        label_map: dict[str, str] | None = None,
    ) -> None:
        self.meta = meta
        self.comments = comments or {}
        self.label_map = label_map or {}

    def _resolve_label(self, bookmark: str) -> str:
        """A sanitised bookmark -> the original label key (manifest map, else a
        prefix heuristic that reverses ``eq_e`` -> ``eq:e``)."""
        return self.label_map.get(bookmark) or _unsanitize(bookmark)

    # -- body ------------------------------------------------------------- #

    def read_body(self, body: etree._Element) -> list[ir.Block]:
        blocks: list[ir.Block] = []
        list_run: list[etree._Element] = []
        quote_run: list[etree._Element] = []
        code_run: list[etree._Element] = []
        desc_run: list[tuple[list[ir.Inline], list[ir.Inline]]] = []

        def flush_list() -> None:
            if list_run:
                blocks.extend(self._build_lists(list_run))
                list_run.clear()

        def flush_quote() -> None:
            if quote_run:
                inner = [self._paragraph(p) for p in quote_run]
                blocks.append(ir.Quote([b for b in inner if b is not None]))
                quote_run.clear()

        def flush_code() -> None:
            if code_run:
                text = "\n".join(_all_text(self._inlines(p)) for p in code_run)
                blocks.append(ir.CodeBlock(text))
                code_run.clear()

        def flush_desc() -> None:
            if desc_run:
                items = [ir.ListItem([ir.Paragraph(d)], term=t) for t, d in desc_run]
                blocks.append(ir.ItemList(ordered=False, items=items, description=True))
                desc_run.clear()

        def flush_all() -> None:
            flush_list()
            flush_quote()
            flush_code()
            flush_desc()

        for child in body:
            tag = _local(child)
            if tag == "tbl":
                flush_all()
                blocks.append(self._algorithm(child) or self._table(child))
                continue
            if tag == "sdt":  # a content control: recover semantics or descend
                flush_all()
                blocks.extend(self._sdt(child))
                continue
            if tag != "p":
                continue  # sectPr and others: ignore
            style = self._style(child) or "Normal"
            if self._numpr(child) is not None and not self._is_heading(child):
                flush_quote()
                flush_code()
                list_run.append(child)
                continue
            if style == "Quote":
                flush_list()
                flush_code()
                quote_run.append(child)
                continue
            if style == "SourceCode":
                flush_list()
                flush_quote()
                flush_desc()
                code_run.append(child)
                continue
            if style == "Normal":
                td = self._description_item(child)
                if td is not None:
                    flush_list()
                    flush_quote()
                    flush_code()
                    desc_run.append(td)
                    continue
            flush_all()
            # a Caption "Figure N: ..." / "Table N: ..." right after the float ->
            # attach it instead of emitting a stray paragraph.
            if style == "Caption" and blocks:
                if isinstance(blocks[-1], ir.Figure):
                    cap = self._caption_after(child, "Figure")
                    if cap is not None:
                        blocks[-1].caption = cap
                        continue
                elif isinstance(blocks[-1], ir.Table):
                    cap = self._caption_after(child, "Table")
                    if cap is not None:
                        blocks[-1].caption = cap
                        continue
            # a drawing-only paragraph is a Figure; a drawing amid text is an
            # inline image (handled by _paragraph -> _inlines below).
            if (child.find(f".//{_w('drawing')}") is not None
                    and not _plain_text(self._inlines(child))):
                blocks.append(self._figure(child))
                continue
            block = self._paragraph(child)
            if block is not None:
                # drop a bold "Contents"/"List of …" title before a TOC field
                if (
                    isinstance(block, ir.TableOfContents)
                    and blocks
                    and isinstance(blocks[-1], ir.Paragraph)
                    and _plain_text(blocks[-1].inlines) in _TOC_TITLES
                ):
                    blocks.pop()
                blocks.append(block)
        flush_all()
        return blocks

    def _figure(self, p: etree._Element) -> ir.Figure:
        """A paragraph carrying a ``w:drawing`` -> a Figure (path from alt-text)."""
        return ir.Figure(image=ir.Image(path=_drawing_descr(p)))

    def _caption_after(self, p: etree._Element, prefix: str) -> list[ir.Inline] | None:
        """The caption text of a ``'<prefix> N: text'`` Caption paragraph, or None."""
        text = _plain_text(self._inlines(p))
        if not text.startswith(prefix):
            return None
        _, _, rest = text.partition(":")
        return [ir.Text(rest.strip())] if rest.strip() else None

    # -- paragraph classification ---------------------------------------- #

    def _style(self, p: etree._Element) -> str | None:
        ppr = p.find(_w("pPr"))
        if ppr is None:
            return None
        st = ppr.find(_w("pStyle"))
        return st.get(_w("val")) if st is not None else None

    def _is_heading(self, p: etree._Element) -> bool:
        return (self._style(p) or "") in _HEADING_LEVEL

    def _numpr(self, p: etree._Element) -> etree._Element | None:
        ppr = p.find(_w("pPr"))
        return ppr.find(_w("numPr")) if ppr is not None else None

    def _alignment(self, p: etree._Element) -> str | None:
        ppr = p.find(_w("pPr"))
        jc = ppr.find(_w("jc")) if ppr is not None else None
        if jc is None:
            return None
        # accept both the legacy (left/right) and current (start/end) jc values
        return {
            "center": "center", "right": "right", "end": "right",
            "left": "left", "start": "left",
        }.get(jc.get(_w("val")) or "")

    def _paragraph(self, p: etree._Element) -> ir.Block | None:
        style = self._style(p) or "Normal"
        # display math paragraph (unnumbered: m:oMathPara)
        if p.find(_m("oMathPara")) is not None:
            return self._math_block(p)
        # numbered equation: inline m:oMath + a SEQ Equation field
        numbered_eq = self._numbered_equation(p)
        if numbered_eq is not None:
            return numbered_eq
        toc = self._toc_block(p)
        if toc is not None:
            return toc
        inlines = self._inlines(p)
        label = self._bookmark(p)
        if style == "Title":
            self.meta.title = inlines
            return None
        if style in ("Subtitle", "Author"):
            self.meta.authors.append(inlines)
            return None
        if style == "Abstract":
            # the abstract lives in meta (rendered into the body); recover it
            # there rather than as a stray body paragraph.
            if self.meta.abstract is None:
                self.meta.abstract = []
            self.meta.abstract.append(ir.Paragraph(inlines))
            return None
        if style in _HEADING_LEVEL:
            numbered = self._numpr(p) is not None
            return ir.Heading(_HEADING_LEVEL[style], inlines, label=label, numbered=numbered)
        if style == "Normal":
            thm = _theorem_block(inlines)
            if thm is not None:
                return thm
        if not inlines:
            return None
        return ir.Paragraph(inlines, align=self._alignment(p))

    def _math_block(self, p: etree._Element) -> ir.MathBlock:
        para = p.find(_m("oMathPara"))
        omath = para.find(_m("oMath")) if para is not None else None
        latex = omath_to_latex(omath) if omath is not None else ""
        return ir.MathBlock(latex=latex, numbered=False, env="displaymath",
                            label=self._bookmark(p))

    def _numbered_equation(self, p: etree._Element) -> ir.MathBlock | None:
        omath = next((e for e in p.iter(_m("oMath"))), None)
        if omath is None:
            return None
        instr = "".join(t.text or "" for t in p.iter(_w("instrText")))
        if "SEQ Equation" not in instr:
            return None
        return ir.MathBlock(latex=omath_to_latex(omath), numbered=True, env="equation",
                            label=self._bookmark(p))

    def _toc_block(self, p: etree._Element) -> ir.TableOfContents | None:
        instr = "".join(t.text or "" for t in p.iter(_w("instrText")))
        if "TOC" not in instr.split():
            return None
        if '\\c "Figure"' in instr:
            kind: str = "figures"
        elif '\\c "Table"' in instr:
            kind = "tables"
        else:
            kind = "contents"
        return ir.TableOfContents(kind=kind)  # type: ignore[arg-type]

    def _bookmark(self, p: etree._Element) -> str | None:
        bm = p.find(_w("bookmarkStart"))
        name = bm.get(_w("name")) if bm is not None else None
        return self._resolve_label(name) if name else None

    # -- inline ----------------------------------------------------------- #

    def _inlines(self, parent: etree._Element) -> list[ir.Inline]:
        out: list[ir.Inline] = []
        self._runs(parent, out, None)
        return out

    def _runs(
        self, parent: etree._Element, out: list[ir.Inline], field: dict | None
    ) -> dict | None:
        """Walk run-level children, accepting tracked changes.

        ``w:ins``/``w:moveTo`` (insertions/move targets) are accepted -- their
        runs are kept; ``w:del``/``w:moveFrom`` (deletions/move sources) are
        accepted by being dropped. So a Word document reviewed with Track Changes
        round-trips as if every change were accepted.
        """
        for el in parent:
            tag = _local(el)
            if tag in ("bookmarkStart", "bookmarkEnd", "proofErr"):
                continue
            if tag in ("del", "moveFrom"):  # accepted deletion -> drop
                continue
            if tag in ("ins", "moveTo"):  # accepted insertion -> keep its runs
                field = self._runs(el, out, field)
            elif tag == "oMath":  # inline math
                out.append(ir.Math(omath_to_latex(el)))
            elif tag == "hyperlink":
                self._runs(el, out, None)  # rels not resolved; keep text
            elif tag == "r":
                field = self._run(el, out, field)
        return field

    def _run(self, r: etree._Element, out: list[ir.Inline], field: dict | None) -> dict | None:
        # a comment anchor -> recover the reviewer's note (no visible text)
        cref = r.find(_w("commentReference"))
        if cref is not None:
            entry = self.comments.get(cref.get(_w("id")) or "")
            if entry is not None:
                out.append(ir.Comment(text=entry[1], author=entry[0]))
            return field
        # complex-field state machine
        fld = r.find(_w("fldChar"))
        if fld is not None:
            kind = fld.get(_w("fldCharType"))
            if kind == "begin":
                return {"instr": "", "phase": "instr", "result": []}
            if kind == "separate" and field is not None:
                field["phase"] = "result"
                return field
            if kind == "end" and field is not None:
                self._emit_field(field, out)
                return None
            return field
        instr = r.find(_w("instrText"))
        if instr is not None and field is not None:
            field["instr"] += instr.text or ""
            return field
        draw = r.find(_w("drawing"))
        if draw is not None and field is None:  # an inline image (icon/logo)
            out.append(ir.Image(path=_drawing_descr(r)))
            return field
        # an oMath nested in a run (rare) or text
        text = "".join(t.text or "" for t in r.findall(_w("t")))
        if field is not None and field.get("phase") == "result":
            field["result"].append(text)
            return field
        if text:
            out.append(self._styled_text(r, text))
        return field

    def _styled_text(self, r: etree._Element, text: str) -> ir.Inline:
        rpr = r.find(_w("rPr"))
        node: ir.Inline = ir.Text(text)
        if rpr is None:
            return node
        rstyle = rpr.find(_w("rStyle"))
        if rstyle is not None and rstyle.get(_w("val")) == "Hyperlink":
            return node  # handled by the hyperlink wrapper
        for child, kind in _EMPH_FROM_RPR:
            if _toggle_on(rpr.find(_w(child))):
                node = ir.Emphasis([node], kind)  # type: ignore[arg-type]
        fonts = rpr.find(_w("rFonts"))
        if fonts is not None and (fonts.get(_w("ascii")) or "").startswith("Consolas"):
            node = ir.Emphasis([node], "typewriter")
        valign = rpr.find(_w("vertAlign"))
        if valign is not None and valign.get(_w("val")) in ("superscript", "subscript"):
            node = ir.Emphasis([node], valign.get(_w("val")))  # type: ignore[arg-type]
        color_el = rpr.find(_w("color"))
        fg = color_el.get(_w("val")) if color_el is not None else None
        shd = rpr.find(_w("shd"))
        bg = shd.get(_w("fill")) if shd is not None else None
        if (fg and fg != "auto") or (bg and bg != "auto"):
            node = ir.Colored([node], fg=fg if fg and fg != "auto" else None,
                              bg=bg if bg and bg != "auto" else None)
        sz = rpr.find(_w("sz"))
        sz_val = sz.get(_w("val")) if sz is not None else None
        if sz_val and sz_val.isdigit():
            node = ir.FontSize([node], half_points=int(sz_val))
        return node

    def _emit_field(self, field: dict, out: list[ir.Inline]) -> None:
        instr = field["instr"].strip()
        result = "".join(field["result"])
        m = re.match(r"REF\s+(\S+)", instr)
        if m:
            out.append(ir.Ref(self._resolve_label(m.group(1)), "generic"))
            return
        m = re.match(r"PAGEREF\s+(\S+)", instr)
        if m:
            out.append(ir.Ref(self._resolve_label(m.group(1)), "page"))
            return
        m = re.match(r'HYPERLINK\s+"([^"]*)"', instr)
        if m:
            out.append(ir.Link([ir.Text(result or m.group(1))], m.group(1)))
            return
        if "CSL_CITATION" in instr:  # Zotero (ZOTERO_ITEM) or Mendeley (bare)
            out.append(self._csl_cite(instr, result))
            return
        if "EN.CITE" in instr or "EN.REF" in instr:  # EndNote
            out.append(self._endnote_cite(instr, result))
            return
        if instr.startswith("SEQ"):
            return  # a regenerated number; drop
        if result:
            out.append(ir.Text(result))

    def _csl_cite(self, instr: str, result: str) -> ir.Cite:
        """A Zotero/Mendeley ``…CSL_CITATION {…}`` field → ``ir.Cite``."""
        keys: list[str] = []
        try:
            payload = json.loads(instr.split("CSL_CITATION", 1)[1].strip())
            for it in payload.get("citationItems", []):
                uris = it.get("uris") or []
                key = (uris[0].rsplit("/", 1)[-1] if uris else "") or str(
                    it.get("itemData", {}).get("id") or it.get("id") or ""
                )
                if key:
                    keys.append(key)
        except Exception:
            pass
        cite = ir.Cite(keys, mode="paren")
        cite.rendered = result or None
        return cite

    def _endnote_cite(self, instr: str, result: str) -> ir.Cite:
        """An EndNote ``ADDIN EN.CITE …<rec-number>…`` field → ``ir.Cite``.

        EndNote stores no BibTeX key, so we use the record number / foreign key
        as a stable identifier (best effort; the formatted text is kept too).
        """
        keys = re.findall(r"<rec-number>([^<]+)</rec-number>", instr)
        if not keys:
            keys = re.findall(r"<key[^>]*>([^<]+)</key>", instr)
        cite = ir.Cite([k.strip() for k in keys if k.strip()], mode="paren")
        cite.rendered = result or None
        return cite

    # -- lists ------------------------------------------------------------ #

    def _build_lists(self, paras: list[etree._Element]) -> list[ir.Block]:
        # group by numId; nest by ilvl with a simple stack.
        roots: list[ir.ItemList] = []
        stack: list[tuple[int, ir.ItemList]] = []  # (ilvl, list)
        for p in paras:
            numpr = self._numpr(p)
            assert numpr is not None  # paras here were selected for having numPr
            ilvl = int(_val(numpr.find(_w("ilvl"))) or "0")
            numid = _val(numpr.find(_w("numId"))) or "1"
            item = ir.ListItem([ir.Paragraph(self._inlines(p))])
            while stack and stack[-1][0] > ilvl:
                stack.pop()
            if stack and stack[-1][0] == ilvl:
                stack[-1][1].items.append(item)
            else:
                lst = ir.ItemList(ordered=(numid == "2"), items=[item])
                if stack:
                    stack[-1][1].items[-1].blocks.append(lst)
                else:
                    roots.append(lst)
                stack.append((ilvl, lst))
        return list(roots)

    # -- algorithm boxes -------------------------------------------------- #

    def _algorithm(self, tbl: etree._Element) -> ir.Algorithm | None:
        """A single-cell ruled box of ``SourceCode`` lines -> ``ir.Algorithm``.

        Reverses our own ``_algorithm`` writer: one row / one cell, an optional
        bold ``Algorithm N: …`` ``Caption`` lead, then numbered/indented
        pseudocode ``SourceCode`` paragraphs. A real ``\\verbatim`` code block is
        emitted as top-level ``SourceCode`` paragraphs, not a table, so a table
        whose cell holds ``SourceCode`` lines is unambiguously our box.
        """
        trs = tbl.findall(_w("tr"))
        if len(trs) != 1:
            return None
        tcs = trs[0].findall(_w("tc"))
        if len(tcs) != 1:
            return None
        paras = tcs[0].findall(_w("p"))
        if not any(self._style(p) == "SourceCode" for p in paras):
            return None
        caption: list[ir.Inline] | None = None
        label: str | None = None
        lines: list[ir.AlgLine] = []
        for p in paras:
            style = self._style(p) or "Normal"
            if style == "Caption":
                text = _all_text(self._inlines(p)).strip()
                if text.startswith("Algorithm"):
                    _, _, rest = text.partition(":")
                    caption = [ir.Text(rest.strip())] if rest.strip() else None
                    label = self._bookmark(p)
                continue
            if style == "SourceCode":
                lines.append(self._alg_line(p))
        return ir.Algorithm(lines=lines, caption=caption, label=label,
                            numbered=caption is not None or label is not None)

    def _alg_line(self, p: etree._Element) -> ir.AlgLine:
        """One pseudocode paragraph -> ``AlgLine`` (indent + number-prefix peeled)."""
        ppr = p.find(_w("pPr"))
        ind = ppr.find(_w("ind")) if ppr is not None else None
        left_attr = ind.get(_w("left")) if ind is not None else None
        left = int(left_attr) if left_attr and left_attr.isdigit() else 360
        indent = max(0, round((left - 360) / 360))
        inlines = self._inlines(p)
        numbered = False
        first = inlines[0] if inlines else None
        if isinstance(first, ir.Text) and re.fullmatch(r"\s*\d+\s+", first.value):
            numbered = True
            inlines = inlines[1:]
        return ir.AlgLine(indent=indent, inlines=inlines, number=numbered)

    # -- description lists ------------------------------------------------ #

    def _description_item(
        self, p: etree._Element
    ) -> tuple[list[ir.Inline], list[ir.Inline]] | None:
        """A ``description``-list item paragraph -> ``(term, definition)`` inlines.

        Reverses our ``_description_item`` writer: an indented ``Normal``
        paragraph (no ``numPr``) whose bold term run(s) are followed by a ``"  "``
        separator, then the definition. The indent + bold-lead + double-space
        shape is specific to our output, so ordinary indented paragraphs and
        theorem leads (whose separator is a bold ``". "``) are not caught.
        """
        ppr = p.find(_w("pPr"))
        if ppr is None or ppr.find(_w("ind")) is None or ppr.find(_w("numPr")) is not None:
            return None
        inlines = self._inlines(p)
        term: list[ir.Inline] = []
        i = 0
        while i < len(inlines):
            head = inlines[i]
            if not (isinstance(head, ir.Emphasis) and head.kind_ == "bold"):
                break
            term.extend(head.inlines)  # unwrap the description-term bold
            i += 1
        if not term or i >= len(inlines):
            return None
        sep = inlines[i]
        if not (isinstance(sep, ir.Text) and sep.value.startswith("  ")):
            return None
        rest = sep.value[2:]
        definition: list[ir.Inline] = ([ir.Text(rest)] if rest else []) + list(inlines[i + 1:])
        return term, definition

    # -- structured document tags (content controls) ---------------------- #

    def _sdt(self, sdt: etree._Element) -> list[ir.Block]:
        """A ``w:sdt``: recover a tagged region (e.g. the bibliography) or, for an
        untagged content control, descend into its content transparently."""
        content = sdt.find(_w("sdtContent"))
        if content is None:
            return []
        pr = sdt.find(_w("sdtPr"))
        tag_el = pr.find(_w("tag")) if pr is not None else None
        tag = tag_el.get(_w("val")) if tag_el is not None else None
        if tag == _BIB_SDT_TAG:
            return [self._bibliography_from_sdt(content)]
        if tag == _FIG_SDT_TAG:
            return [self._figure_from_sdt(content)]
        return self.read_body(content)  # generic content control -> its content

    def _figure_from_sdt(self, content: etree._Element) -> ir.Figure:
        """Recover a figure (incl. a sub-figure grid) from its tagged SDT.

        Image paths come from each drawing's alt-text (the original source path);
        the ``Figure N:`` Caption gives the caption. Multiple drawings -> a
        sub-figure figure, so it round-trips as a Figure, not a Table."""
        paths = [_drawing_descr(d) for d in content.iter(_w("drawing"))]
        caption: list[ir.Inline] | None = None
        for p in content.findall(_w("p")):
            if self._style(p) == "Caption":
                cap = self._caption_after(p, "Figure")
                if cap is not None:
                    caption = cap
                    break
        if len(paths) <= 1:
            image = ir.Image(path=paths[0]) if paths else None
            return ir.Figure(image=image, caption=caption)
        subs = [ir.SubFigure(image=ir.Image(path=p)) for p in paths]
        return ir.Figure(image=None, caption=caption, subfigures=subs)

    def _bibliography_from_sdt(self, content: etree._Element) -> ir.Bibliography:
        """Recover the reference list from its tagged SDT as an ``ir.Bibliography``.

        The reference *text* is preserved (as each entry's CSL ``note``) so a
        foreign round-trip keeps it; for our own output the reconcile keeps the
        exact manifest entries (the signature is type-only)."""
        entries: list[ir.CSLItem] = []
        for p in content.findall(_w("p")):
            if self._style(p) != "Bibliography":
                continue
            text = re.sub(r"^\[\d+\]\s*", "", _plain_text(self._inlines(p)))
            bm = self._bookmark(p) or ""
            cid = bm[4:] if bm.startswith("bib_") else f"ref{len(entries) + 1}"
            entries.append(ir.CSLItem(id=cid or f"ref{len(entries) + 1}", type="",
                                      csl_fields={"note": text}))
        return ir.Bibliography(entries=entries)

    # -- tables ----------------------------------------------------------- #

    def _table(self, tbl: etree._Element) -> ir.Table:
        rows: list[ir.TableRow] = []
        ncols = 0
        for tr in tbl.findall(_w("tr")):
            cells: list[ir.TableCell] = []
            for tc in tr.findall(_w("tc")):
                tcpr = tc.find(_w("tcPr"))
                span = 1
                shade: str | None = None
                if tcpr is not None:
                    if tcpr.find(_w("gridSpan")) is not None:
                        span = int(_val(tcpr.find(_w("gridSpan"))) or "1")
                    shd = tcpr.find(_w("shd"))
                    fill = shd.get(_w("fill")) if shd is not None else None
                    if fill and fill != "auto":
                        shade = fill
                blocks = [self._paragraph(p) or ir.Paragraph([]) for p in tc.findall(_w("p"))]
                cells.append(ir.TableCell([b for b in blocks], colspan=span, shade=shade))
            ncols = max(ncols, sum(c.colspan for c in cells))
            rows.append(ir.TableRow(cells))
        return ir.Table(rows=rows, colspec=["left"] * ncols)


_OFF_VALS = {"false", "0", "none", "off"}


def _toggle_on(e: etree._Element | None) -> bool:
    """A toggle/property element is on unless its w:val says otherwise.

    Guards against ``w:highlight w:val="none"`` / ``w:u w:val="none"`` /
    ``w:b w:val="false"`` being read as the formatting being present.
    """
    if e is None:
        return False
    return (e.get(_w("val")) or "true").lower() not in _OFF_VALS


def _val(e: etree._Element | None) -> str | None:
    return e.get(_w("val")) if e is not None else None


#: common LaTeX cross-reference label prefixes (for the no-manifest heuristic).
_REF_PREFIXES = {
    "eq", "fig", "tab", "tbl", "sec", "subsec", "thm", "lem", "cor", "def", "defn",
    "prop", "rem", "ex", "exa", "alg", "app", "ch", "chap", "chapter", "part",
    "line", "item", "lst", "list", "claim", "assum", "fact", "obs", "note", "step",
}


def _unsanitize(bookmark: str) -> str:
    """Best-effort reverse of bookmark sanitisation without a manifest map.

    Sanitisation turns ``eq:e`` into ``eq_e``; when the part before the first
    underscore is a common cross-ref prefix, restore the colon (``eq_e`` ->
    ``eq:e``). Otherwise leave it as-is."""
    if bookmark.startswith("ref_"):
        bookmark = bookmark[4:]
    head, sep, rest = bookmark.partition("_")
    if sep and rest and head.lower() in _REF_PREFIXES:
        return f"{head}:{rest}"
    return bookmark
