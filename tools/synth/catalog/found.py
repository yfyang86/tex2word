"""Nested cases found by ``fuzz --save`` (stored in ``found.json``)."""

from __future__ import annotations

from ..model import Probe


def probes() -> list[Probe]:
    from ..fuzz import load_found

    return load_found()
