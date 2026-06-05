"""A small BibTeX parser producing CSL-JSON items.

Not a full bibtex implementation: it handles the common entry/field grammar
(``@type{key, field = {value} | "value" | bare, ...}``), brace-aware values,
``@string`` macros, and a heuristic bibtex->CSL field/type mapping. As the PRD
notes, bibtex<->CSL conversion is inherently heuristic and lossy on casing.
"""

from __future__ import annotations

import re

from pylatexenc.latex2text import LatexNodes2Text

from .. import ir

_L2T = LatexNodes2Text(keep_comments=False, strict_latex_spaces=False)

# bibtex entry type -> CSL type
_TYPE_MAP = {
    "article": "article-journal",
    "book": "book",
    "inbook": "chapter",
    "incollection": "chapter",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "proceedings": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "manual": "book",
    "misc": "document",
    "unpublished": "manuscript",
    "online": "webpage",
    "electronic": "webpage",
    "booklet": "pamphlet",
}

# bibtex field -> CSL field (simple string fields)
_FIELD_MAP = {
    "title": "title",
    "journal": "container-title",
    "booktitle": "container-title",
    "publisher": "publisher",
    "school": "publisher",
    "institution": "publisher",
    "volume": "volume",
    "number": "issue",
    "pages": "page",
    "doi": "DOI",
    "url": "URL",
    "edition": "edition",
    "series": "collection-title",
    "note": "note",
    "abstract": "abstract",
    "address": "publisher-place",
    "isbn": "ISBN",
}


def _strip_braces(value: str) -> str:
    """Convert a bibtex field value to plain Unicode (accents, dashes, &, ...)."""
    try:
        text = _L2T.latex_to_text(value)
    except Exception:
        text = value.replace("{", "").replace("}", "").replace("\\&", "&")
    return re.sub(r"\s+", " ", text).strip()


def _split_names(raw: str) -> list[dict[str, str]]:
    """Parse a bibtex ``author``/``editor`` field into CSL name parts."""
    names: list[dict[str, str]] = []
    for chunk in re.split(r"\s+and\s+", raw.strip()):
        chunk = _strip_braces(chunk)
        if not chunk:
            continue
        if "," in chunk:
            family, _, given = chunk.partition(",")
            names.append({"family": family.strip(), "given": given.strip()})
        else:
            parts = chunk.split()
            if len(parts) == 1:
                names.append({"family": parts[0]})
            else:
                names.append({"family": parts[-1], "given": " ".join(parts[:-1])})
    return names


def _tokenize_entry_body(body: str) -> dict[str, str]:
    """Parse ``field = value, ...`` honouring {} and "" delimiters."""
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        # field name
        m = re.match(r"\s*([A-Za-z][A-Za-z0-9_+-]*)\s*=\s*", body[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        if i >= n:
            break
        ch = body[i]
        if ch == "{":
            depth = 0
            j = i
            while j < n:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            value = body[i + 1 : j]
            i = j + 1
        elif ch == '"':
            j = i + 1
            while j < n and body[j] != '"':
                j += 1
            value = body[i + 1 : j]
            i = j + 1
        else:
            j = i
            while j < n and body[j] not in ",\n":
                j += 1
            value = body[i:j]
            i = j
        fields[name] = value
        # consume trailing comma/whitespace
        while i < n and body[i] in ", \n\t\r":
            i += 1
    return fields


def _to_csl(entry_type: str, key: str, raw_fields: dict[str, str]) -> ir.CSLItem:
    csl_type = _TYPE_MAP.get(entry_type, "document")
    out: dict[str, object] = {}
    for name, value in raw_fields.items():
        if name == "author":
            out["author"] = _split_names(value)
        elif name == "editor":
            out["editor"] = _split_names(value)
        elif name == "year":
            out.setdefault("issued", {})
            out["issued"] = {"date-parts": [[_int_or(value)]]}
        elif name == "month":
            continue
        elif name == "date":
            year = re.match(r"\s*(\d{4})", value)
            if year:
                out["issued"] = {"date-parts": [[int(year.group(1))]]}
        elif name in _FIELD_MAP:
            out[_FIELD_MAP[name]] = _strip_braces(value)
    return ir.CSLItem(id=key, type=csl_type, csl_fields=out)


def _int_or(value: str) -> int | str:
    m = re.search(r"\d{4}", value)
    return int(m.group(0)) if m else _strip_braces(value)


def parse_bibtex(source: str) -> dict[str, ir.CSLItem]:
    """Parse BibTeX ``source`` into ``{citekey: CSLItem}`` (insertion order)."""
    # expand simple @string macros
    macros: dict[str, str] = {}
    for sm in re.finditer(r"@string\s*\{\s*([A-Za-z0-9_]+)\s*=\s*[\"{](.+?)[\"}]\s*\}", source,
                          re.IGNORECASE | re.DOTALL):
        macros[sm.group(1).lower()] = sm.group(2)

    items: dict[str, ir.CSLItem] = {}
    for m in re.finditer(r"@(\w+)\s*\{", source):
        entry_type = m.group(1).lower()
        if entry_type in ("string", "comment", "preamble"):
            continue
        start = m.end()
        depth = 1
        j = start
        while j < len(source) and depth:
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
            j += 1
        inner = source[start : j - 1]
        key, _, body = inner.partition(",")
        key = key.strip()
        if not key:
            continue
        raw_fields = _tokenize_entry_body(body)
        # substitute @string macros for bare values
        for fname, fval in list(raw_fields.items()):
            if fval.strip().lower() in macros:
                raw_fields[fname] = macros[fval.strip().lower()]
        items[key] = _to_csl(entry_type, key, raw_fields)
    return items
