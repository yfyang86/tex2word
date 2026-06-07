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

