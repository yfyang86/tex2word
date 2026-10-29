"""Command line: ``python -m tools.synth <command>`` (run from the repo root).

    list      show the probes (ids, tier, what they exercise)
    generate  write every probe as <out>/<id>/main.tex (+ files), e.g. to feed
              another converter such as the Rust port
    verify    run probes, compare with the baseline; exit 1 on NEW findings or
              on FIXED ones still listed in the baseline
    triage    run probes and write a Markdown report that clusters the findings
    repro     write one probe as a standalone folder + a regression-test stub,
              and print what the converter made of it
    update    rewrite the baseline from a run: drop fixed entries; --accept also
              records NEW findings as known
    fuzz      random nestings of contexts around constructs; --save promotes
              failing (minimised) cases into the permanent catalog
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from . import baseline
from .model import Probe, Result


def _select(args) -> list[Probe]:
    from .catalog import all_probes

    probes = all_probes()
    if getattr(args, "tier", None) == "smoke":
        probes = [p for p in probes if p.tier == "smoke"]
    if getattr(args, "filter", None):
        rx = re.compile(args.filter)
        probes = [p for p in probes if rx.search(p.id)]
    return probes


def _run(probes: list[Probe], args) -> list[Result]:
    from .runner import run_all

    start = time.perf_counter()
    results = []
    n = len(probes)
    for i, r in enumerate(run_all(probes, jobs=args.jobs, allow_tikz=args.tikz), 1):
        results.append(r)
        if sys.stderr.isatty() and (i % 50 == 0 or i == n):
            print(f"\r  {i}/{n} probes", end="", file=sys.stderr, flush=True)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    if getattr(args, "render", False):
        from .render import render_check

        render_check({p.id: p for p in probes}, results)
    results.sort(key=lambda r: r.probe_id)
    print(f"ran {n} probes in {time.perf_counter() - start:.1f}s", file=sys.stderr)
    return results


def cmd_list(args) -> int:
    for p in _select(args):
        print(f"{p.id:60} {p.tier:5} {p.note}")
    return 0


def cmd_generate(args) -> int:
    from .runner import write_probe

    probes = _select(args)
    for p in probes:
        d = os.path.join(args.out, p.id.replace("/", "__").replace("@", "__at__"))
        os.makedirs(d, exist_ok=True)
        write_probe(p, d)
        with open(os.path.join(d, "probe.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": p.id, "note": p.note, "tags": p.tags,
                       "expect": p.expect.__dict__}, fh, indent=1, ensure_ascii=False)
    print(f"wrote {len(probes)} probes under {args.out}")
    return 0


_FIXED_SHOWN = 20


def _print_diff(diff: baseline.Diff, results: list[Result]) -> None:
    by_id = {r.probe_id: r for r in results}
    for pid, sigs in sorted(diff.new.items()):
        print(f"NEW    {pid}")
        for f in by_id[pid].findings:
            if f.signature in sigs:
                print(f"         {f.signature}: {f.detail}")
    fixed = sorted(diff.fixed.items())
    for pid, sigs in fixed[:_FIXED_SHOWN]:
        print(f"FIXED  {pid}: {', '.join(sigs)}")
    if len(fixed) > _FIXED_SHOWN:
        print(f"FIXED  ... and {len(fixed) - _FIXED_SHOWN} more probes")


def cmd_verify(args) -> int:
    probes = _select(args)
    results = _run(probes, args)
    known = baseline.load()
    diff = baseline.compare(results, known)
    _print_diff(diff, results)
    failing = sum(1 for r in results if not r.ok)
    print(f"{len(results)} probes: {failing} failing "
          f"({sum(len(v) for v in diff.known.values())} known signatures), "
          f"{len(diff.new)} with NEW findings, {len(diff.fixed)} FIXED")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([{"id": r.probe_id, "findings": [f.__dict__ for f in r.findings],
                        "seconds": round(r.seconds, 4)} for r in results], fh, indent=1)
    if diff.fixed and not args.allow_stale:
        print("baseline is stale: run `python -m tools.synth update` and commit "
              "tools/synth/baseline.json")
    return 0 if (not diff.new and (args.allow_stale or not diff.fixed)) else 1


def cmd_triage(args) -> int:
    from .triage import report

    probes = _select(args)
    results = _run(probes, args)
    text = report({p.id: p for p in probes}, results, title=args.title)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_update(args) -> int:
    from .catalog import all_probes

    probes = _select(args)
    results = _run(probes, args)
    known = baseline.load()
    diff = baseline.compare(results, known)
    new = baseline.updated(results, known, accept=args.accept,
                           all_ids={p.id for p in all_probes()})
    baseline.save(new)
    print(f"baseline: {len(known)} -> {len(new)} probes "
          f"({len(diff.fixed)} fixed dropped, "
          f"{len(diff.new) if args.accept else 0} new accepted)")
    if diff.new and not args.accept:
        print(f"{len(diff.new)} probes have NEW findings (not recorded; fix them or "
              "re-run with --accept)")
    return 0


def cmd_repro(args) -> int:
    from .catalog import all_probes
    from .repro import write_repro

    probes = {p.id: p for p in all_probes()}
    try:
        from .fuzz import load_found

        probes.update({p.id: p for p in load_found()})
    except ImportError:
        pass
    if args.id not in probes:
        close = [i for i in probes if args.id in i][:10]
        print(f"unknown probe {args.id!r}; did you mean: {close}")
        return 2
    return write_repro(probes[args.id], args.out)


def cmd_fuzz(args) -> int:
    from .fuzz import fuzz

    return fuzz(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.synth", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, run=True):
        p.add_argument("--filter", help="regex on probe ids")
        p.add_argument("--tier", choices=["smoke", "full"], default="full")
        if run:
            p.add_argument("--jobs", type=int, default=None)
            p.add_argument("--tikz", action="store_true",
                           help="compile TikZ with the local TeX engine (slow)")
            p.add_argument("--render", action="store_true",
                           help="also check the sentinel in a LibreOffice PDF render")

    p = sub.add_parser("list")
    common(p, run=False)
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("generate")
    common(p, run=False)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_generate)
    p = sub.add_parser("verify")
    common(p)
    p.add_argument("--json")
    p.add_argument("--allow-stale", action="store_true")
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("triage")
    common(p)
    p.add_argument("--out")
    p.add_argument("--title", default="Synthetic probe findings")
    p.set_defaults(fn=cmd_triage)
    p = sub.add_parser("update")
    common(p)
    p.add_argument("--accept", action="store_true")
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("repro")
    p.add_argument("id")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_repro)
    p = sub.add_parser("fuzz")
    p.add_argument("--count", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--save", action="store_true",
                   help="add minimised failing cases to catalog/found.json")
    p.set_defaults(fn=cmd_fuzz, tikz=False, render=False)

    args = ap.parse_args(argv)
    return args.fn(args)
