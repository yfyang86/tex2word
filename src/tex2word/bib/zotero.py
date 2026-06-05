"""Live Zotero/Mendeley citation fields (PRD §D).

Emits ``ADDIN ZOTERO_ITEM CSL_CITATION {…CSL-JSON…}`` field codes (and a
matching ``CSL_BIBLIOGRAPHY`` field) so citations are live and editable by
reference managers in Word, rather than flattened text. The CSL-JSON is built
from the same ``.bib``→CSL-JSON parse used for the static renderer.
"""

from __future__ import annotations

import json
import zlib
from itertools import count

from lxml import etree

from .. import ir
from ..backend import fields

_Element = etree._Element
_CSL_SCHEMA = (
    "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"
)
_citation_seq = count(1)


def reset_ids() -> None:
    global _citation_seq
    _citation_seq = count(1)


def _numeric_id(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF


def _item_data(item: ir.CSLItem) -> dict:
    data: dict = {"id": item.id, "type": item.type}
    data.update(item.csl_fields)
    return data


def _citation_item(cite: ir.Cite, key: str, item: ir.CSLItem) -> dict:
    out: dict = {
        "id": _numeric_id(key),
        "uris": [f"http://zotero.org/users/local/tex2word/items/{key}"],
        "itemData": _item_data(item),
    }
    if cite.suffix:
        out["locator"] = cite.suffix
    if cite.prefix:
        out["prefix"] = cite.prefix
    return out


def citation_field(
    cite: ir.Cite, items: dict[str, ir.CSLItem], rendered: str
) -> list[_Element]:
    """Build the runs for one ``ADDIN ZOTERO_ITEM CSL_CITATION`` field."""
    citation = {
        "citationID": f"l2w{next(_citation_seq)}",
        "properties": {"formattedCitation": rendered, "plainCitation": rendered, "noteIndex": 0},
        "citationItems": [
            _citation_item(cite, k, items[k]) for k in cite.keys if k in items
        ],
        "schema": _CSL_SCHEMA,
    }
    payload = json.dumps(citation, ensure_ascii=False, separators=(",", ":"))
    return fields.field(f"ADDIN ZOTERO_ITEM CSL_CITATION {payload}", rendered or " ")


def bibliography_field_runs(rendered_lines: list[str]) -> list[_Element]:
    """Build the runs for the ``CSL_BIBLIOGRAPHY`` field instruction.

    The formatted reference list itself is emitted as ordinary paragraphs by the
    caller (inside the field's begin/end), so reference managers can refresh it.
    """
    code = 'ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY'
    return fields.field(code, "")
