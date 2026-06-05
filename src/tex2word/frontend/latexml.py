"""LaTeXML front-end (SPRINT-V3 A1): genuine TeX expansion -> IR.

Shells out to ``latexml`` (Perl, public-domain, NIST) which digests TeX through
a real Gullet/Stomach model and emits semantic XML, then maps that XML to the
IR. This expands arbitrary user/corporate macros and packages *before* we build
the IR -- the residual "unknown macro / transparent environment" warnings of the
static `pylatexenc` front-end disappear.

LaTeXML conveniently keeps the normalised TeX of every formula in a ``tex``
attribute on ``<ltx:Math>``, so math still flows through the direct
LaTeX->OMML writer.

The pure-Python front-end stays the zero-dependency default; this is opt-in via
``--frontend latexml`` and degrades gracefully (warn + fall back) when
``latexml`` is not installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from lxml import etree

from .. import ir
from ..report import ConversionReport

LTX = "http://dlmf.nist.gov/LaTeXML"

_SECTION_LEVEL = {
    "part": 1, "chapter": 1, "section": 1, "subsection": 2,
    "subsubsection": 3, "paragraph": 4, "subparagraph": 4,
}
_FONT_EMPH = {
    "bold": "bold", "italic": "italic", "smallcaps": "smallcaps",
    "typewriter": "typewriter", "sansserif": "italic",
}


def latexml_available() -> bool:
    """True if the ``latexml`` executable is on the PATH."""
    return shutil.which("latexml") is not None


def run_latexml(source: str, base_dir: str = ".") -> bytes:
    """Run ``latexml`` on ``source`` and return the LaTeXML XML bytes.

    Raises :class:`RuntimeError` if latexml is unavailable or fails.
    """
    if not latexml_available():
        raise RuntimeError("latexml executable not found")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "main.tex")
        with open(inp, "w", encoding="utf-8") as fh:
            fh.write(source)
        # Write to a real file rather than --dest=- : this latexml treats "-" as
        # a filename and leaves stdout empty (rc=0, 0B). No --quiet, so latexml's
        # diagnostics reach stderr and surface in the error below.
        out = os.path.join(td, "out.xml")
        cmd = ["latexml", "--nocomments", f"--path={base_dir}", f"--dest={out}", inp]
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        data = b""
        if os.path.exists(out):
            with open(out, "rb") as fh:
                data = fh.read()
        if proc.returncode != 0 or not data:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"latexml rc={proc.returncode}, {len(data)}B output; "
                f"{err[-400:] or '(no stderr)'}"
            )
        return data


def parse_document(source: str, base_dir: str = ".") -> tuple[ir.Document, ConversionReport]:
    """Parse via latexml. Falls back to the pure-Python front-end on failure."""
    try:
        xml = run_latexml(source, base_dir)
    except Exception as exc:
        from .parser import parse_document as pure

        doc, report = pure(source, base_dir)
        report.warn("latexml", f"latexml unavailable/failed ({exc}); used pure front-end")
        return doc, report
    report = ConversionReport()
    doc = parse_latexml_xml(xml, report)
    report.info("latexml", "parsed with the latexml front-end")
    return doc, report


def parse_latexml_xml(xml: bytes, report: ConversionReport) -> ir.Document:
    """Map a LaTeXML XML document to the IR."""
    root = etree.fromstring(xml)
    return _Mapper(report).document(root)


# --------------------------------------------------------------------------- #


def _tag(e: etree._Element) -> str:
    return etree.QName(e).localname


def _ltx(name: str) -> str:
    return f"{{{LTX}}}{name}"


def _label_of(e: etree._Element) -> str | None:
    labels = e.get("labels")
    if labels:
        return labels.split()[0].removeprefix("LABEL:")
    return None


def _parent_tag(e: etree._Element) -> str:
    parent = e.getparent()
    return _tag(parent) if parent is not None else ""


class _Mapper:
    def __init__(self, report: ConversionReport) -> None:
        self.report = report
        self.meta = ir.DocumentMeta()

    def document(self, root: etree._Element) -> ir.Document:
        # LaTeXML wraps the body in <ltx:document>; find it (root may be it).
        doc_el = root if _tag(root) == "document" else root.find(_ltx("document"))
        if doc_el is None:
            doc_el = root
        blocks = self._blocks(doc_el)
        return ir.Document(blocks=blocks, meta=self.meta)

    # -- blocks ----------------------------------------------------------- #

    def _blocks(self, parent: etree._Element) -> list[ir.Block]:
        out: list[ir.Block] = []
        for child in parent:
            self._block(child, out)
        return out

    def _block(self, e: etree._Element, out: list[ir.Block]) -> None:  # noqa: C901
        tag = _tag(e)
        if tag in _SECTION_LEVEL:
            title = e.find(_ltx("title"))
            inlines = self._inlines(title) if title is not None else []
            numbered = "unnumbered" not in (e.get("class") or "")
            out.append(ir.Heading(_SECTION_LEVEL[tag], inlines, label=_label_of(e),
                                  numbered=numbered))
            for child in e:
                if _tag(child) != "title":
                    self._block(child, out)
        elif tag == "title" and _parent_tag(e) == "document":
            self.meta.title = self._inlines(e)
        elif tag == "creator":
            self.meta.authors.append(self._inlines(e))
        elif tag == "abstract":
            self.meta.abstract = self._blocks(e)
        elif tag == "para":
            out.extend(self._blocks(e))
        elif tag == "p":
            inl = self._inlines(e)
            if inl:
                out.append(ir.Paragraph(inl))
        elif tag in ("equation", "equationgroup"):
            out.append(self._equation(e))
        elif tag in ("itemize", "enumerate", "description"):
            out.append(self._list(e, tag))
        elif tag in ("quote", "block"):
            out.append(ir.Quote(self._blocks(e)))
        elif tag == "tabular":
            out.append(self._table(e))
        elif tag in ("figure", "float"):
            out.append(self._figure(e))
        elif tag in ("verbatim", "listing"):
            out.append(ir.CodeBlock("".join(str(t) for t in e.itertext())))
        elif tag in ("note",):
            pass  # footnotes handled inline
        else:
            # unknown container: recurse, preserving whatever blocks it holds
            inner = self._blocks(e)
            if inner:
                out.extend(inner)
            else:
                inl = self._inlines(e)
                if inl:
                    out.append(ir.Paragraph(inl))

    def _equation(self, e: etree._Element) -> ir.MathBlock:
        math = e.find(f".//{_ltx('Math')}")
        tex = (math.get("tex") if math is not None else None) or ""
        numbered = e.get("refnum") is not None or _label_of(e) is not None
        return ir.MathBlock(latex=tex, numbered=numbered, env="equation", label=_label_of(e))

    def _list(self, e: etree._Element, tag: str) -> ir.ItemList:
        items = []
        for item in e.findall(_ltx("item")):
            tag_el = item.find(_ltx("tag"))
            term = self._inlines(tag_el) if (tag == "description" and tag_el is not None) else None
            items.append(ir.ListItem(self._blocks(item), term=term))
        return ir.ItemList(ordered=(tag == "enumerate"), items=items,
                           description=(tag == "description"))

    def _table(self, e: etree._Element) -> ir.Table:
        rows = []
        for tr in e.findall(_ltx("tr")):
            cells = []
            for td in tr.findall(_ltx("td")):
                span = int(td.get("colspan") or "1")
                cells.append(ir.TableCell([ir.Paragraph(self._inlines(td))], colspan=span))
            rows.append(ir.TableRow(cells))
        return ir.Table(rows=rows, colspec=["left"] * max((len(r.cells) for r in rows), default=1))

    def _figure(self, e: etree._Element) -> ir.Figure:
        graphic = e.find(f".//{_ltx('graphics')}")
        image = None
        if graphic is not None:
            path = graphic.get("graphic") or graphic.get("candidates") or ""
            ext = path.rsplit(".", 1)[-1] if "." in path else ""
            image = ir.Image(path=path, original_format=ext)
        cap_el = e.find(_ltx("caption"))
        caption = self._inlines(cap_el) if cap_el is not None else None
        return ir.Figure(image=image, caption=caption, label=_label_of(e))

    # -- inline ----------------------------------------------------------- #

    def _inlines(self, e: etree._Element | None) -> list[ir.Inline]:
        if e is None:
            return []
        out: list[ir.Inline] = []
        if e.text:
            out.append(ir.Text(e.text))
        for child in e:
            self._inline(child, out)
            if child.tail:
                out.append(ir.Text(child.tail))
        return _merge_text(out)

    def _inline(self, e: etree._Element, out: list[ir.Inline]) -> None:  # noqa: C901
        tag = _tag(e)
        if tag == "Math":
            out.append(ir.Math(e.get("tex") or ""))
        elif tag == "text":
            font = e.get("font") or ""
            kind = next((v for k, v in _FONT_EMPH.items() if k in font), None)
            inner = self._inlines(e)
            if kind:
                out.append(ir.Emphasis(inner, kind))  # type: ignore[arg-type]
            else:
                out.extend(inner)  # unstyled group -> transparent
        elif tag == "emph":
            out.append(ir.Emphasis(self._inlines(e), "italic"))
        elif tag == "ref":
            labelref = (e.get("labelref") or e.get("idref") or "").removeprefix("LABEL:")
            href = e.get("href")
            if labelref:
                out.append(ir.Ref(labelref, "generic"))
            elif href:
                out.append(ir.Link(self._inlines(e) or [ir.Text(href)], href))
            else:
                out.extend(self._inlines(e))
        elif tag == "cite":
            keys: list[str] = []
            for br in e.findall(f".//{_ltx('bibref')}"):
                keys += (br.get("bibrefs") or "").split(",")
            out.append(ir.Cite([k for k in keys if k], "paren"))
        elif tag == "note":
            out.append(ir.Footnote(self._inlines(e)))
        elif tag == "break":
            out.append(ir.LineBreak())
        else:
            out.extend(self._inlines(e))


def _merge_text(nodes: list[ir.Inline]) -> list[ir.Inline]:
    merged: list[ir.Inline] = []
    for n in nodes:
        if isinstance(n, ir.Text) and merged and isinstance(merged[-1], ir.Text):
            merged[-1] = ir.Text(merged[-1].value + n.value)
        else:
            merged.append(n)
    return [n for n in merged if not (isinstance(n, ir.Text) and not n.value)]
