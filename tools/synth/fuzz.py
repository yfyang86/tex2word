"""Random nestings of contexts around constructs, minimised on failure.

The matrix tests every construct in every single context. ``fuzz`` stacks
2..depth contexts (e.g. a citation in a footnote in a table cell in a
tcolorbox), keeping only legal LaTeX nestings. A failing case is minimised by
removing layers while the same findings persist; only cases that still need
two or more layers are new (one layer is a matrix cell). ``--save`` appends
them to ``catalog/found.json``, which becomes part of the permanent catalog.
"""

from __future__ import annotations

import hashlib
import json
import os
import random

from .catalog.matrix import CONSTRUCTS, CONTEXTS, PREAMBLE, TAIL, TARGETS, Construct, Context
from .model import Expect, Probe

FOUND = os.path.join(os.path.dirname(__file__), "catalog", "found.json")

#: contexts that must be outermost (floats, headings, title parts, ...)
_TOP_WORDS = ("section", "caption", "subcaption", "algorithm", "table-float", "table-star",
              "sidewaystable", "threeparttable", "side-by-side", "resizebox-table",
              "figure-text-body", "longtable", "title", "author", "thanks", "date",
              "abstract", "paragraph-head", "landscape", "wrapfigure", "algorithmic")
#: argument slots that can hold paragraphs and environments
_BLOCK_ARGS = {"parbox", "fbox-parbox", "footnote", "marginpar"}
#: contexts whose slot holds paragraphs and environments
_BLOCK_BODIES = {"theorem", "definition", "proof", "itemize", "enumerate-deep",
                 "description-body", "enumitem-label", "minipage", "minipage-row", "center",
                 "flushright", "quote", "quotation", "multicols", "tcolorbox", "mdframed",
                 "framed", "pcol-cell", "tabularx-cell", "list-in-cell", "itemize-in-theorem",
                 "para"}
#: contexts that are themselves block environments (need a block slot)
_IS_BLOCK = _BLOCK_BODIES | {"table-cell", "table-header", "makecell-cell", "multicolumn-cell",
                             "multirow-cell", "adjustbox-table", "table-in-itemize",
                             "theorem-title", "description-label", "tcolorbox-title"}

_BY_NAME = {x.name: x for x in CONTEXTS}
_C_BY_NAME = {c.name: c for c in CONSTRUCTS}


def _is_top(x: Context) -> bool:
    return bool(x.head) or any(w in x.name for w in _TOP_WORDS)


def _holds_block(x: Context) -> bool:
    return x.name in _BLOCK_BODIES or x.name in _BLOCK_ARGS


def valid(c: Construct, layers: list[Context]) -> bool:
    """``layers`` run outermost first; the construct sits in the last one."""
    if not layers or any(x.name == "para" for x in layers[1:]):
        return False
    if any(_is_top(x) for x in layers[1:]):
        return False
    for outer, inner in zip(layers, layers[1:], strict=False):
        if inner.name in _IS_BLOCK and not _holds_block(outer):
            return False
        if outer.name == inner.name:
            return False
    if c.verbatim and any(x.slot != "body" for x in layers):
        return False
    if c.fragile and any(x.slot == "moving" for x in layers):
        return False
    if c.cell_only and not (layers[-1].cell and layers[-1].slot == "body"):
        return False
    if c.no_cell and any(x.cell for x in layers):
        return False
    if c.name.startswith("footnote") and any(
        x.name in ("footnote", "marginpar", "thanks") for x in layers
    ):
        return False
    return True


def compose(c: Construct, layers: list[Context]) -> Probe:
    inner = c.latex
    for x in reversed(layers[1:]):
        inner = x.body.replace("%X", inner)
    top = layers[0]
    head = top.head.replace("%X", inner) if top.head else ""
    body = top.body.replace("%X", inner) if top.body else ""
    source = PREAMBLE + "\\begin{document}\n" + head + "\n" + TARGETS + body + TAIL
    names = [x.name for x in layers]
    key = c.name + "@" + "/".join(names)
    digest = hashlib.sha1(key.encode()).hexdigest()[:8]
    return Probe(
        id=f"found/{c.name}@{'+'.join(names)}" if len(key) < 90 else f"found/{digest}",
        source=source,
        expect=Expect(texts=list(c.texts), absent=list(c.absent), counts=dict(c.counts),
                      styles=dict(c.styles), allow_dims=c.allow_dims,
                      allow_braces=c.allow_braces, allow_backslash=c.allow_backslash),
        tags={"construct": c.name, "context": "+".join(names)},
        fragment=head or body,
        note=f"{c.name} inside " + " inside ".join(reversed(names)),
    )


