"""Packaged reference templates (the 'reference-doc' pattern)."""

from __future__ import annotations

from importlib import resources


def load_styles_xml() -> bytes:
    """Return the curated reference ``styles.xml`` shipped with the package."""
    return resources.files(__package__).joinpath("styles.xml").read_bytes()
