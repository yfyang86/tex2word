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


def num_to_text(s: str) -> str:
    """Render a number: ``1.5e3`` → ``1.5×10³``; otherwise pass through."""
    s = s.strip()
    m = _NUM_EXP.match(s)
    if m:
        mant, exp = m.group(1), m.group(2).lstrip("+")
        return f"{mant}×10{exp.translate(_SUP)}"
    return s


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
