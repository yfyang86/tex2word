"""The baseline: known failures, keyed by probe id.

``verify`` compares a run against it: a signature not in the baseline is NEW
(a regression, or a defect found for the first time); a baseline signature the
run no longer shows is FIXED (the baseline is stale and must be updated).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .model import Result

PATH = os.path.join(os.path.dirname(__file__), "baseline.json")

#: optional packages that change conversion results (the MathML math route,
#: PDF rasterisation); the baseline is only valid for the set it was made with
_OPTIONAL = ("latex2mathml", "pypdfium2", "PIL")


def environment() -> dict[str, bool]:
    import importlib.util

    return {m: importlib.util.find_spec(m) is not None for m in _OPTIONAL}


def recorded_environment(path: str = PATH) -> dict[str, bool] | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("environment")


def environment_mismatch(path: str = PATH) -> str | None:
    """A description of how this machine differs from the baseline's, or None."""
    rec = recorded_environment(path)
    if rec is None:
        return None
    now = environment()
    diff = [f"{m} {'installed' if now.get(m) else 'missing'} (baseline: "
            f"{'installed' if rec.get(m) else 'missing'})"
            for m in sorted(set(rec) | set(now)) if rec.get(m) != now.get(m)]
    return "; ".join(diff) or None


@dataclass
class Diff:
    new: dict[str, list[str]] = field(default_factory=dict)  # id -> signatures
    fixed: dict[str, list[str]] = field(default_factory=dict)
    known: dict[str, list[str]] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.new and not self.fixed


def load(path: str = PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("known", {})


def save(known: dict[str, dict], path: str = PATH) -> None:
    data = {
        "_about": (
            "Known failures of the synthetic probes (tools/synth). Keyed by probe id; "
            "'signatures' are oracle findings still expected to fail. Add 'issue'/'note' "
            "by hand. Regenerate with: python -m tools.synth update [--accept]. Made with "
            "every optional extra installed (uv sync --all-extras), as in CI."
        ),
        "environment": environment(),
        "known": {k: known[k] for k in sorted(known)},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def compare(results: list[Result], known: dict[str, dict]) -> Diff:
    diff = Diff()
    for r in results:
        got = set(r.signatures)
        base = set(known.get(r.probe_id, {}).get("signatures", []))
        if got - base:
            diff.new[r.probe_id] = sorted(got - base)
        if base - got:
            diff.fixed[r.probe_id] = sorted(base - got)
        if got & base:
            diff.known[r.probe_id] = sorted(got & base)
    return diff


def updated(
    results: list[Result], known: dict[str, dict], *, accept: bool, all_ids: set[str]
) -> dict[str, dict]:
    """The baseline after a run: fixed signatures and vanished probes are
    dropped; NEW signatures are added only with ``accept``."""
    out = {k: dict(v) for k, v in known.items() if k in all_ids}
    for r in results:
        entry = out.get(r.probe_id, {})
        base = set(entry.get("signatures", []))
        got = set(r.signatures)
        keep = (base & got) | (got if accept else set())
        if keep:
            entry["signatures"] = sorted(keep)
            out[r.probe_id] = entry
        else:
            out.pop(r.probe_id, None)
    return out
