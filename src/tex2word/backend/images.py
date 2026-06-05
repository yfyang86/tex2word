"""Image probing and EMU sizing for embedded graphics.

Pure-Python (no Pillow): reads intrinsic pixel dimensions from PNG and JPEG
headers so embedded images get a sensible on-page size. Formats Word can embed
directly are PNG/JPEG/EMF; vector PDF/EPS need an external converter (post-V1),
so they fall back to a placeholder + warning at the call site.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

EMU_PER_INCH = 914400
_PX_PER_INCH = 96
EMU_PER_PX = EMU_PER_INCH // _PX_PER_INCH  # 9525

#: max width on a US-Letter page with 1in margins.
_MAX_WIDTH_EMU = int(6.0 * EMU_PER_INCH)

_EMBEDDABLE = {"png", "jpg", "jpeg", "emf"}


@dataclass
class ImageInfo:
    fmt: str
    width_px: int
    height_px: int

    @property
    def embeddable(self) -> bool:
        return self.fmt in _EMBEDDABLE


def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seg_len
    return None


def probe_bytes(data: bytes, fmt: str) -> ImageInfo:
    """Return :class:`ImageInfo` for in-memory image bytes of a known format."""
    fmt = fmt.lower()
    size: tuple[int, int] | None = None
    if fmt == "png":
        size = _png_size(data)
    elif fmt in ("jpg", "jpeg"):
        size = _jpeg_size(data)
    if size is None:
        # unknown intrinsic size (e.g. emf) -> default 4 x 3 inches worth of px
        size = (4 * _PX_PER_INCH, 3 * _PX_PER_INCH)
    return ImageInfo(fmt=fmt, width_px=size[0], height_px=size[1])


def probe(path: str) -> ImageInfo | None:
    """Return :class:`ImageInfo` for an image file, or ``None`` if unreadable."""
    fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
    except OSError:
        return None
    return probe_bytes(head, fmt)


def emu_size(info: ImageInfo, max_width_emu: int | None = None) -> tuple[int, int]:
    """Compute (cx, cy) in EMU, scaled down to fit ``max_width_emu`` (or text)."""
    limit = max_width_emu if max_width_emu is not None else _MAX_WIDTH_EMU
    cx = info.width_px * EMU_PER_PX
    cy = info.height_px * EMU_PER_PX
    if cx > limit:
        scale = limit / cx
        cx = limit
        cy = int(cy * scale)
    return cx, cy
