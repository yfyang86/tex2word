"""Resolve LaTeX conditionals whose outcome is known without running TeX.

Handled (the branch that TeX would take is kept, the other dropped):

* primitive form: ``\\iftrue``/``\\iffalse``, ``\\newif``-declared switches
  (``\\newif\\ifdraft \\drafttrue ... \\ifdraft A\\else B\\fi``),
  ``\\ifdefined\\cs`` and ``\\ifcsname name\\endcsname``;
* ifthen: ``\\ifthenelse{\\boolean{x}}{A}{B}`` (also ``\\equal``, ``\\not``,
  ``\\isundefined``) with ``\\newboolean``/``\\setboolean``;
* etoolbox: ``\\iftoggle``/``\\nottoggle``, ``\\ifbool``/``\\notbool``,
  ``\\ifdef``/``\\ifundef``;
* ``\\IfFileExists``/``\\InputIfFileExists``, ``\\@ifpackageloaded``,
  ``\\@ifclassloaded``, ``\\IfPackageLoadedTF``, ``\\@ifundefined``.

Switch assignments are applied in document order, and the declarations
themselves are removed. Anything undecidable (``\\ifnum``, ``\\ifx``, engine
tests such as ``\\ifxetex``) is left untouched. Verbatim text is never touched.
"""

from __future__ import annotations

import os
import re

#: primitive conditionals that open an \if...\fi block (for nesting), besides
#: \newif switches; \iff (math) and \ifthenelse (a macro) are not among them
_PRIMITIVE_IFS = frozenset({
    "if", "ifcat", "ifnum", "ifdim", "ifodd", "ifvmode", "ifhmode", "ifmmode", "ifinner",
    "ifvoid", "ifhbox", "ifvbox", "ifx", "ifeof", "iftrue", "iffalse", "ifcase",
    "ifdefined", "ifcsname", "iffontchar", "ifincsname", "ifpdfprimitive",
    "ifpdf", "ifxetex", "ifluatex", "ifPDFTeX", "ifXeTeX", "ifLuaTeX", "ifptex", "ifuptex",
})

#: commands every LaTeX document has (for \ifdefined / \ifdef / \@ifundefined)
_KERNEL = frozenset({
    "section", "subsection", "subsubsection", "paragraph", "subparagraph", "textbf",
    "textit", "emph", "texttt", "label", "ref", "cite", "caption", "footnote", "item",
    "begin", "end", "newcommand", "renewcommand", "def", "let", "relax", "par", "today",
    "LaTeX", "TeX", "maketitle", "title", "author", "date", "includegraphics",
    "url", "href", "textcolor", "color", "frac", "sqrt", "mathbb", "mathbf", "mathrm",
})

_VERB_ENVS = ("verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment",
              "filecontents", "spverbatim", "BVerbatim", "LVerbatim")
_MASK_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in _VERB_ENVS) + r")\}.*?\\end\{\1\}"
    r"|\\verb\*?([^\sA-Za-z*]).*?\2",
    re.S,
)
_CS = r"[A-Za-z@]+"
_NEWIF_RE = re.compile(r"\\newif\s*\\if(" + _CS + ")")
_DEF_RE = re.compile(
    r"\\(?:re)?(?:newcommand|providecommand|DeclareRobustCommand|DeclareMathOperator)\*?"
    r"\s*\{?\s*\\(" + _CS + ")"
    r"|\\(?:def|gdef|edef|xdef|let|newlength|newsavebox|newif)\s*\\(" + _CS + ")"
    r"|\\(?:NewDocumentCommand|RenewDocumentCommand|ProvideDocumentCommand)\s*\{?\s*\\("
    + _CS + ")"
)
_TOKEN_RE = re.compile(r"\\(" + _CS + ")")


def resolve_conditionals(source: str, base_dir: str = ".") -> str:
    if "\\if" not in source and "\\If" not in source and "@if" not in source \
            and "toggle" not in source and "bool" not in source:
        return source
    masked, saved = _mask(source)
    r = _Resolver(masked, base_dir)
    out = r.run()
    return _unmask(out, saved)


