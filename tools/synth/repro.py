"""``repro``: one probe as a standalone folder, a diagnosis, and a test stub.

The stub is a self-contained pytest module (no harness import) asserting what
the probe expects, ready to move into ``tests/`` once the bug is fixed.
"""

from __future__ import annotations

import os
import re
import tempfile
import textwrap

from . import SENTINEL
from .model import Probe
from .runner import convert, run_probe, write_probe


def write_repro(probe: Probe, out: str | None) -> int:
    out = out or tempfile.mkdtemp(prefix="t2w-repro-")
    os.makedirs(out, exist_ok=True)
    write_probe(probe, out)
    result = run_probe(probe)
    conv = convert(probe, out)

    print(f"probe   {probe.id}")
    if probe.note:
        print(f"note    {probe.note}")
    if probe.fragment:
        print(f"latex   {probe.fragment}")
    print(f"folder  {out}")
    print()
    if result.ok:
        print("no findings")
    for f in result.findings:
        print(f"FINDING {f.signature}\n        {f.detail}")
    print("\n-- warnings --")
    for w in conv.report.warnings:
        print(f"  {w.construct}: {w.message}")
    print("\n-- IR outline --")
    print(outline(conv.document.blocks))
    print("\n-- visible text --")
    print(textwrap.indent(result.text.strip() or "(empty)", "  "))

    stub = os.path.join(out, f"test_{_slug(probe.id)}.py")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(test_stub(probe))
    print(f"\nregression test stub: {stub}")
    return 0 if result.ok else 1


def _slug(pid: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", pid.lower()).strip("_")


def outline(blocks, depth: int = 0) -> str:
    from tex2word import ir

    lines: list[str] = []
    pad = "  " * depth
    for b in blocks:
        name = type(b).__name__
        label = getattr(b, "label", None)
        extra = f" label={label}" if label else ""
        if isinstance(b, ir.Paragraph | ir.Heading):
            lines.append(f"{pad}{name}{extra}: {_inl(b.inlines)[:140]}")
        elif isinstance(b, ir.Table):
            cap = _inl(b.caption) if b.caption else ""
            lines.append(f"{pad}Table{extra} rows={len(b.rows)} caption={cap[:60]!r}")
            for ri, row in enumerate(b.rows[:6]):
                for ci, cell in enumerate(row.cells):
                    lines.append(f"{pad}  [r{ri}c{ci}]")
                    lines.append(outline(cell.blocks, depth + 2))
        elif isinstance(b, ir.Figure):
            cap = _inl(b.caption) if b.caption else ""
            lines.append(f"{pad}Figure{extra} image={b.image is not None} caption={cap[:60]!r}")
            if b.blocks:
                lines.append(outline(b.blocks, depth + 1))
        else:
            lines.append(f"{pad}{name}{extra}")
            for attr in ("blocks",):
                sub = getattr(b, attr, None)
                if isinstance(sub, list) and sub:
                    lines.append(outline(sub, depth + 1))
            if isinstance(b, ir.ItemList):
                for it in b.items:
                    lines.append(outline(it.blocks, depth + 1))
    return "\n".join(x for x in lines if x)


def _inl(inlines) -> str:
    from tex2word import ir

    out = []
    for n in inlines or []:
        if isinstance(n, ir.Text):
            out.append(n.value)
        elif isinstance(n, ir.RawInline):
            out.append(f"<RAW {n.latex[:30]}>")
        elif isinstance(n, ir.Math):
            out.append(f"${n.latex[:30]}$")
        elif hasattr(n, "inlines"):
            out.append(f"[{type(n).__name__}:{_inl(n.inlines)}]")
        else:
            out.append(f"<{type(n).__name__}>")
    return "".join(out)


def test_stub(probe: Probe) -> str:
    exp = probe.expect
    checks = []
    if SENTINEL in probe.source and SENTINEL not in exp.counts:
        checks.append(f"assert text.count({SENTINEL!r}) == {probe.source.count(SENTINEL)}")
    for tok, n in exp.counts.items():
        checks.append(f"assert text.count({tok!r}) == {n}")
    for s in exp.texts:
        checks.append(f"assert {s!r} in text")
    for s in exp.absent:
        checks.append(f"assert {s!r} not in text")
    checks.append('assert "??" not in text')
    checks.append("assert not re.search(r'\\\\[A-Za-z]+', text), text")
    if not exp.allow_warnings:
        checks.append("assert [w.message for w in r.report.warnings] == []")
    files = {k: v for k, v in probe.files.items() if isinstance(v, str)}
    body = "\n    ".join(checks)
    return f'''"""Regression test for synthetic probe {probe.id} (tools.synth repro).

{probe.note}
"""

import io
import re
import zipfile

from tex2word import convert_source

SOURCE = {probe.source!r}

FILES = {files!r}

REFS_BIB = {_refs()!r}


def _text(docx: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(docx))
    out = []
    for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
        if name in z.namelist():
            xml = z.read(name).decode()
            out += re.findall(r"<[wm]:t(?: [^>]*)?>([^<]*)</[wm]:t>", xml)
    return "".join(out).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def test_{_slug(probe.id)}(tmp_path):
    (tmp_path / "refs.bib").write_text(REFS_BIB, encoding="utf-8")
    for rel, content in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content, encoding="utf-8")
    r = convert_source(SOURCE, base_dir=str(tmp_path))
    text = _text(r.docx)
    {body}
'''


def _refs() -> str:
    from .assets import REFS_BIB

    return REFS_BIB
