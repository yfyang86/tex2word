"""siunitx units and numbers → Unicode text.

Renders ``\\si``/``\\unit``/``\\SI``/``\\qty``/``\\num``/``\\ang`` to plain
Unicode (e.g. ``\\SI{5}{\\kilo\\gram}`` → ``5 kg``) when the user hasn't
redefined them (the macro expander runs first). Output is text, so it composes
with the rest of the paragraph and round-trips as text.
"""

from __future__ import annotations

import re

from pylatexenc.latexwalker import LatexCharsNode, LatexGroupNode, LatexMacroNode

THIN = " "  # thin space between a value and its unit / between units

# SI prefixes (\kilo, \milli, …) and units (\metre, \joule, …) → symbols.
_PREFIX = {
    "yocto": "y", "zepto": "z", "atto": "a", "femto": "f", "pico": "p",
    "nano": "n", "micro": "µ", "milli": "m", "centi": "c", "deci": "d",
    "deca": "da", "deka": "da", "hecto": "h", "kilo": "k", "mega": "M",
    "giga": "G", "tera": "T", "peta": "P", "exa": "E", "zetta": "Z", "yotta": "Y",
}
_UNIT = {
    "metre": "m", "meter": "m", "gram": "g", "second": "s", "kilogram": "kg",
    "kelvin": "K", "ampere": "A", "mole": "mol", "candela": "cd", "newton": "N",
    "pascal": "Pa", "joule": "J", "watt": "W", "coulomb": "C", "volt": "V",
    "farad": "F", "ohm": "Ω", "siemens": "S", "weber": "Wb", "tesla": "T",
    "henry": "H", "hertz": "Hz", "lumen": "lm", "lux": "lx", "becquerel": "Bq",
    "gray": "Gy", "sievert": "Sv", "katal": "kat", "litre": "L", "liter": "L",
    "electronvolt": "eV", "celsius": "°C", "degreeCelsius": "°C", "percent": "%",
    "degree": "°", "arcminute": "′", "arcsecond": "″", "bar": "bar",
    "angstrom": "Å", "day": "d", "hour": "h", "minute": "min", "tonne": "t",
    "dalton": "Da", "radian": "rad", "steradian": "sr",
}
_POWER = {"squared": "²", "cubed": "³"}      # postfix: \metre\squared
_PREPOWER = {"square": "²", "cubic": "³"}    # prefix: \cubic\metre

_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_NUM_EXP = re.compile(r"^([+-]?[\d.,]+)\s*[eE]\s*([+-]?\d+)$")


def units_to_text(nodes: list) -> str:
    """Render a sequence of unit macros/chars (a ``\\si`` argument) to symbols."""
    out = ""
    attach = True  # next unit attaches without a separator (start, or after a prefix/per)
    prepower = ""  # a \cubic/\square waiting to apply to the next unit
    for n in nodes:
        if isinstance(n, LatexMacroNode):
            name = n.macroname
            if name in _PREPOWER:
                prepower = _PREPOWER[name]
            elif name in _PREFIX:
                if out and not attach:
                    out += THIN
                out += _PREFIX[name]
                attach = True
            elif name in _UNIT:
                if out and not attach:
                    out += THIN
                out += _UNIT[name] + prepower
                prepower = ""
                attach = False
            elif name in _POWER:
                out += _POWER[name]
                attach = False
            elif name == "per":
                out += "/"
                attach = True
        elif isinstance(n, LatexCharsNode):
            out += n.chars
            attach = False
        elif isinstance(n, LatexGroupNode):
            out += units_to_text(n.nodelist)
            attach = False
    return out.strip()


# -- number formatting (siunitx defaults, \sisetup and per-command options) -- #

_DEFAULTS: dict[str, str] = {
    "group-digits": "all",          # all | integer | decimal | none
    "group-separator": THIN,
    "group-minimum-digits": "5",    # a part is grouped once it has this many digits
    "output-decimal-marker": ".",
}
_settings: dict[str, str] = dict(_DEFAULTS)
_NUMBER = re.compile(r"^([+-]?)(\d*)(?:[.,](\d*))?(?:[eE]([+-]?\d+))?$")


def parse_keyvals(text: str) -> dict[str, str]:
    """``key=value, flag`` (one level of braces) -> dict; a bare key is "true"."""
    out: dict[str, str] = {}
    depth, cur, parts = 0, "", []
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    for part in parts:
        key, eq, value = part.partition("=")
        key = key.strip()
        if key:
            value = value.strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1]
            out[key] = value if eq else "true"
    return out


def configure(options: dict[str, str] | None = None) -> None:
    """Set the document's number format (``\\sisetup``); None restores defaults."""
    _settings.clear()
    _settings.update(_DEFAULTS)
    if options:
        _settings.update(options)


def _separator(value: str) -> str:
    v = value.strip(" ")  # not str.strip(): the thin space is the default separator
    return {"\\,": THIN, "\\thinspace": THIN, "~": "\u00a0", "\\ ": " ", "\;": " ",
            "\\:": " ", "\\quad": " ", "": ""}.get(v, v)


def _group(digits: str, size: int, from_left: bool, sep: str) -> str:
    if from_left:
        return sep.join(digits[i:i + 3] for i in range(0, len(digits), 3))
    head = len(digits) % 3 or 3
    return sep.join([digits[:head]] + [digits[i:i + 3] for i in range(head, len(digits), 3)])


def num_to_text(s: str, options: dict[str, str] | None = None) -> str:
    """Render a number as siunitx prints it: digits grouped in threes with a
    thin space once a part has 5 or more digits (``12345`` → ``12 345``),
    ``1.5e3`` → ``1.5×10³``; anything else passes through."""
    o = {**_settings, **(options or {})}
    raw = s.strip()
    compact = raw.replace("\\,", "").replace("{,}", ",").replace(" ", "").replace(THIN, "")
    m = _NUMBER.match(compact)
    if not m or not (m.group(2) or m.group(3)):
        return raw
    sign, whole, frac, exp = m.groups()
    mode = o.get("group-digits", "all").lower()
    mode = {"true": "all", "false": "none"}.get(mode, mode)
    try:
        minimum = int(o.get("group-minimum-digits", "5"))
    except ValueError:
        minimum = 5
    sep = _separator(o.get("group-separator", THIN))
    if mode in ("all", "integer") and len(whole) >= minimum:
        whole = _group(whole, 3, False, sep)
    if frac and mode in ("all", "decimal") and len(frac) >= minimum:
        frac = _group(frac, 3, True, sep)
    out = sign + (whole or "0" if frac is not None else whole)
    if frac is not None:
        marker = o.get("output-decimal-marker", ".").strip("{}") or "."
        out += marker + frac
    if exp is not None:
        out += f"×10{exp.lstrip('+').translate(_SUP)}"
    return out


def ang_to_text(s: str) -> str:
    """Render an angle: ``30`` → ``30°``; ``30;15;0`` → ``30°15′``."""
    parts = [p.strip() for p in s.split(";")]
    if len(parts) == 3:
        out = ""
        if parts[0]:
            out += f"{parts[0]}°"
        if parts[1] and parts[1] != "0":
            out += f"{parts[1]}′"
        if parts[2] and parts[2] != "0":
            out += f"{parts[2]}″"
        return out or "0°"
    return f"{s.strip()}°"
