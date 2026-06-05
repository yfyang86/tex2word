"""Reference-document ("template") support for the ``--reference-doc`` option.

The flagship adoption feature (PRD v3, V5-1): convert onto the named styles,
theme and page geometry of a user-supplied Word template so the output matches a
journal's or organisation's required look -- while keeping latex2word's live
fields intact.

We do *not* clone the reference wholesale (that would lose our content); instead
we lift its styling parts -- ``styles.xml`` (merged with the few custom styles we
require), the theme, and the body section geometry (page size + margins) -- and
emit our own ``document.xml`` against them. Our writer already references the
standard Word style ids (``Title``/``Heading1``..``Heading5``/``Caption``/
``Quote``/``Normal``/...), so a template's definitions of those ids simply take
effect.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field

from lxml import etree

from . import load_styles_xml

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _w(name: str) -> str:
    return f"{{{_W}}}{name}"


# image extensions our package already declares a content-type Default for, so a
# carried header/footer logo needs no extra content-type plumbing.
_CARRY_IMAGE_EXT = {"png", "jpg", "jpeg", "emf"}


@dataclass
class HeaderFooter:
    """A carried header/footer part from the reference template."""

    kind: str  # "header" or "footer"
    w_type: str  # "default" / "first" / "even"
    part_name: str  # archive basename, e.g. "header1.xml"
    content: bytes
    rels: bytes | None = None  # rewritten word/_rels/<part>.rels, if it has any
    media: dict[str, bytes] = field(default_factory=dict)  # arcname -> bytes


@dataclass
class ReferenceParts:
    """Styling parts lifted from a reference ``.docx``."""

    styles_xml: bytes  # the reference styles, merged with our required styles
    theme_xml: bytes | None = None  # word/theme/theme1.xml, if present
    page_pgsz: dict[str, str] | None = None  # body w:pgSz attributes
    page_pgmar: dict[str, str] | None = None  # body w:pgMar attributes
    headers_footers: list[HeaderFooter] = field(default_factory=list)
    skipped_header_footers: int = 0  # carried only rels-free parts; count skipped


def extract_reference(docx_bytes: bytes) -> ReferenceParts:
    """Lift the styling parts from a reference ``.docx``.

    Raises :class:`ValueError` if it is not a readable docx with a ``styles.xml``.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
        names = set(zf.namelist())
        if "word/styles.xml" not in names:
            raise ValueError("reference docx has no word/styles.xml")
        styles = merge_styles(zf.read("word/styles.xml"), load_styles_xml())
        theme = None
        # the theme part name varies (theme1.xml); take the first under word/theme/
        theme_name = next(
            (n for n in sorted(names) if n.startswith("word/theme/") and n.endswith(".xml")),
            None,
        )
        if theme_name is not None:
            theme = zf.read(theme_name)
        pgsz = pgmar = None
        hfs: list[HeaderFooter] = []
        skipped = 0
        if "word/document.xml" in names:
            doc_xml = zf.read("word/document.xml")
            pgsz, pgmar = _page_geometry(doc_xml)
            hfs, skipped = _headers_footers(doc_xml, zf, names)
        return ReferenceParts(styles_xml=styles, theme_xml=theme,
                              page_pgsz=pgsz, page_pgmar=pgmar,
                              headers_footers=hfs, skipped_header_footers=skipped)
    except ValueError:
        raise
    except Exception as exc:  # corrupt zip / malformed XML
        raise ValueError(f"unreadable reference docx: {exc}") from exc


