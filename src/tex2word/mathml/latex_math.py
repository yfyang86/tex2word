"""LaTeX math -> math AST.

A small recursive-descent parser over the (macro-expanded) math token stream.
It models the common + AMS math core. Anything it can't model raises
:class:`MathUnsupported`, which the OMML converter catches to drive the
fallback cascade (and the coverage report), mirroring how ``texmath`` renders
unconvertible math as raw TeX.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import symbols as S


class MathUnsupported(Exception):
    """Raised when a construct cannot be represented in the math AST."""

    def __init__(self, construct: str, detail: str = "") -> None:
        super().__init__(f"unsupported math construct: {construct} {detail}".strip())
        self.construct = construct


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #


@dataclass
class Lit:
    """A leaf run of math text with styling hints."""

    text: str
    upright: bool = False
    bold: bool = False
    script: str | None = None  # OMML m:scr: script/double-struck/fraktur/...


@dataclass
class Row:
    items: list[MNode] = field(default_factory=list)


@dataclass
class Group:
    row: Row


@dataclass
class Frac:
    num: Row
    den: Row


@dataclass
class Sup:
    base: MNode
    sup: MNode


@dataclass
class Sub:
    base: MNode
    sub: MNode


@dataclass
class SubSup:
    base: MNode
    sub: MNode
    sup: MNode


@dataclass
class Sqrt:
    radicand: Row


@dataclass
class Root:
    index: Row
    radicand: Row


@dataclass
class Nary:
    op: str
    body: MNode | None = None
    sub: MNode | None = None
    sup: MNode | None = None
    limloc: str = "undOvr"  # or "subSup"


@dataclass
class Accent:
    base: Row
    char: str


@dataclass
class Fenced:
    open: str
    close: str
    body: Row


@dataclass
class LimLow:
    """Function/operator with a lower limit, e.g. lim_{x\\to0}."""

    base: MNode
    lim: MNode


@dataclass
class GroupChr:
    """An over/under brace-or-bracket group (\\overbrace, \\underbrace)."""

    body: Row
    char: str
    pos: str  # "top" or "bot"


@dataclass
class Matrix:
    rows: list[list[Row]]


MNode = (
    Lit | Row | Group | Frac | Sup | Sub | SubSup | Sqrt | Root | Nary | Accent
    | Fenced | LimLow | Matrix | GroupChr
)

# Functions whose subscript is rendered as an underscript limit in display.
LIMIT_FUNCS = frozenset({"lim", "limsup", "liminf", "max", "min", "sup", "inf", "gcd", "det"})

# \big \Big \bigg \Bigg (+ l/r/m variants): manual delimiter sizing -- the size
# is purely visual, so we drop it and let the following delimiter render itself.
_BIG_DELIMS = frozenset(
    f"{size}{suffix}"
    for size in ("big", "Big", "bigg", "Bigg")
    for suffix in ("", "l", "r", "m")
)

# Escaped literals inside math: \{ \} \% \# \& \$ \_ and \| (norm bar).
_CMD_LITERAL = {
    "{": "{", "}": "}", "|": "‖",
    "%": "%", "#": "#", "&": "&", "$": "$", "_": "_",
}

# Old plain-TeX/LaTeX2.09 math font *declarations*: ``{\rm Lik}`` behaves like
# ``\mathrm{Lik}`` -- it styles the rest of the current group. Without these the
# converter raised MathUnsupported on ``\rm`` and dumped the whole block as raw.
# Value is (upright, bold, script).
_MATH_STYLE_DECL: dict[str, tuple[bool, bool, str | None]] = {
    "rm": (True, False, None),
    "bf": (False, True, None),
    "sf": (True, False, None),
    "tt": (True, False, None),
    "sc": (True, False, None),
    "it": (False, False, None),
    "mit": (False, False, None),
    "cal": (False, False, "script"),
}

# mathtools/physics paired-delimiter macros: \abs{x} -> |x| etc. (the starred
# auto-size form is accepted and the star ignored). Only used when the user
# hasn't \newcommand-ed them (the macro expander runs first if they have).
_PAIRED_DELIM = {
    "abs": ("|", "|"), "norm": ("‖", "‖"), "ceil": ("⌈", "⌉"),
    "floor": ("⌊", "⌋"), "round": ("⌊", "⌉"), "set": ("{", "}"),
    "Set": ("{", "}"), "ket": ("|", "⟩"), "bra": ("⟨", "|"),
    "braket": ("⟨", "⟩"), "ip": ("⟨", "⟩"), "inner": ("⟨", "⟩"),
}  # the \abs*/\norm* auto-size form is handled by the star-peek, not extra keys

# Extensible (stretchy) arrows: \xrightarrow[under]{over} etc.
_XARROWS = {
    "xrightarrow": "→", "xleftarrow": "←",
    "xRightarrow": "⇒", "xLeftarrow": "⇐",
    "xleftrightarrow": "↔", "xLeftrightarrow": "⇔",
    "xhookrightarrow": "↪", "xhookleftarrow": "↩",
    "xmapsto": "↦", "xrightharpoonup": "⇀", "xrightleftharpoons": "⇌",
}

_MATRIX_DELIMS = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"),
    "Vmatrix": ("‖", "‖"),
    "cases": ("{", ""),
    "aligned": ("", ""),
    "array": ("", ""),
    "smallmatrix": ("", ""),
    # amsmath alignment/gather environments: when they appear *wrapped* (inside
    # $$/\[ or \left\{…\right.) the parser meets them here; render as a
    # column-aligned matrix with no surrounding delimiters.
    "align": ("", ""),
    "alignat": ("", ""),
    "flalign": ("", ""),
    "gather": ("", ""),
    "gathered": ("", ""),
    "split": ("", ""),
    "multlined": ("", ""),
    "eqnarray": ("", ""),
}


# --------------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------------- #

Token = tuple[str, str | None]


def tokenize(s: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            j = i + 1
            if j < n and not s[j].isalpha():
                # control symbol: \{ \} \, \\ \; \! \| etc.
                if s[j] == "\\":
                    tokens.append(("newline", None))
                    i = j + 1
                else:
                    tokens.append(("cmd", s[j]))
                    i = j + 1
            else:
                k = j
                while k < n and s[k].isalpha():
                    k += 1
                tokens.append(("cmd", s[j:k]))
                i = k
                while i < n and s[i] == " ":
                    i += 1
        elif c in "{}^_&":
            tokens.append((c, None))
            i += 1
        elif c in " \n\t":
            i += 1
        elif c.isdigit():
            k = i
            while k < n and (s[k].isdigit() or s[k] == "."):
                k += 1
            tokens.append(("num", s[i:k]))
            i = k
        else:
            tokens.append(("char", c))
            i += 1
    return tokens


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.toks = tokens
        self.i = 0

    def _peek(self) -> Token:
        return self.toks[self.i] if self.i < len(self.toks) else ("eof", None)

    def _next(self) -> Token:
        if self.i >= len(self.toks):
            return ("eof", None)
        t = self.toks[self.i]
        self.i += 1
        return t

    def _expect(self, ttype: str) -> None:
        if self._peek()[0] != ttype:
            raise MathUnsupported("syntax", f"expected {ttype}")
        self._next()

    # -- rows ------------------------------------------------------------- #

    def parse_row(self, stop: frozenset[str] = frozenset()) -> Row:
        items: list[MNode] = []
        while True:
            ttype, _ = self._peek()
            if ttype in ("}", "eof") or ttype in stop:
                break
            atom = self.parse_atom()
            if atom is None:
                continue
            atom = self._maybe_scripts(atom)
            items.append(atom)
        return Row(items)

    def parse_group(self) -> Row:
        """Parse a braced group or a single atom (used for command arguments)."""
        ttype, _ = self._peek()
        if ttype == "{":
            self._next()
            row = self.parse_row()
            self._expect("}")
            return row
        atom = self.parse_atom()
        return Row([atom] if atom is not None else [])

    def _maybe_scripts(self, base: MNode) -> MNode:
        sub: MNode | None = None
        sup: MNode | None = None
        while True:
            ttype, _ = self._peek()
            if ttype == "^":
                self._next()
                sup = _flatten(self.parse_group())
            elif ttype == "_":
                self._next()
                sub = _flatten(self.parse_group())
            else:
                break

        if isinstance(base, Nary):
            base.sub, base.sup = sub, sup
            return base
        if isinstance(base, Lit) and base.upright and base.text in LIMIT_FUNCS:
            if sub is not None and sup is None:
                return LimLow(base, sub)
        if sub is not None and sup is not None:
            return SubSup(base, sub, sup)
        if sub is not None:
            return Sub(base, sub)
        if sup is not None:
            return Sup(base, sup)
        return base

    # -- atoms ------------------------------------------------------------ #

    def parse_atom(self) -> MNode | None:
        ttype, tval = self._next()
        if ttype == "{":
            row = self.parse_row()
            self._expect("}")
            return Group(row)
        if ttype == "num":
            return Lit(tval or "", upright=True)
        if ttype == "char":
            return self._char_atom(tval or "")
        if ttype == "cmd":
            return self.parse_command(tval or "")
        if ttype in ("^", "_"):
            # script with no preceding base
            self.i -= 1
            return Lit("")
        if ttype == "newline" or ttype == "&":
            raise MathUnsupported("alignment", "stray & or \\\\")
        return None

    def _char_atom(self, c: str) -> MNode:
        if c.isalpha():
            return Lit(c)  # italic by default in Word math
        return Lit(c, upright=True)

    def parse_command(self, name: str) -> MNode:  # noqa: C901 - dispatch table
        if name in S.ACCENTS:
            return Accent(self.parse_group(), S.ACCENTS[name])
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            return Frac(self.parse_group(), self.parse_group())
        if name in ("overbrace", "overbracket"):
            return GroupChr(self.parse_group(), "⏞", "top")
        if name in ("underbrace", "underbracket"):
            return GroupChr(self.parse_group(), "⏟", "bot")
        if name == "binom":
            inner = Matrix([[self.parse_group()], [self.parse_group()]])
            return Fenced("(", ")", Row([inner]))
        if name == "sqrt":
            if self._peek()[0] == "char" and self._peek()[1] == "[":
                index = self._parse_optional()
                return Root(index, self.parse_group())
            return Sqrt(self.parse_group())
        if name in S.NARY:
            limloc = "subSup" if name in ("int", "iint", "iiint", "oint") else "undOvr"
            return Nary(S.NARY[name], limloc=limloc)
        if name in _CMD_LITERAL:
            return Lit(_CMD_LITERAL[name], upright=True)
        if name in _BIG_DELIMS:
            # delimiter sizing is visual-only; the next delimiter renders itself
            return Lit("")
        if name in _PAIRED_DELIM:
            if self._peek() == ("char", "*"):  # \abs*{x} auto-size form
                self._next()
            open_d, close_d = _PAIRED_DELIM[name]
            return Fenced(open_d, close_d, self.parse_group())
        if name in ("dv", "odv", "pdv", "dd"):
            return self._parse_derivative(name)
        if name in _XARROWS:
            return self._parse_xarrow(_XARROWS[name])
        if name in ("overset", "stackrel"):
            top = self.parse_group()
            base = self.parse_group()
            return Matrix([[top], [base]])
        if name == "underset":
            bot = self.parse_group()
            base = self.parse_group()
            return Matrix([[base], [bot]])
        if name in (
            "text", "mathrm", "operatorname", "operatorname*",
            "mathsf", "mathtt", "mbox",
            "textrm", "textnormal", "textsf", "texttt", "textsc",
        ):
            row = self.parse_group()
            return _styled(row, upright=True)
        if name == "textbf":
            return _styled(self.parse_group(), upright=True, bold=True)
        if name in ("textit", "textsl", "emph"):
            return self.parse_group_as_group()
        if name == "mathbf" or name == "boldsymbol" or name == "bm":
            return _styled(self.parse_group(), bold=True)
        if name == "mathbb":
            return _styled(self.parse_group(), script="double-struck", upright=True)
        if name == "mathcal" or name == "mathscr":
            return _styled(self.parse_group(), script="script")
        if name == "mathfrak":
            return _styled(self.parse_group(), script="fraktur")
        if name == "mathit":
            return self.parse_group_as_group()
        if name == "left":
            return self._parse_fenced()
        if name == "right":
            raise MathUnsupported("delimiter", "stray \\right")
        if name == "substack":  # \substack{a \\ b \\ c} -> a single-column stack
            return self._parse_substack()
        if name == "bmod":  # infix modulo: a \bmod n -> "a mod n"
            return Lit(" mod ", upright=True)
        if name == "pmod":  # \pmod{n} -> " (mod n)"
            mod_row = Row([Lit("mod ", upright=True), self.parse_group()])
            return Row([Lit(" ", upright=True), Fenced("(", ")", mod_row)])
        if name in S.FUNCTIONS:
            return Lit(name, upright=True)
        if name in S.MATHBB:  # bare \N style not expected, but safe
            return Lit(S.MATHBB[name], upright=True)
        if name in S.SPACING:
            return Lit(S.SPACING[name], upright=True)
        if name in S.SYMBOLS:
            return Lit(S.SYMBOLS[name], upright=True)
        if name == "begin":
            return self._parse_environment()
        if name == "end":
            raise MathUnsupported("environment", "stray \\end")
        if name in ("displaystyle", "textstyle", "scriptstyle", "limits", "nolimits"):
            return Lit("")  # styling hints we currently ignore
        if name in ("nonumber", "notag"):
            return Lit("")
        if name in ("hline", "toprule", "midrule", "bottomrule", "hdashline"):
            return Lit("")  # array/table rules: no OMML equivalent, drop them
        if name in ("cline", "cmidrule", "noalign"):
            if self._peek()[0] == "{":
                self.parse_group()  # consume the {a-b} / {…} argument
            return Lit("")
        if name in _MATH_STYLE_DECL:
            # declaration form {\rm ...}: style the rest of the current group.
            upright, bold, script = _MATH_STYLE_DECL[name]
            return _styled(self.parse_row(), upright=upright, bold=bold, script=script)
        raise MathUnsupported(f"\\{name}")

    def parse_group_as_group(self) -> Group:
        return Group(self.parse_group())

    def _parse_derivative(self, name: str) -> MNode:
        """physics ``\\dv``/``\\pdv``/``\\odv``/``\\dd`` derivatives."""
        d = "∂" if name == "pdv" else "d"
        if name == "dd":  # differential: \dd{x} -> "d x", \dd -> "d"
            lead: list[MNode] = [Lit(d, upright=True)]
            if self._peek()[0] == "{":
                lead.extend(self.parse_group().items)
            return Group(Row(lead))
        first = self.parse_group()
        second = self.parse_group() if self._peek()[0] == "{" else None
        if second is not None:  # \dv{f}{x} -> d f / d x
            num = Row([Lit(d, upright=True), *first.items])
            den = Row([Lit(d, upright=True), *second.items])
        else:  # \dv{x} -> d / d x
            num = Row([Lit(d, upright=True)])
            den = Row([Lit(d, upright=True), *first.items])
        return Frac(num, den)

    def _parse_xarrow(self, arrow: str) -> MNode:
        """Parse ``\\xrightarrow[under]{over}`` into a labelled arrow."""
        under: Row | None = None
        if self._peek() == ("char", "["):
            under = self._parse_optional()
        over = self.parse_group()
        base: MNode = Lit(arrow, upright=True)
        if under is not None and under.items:
            return SubSup(base, _flatten(under), _flatten(over))
        return Sup(base, _flatten(over))

    def _parse_optional(self) -> Row:
        """Parse a ``[...]`` optional argument (used by \\sqrt)."""
        assert self._next() == ("char", "[")
        items: list[MNode] = []
        while True:
            ttype, tval = self._peek()
            if ttype == "char" and tval == "]":
                self._next()
                break
            if ttype == "eof":
                break
            atom = self.parse_atom()
            if atom is not None:
                items.append(self._maybe_scripts(atom))
        return Row(items)

    def _read_delim(self) -> str:
        ttype, tval = self._next()
        if ttype == "char":
            return S.DELIMITERS.get(tval or "", tval or "")
        if ttype == "cmd":
            return S.DELIMITERS.get(tval or "", S.SYMBOLS.get(tval or "", tval or ""))
        raise MathUnsupported("delimiter")

    def _parse_fenced(self) -> Fenced:
        open_delim = self._read_delim()
        items: list[MNode] = []
        while True:
            ttype, tval = self._peek()
            if ttype == "eof":
                raise MathUnsupported("delimiter", "unclosed \\left")
            if ttype == "cmd" and tval == "right":
                self._next()
                close_delim = self._read_delim()
                return Fenced(open_delim, close_delim, Row(items))
            atom = self.parse_atom()
            if atom is not None:
                items.append(self._maybe_scripts(atom))

    def _parse_substack(self) -> MNode:
        """\\substack{a \\\\ b \\\\ c} -> a single-column matrix (stacked limits)."""
        if self._peek()[0] == "{":
            self._next()
        rows: list[list[Row]] = [[]]
        current: list[MNode] = []
        while True:
            ttype, _ = self._peek()
            if ttype in ("}", "eof"):
                break
            if ttype == "newline":
                self._next()
                rows[-1].append(Row(current.copy()))
                current.clear()
                rows.append([])
                continue
            atom = self.parse_atom()
            if atom is not None:
                current.append(self._maybe_scripts(atom))
        rows[-1].append(Row(current.copy()))
        if self._peek()[0] == "}":
            self._next()
        if rows and all(len(c.items) == 0 for c in rows[-1]):
            rows.pop()
        return Matrix(rows)

    def _parse_environment(self) -> MNode:
        name_row = self.parse_group()
        env = _row_text(name_row)
        env = env.rstrip("*")
        if env not in _MATRIX_DELIMS:
            raise MathUnsupported(f"environment {env}")
        if env in ("array", "alignat"):
            # consume the column spec / column-count argument and ignore it
            if self._peek()[0] == "{":
                self.parse_group()
        rows: list[list[Row]] = [[]]
        current: list[MNode] = []

        def flush_cell() -> None:
            rows[-1].append(Row(current.copy()))
            current.clear()

        while True:
            ttype, tval = self._peek()
            if ttype == "eof":
                raise MathUnsupported("environment", f"unclosed {env}")
            if ttype == "cmd" and tval == "end":
                self._next()
                self.parse_group()  # consume {env}
                flush_cell()
                break
            if ttype == "&":
                self._next()
                flush_cell()
                continue
            if ttype == "newline":
                self._next()
                flush_cell()
                rows.append([])
                continue
            atom = self.parse_atom()
            if atom is not None:
                current.append(self._maybe_scripts(atom))

        # drop a trailing empty row (from a final \\)
        if rows and all(len(c.items) == 0 for c in rows[-1]):
            rows.pop()
        matrix = Matrix(rows)
        open_d, close_d = _MATRIX_DELIMS[env]
        if open_d or close_d:
            return Fenced(open_d, close_d, Row([matrix]))
        return matrix


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _styled(
    row: Row, *, upright: bool = False, bold: bool = False, script: str | None = None
) -> MNode:
    """Apply styling to every Lit leaf in a parsed group."""
    for item in row.items:
        _apply_style(item, upright=upright, bold=bold, script=script)
    return Group(row)


def _apply_style(node: MNode, *, upright: bool, bold: bool, script: str | None) -> None:
    if isinstance(node, Lit):
        if upright:
            node.upright = True
        if bold:
            node.bold = True
        if script:
            node.script = script
    elif isinstance(node, Group):
        for item in node.row.items:
            _apply_style(item, upright=upright, bold=bold, script=script)
    elif isinstance(node, Row):
        for item in node.items:
            _apply_style(item, upright=upright, bold=bold, script=script)


def _flatten(row: Row) -> MNode:
    """A single-item row collapses to its item; otherwise stays a Group."""
    if len(row.items) == 1:
        return row.items[0]
    return Group(row)


def _row_text(row: Row) -> str:
    out: list[str] = []
    for item in row.items:
        if isinstance(item, Lit):
            out.append(item.text)
        elif isinstance(item, Group):
            out.append(_row_text(item.row))
    return "".join(out)


def parse(latex: str) -> Row:
    """Parse a LaTeX math string into a math AST :class:`Row`."""
    parser = _Parser(tokenize(latex))
    row = parser.parse_row()
    if parser._peek()[0] != "eof":
        raise MathUnsupported("syntax", "trailing tokens")
    return row
