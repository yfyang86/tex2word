"""xcolor colour resolution: named colours, ``\\definecolor``, model parsing.

Maps LaTeX colour specifications onto the 6-hex ``RRGGBB`` strings that Word's
``w:color``/``w:shd`` run properties use. Deliberately bounded: the common
``rgb``/``RGB``/``HTML``/``gray``/``cmyk`` models and the xcolor base + dvips
named palette. Unknown names degrade to ``None`` (the caller drops the colour
rather than emitting wrong output).
"""

from __future__ import annotations

import re

# xcolor base colours + the common dvipsnames a paper is likely to use.
_NAMED: dict[str, str] = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "00FF00",
    "blue": "0000FF", "cyan": "00FFFF", "magenta": "FF00FF", "yellow": "FFFF00",
    "gray": "808080", "grey": "808080", "darkgray": "404040", "lightgray": "BFBFBF",
    "lightgrey": "BFBFBF", "brown": "BF8040", "lime": "BFFF00", "olive": "808000",
    "orange": "FF8000", "pink": "FFBFBF", "purple": "BF0040", "teal": "008080",
    "violet": "800080", "darkgreen": "008000", "darkblue": "000080",
    # a few dvipsnames seen in ML papers
    "navyblue": "006EB8", "royalblue": "4169E1", "forestgreen": "228B22",
    "maroon": "B03060", "crimson": "DC143C", "gold": "FFD700",
}


def _clamp(x: float) -> int:
    return max(0, min(255, round(x)))


def _hex(r: float, g: float, b: float) -> str:
    return f"{_clamp(r):02X}{_clamp(g):02X}{_clamp(b):02X}"


def _floats(spec: str) -> list[float]:
    out: list[float] = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            try:
                out.append(float(part))
            except ValueError:
                return []
    return out


def color_from_model(model: str, spec: str) -> str | None:
    """Resolve an explicit ``[model]{spec}`` colour to ``RRGGBB`` (or None)."""
    model = model.strip()
    spec = spec.strip()
    if model == "HTML":
        h = spec.strip().lstrip("#")
        if re.fullmatch(r"[0-9A-Fa-f]{6}", h):
            return h.upper()
        if re.fullmatch(r"[0-9A-Fa-f]{3}", h):
            return "".join(c * 2 for c in h).upper()
        return None
    nums = _floats(spec)
    if model == "rgb" and len(nums) == 3:
        return _hex(nums[0] * 255, nums[1] * 255, nums[2] * 255)
    if model == "RGB" and len(nums) == 3:
        return _hex(*nums)
    if model == "gray" and len(nums) == 1:
        v = nums[0] * 255
        return _hex(v, v, v)
    if model == "cmyk" and len(nums) == 4:
        c, m, y, k = nums
        return _hex(255 * (1 - c) * (1 - k), 255 * (1 - m) * (1 - k), 255 * (1 - y) * (1 - k))
    return None


class ColorTable:
    """Named-colour registry seeded with xcolor defaults, extended by defs."""

    def __init__(self) -> None:
        self._named = dict(_NAMED)

    def define(self, name: str, model: str, spec: str) -> None:
        hexval = color_from_model(model, spec)
        if hexval is not None:
            self._named[name.strip().lower()] = hexval

    def define_alias(self, name: str, target: str) -> None:
        """``\\colorlet{name}{target}`` -- copy an existing colour."""
        resolved = self.resolve(target)
        if resolved is not None:
            self._named[name.strip().lower()] = resolved

    def resolve(self, spec: str, model: str | None = None) -> str | None:
        """Resolve ``{spec}`` (a name, ``!``-mix, or hex) to ``RRGGBB``."""
        if model:
            return color_from_model(model, spec)
        spec = spec.strip()
        if "!" in spec:
            return self._resolve_mix(spec)
        return self._resolve_name(spec)

    def _resolve_name(self, spec: str) -> str | None:
        key = spec.strip().lower()
        if key in self._named:
            return self._named[key]
        if re.fullmatch(r"#?[0-9A-Fa-f]{6}", spec.strip()):
            return spec.strip().lstrip("#").upper()
        return None

    def _rgb(self, name: str) -> tuple[float, float, float] | None:
        hexval = self._resolve_name(name)
        if hexval is None:
            return None
        return (int(hexval[0:2], 16), int(hexval[2:4], 16), int(hexval[4:6], 16))

    def _resolve_mix(self, spec: str) -> str | None:
        """Compute an xcolor ``!``-mix, e.g. ``blue!8`` = 8% blue + 92% white,
        ``red!40!blue`` = 40% red + 60% blue (left-associative fold)."""
        parts = [p.strip() for p in spec.split("!")]
        cur = self._rgb(parts[0])
        if cur is None:
            return None
        white = (255.0, 255.0, 255.0)
        i = 1
        while i < len(parts):
            try:
                frac = float(parts[i]) / 100.0
            except ValueError:
                return None
            other = self._rgb(parts[i + 1]) if i + 1 < len(parts) else white
            if other is None:
                return None
            cur = tuple(  # type: ignore[assignment]
                frac * c + (1.0 - frac) * o for c, o in zip(cur, other, strict=True)
            )
            i += 2
        return _hex(*cur)
