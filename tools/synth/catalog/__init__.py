"""All probe catalogs."""

from __future__ import annotations

from ..model import Probe


def all_probes() -> list[Probe]:
    from . import classes, documents, found, math, matrix

    probes: list[Probe] = []
    for mod in (matrix, math, documents, classes, found):
        probes.extend(mod.probes())
    ids = [p.id for p in probes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate probe ids: {sorted(dupes)[:5]}")
    return probes
