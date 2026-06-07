"""Packaged reference templates (the 'reference-doc' pattern)."""

from __future__ import annotations

from importlib import resources

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load_styles_xml() -> bytes:
    """Return the curated reference ``styles.xml`` shipped with the package."""
    return resources.files(__package__).joinpath("styles.xml").read_bytes()


def apply_language(styles_xml: bytes, lang: str) -> bytes:
    """Set the document default language (``w:lang``) in the styles docDefaults.

    Word uses this for spell-check and accessibility (document language). Returns
    the styles bytes unchanged if the structure isn't found."""
    from lxml import etree

    def w(name: str) -> str:
        return f"{{{_W}}}{name}"

    try:
        root = etree.fromstring(styles_xml)
    except Exception:
        return styles_xml
    rpr = root.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}")
    if rpr is None:
        return styles_xml
    lang_el = rpr.find(w("lang"))
    if lang_el is None:
        lang_el = etree.SubElement(rpr, w("lang"))  # last child (lang is late in CT_RPr)
    lang_el.set(w("val"), lang)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# Heading/title styles that should pick up the CJK *sans* font.
_SANS_CJK_STYLES = (
    "Title", "Subtitle", "Heading1", "Heading2", "Heading3", "Heading4", "Heading5",
)


def apply_fonts(
    styles_xml: bytes,
    *,
    main: str | None = None,
    cjk_main: str | None = None,
    cjk_sans: str | None = None,
    cjk_mono: str | None = None,
) -> bytes:
    """Apply XeLaTeX/xeCJK font choices to the styles ``docDefaults`` (and styles).

    ``main`` sets the Latin default (``w:ascii``/``w:hAnsi``); ``cjk_main`` sets the
    East-Asian default (``w:eastAsia``) so Word renders CJK runs in that font
    document-wide. ``cjk_sans`` is applied to the heading/title styles and
    ``cjk_mono`` to the Source Code style. Returns the bytes unchanged if the
    expected structure isn't present."""
    from lxml import etree

    def w(name: str) -> str:
        return f"{{{_W}}}{name}"

    def set_rfonts(rpr: etree._Element, **attrs: str | None) -> None:
        """Set/merge ``w:rFonts`` (first child of ``w:rPr`` per CT_RPr order)."""
        rfonts = rpr.find(w("rFonts"))
        if rfonts is None:
            rfonts = etree.Element(w("rFonts"))
            rpr.insert(0, rfonts)
        for key, val in attrs.items():
            if val:
                rfonts.set(w(key), val)

    if not (main or cjk_main or cjk_sans or cjk_mono):
        return styles_xml
    try:
        root = etree.fromstring(styles_xml)
    except Exception:
        return styles_xml

    default_rpr = root.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}")
    if default_rpr is not None and (main or cjk_main):
        set_rfonts(default_rpr, ascii=main, hAnsi=main, eastAsia=cjk_main)

    if cjk_sans or cjk_mono:
        styles_by_id = {s.get(w("styleId")): s for s in root.findall(w("style"))}

        def style_rpr(style_id: str) -> etree._Element | None:
            style = styles_by_id.get(style_id)
            if style is None:
                return None
            rpr = style.find(w("rPr"))
            if rpr is None:  # rPr is late in CT_Style, after name/basedOn/next/pPr
                rpr = etree.SubElement(style, w("rPr"))
            return rpr

        if cjk_sans:
            for sid in _SANS_CJK_STYLES:
                rpr = style_rpr(sid)
                if rpr is not None:
                    set_rfonts(rpr, eastAsia=cjk_sans)
        if cjk_mono:
            rpr = style_rpr("SourceCode")
            if rpr is not None:
                set_rfonts(rpr, eastAsia=cjk_mono)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

