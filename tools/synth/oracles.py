"""Oracles: turn a conversion into a list of findings.

Generic oracles run on every probe; ``Expect`` adds probe-specific checks.
Each finding's ``signature`` is a short stable string (the baseline key), e.g.
``dropped``, ``tex-leak:\\makecell``, ``warning:\\rotatebox``.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass

from lxml import etree

from . import SENTINEL
from .assets import BIB_KEYS
from .model import Finding, Probe

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_TEXT_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml",
               "word/comments.xml")

_TEX_LEAK = re.compile(r"\\[A-Za-z@]+")
_DIM_LEAK = re.compile(r"(?<![\w.])-?\d*\.?\d+\s?(?:pt|em|ex|cm|mm|bp|sp)\b")


@dataclass
class Parsed:
    """The parts of a converted document the oracles look at."""

    xml: str  # word/document.xml
    roots: list[etree._Element]  # parsed text parts
    text: str  # visible text, w:t + m:t, paragraphs joined by newlines
    wtext: str  # visible text from w:t only (no math)
    mtexts: list[str]  # every m:t


def parse_docx(docx: bytes) -> Parsed:
    z = zipfile.ZipFile(io.BytesIO(docx))
    names = set(z.namelist())
    roots = [etree.fromstring(z.read(n)) for n in _TEXT_PARTS if n in names]
    paras: list[str] = []
    wparas: list[str] = []
    mtexts: list[str] = []
    wt, mt = f"{{{W}}}t", f"{{{M}}}t"
    # OMML keeps operator/delimiter glyphs (sum, brackets, accents) in attributes
    glyph_tags = tuple(f"{{{M}}}{n}" for n in ("chr", "begChr", "endChr", "sepChr"))
    for root in roots:
        for p in root.iter(f"{{{W}}}p"):
            both, wonly = [], []
            for el in p.iter(wt, mt, *glyph_tags):
                # skip text of a nested paragraph (text boxes): counted there
                if _owner_paragraph(el) is not p:
                    continue
                if el.tag == wt:
                    both.append(el.text or "")
                    wonly.append(el.text or "")
                elif el.tag == mt:
                    both.append(el.text or "")
                    mtexts.append(el.text or "")
                else:
                    both.append(el.get(f"{{{M}}}val") or "")
            # a no-break space (~) reads as a space for the text checks
            paras.append("".join(both).replace("\u00a0", " "))
            wparas.append("".join(wonly).replace("\u00a0", " "))
    xml = z.read("word/document.xml").decode("utf-8")
    return Parsed(xml, roots, "\n".join(paras), "\n".join(wparas), mtexts)


def _owner_paragraph(el: etree._Element) -> etree._Element | None:
    node = el.getparent()
    while node is not None and node.tag != f"{{{W}}}p":
        node = node.getparent()
    return node


def check(probe: Probe, result, parsed: Parsed | None) -> list[Finding]:  # noqa: C901
    """All findings for one converted probe (``result`` is a ConversionResult)."""
    from tex2word import ir as IR
    from tex2word.validate import validate_docx

    out: list[Finding] = []
    exp = probe.expect

    problems = validate_docx(result.docx)
    if problems:
        out.append(Finding("invalid-docx", "; ".join(map(str, problems))[:300]))
    if parsed is None:
        return out

    # -- raw LaTeX left in the IR ------------------------------------------- #
    if not exp.allow_raw:
        for node in IR.iter_nodes(result.document):
            if isinstance(node, IR.RawInline | IR.RawPassthrough):
                m = _TEX_LEAK.search(node.latex)
                key = m.group(0) if m else node.latex.strip()[:12]
                out.append(Finding(f"raw-ir:{key}", node.latex[:120]))

    # -- leaked markup in the visible text ---------------------------------- #
    if not exp.allow_backslash:
        for cmd in sorted(set(_TEX_LEAK.findall(parsed.wtext))):
            out.append(Finding(f"tex-leak:{cmd}", _context(parsed.wtext, cmd)))
    if not exp.allow_braces:
        for brace in "{}":
            if brace in parsed.wtext:
                out.append(Finding("brace-leak", _context(parsed.wtext, brace)))
                break
    if not exp.allow_dims:
        m = _DIM_LEAK.search(parsed.text)
        if m:
            out.append(Finding("dim-leak", _context(parsed.text, m.group(0))))

    # -- content preserved exactly once -------------------------------------- #
    counts = dict(exp.counts)
    if SENTINEL in probe.source and SENTINEL not in counts:
        counts[SENTINEL] = probe.source.count(SENTINEL)
    for token, want in counts.items():
        got = parsed.text.count(token)
        if got != want:
            sig = "dropped" if got < want else "duplicated"
            if token != SENTINEL:
                sig += f":{token}"
            out.append(Finding(sig, f"{token!r}: expected {want}, found {got}"))

    # -- references and citations -------------------------------------------- #
    if "??" in parsed.text:
        out.append(Finding("unresolved-ref", _context(parsed.text, "??")))
    for key in BIB_KEYS:  # every probe ships refs.bib with these keys
        if key in parsed.wtext:
            out.append(Finding(f"raw-cite:{key}", _context(parsed.wtext, key)))

    # -- report --------------------------------------------------------------- #
    allowed = [re.compile(a) for a in exp.allow_warnings]
    for w in result.report.warnings:
        line = f"{w.construct}: {w.message}"
        if not any(a.search(line) for a in allowed):
            out.append(Finding(f"warning:{w.construct}", line[:200]))
    for e in result.report.errors:
        out.append(Finding(f"error:{e.construct}", f"{e.construct}: {e.message}"[:200]))

    # -- math ------------------------------------------------------------------ #
    if result.report.math_raw:
        out.append(Finding("math-raw", f"{result.report.math_raw} equation(s) left as raw TeX"))
    doc_root = parsed.roots[0]
    for nary in doc_root.iter(f"{{{M}}}nary"):
        e = nary.find(f"{{{M}}}e")
        if e is None or len(e) == 0:
            out.append(Finding("math-empty-nary", "n-ary operator without an operand"))
            break
    for t in parsed.mtexts:
        if "\\" in t or _DIM_LEAK.fullmatch(t.strip() or "x"):
            out.append(Finding("math-leak", repr(t)))
            break
    n_math = sum(1 for _ in doc_root.iter(f"{{{M}}}oMath"))
    if n_math < exp.min_math:
        out.append(Finding("math-missing",
                           f"{n_math} OMML equation(s), expected >= {exp.min_math}"))
    if exp.roundtrip:
        out.extend(_roundtrip(doc_root))

    # -- probe-specific expectations ------------------------------------------- #
    for s in exp.texts:
        if s not in parsed.text:
            out.append(Finding(f"expect-text:{s}", f"missing {s!r}"))
    for s in exp.absent:
        if s in parsed.text:
            out.append(Finding(f"expect-absent:{s}", _context(parsed.text, s)))
    for i, rx in enumerate(exp.xml):
        if not re.search(rx, parsed.xml, re.S):
            out.append(Finding(f"expect-xml:{i}", f"no match for {rx!r}"))
    for i, rx in enumerate(exp.no_xml):
        m = re.search(rx, parsed.xml, re.S)
        if m:
            out.append(Finding(f"expect-no-xml:{i}", f"{rx!r} matched {m.group(0)[:80]!r}"))
    for key in exp.labels:
        if key not in result.document.labels:
            out.append(Finding(f"label:{key}", f"label {key!r} not registered"))
    if exp.ir or exp.no_ir:
        ir_json = json.dumps(result.document.to_dict(), ensure_ascii=False)
        for s in exp.ir:
            if s not in ir_json:
                out.append(Finding(f"expect-ir:{s}", f"IR lacks {s!r}"))
        for s in exp.no_ir:
            if s in ir_json:
                out.append(Finding(f"expect-no-ir:{s}", f"IR has {s!r}"))
    for token, tag in exp.styles.items():
        if not _styled(parsed.roots, token, tag):
            out.append(Finding(f"style:{tag}", f"run holding {token!r} lacks <{tag}>"))
    return out


def _context(text: str, needle: str, width: int = 40) -> str:
    i = text.find(needle)
    if i < 0:
        return needle
    snippet = text[max(0, i - width) : i + len(needle) + width]
    return snippet.replace("\n", " / ")


def _styled(roots: list[etree._Element], token: str, tag: str) -> bool:
    prefix, local = tag.split(":")
    ns = W if prefix == "w" else M
    for root in roots:
        for t in root.iter(f"{{{W}}}t"):
            if token not in (t.text or ""):
                continue
            run = t.getparent()
            rpr = run.find(f"{{{W}}}rPr") if run is not None else None
            if rpr is not None and rpr.find(f"{{{ns}}}{local}") is not None:
                return True
    return False


def _roundtrip(root: etree._Element) -> list[Finding]:
    from tex2word.mathml import omml
    from tex2word.mathml.omml_reader import omath_to_latex

    for o in root.iter(f"{{{M}}}oMath"):
        try:
            latex = omath_to_latex(o)
            again = omml.render_inline(latex)
        except Exception as exc:  # noqa: BLE001 - any reader/writer failure is a finding
            return [Finding("math-roundtrip-error", f"{type(exc).__name__}: {exc}"[:200])]
        if _flat_text(o) != _flat_text(again):
            return [Finding("math-roundtrip",
                            f"{_flat_text(o)!r} -> {latex!r} -> {_flat_text(again)!r}")]
    return []


def _flat_text(el: etree._Element) -> str:
    """The math text plus operator/delimiter characters, in order."""
    out: list[str] = []
    for e in el.iter():
        name = etree.QName(e).localname
        if name == "t":
            out.append(e.text or "")
        elif name in ("chr", "begChr", "endChr", "sepChr"):
            out.append(e.get(f"{{{M}}}val") or "")
        elif name in ("f", "rad", "nary", "sSup", "sSub", "sSubSup", "acc", "m", "limLow",
                      "limUpp", "groupChr", "d", "bar", "box", "borderBox", "eqArr"):
            out.append(f"<{name}>")
    return "".join(out).replace(" ", "")
