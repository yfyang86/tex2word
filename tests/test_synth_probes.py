"""Gate on the synthetic probe harness (tools/synth).

Runs the smoke tier (or every probe with ``T2W_SYNTH_FULL=1``) and compares
with ``tools/synth/baseline.json``:

* a finding not in the baseline is a regression (or a new defect): fix it, or
  record it with ``python -m tools.synth update --accept``;
* a baseline finding that no longer occurs means a bug was fixed: prune the
  baseline with ``python -m tools.synth update``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.synth import baseline  # noqa: E402
from tools.synth.catalog import all_probes  # noqa: E402
from tools.synth.runner import run_all  # noqa: E402


def _selected():
    probes = all_probes()
    if os.environ.get("T2W_SYNTH_FULL"):
        return probes
    return [p for p in probes if p.tier == "smoke"]


def test_catalog_is_consistent():
    probes = all_probes()
    assert len({p.id for p in probes}) == len(probes)
    assert any(p.tier == "smoke" for p in probes)
    known = baseline.load()
    ids = {p.id for p in probes}
    orphans = sorted(set(known) - ids)
    assert not orphans, f"baseline lists probes that no longer exist: {orphans[:5]}"


def test_probes_match_baseline():
    probes = _selected()
    results = list(run_all(probes, jobs=min(os.cpu_count() or 1, 4)))
    diff = baseline.compare(results, baseline.load())
    by_id = {r.probe_id: r for r in results}
    new = {
        pid: [f"{f.signature}: {f.detail}" for f in by_id[pid].findings if f.signature in sigs]
        for pid, sigs in diff.new.items()
    }
    assert not new, (
        "NEW probe findings (regression or new defect) -- fix, or record with "
        f"`python -m tools.synth update --accept`: {new}"
    )
    assert not diff.fixed, (
        "probe findings FIXED -- prune the baseline with `python -m tools.synth update`: "
        f"{diff.fixed}"
    )