def merge_styles(reference_styles: bytes, our_styles: bytes) -> bytes:
    """Reference styles, augmented with any of *our* styles it doesn't define.

    The reference's definitions of standard ids (``Heading1``, ``Title``, ...)
    win -- that is the whole point. We only append the custom styles our writer
    relies on (``SourceCode``, ``Abstract``, ``Bibliography``, ``Hyperlink``,
    footnote styles, ...) when the template lacks them, so no content renders
    unstyled.
    """
    ref_root = etree.fromstring(reference_styles)
    have = {
        s.get(_w("styleId"))
        for s in ref_root.findall(_w("style"))
        if s.get(_w("styleId"))
    }
    our_root = etree.fromstring(our_styles)
    for style in our_root.findall(_w("style")):
        sid = style.get(_w("styleId"))
        if sid and sid not in have:
            ref_root.append(style)
            have.add(sid)
    return etree.tostring(ref_root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _headers_footers(
    document_xml: bytes, zf: zipfile.ZipFile, names: set[str]
) -> tuple[list[HeaderFooter], int]:
    """Carry the body sectPr's header/footer parts (with image sub-resources).

    Running-title text + page-number fields carry directly; a header/footer that
    references **images** (a logo) carries its media too (namespaced under
    ``media/tmpl/`` with the rels rewritten). Anything we can't represent safely
    (a non-image internal relationship, an unsupported image type, a missing
    target) is skipped so we never emit a dangling relationship; external (URL)
    relationships are kept as-is. Returns (carried, skipped_count).
    """
    root = etree.fromstring(document_xml)
    body = root.find(_w("body"))
    if body is None:
        return [], 0
    sect = next((c for c in reversed(list(body)) if c.tag == _w("sectPr")), None)
    if sect is None:
        return [], 0
    rid_target = _rel_targets(zf, names)
    rid_attr = f"{{{_R}}}id"
    carried: list[HeaderFooter] = []
    skipped = 0
    for ref in sect:
        if ref.tag == _w("headerReference"):
            kind = "header"
        elif ref.tag == _w("footerReference"):
            kind = "footer"
        else:
            continue
        target = rid_target.get(ref.get(rid_attr) or "")
        if not target:
            continue
        base = target.rsplit("/", 1)[-1]
        part = f"word/{base}"
        if part not in names:
            skipped += 1
            continue
        sub = _carry_subresources(zf, names, base)
        if sub is None:  # an unsupported sub-resource -> skip, don't dangle a rel
            skipped += 1
            continue
        rels_bytes, media = sub
        carried.append(HeaderFooter(
            kind=kind, w_type=ref.get(_w("type")) or "default",
            part_name=base, content=zf.read(part),
            rels=rels_bytes or None, media=media,
        ))
    return carried, skipped


def _carry_subresources(
    zf: zipfile.ZipFile, names: set[str], base: str
) -> tuple[bytes, dict[str, bytes]] | None:
    """Rewrite a header/footer's ``.rels`` + collect its image media, or None.

    Returns ``(rewritten_rels_bytes_or_empty, {arcname: bytes})``. ``None`` means
    the part has a sub-resource we can't carry safely (skip the whole part).
    """
    rels_path = f"word/_rels/{base}.rels"
    if rels_path not in names:
        return b"", {}  # no sub-rels at all
    try:
        root = etree.fromstring(zf.read(rels_path))
    except Exception:
        return None
    stem = base.rsplit(".", 1)[0]
    media: dict[str, bytes] = {}
    for rel in root.findall(f"{{{_PKG_REL}}}Relationship"):
        if (rel.get("TargetMode") or "Internal") == "External":
            continue  # a URL: no part to carry, keep the relationship as-is
        rtype = rel.get("Type") or ""
        target = rel.get("Target") or ""
        ext = target.rsplit(".", 1)[-1].lower() if "." in target else ""
        if not rtype.endswith("/image") or ext not in _CARRY_IMAGE_EXT or ".." in target:
            return None
        src = posixpath.normpath(f"word/{target.lstrip('/')}")
        if src not in names:
            return None
        new_base = f"{stem}_{target.rsplit('/', 1)[-1]}"
        media[f"word/media/tmpl/{new_base}"] = zf.read(src)
        rel.set("Target", f"media/tmpl/{new_base}")
    rels_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return rels_bytes, media


def _rel_targets(zf: zipfile.ZipFile, names: set[str]) -> dict[str, str]:
    """{relationship id -> target} from word/_rels/document.xml.rels."""
    path = "word/_rels/document.xml.rels"
    if path not in names:
        return {}
    root = etree.fromstring(zf.read(path))
    out: dict[str, str] = {}
    for r in root.findall(f"{{{_PKG_REL}}}Relationship"):
        rid, target = r.get("Id"), r.get("Target")
        if rid and target:
            out[rid] = target
    return out


def _page_geometry(document_xml: bytes) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """The body ``w:sectPr`` page size + margins from a document.xml, if present."""
    root = etree.fromstring(document_xml)
    body = root.find(_w("body"))
    if body is None:
        return None, None
    # the body-level sectPr is the last direct child of <w:body>.
    sect = next((c for c in reversed(list(body)) if c.tag == _w("sectPr")), None)
    if sect is None:
        return None, None

    def attrs(el: etree._Element | None) -> dict[str, str] | None:
        if el is None:
            return None
        return {
            f"w:{etree.QName(k).localname}": v.decode() if isinstance(v, bytes) else v
            for k, v in el.attrib.items()
        }

    return attrs(sect.find(_w("pgSz"))), attrs(sect.find(_w("pgMar")))