def _mask(source: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def keep(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return f"\x00{len(saved) - 1}\x00"

    return _MASK_RE.sub(keep, source), saved


def _unmask(source: str, saved: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], source)


class _Resolver:
    def __init__(self, src: str, base_dir: str) -> None:
        self.src = src
        self.base_dir = base_dir
        self.switches: dict[str, bool] = {n: False for n in _NEWIF_RE.findall(src)}
        self.booleans: dict[str, bool] = {}  # ifthen \newboolean / etoolbox \newbool
        self.toggles: dict[str, bool] = {}
        self.defined: set[str] = set()
        self.packages = _loaded(src, "usepackage|RequirePackage")
        self.classes = _loaded(src, "documentclass|LoadClass")
        if self.classes & {"book", "report", "memoir", "scrbook", "scrreprt", "amsbook"}:
            self.defined.add("chapter")

    # -- scanning ----------------------------------------------------------- #

    def run(self) -> str:
        return self._scan(self.src)

    def _scan(self, s: str) -> str:  # noqa: C901 - one dispatch over control words
        out: list[str] = []
        i, n = 0, len(s)
        while i < n:
            m = _TOKEN_RE.search(s, i)
            if m is None:
                out.append(s[i:])
                break
            out.append(s[i:m.start()])
            name = m.group(1)
            j = m.end()
            # remember definitions in document order (for \ifdefined & co.)
            d = _DEF_RE.match(s, m.start())
            if d:
                self.defined.add(next(g for g in d.groups() if g))
            res = self._handle(s, m.start(), j, name)
            if res is None:
                out.append(s[m.start():j])
                i = j
            else:
                text, i = res
                # never glue the kept text onto a preceding control word
                tail = "".join(out[-3:])
                if text[:1].isalpha() and re.search(r"\\[A-Za-z@]+$", tail):
                    text = " " + text
                out.append(text)
        return "".join(out)

    def _handle(self, s: str, start: int, j: int, name: str) -> tuple[str, int] | None:  # noqa: C901
        # -- declarations and assignments -------------------------------------- #
        if name == "newif":
            m = re.compile(r"\s*\\if(" + _CS + ")").match(s, j)
            if m:
                self.switches.setdefault(m.group(1), False)
                return "", m.end()
            return None
        for sw in self.switches:
            if name == sw + "true" or name == sw + "false":
                self.switches[sw] = name.endswith("true")
                return "", _skip_space(s, j)
        if name in ("newboolean", "provideboolean", "newbool", "providebool", "newtoggle",
                    "providetoggle"):
            args = _groups(s, j, 1)
            if args:
                (key,), end = args
                table = self.toggles if "toggle" in name else self.booleans
                if not name.startswith("provide") or key.strip() not in table:
                    table[key.strip()] = False
                return "", end
            return None
        if name in ("setboolean", "setbool", "settoggle"):
            args = _groups(s, j, 2)
            if args:
                (key, val), end = args
                table = self.toggles if name == "settoggle" else self.booleans
                table[key.strip()] = val.strip().lower() == "true"
                return "", end
            return None
        if name in ("booltrue", "boolfalse", "toggletrue", "togglefalse"):
            args = _groups(s, j, 1)
            if args:
                (key,), end = args
                table = self.toggles if name.startswith("toggle") else self.booleans
                table[key.strip()] = name.endswith("true")
                return "", end
            return None
        # -- brace-form conditionals ------------------------------------------- #
        cond = self._brace_condition(s, j, name)
        if cond is not None:
            value, nargs_before, end = cond
            branches = _groups(s, end, 2)
            if branches is None:
                return None
            (yes, no), stop = branches
            return self._scan(yes if value else no), stop
        # -- primitive \if...\else...\fi --------------------------------------- #
        if name.startswith("if") and (name in _PRIMITIVE_IFS or name[2:] in self.switches):
            return self._primitive(s, j, name)
        return None

    def _brace_condition(self, s: str, j: int, name: str) -> tuple[bool, int, int] | None:
        """(value, -, index after the condition argument(s)) for brace-form tests."""
        if name in ("ifthenelse",):
            args = _groups(s, j, 1)
            if args is None:
                return None
            (test,), end = args
            value = self._ifthen_test(test)
            return None if value is None else (value, 1, end)
        if name in ("iftoggle", "nottoggle", "ifbool", "notbool"):
            args = _groups(s, j, 1)
            if args is None:
                return None
            (key,), end = args
            table = self.toggles if "toggle" in name else self.booleans
            if key.strip() not in table:
                return None
            value = table[key.strip()]
            return (not value if name.startswith("not") else value), 1, end
        if name in ("ifdef", "ifundef", "ifdefmacro", "ifcsdef", "ifcsundef"):
            args = _groups(s, j, 1)
            if args is None:
                return None
            (cs,), end = args
            value = self._is_defined(cs.strip().lstrip("\\"))
            return (not value if "undef" in name else value), 1, end
        if name in ("IfFileExists", "InputIfFileExists"):
            args = _groups(s, j, 1)
            if args is None:
                return None
            (fname,), end = args
            return self._file_exists(fname.strip()), 1, end
        if name in ("@ifpackageloaded", "IfPackageLoadedTF", "@ifclassloaded",
                    "IfClassLoadedTF"):
            args = _groups(s, j, 1)
            if args is None:
                return None
            (pkg,), end = args
            pool = self.classes if "class" in name.lower() else self.packages
            return pkg.strip() in pool, 1, end
        if name == "@ifundefined":
            args = _groups(s, j, 1)
            if args is None:
                return None
            (cs,), end = args
            return not self._is_defined(cs.strip().lstrip("\\")), 1, end
        return None

    def _primitive(self, s: str, j: int, name: str) -> tuple[str, int] | None:
        value: bool | None
        cond_end = j
        if name == "iftrue":
            value = True
        elif name == "iffalse":
            value = False
        elif name[2:] in self.switches:
            value = self.switches[name[2:]]
        elif name == "ifdefined":
            m = re.compile(r"\s*\\(" + _CS + ")").match(s, j)
            if not m:
                return None
            value, cond_end = self._is_defined(m.group(1)), m.end()
        elif name == "ifcsname":
            m = re.compile(r"\s*(" + _CS + r")\s*\\endcsname").match(s, j)
            if not m:
                return None
            value, cond_end = self._is_defined(m.group(1)), m.end()
        else:
            value = None
        block = _match_fi(s, cond_end, set(self.switches))
        if block is None:
            return None
        else_at, fi_start, fi_end = block
        if value is None:
            # undecidable: keep the whole block, but resolve what is inside it
            return s[j - len(name) - 1:cond_end] + self._scan(s[cond_end:fi_start]) \
                + s[fi_start:fi_end], fi_end
        if value:
            chosen = s[cond_end:else_at[0]] if else_at else s[cond_end:fi_start]
        else:
            chosen = s[else_at[1]:fi_start] if else_at else ""
        return self._scan(chosen), fi_end

    # -- tests ----------------------------------------------------------------- #

    def _ifthen_test(self, test: str) -> bool | None:
        t = test.strip()
        neg = False
        while t.startswith("\\not"):
            neg = not neg
            t = t[4:].strip()
        m = re.fullmatch(r"\\boolean\s*\{([^{}]*)\}", t)
        if m:
            if m.group(1).strip() not in self.booleans:
                return None
            v = self.booleans[m.group(1).strip()]
            return not v if neg else v
        m = re.fullmatch(r"\\equal\s*\{([^{}]*)\}\s*\{([^{}]*)\}", t)
        if m:
            v = m.group(1).strip() == m.group(2).strip()
            return not v if neg else v
        m = re.fullmatch(r"\\isundefined\s*\{?\s*\\(" + _CS + r")\s*\}?", t)
        if m:
            v = not self._is_defined(m.group(1))
            return not v if neg else v
        return None

    def _is_defined(self, cs: str) -> bool:
        return cs in self.defined or cs in _KERNEL or cs in self.switches \
            or any(cs == "if" + sw for sw in self.switches)

    def _file_exists(self, name: str) -> bool:
        for cand in (name, name + ".tex"):
            if os.path.isfile(os.path.join(self.base_dir, cand)):
                return True
        return False


def _loaded(src: str, cmds: str) -> set[str]:
    out: set[str] = set()
    for m in re.finditer(r"\\(?:" + cmds + r")\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", src):
        out.update(p.strip() for p in m.group(1).split(",") if p.strip())
    return out


def _skip_space(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _groups(s: str, i: int, count: int) -> tuple[tuple[str, ...], int] | None:
    """Read ``count`` balanced ``{...}`` groups starting at ``i`` (whitespace and
    newlines between them allowed)."""
    out: list[str] = []
    for _ in range(count):
        while i < len(s) and s[i] in " \t\n":
            i += 1
        if i >= len(s) or s[i] != "{":
            return None
        depth = 0
        for k in range(i, len(s)):
            c = s[k]
            if c == "\\":
                continue
            if c == "{" and (k == 0 or s[k - 1] != "\\"):
                depth += 1
            elif c == "}" and (k == 0 or s[k - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    out.append(s[i + 1:k])
                    i = k + 1
                    break
        else:
            return None
    return tuple(out), i


_IF_TOKEN_RE = re.compile(r"\\(" + _CS + ")")


def _match_fi(
    s: str, start: int, switches: set[str]
) -> tuple[tuple[int, int] | None, int, int] | None:
    """Find this conditional's ``\\else`` (start, end) and ``\\fi`` (start, end)."""
    depth = 1
    else_at: tuple[int, int] | None = None
    for m in _IF_TOKEN_RE.finditer(s, start):
        name = m.group(1)
        if name == "fi":
            depth -= 1
            if depth == 0:
                return else_at, m.start(), m.end()
        elif name == "else":
            if depth == 1 and else_at is None:
                else_at = (m.start(), m.end())
        elif name.startswith("if") and (name in _PRIMITIVE_IFS or name[2:] in switches):
            depth += 1
    return None
