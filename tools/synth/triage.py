"""Triage: cluster failures and write a Markdown report.

The construct x context matrix is read three ways: a construct failing in most
contexts is a construct bug, a context failing for most constructs is a context
bug, and the remaining isolated cells are interactions (the #44 kind).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .model import Probe, Result

#: a row/column counts as broken when at least this share of its cells fail
#: the same way
BROKEN = 0.6


def _sig_family(sig: str) -> str:
    """Group signatures that differ only in detail (``raw-cite:tk1991``)."""
    head = sig.split(":", 1)[0]
    if head in ("raw-cite", "expect-xml", "expect-no-xml"):
        return head
    return sig


def report(probes: dict[str, Probe], results: list[Result], *, title: str) -> str:
    failing = [r for r in results if not r.ok]
    by_area: Counter[str] = Counter()
    fail_area: Counter[str] = Counter()
    for r in results:
        area = r.probe_id.split("/", 1)[0]
        by_area[area] += 1
        if not r.ok:
            fail_area[area] += 1

    lines = [f"# {title}", ""]
    lines.append(f"{len(results)} probes, {len(failing)} with findings.")
    lines.append("")
    lines.append("| area | probes | failing |")
    lines.append("|---|---:|---:|")
    for area in sorted(by_area):
        lines.append(f"| {area} | {by_area[area]} | {fail_area[area]} |")
    lines.append("")

    lines += _matrix_section(probes, results)
    lines += _cluster_section(probes, failing, exclude_matrix=True)
    return "\n".join(lines) + "\n"


def _matrix_section(probes: dict[str, Probe], results: list[Result]) -> list[str]:
    cells: dict[tuple[str, str], Result] = {}
    for r in results:
        p = probes.get(r.probe_id)
        if p and p.area == "matrix":
            cells[(p.tags["construct"], p.tags["context"])] = r
    if not cells:
        return []
    constructs = sorted({c for c, _ in cells})
    contexts = sorted({x for _, x in cells})

    # family -> construct -> failing contexts (and the totals per row/column)
    row_total = Counter(c for c, _ in cells)
    col_total = Counter(x for _, x in cells)
    fam_cells: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for key, r in cells.items():
        for sig in r.signatures:
            fam_cells[_sig_family(sig)].add(key)

    explained: set[tuple[str, str, str]] = set()
    rows, cols = [], []
    for fam, keys in fam_cells.items():
        per_row = Counter(c for c, _ in keys)
        per_col = Counter(x for _, x in keys)
        for c in constructs:
            if per_row[c] and per_row[c] >= BROKEN * row_total[c] and per_row[c] > 1:
                rows.append((per_row[c], c, fam, row_total[c]))
                explained.update((c, x, fam) for cc, x in keys if cc == c)
        for x in contexts:
            if per_col[x] and per_col[x] >= BROKEN * col_total[x] and per_col[x] > 1:
                cols.append((per_col[x], x, fam, col_total[x]))
                explained.update((c, x, fam) for c, xx in keys if xx == x)

    out = ["## Construct x context matrix", ""]
    out.append(f"{len(constructs)} constructs x {len(contexts)} contexts "
               f"({len(cells)} legal cells).")
    out.append("")
    for title, items, what in (
        ("Broken constructs (fail in most contexts)", rows, "construct"),
        ("Broken contexts (fail for most constructs)", cols, "context"),
    ):
        if not items:
            continue
        merged: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
        for n, name, fam, tot in items:
            merged[name].append((n, fam, tot))
        out += [f"### {title}", "", f"| {what} | cells | findings | example |",
                "|---|---:|---|---|"]
        for name, fams in sorted(merged.items(), key=lambda kv: -max(f[0] for f in kv[1])):
            n = max(f[0] for f in fams)
            tot = fams[0][2]
            names = ", ".join(f"`{f[1]}`" for f in sorted(fams, key=lambda f: f[1]))
            top = max(fams)[1]
            ex = _example(probes, cells, top, **({what: name}))
            out.append(f"| `{name}` | {n}/{tot} | {names} | {ex} |")
        out.append("")
    inter = sorted(
        (fam, c, x) for fam, keys in fam_cells.items() for c, x in keys
        if (c, x, fam) not in explained
    )
    if inter:
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        for fam, c, x in inter:
            grouped[(c, fam)].append(x)
        out += ["### Interactions (construct fails only in some contexts)", "",
                "| construct | finding | contexts | detail |", "|---|---|---|---|"]
        for (c, fam), xs in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            r = cells[(c, xs[0])]
            detail = next((f.detail for f in r.findings if _sig_family(f.signature) == fam), "")
            more = f" +{len(xs) - 8}" if len(xs) > 8 else ""
            where = ", ".join(f"`{x}`" for x in xs[:8]) + more
            out.append(f"| `{c}` | `{fam}` | {len(xs)}: {where} | {_md(detail)} |")
        out.append("")
    return out


def _example(probes, cells, fam, construct=None, context=None) -> str:
    for (c, x), r in sorted(cells.items()):
        if construct and c != construct or context and x != context:
            continue
        for f in r.findings:
            if _sig_family(f.signature) == fam:
                return f"`{c}@{x}`: {_md(f.detail)}"
    return ""


def _cluster_section(probes, failing: list[Result], *, exclude_matrix: bool) -> list[str]:
    """Non-matrix probes: one line per failing probe (each probe is one issue)."""
    areas: dict[str, list[Result]] = defaultdict(list)
    for r in failing:
        area = r.probe_id.split("/", 1)[0]
        if exclude_matrix and area == "matrix":
            continue
        areas[area].append(r)
    out: list[str] = []
    titles = {"math": "Math", "doc": "Documents", "class": "Classes and templates",
              "found": "Nested cases found by fuzzing"}
    for area in ("math", "doc", "class", "found", *sorted(set(areas) - set(titles))):
        rs = areas.get(area)
        if not rs:
            continue
        out += [f"## {titles.get(area, area)} ({len(rs)} failing)", "",
                "| probe | findings | detail |", "|---|---|---|"]
        for r in sorted(rs, key=lambda r: r.probe_id):
            sigs = _summarise(r.signatures)
            first = _primary(r)
            out.append(f"| `{r.probe_id}` | {sigs} | {_md(first)} |")
        out.append("")
    return out


def _summarise(sigs: list[str], limit: int = 4) -> str:
    # raw-ir / warning / tex-leak usually repeat the same command three times
    keys: list[str] = []
    for s in sigs:
        head, _, tail = s.partition(":")
        k = f"{head}:{tail}" if head in ("expect-text", "expect-absent", "label") else head
        if k not in keys:
            keys.append(k)
    shown = ", ".join(f"`{k}`" for k in keys[:limit])
    return shown + (f" +{len(keys) - limit}" if len(keys) > limit else "")


def _primary(r: Result) -> str:
    order = ("crash", "timeout", "dropped", "expect", "label", "unresolved", "raw-cite",
             "warning", "math", "tex-leak", "raw-ir")
    for head in order:
        for f in r.findings:
            if f.signature.startswith(head):
                return f.detail
    return r.findings[0].detail if r.findings else ""


def _md(s: str) -> str:
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) < 160 else s[:157] + "..."
