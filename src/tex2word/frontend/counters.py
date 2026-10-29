"""Evaluate user-declared LaTeX counters in document order.

``\\newcounter{c}`` declares a counter; ``\\setcounter``, ``\\addtocounter``,
``\\stepcounter`` and ``\\refstepcounter`` change it; ``\\arabic{c}``,
``\\roman``, ``\\Roman``, ``\\alph``, ``\\Alph``, ``\\fnsymbol``, ``\\value{c}``
and ``\\thec`` print it. This pass runs after macro expansion (so a user macro
that steps and prints a counter has been inlined at each use), replaces the
printing commands with their value at that point, and removes the changing
commands. A ``\\newcounter{c}[p]`` resets when the user counter ``p`` steps.

Only counters the document declares are touched: LaTeX's own (section,
figure, enumi, page, ...) are numbered by Word and left as they are.
"""

from __future__ import annotations

import re

from .conditionals import _mask, _unmask

_DECL_RE = re.compile(r"\\newcounter\s*\{([A-Za-z@]+)\}(?:\s*\[([A-Za-z@]+)\])?")
_TOKEN_RE = re.compile(
    r"\\(newcounter|setcounter|addtocounter|stepcounter|refstepcounter|arabic|roman|Roman|"
    r"alph|Alph|fnsymbol|value)\s*\{\s*([A-Za-z@]+)\s*\}"
    r"|\\the([A-Za-z@]+)(?![A-Za-z@])"
)
_FNSYMBOLS = ["", "*", "†", "‡", "§", "¶", "‖", "**", "††", "‡‡"]


def resolve_counters(source: str) -> str:
    if "\\newcounter" not in source:
        return source
    masked, saved = _mask(source)
    parents: dict[str, str | None] = {}
    for m in _DECL_RE.finditer(masked):
        parents[m.group(1)] = m.group(2)
    values = {name: 0 for name in parents}
    out: list[str] = []
    i = 0
    while True:
        found = _TOKEN_RE.search(masked, i)
        if found is None:
            out.append(masked[i:])
            break
        m = found
        cmd, name, the = m.group(1), m.group(2), m.group(3)
        if the is not None:
            if the not in values:
                out.append(masked[i:m.end()])
                i = m.end()
                continue
            out.append(masked[i:m.start()])
            out.append(_glue(out, str(values[the])))
            i = m.end()
            continue
        if name not in values:
            out.append(masked[i:m.end()])
            i = m.end()
            continue
        out.append(masked[i:m.start()])
        j = m.end()
        if cmd == "newcounter":
            opt = re.compile(r"\s*\[[A-Za-z@]+\]").match(masked, j)
            j = opt.end() if opt else j
        elif cmd in ("setcounter", "addtocounter"):
            arg = _group(masked, j)
            if arg is None:
                out.append(masked[m.start():j])
                i = j
                continue
            text, j = arg
            n = _number(text, values)
            if n is not None:
                values[name] = n if cmd == "setcounter" else values[name] + n
        elif cmd in ("stepcounter", "refstepcounter"):
            values[name] += 1
            for child, parent in parents.items():
                if parent == name:
                    values[child] = 0
        else:
            out.append(_glue(out, _format(values[name], cmd)))
        i = j
    return _unmask("".join(out), saved)


def _group(s: str, i: int) -> tuple[str, int] | None:
    while i < len(s) and s[i] in " \t\n":
        i += 1
    if i >= len(s) or s[i] != "{":
        return None
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:k], k + 1
    return None


def _number(text: str, values: dict[str, int]) -> int | None:
    t = text.strip()
    m = re.fullmatch(r"\\value\s*\{\s*([A-Za-z@]+)\s*\}", t)
    if m:
        return values.get(m.group(1))
    try:
        return int(t)
    except ValueError:
        return None


def _format(n: int, cmd: str) -> str:
    if cmd in ("roman", "Roman"):
        s = _roman(n)
        return s.lower() if cmd == "roman" else s
    if cmd in ("alph", "Alph"):
        s = _letters(n)
        return s.lower() if cmd == "alph" else s
    if cmd == "fnsymbol":
        return _FNSYMBOLS[n] if 0 <= n < len(_FNSYMBOLS) else str(n)
    return str(n)


def _roman(n: int) -> str:
    if n <= 0:
        return ""
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                 (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s
            n -= v
    return out


def _letters(n: int) -> str:
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def _glue(out: list[str], text: str) -> str:
    """A value right after a control word gets a separating space."""
    if text[:1].isalnum() and re.search(r"\\[A-Za-z@]+$", "".join(out[-2:])):
        return " " + text
    return text
