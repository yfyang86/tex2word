"""OOXML namespace registry and a tiny lxml element-builder.

All OOXML generation goes through :func:`el`/:func:`sub` so namespaces are
declared once and consistently. We deliberately work at the raw-XML level
(rather than via ``python-docx``) because the PRD's headline features -- OMML
math, bookmarks, and cross-reference fields -- are exactly what ``python-docx``
cannot create natively.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def qn(tag: str) -> str:
    """Resolve a ``prefix:local`` tag into a Clark-notation qualified name."""
    prefix, _, local = tag.partition(":")
    if not local:
        prefix, local = "w", prefix
    return f"{{{NS[prefix]}}}{local}"


def el(tag: str, *children: etree._Element, **attrs: Any) -> etree._Element:
    """Create an element. Attribute keys may be ``prefix:local`` or plain.

    Every element carries the full ``NS`` map; lxml only emits each declaration
    once (at the outermost element where it comes into scope), so a serialized
    document declares all namespaces on its root with stable ``w:``/``m:``
    prefixes.
    """
    node = etree.Element(qn(tag), nsmap=NS)
    _set_attrs(node, attrs)
    for child in children:
        node.append(child)
    return node


def sub(parent: etree._Element, tag: str, **attrs: Any) -> etree._Element:
    node = etree.SubElement(parent, qn(tag), nsmap=NS)
    _set_attrs(node, attrs)
    return node


def _set_attrs(node: etree._Element, attrs: dict[str, Any]) -> None:
    """Set attributes; ``prefix:local`` keys are namespaced, plain keys are not.

    DrawingML attributes (``uri``, ``cx``, ``id``, ``prst``, ...) live in no
    namespace, whereas WordprocessingML attributes are spelled ``w:val`` etc.
    """
    for key, value in attrs.items():
        node.set(qn(key) if ":" in key else key, str(value))


def text_el(tag: str, text: str, **attrs: Any) -> etree._Element:
    node = el(tag, **attrs)
    node.text = text
    return node


def serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def preserve_space(node: etree._Element) -> etree._Element:
    """Mark a ``w:t`` (or similar) to preserve leading/trailing whitespace."""
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return node
