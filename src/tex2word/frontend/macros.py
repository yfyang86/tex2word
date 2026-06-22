"""Expansion of user-defined ``\\newcommand``/``\\def``/``\\NewDocumentCommand``.

This is a deliberately bounded, pure-Python expander -- *not* a TeX engine. It
handles the common forms: fixed arity with ``#1..#9`` parameters and one
optional argument (``\\newcommand``/``\\def``), plus the xparse argspec grammar
(``\\NewDocumentCommand`` with ``s``/``m``/``o``/``O{}``/``r``/``d`` arguments
and the ``\\IfValueTF``/``\\IfNoValueTF``/``\\IfBooleanTF`` conditionals).
Arbitrary macro/catcode trickery remains out of scope -- the LaTeXML front-end
(``--frontend latexml``) is the route for that.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_NEWCOMMAND_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand"
    r"|DeclareTextFontCommand)\s*\*?\s*"
    r"\{?\\(?P<name>[A-Za-z]+)\}?"
    r"(?:\[(?P<nargs>\d+)\])?"
    r"(?:\[(?P<default>[^\]]*)\])?"
)
_DEF_RE = re.compile(r"\\def\s*\\(?P<name>[A-Za-z]+)\s*(?P<params>(?:#\d)*)\s*\{")
# xparse: \NewDocumentCommand{\name}{argspec}{body}
_XPARSE_RE = re.compile(
    r"\\(?:New|Renew|Provide|Declare)DocumentCommand\s*\{?\s*\\(?P<name>[A-Za-z]+)\}?\s*"
)

# sentinels for xparse argument conditionals (chosen not to appear in source)
_NOVALUE = "\x00NoValue\x00"
_BOOL_T = "\x00BoolTrue\x00"
_BOOL_F = "\x00BoolFalse\x00"


@dataclass
class Macro:
    name: str
    nargs: int
    default: str | None
    body: str
    #: xparse argument spec (list of (kind, default)); None for newcommand/def.
    argspec: list[tuple[str, str | None]] | None = field(default=None)


def _read_balanced(text: str, start: int) -> tuple[str, int]:
    """Read a ``{...}`` group starting at ``text[start] == '{'``; return body+end."""
    assert text[start] == "{"
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], len(text)


def collect_macros(source: str) -> tuple[dict[str, Macro], str]:
    """Find macro definitions, returning the table and source with defs removed."""
    macros: dict[str, Macro] = {}
    out: list[str] = []
    i = 0
    while i < len(source):
        x = _XPARSE_RE.match(source, i)
        if x and source[x.end():].lstrip().startswith("{"):
            spec_start = source.index("{", x.end())
            argspec_str, pos = _read_balanced(source, spec_start)
            if pos < len(source) and source[pos:].lstrip().startswith("{"):
                body_start = source.index("{", pos)
                body, end = _read_balanced(source, body_start)
                macros[x.group("name")] = Macro(
                    x.group("name"), 0, None, body, argspec=parse_argspec(argspec_str)
                )
                i = end
                continue
        m = _NEWCOMMAND_RE.match(source, i)
        if m and source[m.end():].lstrip().startswith("{"):
            brace_start = source.index("{", m.end())
            body, end = _read_balanced(source, brace_start)
            nargs = int(m.group("nargs") or 0)
            macros[m.group("name")] = Macro(
                m.group("name"), nargs, m.group("default"), body
            )
            i = end
            continue
        if m and m.group("nargs") is None:
            # Unbraced single-token body: ``\newcommand\BE\textbf`` (a common
            # preamble idiom -- \CAL\mathcal, \BB\mathbb, …). The definition is
            # the next single control sequence or character.
            body, end = _read_arg(source, m.end())
            if body:
                macros[m.group("name")] = Macro(m.group("name"), 0, None, body)
                i = end
                continue
        d = _DEF_RE.match(source, i)
        if d:
            brace_start = d.end() - 1
            body, end = _read_balanced(source, brace_start)
            nargs = len(re.findall(r"#\d", d.group("params")))
            macros[d.group("name")] = Macro(d.group("name"), nargs, None, body)
            i = end
            continue
        out.append(source[i])
        i += 1
    return macros, "".join(out)


def parse_argspec(spec: str) -> list[tuple[str, str | None]]:
    """Parse an xparse argument specification into ``[(kind, default)]``."""
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(spec):
        c = spec[i]
        if c in " +!":  # spaces, long (+), required-token (!): no extra arg
            i += 1
        elif c == ">":  # >{processor} -- ignore the processor group
            if i + 1 < len(spec) and spec[i + 1] == "{":
                _, i = _read_balanced(spec, i + 1)
            else:
                i += 1
        elif c in "smo":
            out.append((c, None))
            i += 1
        elif c == "O":  # O{default}
            if i + 1 < len(spec) and spec[i + 1] == "{":
                default, i = _read_balanced(spec, i + 1)
                out.append(("O", default))
            else:
                out.append(("o", None))
                i += 1
        elif c in "rR":  # required delimited r<d1><d2> -> treat as mandatory
            out.append(("m", None))
            i += 3
        elif c in "dD":  # optional delimited d<d1><d2> -> treat as optional
            out.append(("o", None))
            i += 3
        else:
            i += 1
    return out


def _read_xparse_args(
    argspec: list[tuple[str, str | None]], text: str, i: int
) -> tuple[list[str], int]:
    values: list[str] = []
    for kind, default in argspec:
        while i < len(text) and text[i] in " \n\t":
            i += 1
        if kind == "s":
            if i < len(text) and text[i] == "*":
                values.append(_BOOL_T)
                i += 1
            else:
                values.append(_BOOL_F)
        elif kind == "o":
            opt, i = _read_optional(text, i)
            values.append(opt if opt is not None else _NOVALUE)
        elif kind == "O":
            opt, i = _read_optional(text, i)
            values.append(opt if opt is not None else (default or ""))
        else:  # 'm' (mandatory)
            arg, i = _read_arg(text, i)
            values.append(arg)
    return values, i


# (macro name, number of branch groups, predicate over the condition value -> branch index or None)
_COND = {
    "IfValueTF": (2, lambda v: 0 if v != _NOVALUE else 1),
    "IfValueT": (1, lambda v: 0 if v != _NOVALUE else -1),
    "IfValueF": (1, lambda v: 0 if v == _NOVALUE else -1),
    "IfNoValueTF": (2, lambda v: 0 if v == _NOVALUE else 1),
    "IfNoValueT": (1, lambda v: 0 if v == _NOVALUE else -1),
    "IfNoValueF": (1, lambda v: 0 if v != _NOVALUE else -1),
    "IfBooleanTF": (2, lambda v: 0 if v == _BOOL_T else 1),
    "IfBooleanT": (1, lambda v: 0 if v == _BOOL_T else -1),
    "IfBooleanF": (1, lambda v: 0 if v != _BOOL_T else -1),
}
_COND_RE = re.compile(r"\\(" + "|".join(_COND) + r")(?![A-Za-z])")


def _resolve_conditionals(text: str, _depth: int = 0) -> str:
    """Resolve xparse ``\\IfValueTF`` / ``\\IfBooleanTF`` family in ``text``."""
    if _depth > 40:
        return text
    m = _COND_RE.search(text)
    if not m:
        return text
    name = m.group(1)
    nbranches, predicate = _COND[name]
    i = m.end()
    cond, i = _read_arg(text, i)
    branches: list[str] = []
    for _ in range(nbranches):
        while i < len(text) and text[i] in " \n\t":
            i += 1
        if i < len(text) and text[i] == "{":
            br, i = _read_balanced(text, i)
        else:
            br, i = _read_arg(text, i)
        branches.append(br)
    choice = predicate(cond)
    chosen = branches[choice] if 0 <= choice < len(branches) else ""
    return _resolve_conditionals(text[: m.start()] + chosen + text[i:], _depth + 1)


def _read_arg(text: str, i: int) -> tuple[str, int]:
    while i < len(text) and text[i] in " \n\t":
        i += 1
    if i < len(text) and text[i] == "{":
        return _read_balanced(text, i)
    if i < len(text) and text[i] == "\\":
        j = i + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        return text[i:j], j
    if i < len(text):
        return text[i], i + 1
    return "", i


def _read_optional(text: str, i: int) -> tuple[str | None, int]:
    if i < len(text) and text[i] == "[":
        depth = 0
        j = i
        while j < len(text):
            if text[j] == "[":
                depth += 1
            elif text[j] == "]":
                depth -= 1
                if depth == 0:
                    return text[i + 1 : j], j + 1
            j += 1
    return None, i


def expand(
    source: str,
    macros: dict[str, Macro],
    _depth: int = 0,
    _pattern: re.Pattern[str] | None = None,
) -> str:
    """Expand known macros in ``source`` (bounded recursion)."""
    if _depth > 32 or not macros:
        return source
    if _pattern is None:
        # longest names first so e.g. \EE wins over \E at the same position
        keys = sorted(macros, key=len, reverse=True)
        _pattern = re.compile(r"\\(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z])")
    pattern = _pattern
    out: list[str] = []
    i = 0
    changed = False
    n = len(source)
    while i < n:
        m = pattern.search(source, i)
        if not m:
            out.append(source[i:])
            break
        out.append(source[i : m.start()])  # copy the gap up to the macro in one go
        macro = macros[m.group(1)]
        j = m.end()
        if macro.argspec is not None:
            args, j = _read_xparse_args(macro.argspec, source, j)
            body = macro.body
            for idx, arg in enumerate(args, start=1):
                body = body.replace(f"#{idx}", arg)
            body = _resolve_conditionals(body)
        else:
            args = []
            if macro.nargs:
                if macro.default is not None:
                    opt, j = _read_optional(source, j)
                    args.append(opt if opt is not None else macro.default)
                    remaining = macro.nargs - 1
                else:
                    remaining = macro.nargs
                for _ in range(remaining):
                    arg, j = _read_arg(source, j)
                    args.append(arg)
            body = macro.body
            for idx, arg in enumerate(args, start=1):
                body = body.replace(f"#{idx}", arg)
        out.append(body)
        i = j
        changed = True
    result = "".join(out)
    if changed:
        return expand(result, macros, _depth + 1, pattern)
    return result


# ----------------------------------------------------------------------------
# Local package (.sty) macro loading
# ----------------------------------------------------------------------------
# Real papers split their custom commands into a local style file pulled in via
# ``\usepackage{style}``; without expanding those, half the math falls through
# to the lossy fallback path. We read any ``<name>.sty`` sitting next to the
# source (system packages won't be found and are skipped) and harvest its
# definitions -- including the ``\@for ... \do{...}`` generator idiom common in
# ML papers (``\cA..\cZ`` calligraphic, ``\bA..\bZ`` blackboard, etc.).

_USEPKG_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{(?P<names>[^}]+)\}"
)
_FOR_RE = re.compile(
    r"\\@for\s*\\(?P<var>[A-Za-z@]+)\s*:=\s*\\(?P<list>[A-Za-z@]+)\s*\\do\s*"
)
_CSNAME_RE = re.compile(r"\\csname\s*(?P<body>.*?)\\endcsname", re.DOTALL)

# A package macro is only safe to expand statically if its body is free of
# TeX-engine machinery (conditionals, \csname/\expandafter gymnastics, counter
# and group manipulation, nested \def). Those belong to package internals
# (icml2026.sty's author block, fancyhdr, recursive \ifx loops) that our pure
# expander cannot evaluate and that blow up under naive repeated substitution.
_UNSAFE_BODY_RE = re.compile(
    r"\\(?:if[A-Za-z@]*|else|fi|or|csname|endcsname|expandafter|noexpand"
    r"|@for|@ifnextchar|@ifstar|loop|repeat|global|let|edef|xdef|gdef|def"
    r"|newcommand|renewcommand|providecommand|DeclareRobustCommand"
    r"|begingroup|endgroup|protect|stepcounter|addtocounter|setcounter"
    r"|newcounter|the|value|lowercase|uppercase|futurelet|aftergroup)"
    r"(?![A-Za-z])"
)


# Structural / front-matter commands the parser handles natively -- a package
# is free to redefine them (icml2026.sty rebuilds \section via \@startsection),
# but harvesting that definition would clobber the real heading with raw markup.
_PROTECTED_NAMES = frozenset({
    "section", "subsection", "subsubsection", "paragraph", "subparagraph",
    "chapter", "part", "title", "author", "date", "thanks", "maketitle",
    "caption", "captionof", "label", "ref", "cref", "Cref", "autoref",
    "eqref", "pageref", "cite", "citep", "citet", "item", "footnote",
    "begin", "end", "abstract", "appendix", "bibliography", "tableofcontents",
    "includegraphics", "newpage", "clearpage", "input", "include", "today",
})

# A control sequence containing ``@`` is package-internal machinery.
_AT_COMMAND_RE = re.compile(r"\\[A-Za-z]*@|@[A-Za-z]")


def _is_safe_macro(mac: Macro) -> bool:
    """True if a harvested package macro is safe for the pure expander."""
    if "@" in mac.name or mac.name in _PROTECTED_NAMES:
        return False
    if _UNSAFE_BODY_RE.search(mac.body) or _AT_COMMAND_RE.search(mac.body):
        return False
    # reject self-reference (direct recursion the expander can't terminate)
    if re.search(r"\\" + re.escape(mac.name) + r"(?![A-Za-z])", mac.body):
        return False
    return True


def _safe_only(macros: dict[str, Macro]) -> dict[str, Macro]:
    return {name: mac for name, mac in macros.items() if _is_safe_macro(mac)}


def _resolve_csname(text: str) -> str:
    """Turn ``\\csname foo\\endcsname`` into ``\\foo`` (dropping inner spaces)."""
    return _CSNAME_RE.sub(lambda m: "\\" + m.group("body").strip().replace(" ", ""), text)


def _unroll_for_loops(source: str, macros: dict[str, Macro]) -> str:
    """Unroll ``\\@for\\i:=\\List\\do{ body }`` and return *only* the bodies.

    We deliberately discard everything outside the loops: the surrounding
    stylesheet can contain TeX we don't emulate (recursive ``\\ifx`` macros),
    and we only want the synthesised generator calls so they can be expanded.
    """
    parts: list[str] = []
    for m in _FOR_RE.finditer(source):
        j = m.end()
        while j < len(source) and source[j] in " \n\t":
            j += 1
        list_macro = macros.get(m.group("list"))
        if j < len(source) and source[j] == "{" and list_macro is not None:
            body, _ = _read_balanced(source, j)
            elems = [e.strip() for e in list_macro.body.split(",") if e.strip()]
            var_re = re.compile(r"\\" + re.escape(m.group("var")) + r"(?![A-Za-z])")
            for elem in elems:
                # brace the element so \expandafter\genCal\i -> \genCal{A}
                # (the \expandafter, dropped next, is what separates the tokens)
                parts.append(var_re.sub("{" + elem + "}", body))
    return "".join(parts)


def _collect_package_macros(sty_source: str) -> dict[str, Macro]:
    """Harvest macro definitions from a style-file source (best effort)."""
    from .preprocess import _rewrite_mathoperators, strip_comments

    # \DeclareMathOperator in a package becomes a \newcommand wrapping
    # \operatorname, so the operator names defined there are harvested too.
    sty_source = _rewrite_mathoperators(strip_comments(sty_source))
    macros, _ = collect_macros(sty_source)
    # Unroll generator loops, run the (terminating) generator macros, and
    # resolve \csname so the synthesised \newcommand definitions are collectable.
    try:
        generated = _unroll_for_loops(strip_comments(sty_source), macros)
        if generated.strip():
            generated = generated.replace("\\expandafter", "")
            generated = expand(generated, macros)
            generated = generated.replace("\\expandafter", "")
            generated = _resolve_csname(generated)
            gen_macros, _ = collect_macros(generated)
            # generated fills in; explicitly-written definitions still win
            return _safe_only({**gen_macros, **macros})
    except Exception:  # never let a stylesheet quirk abort the build
        pass
    return _safe_only(macros)


def _load_local_package_macros(
    source: str, base_dir: str, _seen: set[str] | None = None, _depth: int = 0
) -> dict[str, Macro]:
    """Collect macros from local ``.sty`` files referenced by ``\\usepackage``."""
    if _depth > 8:
        return {}
    seen = _seen if _seen is not None else set()
    macros: dict[str, Macro] = {}
    for m in _USEPKG_RE.finditer(source):
        for name in m.group("names").split(","):
            name = name.strip()
            if not name:
                continue
            path = os.path.join(base_dir, name + ".sty")
            real = os.path.abspath(path)
            if real in seen or not os.path.isfile(path):
                continue
            seen.add(real)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    sty = fh.read()
            except OSError:
                continue
            # a .sty may pull in further local style files
            macros.update(_load_local_package_macros(sty, base_dir, seen, _depth + 1))
            macros.update(_collect_package_macros(sty))
    return macros


def expand_macros(source: str, base_dir: str = ".") -> str:
    """Collect user macros (incl. local ``.sty`` packages) and expand them."""
    pkg_macros = _load_local_package_macros(source, base_dir)
    macros, stripped = collect_macros(source)
    # document-body definitions take precedence over package definitions
    merged = {**pkg_macros, **macros}
    return expand(stripped, merged)
