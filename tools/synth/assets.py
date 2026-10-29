"""Files shared by probes: a bibliography and a tiny PNG."""

from __future__ import annotations

import struct
import zlib

#: citation keys whose raw form must never reach the text
BIB_KEYS = ("tk1991", "laibson1997", "knuth1984")

REFS_BIB = r"""@article{tk1991,
  author = {Amos Tversky and Daniel Kahneman},
  title = {Loss Aversion in Riskless Choice},
  journal = {Quarterly Journal of Economics},
  volume = {106},
  pages = {1039--1061},
  year = {1991}
}
@article{laibson1997,
  author = {David Laibson},
  title = {Golden Eggs and Hyperbolic Discounting},
  journal = {Quarterly Journal of Economics},
  volume = {112},
  year = {1997}
}
@book{knuth1984,
  author = {Donald E. Knuth},
  title = {The {\TeX}book},
  publisher = {Addison-Wesley},
  year = {1984}
}
"""


def png(width: int = 16, height: int = 8, rgb: tuple[int, int, int] = (40, 90, 200)) -> bytes:
    """A solid-colour PNG, built without Pillow."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


IMG_PNG = png()

#: the files every probe gets unless it brings its own
DEFAULT_FILES: dict[str, str | bytes] = {"refs.bib": REFS_BIB, "img.png": IMG_PNG}
