"""Pragmatic OOXML/OPC validation of a generated .docx.

Full ECMA-376 XSD validation needs the (large, cross-importing) transitional
schema set, which doesn't load cleanly under ``lxml`` without substantial
patching and would require vendoring/fetching ~2.5 MB of schemas. This module
instead enforces the invariants that actually catch *our* bugs:

1. **OPC structure** — the package opens, required parts exist, every XML part
   is well-formed, every part has a declared content type, and every
   relationship target resolves to a real part.
2. **Schema-aware content model** — a curated subset of the ECMA-376
   WordprocessingML rules for the elements we emit: the child-ordering of the
   run/paragraph/table property complex types (``w:rPr``/``w:pPr``/``w:tblPr``/
   ``w:trPr``/``w:tcPr`` follow the schema sequence — the exact class of defect
   that ships invalid documents Word silently repairs), plus a few enumerated
   attribute-value checks. This is **not** full XSD validation, but it catches
   the realistic violations and runs offline in CI.

Wired into the test/corpus harness so malformed output fails CI.
"""

from __future__ import annotations

import io
import posixpath
import zipfile

from lxml import etree

_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_REQUIRED = (
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/styles.xml",
)

# ECMA-376 content-model child order for the property complex types we emit.
# Each maps the parent element local-name to its canonical child sequence
# (a subset — children not listed carry no ordering constraint, so we never
# false-positive on elements we haven't enumerated). Sources: EG_RPrBase,
# EG_PPrBase/CT_PPr, CT_TblPr, CT_TrPr, CT_TcPr.
_CHILD_ORDER: dict[str, list[str]] = {
    "rPr": [
        "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
        "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
        "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
        "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
        "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
        "eastAsianLayout", "specVanish", "oMath",
    ],
    "pPr": [
        "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
        "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
        "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
        "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
        "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
        "suppressOverlap", "jc", "textDirection", "textAlignment",
        "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
        "pPrChange",
    ],
    "tblPr": [
        "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
        "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
        "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption",
        "tblDescription", "tblPrChange",
    ],
    "trPr": [
        "cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter",
        "cantSplit", "trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden",
        "ins", "del", "trPrChange",
    ],
    "tcPr": [
        "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd",
        "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark",
        "cellIns", "cellDel", "cellMerge", "tcPrChange",
    ],
}

# Enumerated attribute values we emit, per ECMA-376 simple types.
_ST_HIGHLIGHT = {
    "black", "blue", "cyan", "darkBlue", "darkCyan", "darkGray", "darkGreen",
    "darkMagenta", "darkRed", "darkYellow", "green", "lightGray", "magenta",
    "none", "red", "white", "yellow",
}
_ST_VERTALIGN = {"baseline", "superscript", "subscript"}


def validate_docx(docx_bytes: bytes) -> list[str]:
    """Return a list of validation problems (empty == valid)."""
    problems: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    except zipfile.BadZipFile as exc:
        return [f"not a valid zip: {exc}"]

    names = set(zf.namelist())
    for required in _REQUIRED:
        if required not in names:
            problems.append(f"missing required part: {required}")

    # every xml/rels part must be well-formed
    for name in names:
        if name.endswith((".xml", ".rels")):
            try:
                root = etree.fromstring(zf.read(name))
            except etree.XMLSyntaxError as exc:
                problems.append(f"malformed XML in {name}: {exc}")
                continue
            if name.startswith("word/") and name.endswith(".xml"):
                problems += _check_content_model(name, root)

    problems += _check_content_types(zf, names)
    problems += _check_relationships(zf, names)
    return problems


def _check_content_model(part: str, root: etree._Element) -> list[str]:
    """Schema-aware checks on WordprocessingML property elements."""
    problems: list[str] = []
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str) or not tag.startswith(f"{{{_W}}}"):
            continue
        local = tag[len(_W) + 2:]
        order = _CHILD_ORDER.get(local)
        if order is not None:
            problems += _check_order(part, local, el, order)
        elif local == "highlight":
            problems += _check_enum(part, el, _ST_HIGHLIGHT, "highlight")
        elif local == "vertAlign":
            problems += _check_enum(part, el, _ST_VERTALIGN, "vertAlign")
        elif local in ("sz", "szCs"):
            val = el.get(f"{{{_W}}}val")
            if val is not None and not val.isdigit():
                problems.append(f"{part}: w:{local}@w:val must be an integer, got {val!r}")
    return problems


def _check_order(part: str, parent: str, el: etree._Element, order: list[str]) -> list[str]:
    rank = {name: i for i, name in enumerate(order)}
    seen: list[tuple[int, str]] = []
    for child in el:
        ctag = child.tag
        if not isinstance(ctag, str) or not ctag.startswith(f"{{{_W}}}"):
            continue
        name = ctag[len(_W) + 2:]
        if name in rank:
            seen.append((rank[name], name))
    for (a_rank, a_name), (b_rank, b_name) in zip(seen, seen[1:], strict=False):
        if b_rank < a_rank:
            return [
                f"{part}: w:{parent} children out of ECMA-376 order: "
                f"w:{b_name} must precede w:{a_name}"
            ]
    return []


def _check_enum(part: str, el: etree._Element, allowed: set[str], name: str) -> list[str]:
    val = el.get(f"{{{_W}}}val")
    if val is not None and val not in allowed:
        return [f"{part}: w:{name}@w:val={val!r} is not a valid ST value"]
    return []


def _check_content_types(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    if "[Content_Types].xml" not in names:
        return []
    problems: list[str] = []
    root = etree.fromstring(zf.read("[Content_Types].xml"))
    defaults = {
        e.get("Extension", "").lower()
        for e in root.findall(f"{{{_CT_NS}}}Default")
    }
    overrides = {e.get("PartName") for e in root.findall(f"{{{_CT_NS}}}Override")}
    for name in names:
        if name == "[Content_Types].xml" or name.endswith("/"):
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        partname = "/" + name
        if ext not in defaults and partname not in overrides:
            problems.append(f"no declared content type for part: {name}")
    return problems


def _check_relationships(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    problems: list[str] = []
    for name in names:
        if not name.endswith(".rels"):
            continue
        base = posixpath.dirname(posixpath.dirname(name))  # strip "_rels/x.rels"
        root = etree.fromstring(zf.read(name))
        for rel in root.findall(f"{{{_REL_NS}}}Relationship"):
            if (rel.get("TargetMode") or "Internal") == "External":
                continue
            target = rel.get("Target", "")
            resolved = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
            if resolved not in names:
                problems.append(f"{name}: relationship target not found: {target}")
    return problems