def _families(sigs: list[str]) -> set[str]:
    return {s.split(":", 1)[0] for s in sigs}


def minimise(c: Construct, layers: list[Context], fams: set[str]) -> list[Context]:
    from .runner import run_probe

    current = list(layers)
    changed = True
    while changed and len(current) > 1:
        changed = False
        for i in range(len(current)):
            trial = current[:i] + current[i + 1:]
            if not valid(c, trial):
                continue
            got = _families(run_probe(compose(c, trial)).signatures)
            if fams & got:
                current, fams, changed = trial, fams & got, True
                break
    return current


def fuzz(args) -> int:
    from .runner import _init_worker, run_all, run_probe

    rng = random.Random(args.seed)
    combos: list[tuple[Construct, list[Context]]] = []
    seen: set[str] = set()
    tries = 0
    while len(combos) < args.count and tries < args.count * 200:
        tries += 1
        c = rng.choice(CONSTRUCTS)
        depth = rng.randint(2, max(2, args.depth))
        layers = [rng.choice(CONTEXTS) for _ in range(depth)]
        if not valid(c, layers):
            continue
        key = c.name + "@" + "/".join(x.name for x in layers)
        if key not in seen:
            seen.add(key)
            combos.append((c, layers))
    probes = [compose(c, layers) for c, layers in combos]
    results = {r.probe_id: r for r in run_all(probes, jobs=args.jobs)}
    _init_worker(False)

    # what single contexts already fail (matrix cells): a minimised case that
    # reduces to one of them is not new
    found: dict[str, tuple[Construct, list[Context], list[str]]] = {}
    for (c, layers), p in zip(combos, probes, strict=True):
        r = results[p.id]
        if r.ok:
            continue
        fams = _families(r.signatures)
        small = minimise(c, layers, fams)
        if len(small) < 2:
            continue
        # if plain text fails the same way, the layers are the cause: keep one
        # case per layer pattern instead of one per construct
        plain = _C_BY_NAME["plain"]
        if c is not plain and valid(plain, small):
            if fams & _families(run_probe(compose(plain, small)).signatures):
                c = plain
        probe = compose(c, small)
        if probe.id not in found:
            found[probe.id] = (c, small, run_probe(probe).signatures)
    print(f"fuzz: {len(probes)} nestings, {sum(1 for r in results.values() if not r.ok)} "
          f"failing, {len(found)} minimal multi-layer cases")
    for pid, (_c, _small, sigs) in sorted(found.items()):
        print(f"  {pid}: {', '.join(sigs[:4])}")
    if args.save and found:
        existing = _load_found_json()
        for _pid, (c, small, _sigs) in found.items():
            existing.append({"construct": c.name, "contexts": [x.name for x in small]})
        uniq = {json.dumps(e, sort_keys=True): e for e in existing}
        with open(FOUND, "w", encoding="utf-8") as fh:
            json.dump(sorted(uniq.values(), key=lambda e: (e["construct"], e["contexts"])),
                      fh, indent=1)
            fh.write("\n")
        print(f"saved {len(found)} cases to {FOUND}")
    return 0


def _load_found_json() -> list[dict]:
    if not os.path.exists(FOUND):
        return []
    with open(FOUND, encoding="utf-8") as fh:
        return json.load(fh)


def load_found() -> list[Probe]:
    """The promoted fuzz cases as probes (see ``catalog/found.py``)."""
    out = []
    for e in _load_found_json():
        c = _C_BY_NAME.get(e["construct"])
        layers = [_BY_NAME[n] for n in e["contexts"] if n in _BY_NAME]
        if c is None or len(layers) != len(e["contexts"]) or not valid(c, layers):
            continue
        out.append(compose(c, layers))
    return out
