"""LaTeX -> IR conversion built on pylatexenc's walker.

Macro expansion (``\\newcommand``/``\\def``) is done *before* walking, so custom
commands become standard content. Unknown constructs degrade gracefully into
``RawInline``/``RawPassthrough`` nodes plus a coverage-report entry -- never an
abort.
"""

from __future__ import annotations

import os
import re

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexSpecialsNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import EnvironmentSpec, MacroSpec

from .. import ir
from ..report import ConversionReport
from . import siunitx
from .colors import ColorTable
from .macros import expand_macros, local_package_sources
from .preprocess import preprocess, replace_inline_tikz

# --------------------------------------------------------------------------- #
# Static maps
# --------------------------------------------------------------------------- #

_SECTION_LEVELS = {
    "part": 1, "chapter": 1, "section": 1, "subsection": 2,
    "subsubsection": 3, "paragraph": 4, "subparagraph": 4,
}
# book/report classes: \chapter is the top numbered level, sections nest under it
_SECTION_LEVELS_BOOK = {
    "part": 1, "chapter": 1, "section": 2, "subsection": 3,
    "subsubsection": 4, "paragraph": 5, "subparagraph": 5,
}
# the sectioning commands LaTeX auto-numbers (\part is shown unnumbered here)
_NUMBERED_SECTIONS = {"chapter", "section", "subsection", "subsubsection"}

# spacing/box macros that print nothing (their argument is consumed)
_DROP_MACROS = {"phantom", "hphantom", "vphantom", "rule"}
# box wrappers that are visually transparent: emit the (last) content group
_TRANSPARENT_BOX = {"mbox", "fbox", "framebox", "makebox", "raisebox"}
# IEEEtran author-block wrappers: render their content (name / affiliation text).
_AUTHOR_BLOCK = {"IEEEauthorblockN", "IEEEauthorblockA"}

_EMPHASIS = {
    "textbf": "bold", "textit": "italic", "emph": "italic",
    "textsl": "italic", "underline": "underline",
    "texttt": "typewriter", "textsc": "smallcaps",
    "textsuperscript": "superscript", "textsubscript": "subscript",
    # ulem strike/underline, soul highlight
    "sout": "strike", "st": "strike", "xout": "strike",
    "uline": "underline", "uuline": "underline",
    "hl": "highlight",
}

# Declaration-form font switches (no argument): ``{\bfseries ...}`` / ``{\bf ...}``
# apply to the rest of the enclosing group, like ``\color``. The short forms are
# the old plain-TeX equivalents that still appear in real documents; left
# unhandled they leaked literally (``\bf1.``) or silently dropped their effect.
_EMPHASIS_DECL = {
    "bfseries": "bold", "bf": "bold",
    "itshape": "italic", "it": "italic", "em": "italic",
    "slshape": "italic", "sl": "italic",
    "ttfamily": "typewriter", "tt": "typewriter",
    "scshape": "smallcaps", "sc": "smallcaps",
}

# Upright/roman/sans/medium font resets: render the content with no added
# emphasis (\textrm/\textnormal are *upright*, not italic). True cancellation of
# a surrounding emphasis isn't modelled; a transparent passthrough is the closest
# faithful behaviour and avoids the previous "\textrm -> italic" inversion.
_FONT_RESET = {"textnormal", "textrm", "textsf", "textmd", "textup", "text"}

# Font-size declarations (10pt base) -> w:sz half-points.
_FONT_SIZE_HP = {
    "tiny": 10, "scriptsize": 14, "footnotesize": 16, "small": 18,
    "normalsize": 20, "large": 24, "Large": 29, "LARGE": 34,
    "huge": 41, "Huge": 50,
}

_MATH_ENVS = {
    "equation", "align", "gather", "multline", "eqnarray", "displaymath",
    "math", "alignat", "flalign",
    # amsmath inner-alignment envs that real (often OCR'd / copy-pasted) papers
    # use *bare* at block level, outside $$/\[ -- treat them as display math
    # rather than parsing the body as text (which leaks \frac, \int, … as raw).
    "aligned", "gathered", "split", "multlined",
}
# Of the above, these never carry equation numbers.
_UNNUMBERED_MATH_ENVS = {"displaymath", "math", "aligned", "gathered", "split", "multlined"}

# Environments we cannot translate to Word primitives -> graphics placeholder.
_OPAQUE_ENVS = {
    "tikzpicture", "pspicture", "pgfpicture", "circuitikz", "tikzcd",
    "tikzcd*", "forest", "pgfplots", "axis",
}

_CITE_MODES = {
    "cite": "paren", "citep": "paren", "Citep": "paren", "parencite": "paren",
    "citealp": "paren", "footcite": "foot", "smartcite": "paren",
    "autocite": "paren", "Autocite": "paren", "Parencite": "paren", "Cite": "paren",
    "citet": "text", "Citet": "text", "textcite": "text", "citealt": "text",
    "Textcite": "text",
    "citeauthor": "author", "Citeauthor": "author", "citeyear": "year",
    "citeyearpar": "year", "citenum": "num", "citenumber": "num",
}

_REF_KINDS = {
    "ref": "generic", "eqref": "equation", "pageref": "page",
    "autoref": "generic", "cref": "generic", "Cref": "generic", "vref": "generic",
    "crefrange": "generic", "Crefrange": "generic", "labelcref": "generic",
    "nameref": "name", "Nameref": "name",
}
# cleveref-style commands carry a type prefix; \ref/\eqref/\pageref stay bare.
_REF_STYLE = {
    "autoref": "full", "cref": "abbrev", "Cref": "full", "vref": "full",
    "crefrange": "abbrev", "Crefrange": "full",
}

_TEXT_SYMBOLS = {
    "LaTeX": "LaTeX", "TeX": "TeX", "ldots": "…", "dots": "…",
    "textellipsis": "…", "textemdash": "—", "textendash": "–",
    "textasciitilde": "~", "textbackslash": "\\", "textasciicircum": "^",
    "textbar": "|", "textless": "<", "textgreater": ">", "S": "§",
    "P": "¶", "copyright": "©", "textregistered": "®", "texttrademark": "™",
    "dag": "†", "ddag": "‡", "pounds": "£", "euro": "€", "%": "%",
    "textdegree": "°", "textbullet": "•", "textmu": "µ", "textperthousand": "‰",
    "textquotedblleft": "“", "textquotedblright": "”",
    "textquoteleft": "‘", "textquoteright": "’",
    "guillemotleft": "«", "guillemotright": "»", "textsection": "§",
    "textparagraph": "¶",
    # vulgar fractions, currencies, and assorted text symbols
    "textonehalf": "½", "textonequarter": "¼", "textthreequarters": "¾",
    "textonesuperior": "¹", "texttwosuperior": "²", "textthreesuperior": "³",
    "texteuro": "€", "textcent": "¢", "textsterling": "£", "textyen": "¥",
    "textdollar": "$", "textnumero": "№", "textcelsius": "℃", "textohm": "Ω",
    "textmho": "℧", "textdiv": "÷", "texttimes": "×", "textpm": "±",
    "textminus": "−", "textperiodcentered": "·", "textdaggerdbl": "‡",
    "textdagger": "†", "checkmark": "✓", "slash": "/", "nobreakspace": " ",
    # gensymb package text/math symbols
    "degree": "°", "celsius": "℃", "ohm": "Ω", "micro": "µ", "perthousand": "‰",
    "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}",
    " ": " ", ",": " ", ";": " ", ":": " ", "!": "", "@": "",
    "quad": " ", "qquad": "  ", "hfill": " ", "newline": "\n",
    # \xspace re-inserts the space pylatexenc gobbles after a control word,
    # so adjacent words don't fuse ("Cache\\xspace Practical").
    "xspace": " ",
    # common math-ish operators that also appear in text / pseudocode
    "gets": "←", "to": "→", "leftarrow": "←", "rightarrow": "→",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔",
    "land": "∧", "lor": "∨", "lnot": "¬", "neg": "¬", "neq": "≠", "ne": "≠",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "times": "×", "cdot": "·",
    "infty": "∞", "star": "★", "ast": "∗", "approx": "≈", "equiv": "≡",
    "in": "∈", "forall": "∀", "exists": "∃", "emptyset": "∅",
}

# pifont \ding{N}: Zapf-Dingbats slot -> Unicode. Common check/cross marks plus
# the three circled-digit ranges (used as level markers ❶❷… in many tables).
_DING_MAP: dict[int, str] = {
    51: "✓", 52: "✔", 53: "✗", 54: "✘", 55: "✗", 56: "✘",
}
for _i in range(10):
    _DING_MAP[172 + _i] = chr(0x2780 + _i)  # ➀..➉ circled sans-serif digit
    _DING_MAP[182 + _i] = chr(0x2776 + _i)  # ❶..❿ negative circled digit
    _DING_MAP[192 + _i] = chr(0x278A + _i)  # ➊..➓ negative circled sans-serif


def _ding_char(code: str) -> str:
    """Map a pifont ``\\ding{N}`` code to a Unicode dingbat (``•`` if unknown)."""
    try:
        return _DING_MAP.get(int(code.strip()), "•")
    except ValueError:
        return "•"

# Structural wrappers with no Word-visible formatting -> pass content through
# silently (no "unknown environment" warning). subequations groups display math;
# samepage/sloppypar/spacing affect TeX layout only; center/... handled earlier.
_TRANSPARENT_ENVS = {
    "subequations", "samepage", "sloppypar", "spacing", "singlespace",
    "doublespace", "onehalfspace", "noindent", "raggedright", "raggedleft",
    "small", "footnotesize", "large", "Large", "flushleftright",
}

# theorem-like environment name -> display name. proof is handled specially.
_THEOREM_ENVS = {
    "theorem": "Theorem", "thm": "Theorem", "lemma": "Lemma",
    "corollary": "Corollary", "cor": "Corollary", "proposition": "Proposition",
    "prop": "Proposition", "definition": "Definition", "defn": "Definition",
    "remark": "Remark", "example": "Example", "conjecture": "Conjecture",
    "claim": "Claim", "fact": "Fact", "observation": "Observation",
    "notation": "Notation", "assumption": "Assumption", "axiom": "Axiom",
    "exercise": "Exercise", "problem": "Problem", "question": "Question",
}

_TOC_MACROS = {
    "tableofcontents": "contents",
    "listoffigures": "figures",
    "listoftables": "tables",
}

_IGNORE_MACROS = {
    "maketitle", "frontmatter", "mainmatter", "backmatter",
    "newpage", "clearpage", "pagebreak", "noindent", "centering",
    "small", "large", "Large", "LARGE", "normalsize", "footnotesize",
    "scriptsize", "tiny", "huge", "Huge", "vspace", "hspace", "vfill",
    "bigskip", "medskip", "smallskip", "indent", "par", "protect",
    "displaystyle", "unskip", "ignorespaces", "leavevmode",
    "/",  # italic correction -> no output
    "sloppy", "fussy", "raggedright", "raggedleft", "flushbottom",
    "samepage", "frenchspacing", "boldmath", "unboldmath",
    "selectfont", "rmfamily", "sffamily", "normalfont", "floatbarrier",
    "rm", "sf", "md", "up", "mdseries", "upshape",  # upright/reset declarations
    "FloatBarrier", "height", "width", "depth", "totalheight",
    "fontfamily", "fontsize", "nohyphens",
    # preamble / packaging macros -- silently dropped
    "documentclass", "usepackage", "RequirePackage", "pagestyle",
    "thispagestyle", "setlength", "setcounter", "hypersetup",
    "graphicspath", "definecolor", "pagenumbering",
    "renewcommand", "newcommand", "providecommand",
    "setitemize", "setenumerate", "hyphenation", "settopmatter",
    # grouping / layout / counter declarations -> drop (args consumed by specs)
    "begingroup", "endgroup", "bgroup", "egroup",
    "AddToShipoutPicture", "ClearShipoutPicture",
    "newcounter", "addtocounter", "refstepcounter", "stepcounter",
    # ACM/IEEE front-matter + layout macros with no body-visible output. The
    # affiliation sub-fields take an argument (consumed by their MacroSpec below).
    "authornote", "authornotemark", "balance", "acmnote",
    "institution", "department", "city", "state", "country",
    "postcode", "streetaddress", "position",
}


# --------------------------------------------------------------------------- #
# Node helpers
# --------------------------------------------------------------------------- #


def _flatten_stacked_tables(blocks: list[ir.Block]) -> list[ir.Block]:
    """Flatten a single-column nested ``tabular`` (the ``{@{}c@{}}a\\\\b`` line-
    stacking idiom common inside cells) into one paragraph with line breaks,
    instead of emitting a nested table per cell.

    Only flattened when every row is a single cell whose content is plain
    paragraphs -- a cell holding a block (display math, nested list, another
    table) keeps its nested-table form so that content isn't dropped."""
    out: list[ir.Block] = []
    for b in blocks:
        if (
            isinstance(b, ir.Table)
            and b.rows
            and all(len(r.cells) == 1 for r in b.rows)
            and all(
                isinstance(cb, ir.Paragraph)
                for r in b.rows for cb in r.cells[0].blocks
            )
        ):
            inlines: list[ir.Inline] = []
            for i, row in enumerate(b.rows):
                if i:
                    inlines.append(ir.LineBreak())
                for cb in row.cells[0].blocks:
                    inlines.extend(cb.inlines)  # type: ignore[union-attr]
            out.append(ir.Paragraph(inlines))
        else:
            out.append(b)
    return out


def _brace_groups(node: LatexMacroNode) -> list[list]:
    """The node-lists of a macro's ``{}`` mandatory groups (skips ``[]`` options)."""
    argd = node.nodeargd
    if argd is None or not argd.argnlist:
        return []
    return [
        a.nodelist for a in argd.argnlist
        if isinstance(a, LatexGroupNode) and (not a.delimiters or a.delimiters[0] == "{")
    ]


def _optional_group(node: LatexMacroNode) -> list | None:
    """The nodelist of a macro's first ``[]`` optional argument, or None."""
    argd = node.nodeargd
    if argd is None or not argd.argnlist:
        return None
    for a in argd.argnlist:
        if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
            return a.nodelist
    return None


def _join_and(items: list[str]) -> str:
    """``a`` / ``a and b`` / ``a, b and c`` (siunitx list separators)."""
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _split_on_and(nodes: list) -> list[list]:
    """Split a node list at ``\\and`` macros (one ``\\author`` -> several authors)."""
    segments: list[list] = [[]]
    for n in nodes:
        if isinstance(n, LatexMacroNode) and n.macroname == "and":
            segments.append([])
        else:
            segments[-1].append(n)
    return [s for s in segments if s]


def _group_nodes(node: LatexMacroNode, which: int = -1) -> list:
    """Return the nodelist of a macro's mandatory group argument.

    ``which == -1`` picks the last group argument (the mandatory one for
    sectioning/emphasis); otherwise the n-th non-None argument.
    """
    argd = node.nodeargd
    if argd is None or not argd.argnlist:
        return []
    groups = [a for a in argd.argnlist if isinstance(a, LatexGroupNode)]
    if not groups:
        # a single non-group argument (e.g. \ref e)
        for a in argd.argnlist:
            if a is not None:
                return [a]
        return []
    if which == -1:
        return groups[-1].nodelist
    if which < len(groups):
        return groups[which].nodelist
    return []


def _verbatim_inner(env: LatexEnvironmentNode) -> str:
    """Inner LaTeX of an environment, without the \\begin/\\end wrappers."""
    # pylatexenc captures verbatim/lstlisting bodies as nodeargd.verbatim_text,
    # leaving nodelist empty -- check there first or the code block comes back blank.
    argd = env.nodeargd
    verb = getattr(argd, "verbatim_text", None) if argd is not None else None
    if verb is not None:
        return verb.strip("\n")
    if not env.nodelist:
        return ""
    first = env.nodelist[0]
    last = env.nodelist[-1]
    return env.parsing_state.s[first.pos : last.pos + last.len]


def _chars_of(nodes: list) -> str:
    out: list[str] = []
    for n in nodes:
        if isinstance(n, LatexCharsNode):
            out.append(n.chars)
        elif isinstance(n, LatexGroupNode):
            out.append(_chars_of(n.nodelist))
    return "".join(out).strip()


def _latex_of(nodes: list) -> str:
    """The verbatim LaTeX source of a node list (for \\ensuremath bodies)."""
    return "".join(n.latex_verbatim() for n in nodes).strip()


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


class _Builder:
    def __init__(self, report: ConversionReport) -> None:
        self.report = report
        self.meta = ir.DocumentMeta()
        self.bib_files: list[str] = []
        self.bib_style: str = "plain"
        self.bibstyle_set: bool = False  # an explicit \bibliographystyle was seen
        self.thebib_items: dict[str, ir.CSLItem] = {}
        self.colors = ColorTable()
        # glossaries/acronyms: label -> (short, long); track first use of \gls
        self.acronyms: dict[str, tuple[str, str]] = {}
        # plain glossary terms (\newglossaryentry): label -> name (display text)
        self.glossary: dict[str, str] = {}
        self._acr_seen: set[str] = set()
        self.nocite_keys: list[str] = []  # \nocite{key} / \nocite{*}
        self.book_mode = False  # book/report class: \chapter is the top level
        self.in_appendix = False  # seen \appendix -> later sections use letters
        # \footnotemark placeholders awaiting their \footnotetext{...} content
        self._pending_footmarks: list[ir.Footnote] = []
        # theorem-like environment name -> display title (built-ins + \newtheorem)
        self.theorem_envs: dict[str, str] = dict(_THEOREM_ENVS)
        self.unnumbered_theorems: set[str] = set()  # \newtheorem*-defined names
        # env name -> counter display title (shared counters resolve here)
        self.theorem_counters: dict[str, str] = {}
        # user \newtcolorbox / \newmdenv callout environments -> Quote blocks
        self.box_envs: set[str] = set()
        #: env name -> (backgroundcolor, linecolor) names for coloured callouts
        self.box_styles: dict[str, tuple[str | None, str | None]] = {}

    # -- inline ----------------------------------------------------------- #

    def inlines(self, nodes: list) -> list[ir.Inline]:
        return _clean_inlines(self._scoped_inlines(nodes))

    def _scoped_inlines(self, nodes: list) -> list[ir.Inline]:
        """Build inlines, honouring ``\\color`` as a scope switch.

        ``\\color{c}`` (and a leading ``\\color`` inside ``{...}``) tints every
        following sibling in the current group, so we wrap the remainder rather
        than treating it as a standalone macro.
        """
        out: list[ir.Inline] = []
        for i, node in enumerate(nodes):
            if isinstance(node, LatexMacroNode) and node.macroname in ("color", "normalcolor"):
                rest = self._scoped_inlines(nodes[i + 1:])
                fg = self._color_of(node) if node.macroname == "color" else None
                if fg:
                    out.append(ir.Colored(rest, fg=fg))
                else:  # unresolved colour or \normalcolor reset -- emit untinted
                    out.extend(rest)
                return out
            if isinstance(node, LatexMacroNode) and node.macroname in _FONT_SIZE_HP:
                rest = self._scoped_inlines(nodes[i + 1:])
                hp = _FONT_SIZE_HP[node.macroname]
                if hp == 20:  # \normalsize -- no span needed
                    out.extend(rest)
                else:
                    out.append(ir.FontSize(rest, half_points=hp))
                return out
            if isinstance(node, LatexMacroNode) and node.macroname in _EMPHASIS_DECL:
                rest = self._scoped_inlines(nodes[i + 1:])  # {\bfseries ...} scope
                out.append(ir.Emphasis(rest, _EMPHASIS_DECL[node.macroname]))  # type: ignore[arg-type]
                return out
            self._inline_node(node, out)
        return out

    def _color_of(self, node: LatexMacroNode) -> str | None:
        """Resolve the colour of a ``\\color``/``\\textcolor``-style macro arg."""
        model: str | None = None
        color: str | None = None
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if a is None:
                continue
            if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
                model = _chars_of(a.nodelist)
            elif color is None:
                color = _chars_of(a.nodelist) if isinstance(a, LatexGroupNode) else _chars_of([a])
        if not color:
            return None
        return self.colors.resolve(color, model or None)

    def _inline_node(self, node, out: list[ir.Inline]) -> None:  # noqa: C901
        if isinstance(node, LatexCharsNode):
            text = _normalize_ws(node.chars)
            if text:
                out.append(ir.Text(text))
            return
        if isinstance(node, LatexCommentNode):
            return
        if isinstance(node, LatexMathNode):
            latex = _strip_math_delims(node.latex_verbatim(), "math")
            out.append(ir.Math(latex))
            return
        if isinstance(node, LatexGroupNode):
            out.extend(self._scoped_inlines(node.nodelist))  # contain \color scope
            return
        if isinstance(node, LatexSpecialsNode):
            self._inline_special(node, out)
            return
        if isinstance(node, LatexMacroNode):
            self._inline_macro(node, out)
            return

    def _inline_special(self, node: LatexSpecialsNode, out: list[ir.Inline]) -> None:
        spec = node.specials_chars
        if spec == "~":
            out.append(ir.Text(" "))
        elif spec in ("``", "''"):
            out.append(ir.Text('"'))
        elif spec in ("`", "'"):
            out.append(ir.Text("'"))
        elif spec in ("--", "---"):
            out.append(ir.Text("–" if spec == "--" else "—"))
        # otherwise ignore

    def _inline_macro(self, node: LatexMacroNode, out: list[ir.Inline]) -> None:  # noqa: C901
        name = node.macroname
        if name in _FONT_RESET:  # \textrm/\textnormal/... -> upright passthrough
            out.extend(self.inlines(_group_nodes(node)))
            return
        if name in _EMPHASIS:
            inner = self.inlines(_group_nodes(node))
            out.append(ir.Emphasis(inner, _EMPHASIS[name]))  # type: ignore[arg-type]
            return
        if name in ("textcolor", "colorbox", "fcolorbox"):
            self._inline_color(node, name, out)
            return
        if name in ("\\", "newline"):
            out.append(ir.LineBreak())
            return
        if name == "verb":
            text = getattr(node.nodeargd, "verbatim_text", None)
            if text is not None:
                out.append(ir.Emphasis([ir.Text(text)], "typewriter"))
                return
        if name in ("lstinline", "mintinline"):  # brace form -> typewriter text
            groups = _brace_groups(node)  # \mintinline{lang}{code} -> last group
            if groups:
                out.append(ir.Emphasis([ir.Text(_chars_of(groups[-1]))], "typewriter"))
            return
        if name in ("crefrange", "Crefrange"):
            # \crefrange{a}{b} -> "secs. 1 to 3": both endpoints, joined by "to"
            groups = _brace_groups(node)
            kind = _REF_KINDS[name]
            style = _REF_STYLE.get(name, "plain")
            if len(groups) >= 2:
                out.append(ir.Ref(_chars_of(groups[0]).strip(), kind, style=style))  # type: ignore[arg-type]
                out.append(ir.Text(" to "))
                out.append(ir.Ref(_chars_of(groups[1]).strip(), kind, style="plain"))  # type: ignore[arg-type]
            elif groups:
                out.append(ir.Ref(_chars_of(groups[-1]).strip(), kind, style=style))  # type: ignore[arg-type]
            return
        if name in _REF_KINDS:
            kind = _REF_KINDS[name]
            style = _REF_STYLE.get(name, "plain")
            keys = [k.strip() for k in _chars_of(_group_nodes(node)).split(",") if k.strip()]
            for idx, key in enumerate(keys):
                if idx > 0:  # cleveref joins multi-labels with ", " / " and "
                    out.append(ir.Text(" and " if idx == len(keys) - 1 else ", "))
                # only the first reference carries the cleveref type prefix
                out.append(ir.Ref(key, kind, style=(style if idx == 0 else "plain")))  # type: ignore[arg-type]
            if not keys:
                out.append(ir.Ref("", kind, style=style))  # type: ignore[arg-type]
            return
        if name in _CITE_MODES:
            key = _chars_of(_group_nodes(node))
            keys = [k.strip() for k in key.split(",") if k.strip()]
            prefix, suffix = self._cite_locators(node)
            out.append(
                ir.Cite(keys, _CITE_MODES[name], prefix=prefix, suffix=suffix)  # type: ignore[arg-type]
            )
            return
        if name == "label":
            label = _chars_of(_group_nodes(node))
            if self._labelable is not None and label:
                self._labelable.label = label
            return
        if name in ("href", "url"):
            self._inline_link(node, out)
            return
        if name == "hyperref":  # \hyperref[label]{text} -> internal link to label
            opt = _optional_group(node)
            groups = _brace_groups(node)
            text = self.inlines(groups[-1]) if groups else []
            if opt is not None:
                anchor = _chars_of(opt).strip()
                out.append(ir.Link(text or [ir.Text(anchor)], "", anchor=anchor))
            else:
                out.extend(text)  # \hyperref{url}{cat}{name}{text} -> just the text
            return
        if name in ("footnote", "thanks", "marginpar", "sidenote"):
            # \thanks (title/author note), \marginpar/\sidenote (margin asides)
            # all degrade to a Word footnote -- the closest aside Word offers.
            out.append(ir.Footnote(self.inlines(_group_nodes(node))))
            return
        if name == "footnotemark":
            # split footnote: a mark here, its text supplied later by \footnotetext.
            fn = ir.Footnote([])
            self._pending_footmarks.append(fn)
            out.append(fn)
            return
        if name == "footnotetext":
            # fill the oldest pending \footnotemark; if none, emit inline.
            content = self.inlines(_group_nodes(node))
            if self._pending_footmarks:
                self._pending_footmarks.pop(0).inlines = content
            else:
                out.append(ir.Footnote(content))
            return
        if name in ("enquote", "textquote", "foreignquote", "hyphenquote"):
            # csquotes inline quotes -> curly quotes around the quoted group
            # (\foreignquote/\hyphenquote carry a leading {lang}; quote the last).
            inner = self.inlines(_group_nodes(node))
            lq, rq = ("‘", "’") if _has_star(node) else ("“", "”")
            out.append(ir.Text(lq))
            out.extend(inner)
            out.append(ir.Text(rq))
            return
        if name == "endnote":
            out.append(ir.Endnote(self.inlines(_group_nodes(node))))
            return
        if name == "theendnotes":  # endnotes render natively at the doc end
            return
        if name == "index":  # -> a hidden Word XE index-entry field
            term = _chars_of(_group_nodes(node)).strip().replace('"', "'")
            if term:
                out.append(ir.IndexEntry(term))
            return
        if name in ("todo", "comment", "note"):  # review annotations -> Word comment
            text = _chars_of(_group_nodes(node)).strip()
            if text:
                out.append(ir.Comment(text=text))
            return
        if name in ("nicefrac", "sfrac"):  # text-mode fraction a/b
            groups = _brace_groups(node)
            if len(groups) >= 2:
                out.append(ir.Text(_chars_of(groups[0])))
                out.append(ir.Text("/"))
                out.append(ir.Text(_chars_of(groups[1])))
            return
        if name in ("si", "unit"):
            out.append(ir.Text(siunitx.units_to_text(_group_nodes(node))))
            return
        if name in ("SI", "qty"):
            groups = _brace_groups(node)
            num = siunitx.num_to_text(_chars_of(groups[0])) if groups else ""
            unit = siunitx.units_to_text(groups[1]) if len(groups) > 1 else ""
            out.append(ir.Text(f"{num}{siunitx.THIN}{unit}".strip()))
            return
        if name == "num":
            out.append(ir.Text(siunitx.num_to_text(_chars_of(_group_nodes(node)))))
            return
        if name == "ang":
            out.append(ir.Text(siunitx.ang_to_text(_chars_of(_group_nodes(node)))))
            return
        if name in ("numrange", "SIrange", "qtyrange"):  # a to b [unit]
            groups = _brace_groups(node)
            if len(groups) >= 2:
                a = siunitx.num_to_text(_chars_of(groups[0]))
                b = siunitx.num_to_text(_chars_of(groups[1]))
                unit = siunitx.units_to_text(groups[2]) if len(groups) > 2 else ""
                out.append(ir.Text(f"{a} to {b}" + (f"{siunitx.THIN}{unit}" if unit else "")))
            return
        if name in ("numlist", "SIlist", "qtylist"):  # a, b and c [unit]
            groups = _brace_groups(node)
            if groups:
                items = [siunitx.num_to_text(x.strip())
                         for x in _chars_of(groups[0]).split(";") if x.strip()]
                unit = siunitx.units_to_text(groups[1]) if len(groups) > 1 else ""
                out.append(ir.Text(_join_and(items) + (f"{siunitx.THIN}{unit}" if unit else "")))
            return
        if name == "includegraphics":  # an inline image (icon/logo in text)
            out.append(_make_image(node))
            return
        if name in _DROP_MACROS:  # phantom/rule: reserve space, print nothing
            return
        if name == "IEEEPARstart":  # \IEEEPARstart{T}{he} -> "The" (IEEE drop cap)
            groups = _brace_groups(node)
            for g in groups:
                out.extend(self.inlines(g))
            return
        if name == "ensuremath":  # \ensuremath{x} -> inline math
            out.append(ir.Math(_latex_of(_group_nodes(node))))
            return
        if name == "texorpdfstring":  # \texorpdfstring{TeX}{PDF} -> the TeX form
            groups = _brace_groups(node)
            if groups:
                out.extend(self.inlines(groups[0]))
            return
        if name in _TRANSPARENT_BOX or name in _AUTHOR_BLOCK:  # ...{X} -> X
            groups = _brace_groups(node)
            if groups:
                out.extend(self.inlines(groups[-1]))
            return
        if name in ("inst", "IEEEauthorrefmark"):  # affiliation marker -> superscript
            out.append(ir.Emphasis(self.inlines(_group_nodes(node)), "superscript"))
            return
        if name in ("newacronym", "newglossaryentry", "acro", "acrodef"):
            return  # definitions are collected separately; emit nothing
        if name.lower() in _AC_TO_GLS:  # acronym package: \ac/\acs/\acl/\acf/...
            label = _chars_of(_group_nodes(node)).strip()
            tname = _AC_TO_GLS[name.lower()]
            if name[:1].isupper():  # \Ac/\Acl/... -> capitalise the result
                tname = tname[:1].upper() + tname[1:]
            out.append(ir.Text(self._acronym_text(tname, label)))
            return
        if name.lower() in _GLS_MACROS:
            label = _chars_of(_group_nodes(node)).strip()
            out.append(ir.Text(self._acronym_text(name, label)))
            return
        if name == "ding":  # pifont dingbat: \ding{51}=✓, \ding{182}=❶, ...
            out.append(ir.Text(_ding_char(_chars_of(_group_nodes(node)))))
            return
        if name in ("shortstack", "stackanchor", "Shortstack"):
            # \shortstack[pos]{a \\ b}: stacked lines -> the content with \\ kept
            # as line breaks (the LatexMacroNode "\\" becomes ir.LineBreak).
            out.extend(self.inlines(_group_nodes(node)))
            return
        if name in _TEXT_SYMBOLS:
            out.append(ir.Text(_TEXT_SYMBOLS[name]))
            return
        if name in _IGNORE_MACROS:
            return
        if _accent_char(name) is not None:
            base = _chars_of(_group_nodes(node))
            out.append(ir.Text(_apply_text_accent(name, base)))
            return
        # graceful degradation
        self.report.warn(f"\\{name}", f"unsupported inline macro \\{name}")
        out.append(ir.RawInline(node.latex_verbatim(), f"unsupported macro \\{name}"))

    def _acronym_text(self, name: str, label: str) -> str:
        """Expand a glossaries/acronym reference (\\gls/\\acrshort/…) to text."""
        entry = self.acronyms.get(label)
        if entry is None:
            # a plain \newglossaryentry term: \gls/\glspl just print its name
            term = self.glossary.get(label)
            if term is not None:
                low = name.lower()
                text = term + ("s" if low.endswith("pl") else "")
                if name[:1].isupper() and text:
                    text = text[:1].upper() + text[1:]
                return text
            return label  # undefined acronym -> emit the key, never crash
        short, long = entry
        low = name.lower()
        plural = low.endswith("pl")
        key = low[:-2] if plural else low
        s = short + ("s" if plural else "")
        lg = long + ("s" if plural else "")
        full = f"{lg} ({s})"
        if key == "gls":
            text = s if label in self._acr_seen else full
            self._acr_seen.add(label)
        elif key in ("acrshort", "glsentryshort"):
            text = s
        elif key in ("acrlong", "glsentrylong"):
            text = lg
        elif key == "acrfull":
            text = full
        else:
            text = s
        if name[:1].isupper() and text:  # \Gls/\Acrlong/... capitalise
            text = text[:1].upper() + text[1:]
        return text

    def _glossary_list(self) -> ir.Block | None:
        """\\printglossaries/\\printacronyms -> a description list of the entries."""
        items: list[ir.ListItem] = []
        for short, long in self.acronyms.values():
            items.append(ir.ListItem([ir.Paragraph([ir.Text(long)])], term=[ir.Text(short)]))
        for key, name in self.glossary.items():
            items.append(ir.ListItem([ir.Paragraph([ir.Text(name)])], term=[ir.Text(key)]))
        if not items:
            return None
        return ir.ItemList(ordered=False, items=items, description=True)

    def _inline_color(self, node: LatexMacroNode, name: str, out: list[ir.Inline]) -> None:
        model: str | None = None
        groups: list[list] = []
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if a is None:
                continue
            if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
                model = _chars_of(a.nodelist)
            elif isinstance(a, LatexGroupNode):
                groups.append(a.nodelist)
        if not groups:
            return
        inner = self.inlines(groups[-1])  # last mandatory group is the content
        # the colour group: \textcolor{C}{t} / \colorbox{C}{t} -> groups[0];
        # \fcolorbox{frame}{C}{t} -> groups[-2] (the background colour).
        color_group = groups[-2] if len(groups) >= 2 else None
        hexval = self.colors.resolve(_chars_of(color_group), model or None) if color_group else None
        if hexval is None:
            out.extend(inner)
        elif name == "textcolor":
            out.append(ir.Colored(inner, fg=hexval))
        else:
            out.append(ir.Colored(inner, bg=hexval))

    def _inline_link(self, node: LatexMacroNode, out: list[ir.Inline]) -> None:
        argd = node.nodeargd
        groups = [a for a in (argd.argnlist if argd else []) if isinstance(a, LatexGroupNode)]
        if node.macroname == "url" and groups:
            url = _chars_of(groups[0].nodelist)
            out.append(ir.Link([ir.Text(url)], url))
        elif len(groups) >= 2:
            url = _chars_of(groups[0].nodelist)
            out.append(ir.Link(self.inlines(groups[1].nodelist), url))
        elif groups:
            url = _chars_of(groups[0].nodelist)
            out.append(ir.Link([ir.Text(url)], url))

    # -- blocks ----------------------------------------------------------- #

    def blocks(self, nodes: list) -> list[ir.Block]:
        out: list[ir.Block] = []
        inline_buf: list[ir.Inline] = []
        # block-level declaration scopes (\color{c} / {\bfseries} used *unbraced*
        # at block level): (index into inline_buf, kind, value). Applied at flush
        # so the declaration wraps the run of inlines that followed it, like the
        # braced form does via _scoped_inlines.
        scope_marks: list[tuple[int, str, object]] = []

        def flush() -> None:
            for idx, kind, val in reversed(scope_marks):
                seg = inline_buf[idx:]
                if not seg:
                    continue
                if kind == "color" and val:
                    inline_buf[idx:] = [ir.Colored(seg, fg=val)]  # type: ignore[arg-type]
                elif kind == "emph":
                    inline_buf[idx:] = [ir.Emphasis(seg, val)]  # type: ignore[arg-type]
            scope_marks.clear()
            if any(not (isinstance(x, ir.Text) and not x.value.strip()) for x in inline_buf):
                cleaned = _clean_inlines(inline_buf.copy(), trim=True)
                if cleaned:
                    out.append(ir.Paragraph(cleaned))
            inline_buf.clear()

        for node in nodes:
            if isinstance(node, LatexCharsNode):
                self._chars_into_blocks(node.chars, inline_buf, out, flush)
                continue
            if isinstance(node, LatexCommentNode):
                continue
            if isinstance(node, LatexMathNode) and _is_display(node):
                flush()
                out.append(self._math_block(node.latex_verbatim(), "displaymath", False))
                continue
            if isinstance(node, LatexEnvironmentNode):
                flush()
                self._environment(node, out)
                continue
            # a bare {...} group wrapping a block environment (e.g. the common
            # {\footnotesize \begin{verbatim}...\end{verbatim}}) -> descend as blocks
            if isinstance(node, LatexGroupNode) and any(
                isinstance(c, LatexEnvironmentNode) for c in node.nodelist
            ):
                flush()
                out.extend(self.blocks(node.nodelist))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "label":
                label = _chars_of(_group_nodes(node))
                # Don't overwrite a label the target already captured (e.g. a
                # figure's own \label, when a stray \label follows \end{figure}).
                if self._labelable is not None and label and self._labelable.label is None:
                    self._labelable.label = label
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in ("appendix", "beginappendix"):
                # \appendix (and class wrappers like fairmeta's \beginappendix)
                # switch later sections to lettered numbering.
                self.in_appendix = True
                continue
            if isinstance(node, LatexMacroNode) and node.macroname.rstrip("*") in _SECTION_LEVELS:
                flush()
                self._heading(node, out)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _TOC_MACROS:
                flush()
                out.append(ir.TableOfContents(kind=_TOC_MACROS[node.macroname]))  # type: ignore[arg-type]
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in (
                "title", "author", "date", "keywords", "IEEEkeywords",
                "institute", "affiliation", "affil", "address", "email", "orcid",
                "markboth", "markright", "runninghead", "shorttitle",
            ):
                self._meta_macro(node)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in ("resizebox", "scalebox"):
                # box-scaling wrappers are transparent: process their content as
                # blocks so nested tabulars/minipages survive (\resizebox{w}{h}{X}).
                flush()
                groups = _brace_groups(node)
                if groups:
                    out.extend(self.blocks(groups[-1]))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "includegraphics":
                # mid-paragraph (text already buffered) -> inline image (icon);
                # otherwise a standalone bare image -> a centered Figure
                if any(not (isinstance(x, ir.Text) and not x.value.strip())
                       for x in inline_buf):
                    self._inline_node(node, inline_buf)
                else:
                    flush()
                    out.append(self._figure_from_graphics(node))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "bibliographystyle":
                self.bib_style = _chars_of(_group_nodes(node)) or self.bib_style
                self.bibstyle_set = True
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "nocite":
                for key in _chars_of(_group_nodes(node)).split(","):
                    if key.strip():
                        self.nocite_keys.append(key.strip())
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "bibliography":
                flush()
                for name in _chars_of(_group_nodes(node)).split(","):
                    if name.strip():
                        self.bib_files.append(name.strip())
                out.append(ir.Bibliography(entries=[], style="numeric"))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "addbibresource":
                for name in _chars_of(_group_nodes(node)).split(","):  # biblatex
                    if name.strip():
                        self.bib_files.append(name.strip())
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "printbibliography":
                flush()
                out.append(ir.Bibliography(entries=[], style="numeric"))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "printindex":
                flush()
                out.append(ir.Index())
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _PRINTGLOSSARY_MACROS:
                flush()
                glossary = self._glossary_list()
                if glossary is not None:
                    out.append(glossary)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in (
                "blockquote", "blockcquote", "foreignblockquote",
            ):
                # csquotes block quote -> a Quote block (the last {} group is the
                # quoted body; \blockcquote/\foreignblockquote carry a leading arg)
                flush()
                groups = _brace_groups(node)
                body = self.blocks(groups[-1]) if groups else []
                out.append(ir.Quote(body or [ir.Paragraph([])]))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "epigraph":
                # \epigraph{quote}{source} -> a Quote with a right-aligned italic
                # attribution line underneath.
                flush()
                groups = _brace_groups(node)
                quote = self.inlines(groups[0]) if groups else []
                blocks: list[ir.Block] = [ir.Paragraph(quote)]
                if len(groups) > 1:
                    src = _clean_inlines(self.inlines(groups[1]), trim=True)
                    if src:
                        blocks.append(ir.Paragraph([ir.Emphasis(src, "italic")], align="right"))
                out.append(ir.Quote(blocks))
                continue
            # block-level declaration scopes: \color{c} / \normalcolor and the
            # font switches {\bfseries}/{\bf}/... used unbraced -- record where
            # they start so flush() wraps the inlines that follow.
            if isinstance(node, LatexMacroNode) and node.macroname in ("color", "normalcolor"):
                fg = self._color_of(node) if node.macroname == "color" else None
                scope_marks.append((len(inline_buf), "color", fg))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _EMPHASIS_DECL:
                scope_marks.append((len(inline_buf), "emph", _EMPHASIS_DECL[node.macroname]))
                continue
            # otherwise inline content
            self._inline_node(node, inline_buf)
        flush()
        return out

    def _chars_into_blocks(self, chars: str, buf: list[ir.Inline], out, flush) -> None:
        # split on blank lines (paragraph breaks)
        parts = chars.split("\n\n")
        for idx, part in enumerate(parts):
            if idx > 0:
                flush()
            text = _normalize_ws(part)
            if text:
                buf.append(ir.Text(text))

    def _meta_macro(self, node: LatexMacroNode) -> None:
        if node.macroname == "author":
            # one \author may list several authors separated by \and
            for seg in _split_on_and(_group_nodes(node)):
                inner = _clean_inlines(self.inlines(seg), trim=True)
                if inner:
                    self.meta.authors.append(inner)
            return
        if node.macroname in ("institute", "affiliation", "affil", "address"):
            for seg in _split_on_and(_group_nodes(node)):
                inner = _clean_inlines(self.inlines(seg), trim=True)
                if inner:
                    self.meta.affiliations.append(inner)
            return
        if node.macroname in ("markboth", "markright", "runninghead", "shorttitle"):
            # \markboth{even}{odd} -> the odd (recto) head; others take their group
            groups = _brace_groups(node)
            head_nodes = groups[-1] if groups else _group_nodes(node)
            head = _normalize_ws(_chars_of(head_nodes)).strip()
            if head and not self.meta.running_head:
                self.meta.running_head = head
            return
        inner = _clean_inlines(self.inlines(_group_nodes(node)), trim=True)
        if node.macroname == "title":
            self.meta.title = inner
            opt = _optional_group(node)  # \title[running head]{full title}
            if opt is not None and not self.meta.running_head:
                head = _normalize_ws(_chars_of(opt)).strip()
                if head:
                    self.meta.running_head = head
        elif node.macroname == "date":
            self.meta.date = inner
        elif node.macroname in ("keywords", "IEEEkeywords"):
            self.meta.keywords = inner
        elif node.macroname == "email" and inner:
            self.meta.affiliations.append([ir.Text("Email: "), *inner])
        elif node.macroname == "orcid":
            oid = _chars_of(_group_nodes(node)).strip()
            if oid:
                url = oid if oid.startswith("http") else f"https://orcid.org/{oid}"
                self.meta.affiliations.append([ir.Link([ir.Text(f"ORCID: {oid}")], url)])

    def _heading(self, node: LatexMacroNode, out: list[ir.Block]) -> None:
        name = node.macroname.rstrip("*")
        levels = _SECTION_LEVELS_BOOK if self.book_mode else _SECTION_LEVELS
        level = levels.get(name, 1)
        inner = _clean_inlines(self.inlines(_group_nodes(node)), trim=True)
        # LaTeX numbers \chapter..\subsubsection by default; starred forms and the
        # run-in \paragraph/\subparagraph are not. \part is numbered too, but with
        # an independent upper-roman counter ("Part I"), so it gets its own flag.
        is_part = name == "part"
        numbered = not _has_star(node) and (name in _NUMBERED_SECTIONS or is_part)
        heading = ir.Heading(
            level,
            inner,
            numbered=numbered,
            appendix=self.in_appendix and numbered and not is_part,
            part=is_part,
        )
        out.append(heading)
        self._labelable = heading

    def _math_block(self, verbatim: str, env: str, numbered: bool) -> ir.MathBlock:
        latex = _strip_math_delims(verbatim, env)
        label = _extract_label(latex) if "\\label" in latex else None
        latex = _LABEL_TAG_RE.sub("", latex).strip()
        block = ir.MathBlock(latex=latex, numbered=numbered, env=env, label=label)
        self._labelable = block
        return block

    _labelable: (
        ir.Heading | ir.MathBlock | ir.Figure | ir.Table | ir.Theorem
        | ir.Algorithm | ir.ListItem | None
    ) = None

    def _environment(self, node: LatexEnvironmentNode, out: list[ir.Block]) -> None:  # noqa: C901
        name = node.environmentname
        base = name.rstrip("*")
        starred = name.endswith("*")
        if base in _MATH_ENVS:
            numbered = (base not in _UNNUMBERED_MATH_ENVS) and not starred
            out.append(self._math_block(_verbatim_inner(node), base, numbered))
            return
        if base in ("itemize", "enumerate", "description"):
            out.append(self._list(
                node, ordered=(base == "enumerate"), description=(base == "description")
            ))
            return
        if base in ("figure", "wrapfigure"):
            out.append(self._figure(node, spanning=starred))
            return
        if base in ("table", "wraptable"):
            self._table_float(node, out, spanning=starred)
            return
        if base in (
            "tabular", "array", "tabularx", "tabulary", "longtable",
            "supertabular", "xtabular", "mpsupertabular",
        ):
            out.append(self._tabular(node))
            return
        if base in (
            "quote", "quotation", "verse", "displayquote", "displaycquote",
            # boxed-content environments -> a set-off Quote block (the closest IR)
            "framed", "shaded", "mdframed", "tcolorbox", "boxedminipage", "leftbar",
        ) or base in self.box_envs:
            bg, line = self.box_styles.get(base, (None, None))
            shade = self.colors.resolve(bg, None) if bg else None
            border = self.colors.resolve(line, None) if line else None
            out.append(ir.Quote(self.blocks(node.nodelist), shade=shade, border=border))
            return
        if base in ("verbatim", "lstlisting", "minted"):
            out.append(ir.CodeBlock(_verbatim_inner(node), lang=None))
            return
        if base == "abstract":
            self.meta.abstract = self.blocks(node.nodelist)
            return
        if base in ("center", "flushleft", "flushright"):
            align = {"center": "center", "flushleft": "left", "flushright": "right"}[base]
            for blk in self.blocks(node.nodelist):
                if isinstance(blk, ir.Paragraph) and blk.align is None:
                    blk.align = align
                out.append(blk)
            return
        if base in ("document", "minipage"):
            out.extend(self.blocks(node.nodelist))
            return
        if base == "thebibliography":
            out.append(self._thebibliography(node))
            return
        if base in self.theorem_envs or base == "proof":
            out.append(self._theorem(node, base, starred))
            return
        if base in ("algorithm", "algorithm2e"):
            out.append(self._algorithm(node))
            return
        if base in _OPAQUE_ENVS:
            # graphics we cannot translate -> placeholder + warning (PRD: TikZ).
            self.report.warn(name, f"{name} kept as a graphics placeholder")
            out.append(ir.Figure(image=None, source=node.latex_verbatim()))
            return
        # A custom wrapper that contains \item is a list (e.g. a user-defined
        # `ul`/`enum` wrapping itemize/enumerate) -> render as a list so the
        # items keep their structure instead of leaking "\item".
        if any(
            isinstance(c, LatexMacroNode) and c.macroname == "item" for c in node.nodelist
        ):
            ordered = "enum" in base or "ordered" in base or "number" in base
            self.report.info(name, f"custom list environment {name}: rendered as a list")
            out.append(self._list(node, ordered=ordered))
            return
        # Known structural wrappers that carry no Word-visible formatting of their
        # own: pass the content through silently (no warning).
        if base in _TRANSPARENT_ENVS:
            out.extend(self.blocks(node.nodelist))
            return
        # Otherwise treat the unknown environment as a transparent wrapper so its
        # content is preserved (boxes, algorithm, subfig, ...).
        self.report.warn(name, f"unknown environment {name}: treated as transparent")
        out.extend(self.blocks(node.nodelist))

    def _theorem(self, node: LatexEnvironmentNode, base: str, starred: bool) -> ir.Theorem:
        is_proof = base == "proof"
        display = "Proof" if is_proof else self.theorem_envs.get(base, base.capitalize())
        title = self._env_optional_title(node)
        # proof is unnumbered; so are starred uses (\begin{theorem*}) and any
        # environment defined with \newtheorem* (no counter).
        unnumbered = is_proof or starred or base in self.unnumbered_theorems
        # a shared-counter env (\newtheorem{LEM}[THM]{Lemma}) numbers against the
        # counter it shares (THM's "Theorem"), so they form one running sequence.
        counter = None if unnumbered else self.theorem_counters.get(base, display)
        theorem = ir.Theorem(kind=display, blocks=[], title=title, counter=counter)
        # become the label target *before* parsing the body, so a \label at the
        # start of the environment attaches here, not to the preceding block.
        self._labelable = theorem
        theorem.blocks = self.blocks(node.nodelist)
        return theorem

    def _algorithm(self, node: LatexEnvironmentNode) -> ir.Algorithm:
        from .algorithms import parse_algorithm_body

        caption: list[ir.Inline] | None = None
        label: str | None = None
        for child in _walk_macros(node.nodelist):
            if child.macroname == "caption":
                caption = self.inlines(_group_nodes(child))
            elif child.macroname == "label":
                label = _chars_of(_group_nodes(child))
        lines = parse_algorithm_body(node.nodelist, self.inlines)
        alg = ir.Algorithm(lines=lines, caption=caption, label=label)
        self._labelable = alg
        return alg

    def _env_optional_title(self, node: LatexEnvironmentNode) -> list[ir.Inline] | None:
        argd = node.nodeargd
        if argd and argd.argnlist:
            opt = argd.argnlist[0]
            if isinstance(opt, LatexGroupNode) and opt.nodelist:
                return self.inlines(opt.nodelist)
        return None

    def _thebibliography(self, node: LatexEnvironmentNode) -> ir.Bibliography:
        """Parse a ``thebibliography`` env's ``\\bibitem`` entries into CSL items."""
        key: str | None = None
        buf: list = []
        order = 0

        def flush() -> None:
            nonlocal order
            if key is not None:
                text = _inlines_to_text(self.inlines(buf))
                order += 1
                self.thebib_items[key] = ir.CSLItem(
                    id=key, type="document", csl_fields={"note": text, "_order": order}
                )
            buf.clear()

        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "bibitem":
                flush()
                key = _chars_of(_group_nodes(child))
            elif key is not None:
                buf.append(child)
        flush()
        return ir.Bibliography(entries=[], style="numeric")

    def _list(
        self, node: LatexEnvironmentNode, ordered: bool, description: bool = False
    ) -> ir.ItemList:
        items: list[ir.ListItem] = []
        current: list = []
        term: list[ir.Inline] | None = None
        started = False

        def flush_item() -> None:
            nonlocal term
            # become the label target before parsing the body, so an \item\label{}
            # attaches to this item (referenceable list number), not the preceding
            # block -- mirroring how _theorem captures its label.
            item = ir.ListItem([], term=term)
            self._labelable = item
            item.blocks = self.blocks(current.copy())
            items.append(item)
            current.clear()
            term = None

        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "item":
                if started:
                    flush_item()
                started = True
                term = self._item_term(child)
            elif started:
                current.append(child)
            # content before the first \item is discarded (it isn't an item)
        if started:
            flush_item()
        return ir.ItemList(ordered=ordered, items=items, description=description)

    def _cite_locators(self, node: LatexMacroNode) -> tuple[str | None, str | None]:
        """Extract ``\\citep[pre][post]{key}`` locators.

        natbib: a single optional is the *post*-note (suffix); two optionals are
        (pre, post).
        """
        argd = node.nodeargd
        opts = [
            _chars_of(a.nodelist)
            for a in (argd.argnlist if argd else [])
            if isinstance(a, LatexGroupNode) and a.delimiters == ("[", "]")
        ]
        if len(opts) >= 2:
            return (opts[0] or None, opts[1] or None)
        if len(opts) == 1:
            return (None, opts[0] or None)
        return (None, None)

    def _item_term(self, node: LatexMacroNode) -> list[ir.Inline] | None:
        """Extract the optional ``\\item[term]`` label (description lists)."""
        argd = node.nodeargd
        for arg in argd.argnlist if argd else []:
            if isinstance(arg, LatexGroupNode) and arg.delimiters == ("[", "]"):
                return _clean_inlines(self.inlines(arg.nodelist), trim=True)
        return None

    def _figure(self, node: LatexEnvironmentNode, spanning: bool = False) -> ir.Figure:
        fig = ir.Figure(image=None, source=node.latex_verbatim(), spanning=spanning)
        self._collect_figure_parts(node.nodelist, fig, top=True)
        if fig.image is None and not fig.subfigures:
            self.report.warn("figure", "figure without convertible graphics (e.g. TikZ)")
        self._labelable = fig
        return fig

    def _collect_figure_parts(self, nodes: list, fig: ir.Figure, top: bool) -> None:
        """Walk a figure body, pulling out the parent image/caption/label and
        any ``subfigure`` environments / ``\\subfloat`` commands."""
        for child in nodes:
            if isinstance(child, LatexEnvironmentNode):
                if child.environmentname.rstrip("*") == "subfigure":
                    fig.subfigures.append(self._subfigure_from_env(child))
                else:
                    self._collect_figure_parts(child.nodelist, fig, top=False)
            elif isinstance(child, LatexGroupNode):
                self._collect_figure_parts(child.nodelist, fig, top=False)
            elif isinstance(child, LatexMacroNode):
                if child.macroname in ("subfloat", "subfigure"):
                    fig.subfigures.append(self._subfigure_from_macro(child))
                elif child.macroname == "includegraphics":
                    fig.image = _make_image(child)
                elif child.macroname == "caption":
                    fig.caption = self.inlines(_group_nodes(child))
                    fig.caption_numbered = not _has_star(child)
                elif child.macroname == "label" and fig.label is None:
                    fig.label = _chars_of(_group_nodes(child))

    def _subfigure_from_env(self, node: LatexEnvironmentNode) -> ir.SubFigure:
        sub = ir.SubFigure(image=None)
        for child in _walk_macros(node.nodelist):
            if child.macroname == "includegraphics":
                sub.image = _make_image(child)
            elif child.macroname == "caption":
                sub.caption = self.inlines(_group_nodes(child))
            elif child.macroname == "label":
                sub.label = _chars_of(_group_nodes(child))
        return sub

    def _subfigure_from_macro(self, node: LatexMacroNode) -> ir.SubFigure:
        # \subfloat[caption]{content}; content holds the \includegraphics.
        groups = [
            a for a in (node.nodeargd.argnlist if node.nodeargd else [])
            if isinstance(a, LatexGroupNode)
        ]
        caption = self._env_optional_title(node)
        sub = ir.SubFigure(image=None, caption=caption)
        if groups:
            for child in _walk_macros(groups[-1].nodelist):
                if child.macroname == "includegraphics":
                    sub.image = _make_image(child)
                elif child.macroname == "label":
                    sub.label = _chars_of(_group_nodes(child))
        return sub

    def _figure_from_graphics(self, node: LatexMacroNode) -> ir.Figure:
        return ir.Figure(image=_make_image(node), source=node.latex_verbatim())

    def _table_float(
        self, node: LatexEnvironmentNode, out: list[ir.Block], spanning: bool = False
    ) -> None:
        # Pull the float's own caption/label, then process the rest as blocks --
        # which descends \resizebox/\scalebox and minipage so nested tabulars (a
        # grid of sub-tables) survive instead of being dumped as raw LaTeX.
        caption: list[ir.Inline] | None = None
        caption_numbered = True
        label: str | None = None
        content: list = []
        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "caption":
                caption = self.inlines(_group_nodes(child))
                caption_numbered = not _has_star(child)
            elif isinstance(child, LatexMacroNode) and child.macroname == "label":
                label = _chars_of(_group_nodes(child))
            else:
                content.append(child)
        sub_blocks = self.blocks(content)
        tables = [b for b in sub_blocks if isinstance(b, ir.Table)]
        if not tables:
            self.report.warn("table", "table float without tabular")
            out.append(ir.RawPassthrough(node.latex_verbatim(), "table without tabular"))
            return
        # attach the float caption/label to the first table (for \ref); a plain
        # single-tabular float behaves exactly as before.
        tables[0].caption = caption
        tables[0].caption_numbered = caption_numbered
        tables[0].label = label
        tables[0].spanning = spanning
        self._labelable = tables[0]
        out.extend(sub_blocks)

    def _tabular(self, node: LatexEnvironmentNode) -> ir.Table:
        # column spec is the first mandatory group argument of the environment
        colspec, colwidths = _parse_colspec(_env_colspec(node))
        booktabs = "\\toprule" in node.latex_verbatim() or "\\midrule" in node.latex_verbatim()
        rows = self._tabular_rows(node.nodelist, len(colspec) or 1, colspec)
        return ir.Table(rows=rows, colspec=colspec, booktabs=booktabs, colwidths=colwidths)

    def _tabular_rows(self, nodes: list, ncols: int, colspec: list) -> list[ir.TableRow]:
        rows: list[ir.TableRow] = []
        cur_cells: list[list] = [[]]
        row_started = [False]
        row_shade: list[str | None] = [None]  # \rowcolor applies to the whole row
        # number of leading rows that form the (repeatable) header; None until a
        # header delimiter (\midrule / \endhead) is seen.
        header_end: list[int | None] = [None]

        def end_row() -> None:
            if row_started[0]:
                cells = []
                for ci, cell_nodes in enumerate(cur_cells):
                    align = colspec[ci] if ci < len(colspec) else "left"
                    cell = self._make_cell(cell_nodes, align)
                    if cell.shade is None:  # \cellcolor overrides the row colour
                        cell.shade = row_shade[0]
                    cells.append(cell)
                rows.append(ir.TableRow(cells))
            cur_cells.clear()
            cur_cells.append([])
            row_started[0] = False
            row_shade[0] = None

        for child in nodes:
            if isinstance(child, LatexSpecialsNode) and child.specials_chars == "&":
                cur_cells.append([])
                row_started[0] = True
                continue
            if isinstance(child, LatexMacroNode) and child.macroname == "rowcolor":
                row_shade[0] = self._color_of(child)
                continue
            if isinstance(child, LatexMacroNode) and child.macroname in ("\\", "tabularnewline"):
                end_row()
                continue
            if isinstance(child, LatexMacroNode) and child.macroname in (
                "midrule", "endhead", "endfirsthead",
            ):
                end_row()
                if header_end[0] is None:
                    header_end[0] = len(rows)
                continue
            if isinstance(child, LatexMacroNode) and child.macroname in ("cline", "cmidrule"):
                rng = _cmidrule_range(child)
                if rng is not None and rows:
                    _apply_partial_rule(rows[-1], rng)
                continue
            if isinstance(child, LatexMacroNode) and child.macroname in (
                "hline", "toprule", "bottomrule", "endfoot", "endlastfoot",
                "morecmidrules", "addlinespace",
            ):
                continue
            if isinstance(child, LatexCharsNode) and not child.chars.strip():
                cur_cells[-1].append(child)
                continue
            cur_cells[-1].append(child)
            row_started[0] = True
        end_row()

        if header_end[0]:
            for row in rows[: header_end[0]]:
                row.is_header = True
        return rows

    def _strip_cellcolor(self, nodes: list) -> tuple[str | None, list]:
        """Pull any ``\\cellcolor[model]{c}`` out of a node list; return (shade, rest)."""
        shade: str | None = None
        content: list = []
        for n in nodes:
            if isinstance(n, LatexMacroNode) and n.macroname == "cellcolor":
                shade = self._color_of(n) or shade
            else:
                content.append(n)
        return shade, content

    def _make_cell(self, cell_nodes: list, align) -> ir.TableCell:
        shade, cell_nodes = self._strip_cellcolor(cell_nodes)
        colspan, rowspan = 1, 1
        # Peel \multicolumn / \multirow wrappers. They nest in either order in
        # generated colour tables, e.g. \multicolumn{1}{c|}{\multirow{-2}{*}{X}};
        # loop so both the horizontal span (gridSpan) and vertical span (vMerge)
        # plus the innermost content are recovered instead of one being lost.
        peeled = True
        while peeled:
            peeled = False
            for m in cell_nodes:
                if not isinstance(m, LatexMacroNode):
                    continue
                groups = [
                    a for a in (m.nodeargd.argnlist if m.nodeargd else [])
                    if isinstance(a, LatexGroupNode)
                ]
                if m.macroname == "multicolumn" and len(groups) >= 3:
                    colspan = _int_or_default(_chars_of(groups[0].nodelist), 1)
                    cspec, _ = _parse_colspec(_chars_of(groups[1].nodelist))
                    align = cspec[0] if cspec else "center"
                    inner_shade, cell_nodes = self._strip_cellcolor(groups[2].nodelist)
                    shade = shade or inner_shade
                    peeled = True
                    break
                if m.macroname == "multirow" and len(groups) >= 2:
                    # \multirow{n}{width}{content}; the width is irrelevant and is
                    # often the bare ``*`` (\multirow{6}*{X}, only two groups), so
                    # take span from the first group and content from the last.
                    # A negative span (\multirow{-2}{*}{X}, generated tables anchor
                    # the content in the *bottom* row) can't drive a top-down
                    # w:vMerge, so we keep the content without merging.
                    span = _int_or_default(_chars_of(groups[0].nodelist), 1)
                    if span > 1:
                        rowspan = span
                    inner_shade, cell_nodes = self._strip_cellcolor(groups[-1].nodelist)
                    shade = shade or inner_shade
                    peeled = True
                    break
        return ir.TableCell(
            _flatten_stacked_tables(self.blocks(cell_nodes)),
            colspan=colspan,
            rowspan=rowspan,
            align=align,
            shade=shade,
        )

def _has_star(node: LatexMacroNode) -> bool:
    """True if a macro was invoked with a starred form (e.g. ``\\section*``)."""
    argd = node.nodeargd
    if not argd or not argd.argnlist:
        return False
    first = argd.argnlist[0]
    return first is not None and getattr(first, "chars", None) == "*"


def _int_or_default(value: str, default: int) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return default


def _inlines_to_text(inlines: list[ir.Inline]) -> str:
    out: list[str] = []
    for node in inlines:
        if isinstance(node, ir.Text):
            out.append(node.value)
        elif isinstance(node, ir.Emphasis | ir.Link | ir.Footnote | ir.Endnote):
            out.append(_inlines_to_text(node.inlines))
        elif isinstance(node, ir.Math):
            out.append(node.latex)
    return " ".join(" ".join(out).split())


def _walk_macros(nodes: list):
    for n in nodes:
        if isinstance(n, LatexMacroNode):
            yield n
        elif isinstance(n, LatexGroupNode):
            yield from _walk_macros(n.nodelist)
        elif isinstance(n, LatexEnvironmentNode):
            yield from _walk_macros(n.nodelist)


# --------------------------------------------------------------------------- #
# Free helpers
# --------------------------------------------------------------------------- #


def _normalize_ws(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


# Punctuation that should not be preceded by a space (e.g. a space inserted by
# \xspace before a colon).
_SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:!?)\]}])")


def _clean_inlines(nodes: list[ir.Inline], *, trim: bool = False) -> list[ir.Inline]:
    """Tidy a freshly built inline list.

    Merges adjacent Text runs (so spacing introduced by dropped/space-emitting
    macros like ``\\xspace`` collapses), squeezes repeated spaces, and removes a
    space sitting before closing punctuation. With ``trim`` (used at block
    level) it also strips leading/trailing whitespace of the paragraph.
    """
    merged: list[ir.Inline] = []
    for node in nodes:
        if isinstance(node, ir.Text) and merged and isinstance(merged[-1], ir.Text):
            merged[-1] = ir.Text(merged[-1].value + node.value)
        else:
            merged.append(node)
    for node in merged:
        if isinstance(node, ir.Text):
            value = re.sub(r" {2,}", " ", node.value)
            node.value = _SPACE_BEFORE_PUNCT.sub(r"\1", value)
    if trim:
        if merged and isinstance(merged[0], ir.Text):
            merged[0].value = merged[0].value.lstrip()
        if merged and isinstance(merged[-1], ir.Text):
            merged[-1].value = merged[-1].value.rstrip()
        merged = [n for n in merged if not (isinstance(n, ir.Text) and n.value == "")]
    return merged


def _is_display(node: LatexMathNode) -> bool:
    delims = getattr(node, "delimiters", ("$", "$"))
    return delims[0] in ("\\[", "$$")


def _strip_math_delims(verbatim: str, env: str) -> str:
    v = verbatim.strip()
    for op, cl in (("\\[", "\\]"), ("$$", "$$"), ("\\(", "\\)"), ("$", "$")):
        if v.startswith(op) and v.endswith(cl):
            return v[len(op) : len(v) - len(cl)].strip()
    if v.startswith("\\begin"):
        # \begin{env} ... \end{env}
        start = v.find("}")
        end = v.rfind("\\end")
        if start != -1 and end != -1:
            return v[start + 1 : end].strip()
    return v


_LABEL_TAG_RE = re.compile(r"\\(?:label|tag|nonumber|notag)\b\s*(?:\{[^{}]*\})?")


def _extract_label(latex: str) -> str | None:
    m = re.search(r"\\label\{([^}]*)\}", latex)
    return m.group(1) if m else None


def _env_colspec(node: LatexEnvironmentNode) -> str:
    # The column spec is the *last* mandatory group: plain tabular has just
    # {colspec}, but tabularx/tabulary carry a leading {width} we must skip.
    argd = node.nodeargd
    if argd and argd.argnlist:
        groups = [a for a in argd.argnlist if isinstance(a, LatexGroupNode)]
        if groups:
            verb = groups[-1].latex_verbatim().strip()
            if verb.startswith("{") and verb.endswith("}"):
                return verb[1:-1]  # keep raw text so p{3cm} braces survive
            return _chars_of(groups[-1].nodelist)
        for a in argd.argnlist:
            if isinstance(a, LatexCharsNode):
                return a.chars
    return ""


_CMIDRULE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _cmidrule_range(node: LatexMacroNode) -> tuple[int, int] | None:
    """The 1-based ``{a-b}`` column range of a ``\\cmidrule``/``\\cline``.

    Tolerates the ``\\cmidrule(lr){a-b}`` trim form by scanning the verbatim.
    """
    text = _chars_of(_group_nodes(node)) or node.latex_verbatim()
    m = _CMIDRULE_RE.search(text)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if a <= b else (b, a)


def _apply_partial_rule(row: ir.TableRow, rng: tuple[int, int]) -> None:
    """Set ``border_bottom`` on the cells of ``row`` overlapping 1-based ``rng``."""
    a, b = rng
    col = 1  # 1-based start column of the current cell
    for cell in row.cells:
        cell_end = col + cell.colspan - 1
        if col <= b and cell_end >= a:  # overlaps [a, b]
            cell.border_bottom = True
        col = cell_end + 1


def _braced_group(spec: str, start: int) -> tuple[str, int]:
    """Read a ``{...}`` group beginning at ``spec[start] == '{'``; return (body, end)."""
    depth, i = 0, start
    while i < len(spec):
        if spec[i] == "{":
            depth += 1
        elif spec[i] == "}":
            depth -= 1
            if depth == 0:
                return spec[start + 1:i], i
        i += 1
    return spec[start + 1:], len(spec)


_COL_PROCESSOR_ALIGN = {
    "centering": "center", "raggedright": "left", "raggedleft": "right",
}


def _parse_colspec(spec: str) -> tuple[list, list[float | None]]:
    """Parse a column spec into (alignments, per-column EMU widths or None)."""
    aligns: list = []
    widths: list[float | None] = []
    pending_align: str | None = None  # set by a >{...} column processor
    i = 0
    while i < len(spec):
        c = spec[i]
        if c == ">" and i + 1 < len(spec) and spec[i + 1] == "{":
            body, i = _braced_group(spec, i + 1)
            for key, al in _COL_PROCESSOR_ALIGN.items():
                if f"\\{key}" in body:
                    pending_align = al
            i += 1
            continue
        if c in "lcr":
            aligns.append(pending_align or {"l": "left", "c": "center", "r": "right"}[c])
            widths.append(None)
            pending_align = None
        elif c == "X":
            # tabularx flexible column: a paragraph column that fills the
            # remaining width. Count it (so cells line up) with an auto width;
            # a >{\raggedright}X etc. supplies the alignment.
            aligns.append(pending_align or "left")
            widths.append(None)
            pending_align = None
        elif c in "LCRJ":
            # tabulary auto-width columns (L/C/R = left/centre/right, J = justify)
            aligns.append(
                pending_align or {"L": "left", "C": "center", "R": "right", "J": "left"}[c]
            )
            widths.append(None)
            pending_align = None
        elif c in "pmb" and i + 1 < len(spec) and spec[i + 1] == "{":
            aligns.append(pending_align or "left")
            pending_align = None
            body, i = _braced_group(spec, i + 1)
            widths.append(_length_to_emu(body))
        # ignore |, @{...}, etc.
        i += 1
    return aligns, widths


#: LaTeX length units -> EMU (914400 per inch). bp/pt approximated as points.
_EMU_PER_INCH = 914400
_UNIT_EMU = {
    "in": _EMU_PER_INCH, "pt": _EMU_PER_INCH / 72.27, "bp": _EMU_PER_INCH / 72.0,
    "cm": _EMU_PER_INCH / 2.54, "mm": _EMU_PER_INCH / 25.4, "px": _EMU_PER_INCH / 96.0,
    "em": _EMU_PER_INCH / 72.27 * 10, "ex": _EMU_PER_INCH / 72.27 * 4.3,
}
_LEN_RE = re.compile(r"^\s*([-\d.]+)\s*([a-zA-Z]*)")


def _length_to_emu(value: str) -> float | None:
    """Convert a LaTeX length (``2.5cm``, ``300pt``) to EMU; relative widths skip."""
    value = value.strip()
    if "\\" in value:
        # relative to \linewidth/\textwidth/\columnwidth -- let the backend fit
        return None
    m = _LEN_RE.match(value)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "pt").lower()
    if unit not in _UNIT_EMU:
        return None
    return num * _UNIT_EMU[unit]


def _parse_graphics_options(opts: str) -> dict[str, str]:
    """Parse the ``[key=val,key=val,flag]`` option list of \\includegraphics."""
    out: dict[str, str] = {}
    depth = 0
    buf: list[str] = []
    parts: list[str] = []
    for ch in opts:  # split on commas not inside braces/brackets
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    for part in parts:
        if "=" in part:
            key, _, val = part.partition("=")
            out[key.strip().lower()] = val.strip()
        elif part.strip():
            out[part.strip().lower()] = ""
    return out


def _make_image(node: LatexMacroNode) -> ir.Image:
    path = _chars_of(_group_nodes(node))
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    image = ir.Image(path=path, original_format=ext, alt=path)
    opts = _graphics_option_text(node)
    if opts:
        parsed = _parse_graphics_options(opts)
        if "width" in parsed:
            image.width = _length_to_emu(parsed["width"])
        if "height" in parsed:
            image.height = _length_to_emu(parsed["height"])
        if "scale" in parsed:
            try:
                image.scale = float(parsed["scale"])
            except ValueError:
                pass
        if "angle" in parsed:
            try:
                image.angle = float(parsed["angle"])
            except ValueError:
                pass
        if "clip" in parsed:
            image.clip = True
        if "trim" in parsed:
            trims = [_length_to_emu(v) for v in parsed["trim"].split()]
            if len(trims) == 4 and all(t is not None for t in trims):
                image.trim = [t for t in trims if t is not None]
    return image


def _graphics_option_text(node: LatexMacroNode) -> str:
    """The raw ``[...]`` optional-argument text of \\includegraphics, if any.

    Uses verbatim text, not ``_chars_of``: the latter drops macro tokens, so
    ``width=0.5\\linewidth`` would collapse to ``width=0.5`` and be misread as
    0.5pt instead of a relative width (which must fall back to fit-to-column).
    """
    for a in node.nodeargd.argnlist if node.nodeargd else []:
        if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
            verb = a.latex_verbatim().strip()
            if verb.startswith("[") and verb.endswith("]"):
                return verb[1:-1]
            return _chars_of(a.nodelist)
    return ""


# Text-mode accents via combining characters.
_ACCENT_COMBINING = {
    "'": "́", "`": "̀", "^": "̂", '"': "̈",
    "~": "̃", "=": "̄", ".": "̇", "v": "̌",
    "u": "̆", "c": "̧", "H": "̋", "r": "̊",
}


def _accent_char(name: str) -> str | None:
    return _ACCENT_COMBINING.get(name)


def _apply_text_accent(name: str, base: str) -> str:
    import unicodedata

    comb = _ACCENT_COMBINING.get(name, "")
    if not base:
        return comb
    return unicodedata.normalize("NFC", base[0] + comb + base[1:])


# User-defined tcolorbox callout environments -> rendered as set-off Quote blocks.
# \newtcolorbox[init opts]{name}{style}, \DeclareTColorBox{name}{spec}{style},
# \newtcbox / \NewTColorBox / \ProvideTColorBox variants.
_NEWTCOLORBOX_RE = re.compile(
    r"\\(?:new|renew|provide|Declare|New|Renew|Provide)?"
    r"(?:tcolorbox|TColorBox|tcbox)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)


def _collect_tcolorbox_envs(source: str) -> set[str]:
    """Names of user ``\\newtcolorbox`` environments (rendered as Quote blocks)."""
    return {m.group(1).strip() for m in _NEWTCOLORBOX_RE.finditer(source) if m.group(1).strip()}


# User-defined mdframed callout environments: \newmdenv[opts]{name},
# \newmdtheoremenv[opts]{name}{caption}, \surroundwithmdframed[opts]{name}. The
# option list may span lines (re.DOTALL). Rendered as set-off Quote blocks like
# the other boxed environments. (\mdfdefinestyle defines a *style*, not an env,
# so it is deliberately not matched.)
_NEWMDENV_RE = re.compile(
    r"\\(?:newmdenv|newmdtheoremenv|surroundwithmdframed)\s*"
    r"(?:\[([^\]]*)\])?\s*\{([^}]+)\}",
    re.DOTALL,
)
_MDOPT_RE = re.compile(r"(backgroundcolor|linecolor)\s*=\s*([A-Za-z][\w!.]*)")


def _collect_mdframed_envs(source: str) -> dict[str, tuple[str | None, str | None]]:
    """Map each user ``\\newmdenv`` (mdframed) environment name to its
    ``(backgroundcolor, linecolor)`` colour names, for a coloured callout box."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for m in _NEWMDENV_RE.finditer(source):
        name = m.group(2).strip()
        if not name:
            continue
        opts = dict(_MDOPT_RE.findall(m.group(1) or ""))
        out[name] = (opts.get("backgroundcolor"), opts.get("linecolor"))
    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


# \newtheorem{env}{Display}, \newtheorem{env}[shared]{Display}{,
# \newtheorem{env}{Display}[parent], and the unnumbered \newtheorem*{env}{Display}.
# The display group may itself wrap the title in a font command -- real preambles
# write \newtheorem{THM}{\textbf{Theorem}} -- so allow one level of nested braces
# and clean the result below.
_NEWTHEOREM_RE = re.compile(
    r"\\newtheorem(\*?)\s*\{([^}]*)\}\s*(?:\[([^\]]*)\])?\s*"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)
# Font/format declarations to peel off a \newtheorem display title.
_TITLE_DECL_RE = re.compile(
    r"\\(?:textbf|textit|textrm|textsf|textsc|textnormal|texttt|emph|mathrm|"
    r"bfseries|itshape|scshape|sffamily|mdseries|normalfont|upshape|rmfamily)\b"
)


def _clean_theorem_title(raw: str) -> str:
    """Strip wrapping font commands/braces from a ``\\newtheorem`` display title."""
    title = _TITLE_DECL_RE.sub("", raw)
    title = title.replace("{", "").replace("}", "")
    return _normalize_ws(title).strip()


def _collect_newtheorems(
    source: str,
) -> tuple[dict[str, str], set[str], dict[str, str]]:
    """Map user ``\\newtheorem`` environment names to their display title.

    Returns ``(envs, unnumbered, shared)`` where ``unnumbered`` holds the names
    defined with the starred ``\\newtheorem*`` (no counter) and ``shared`` maps an
    environment to the environment whose counter it shares
    (``\\newtheorem{LEM}[THM]{Lemma}`` -> ``{"LEM": "THM"}``).
    """
    envs: dict[str, str] = {}
    unnumbered: set[str] = set()
    shared: dict[str, str] = {}
    for m in _NEWTHEOREM_RE.finditer(source):
        name = m.group(2).strip()
        display = _clean_theorem_title(m.group(4))
        if name and display:
            envs[name] = display
            if m.group(3):  # \newtheorem{env}[shared]{Display}: share a counter
                shared[name] = m.group(3).strip()
            if m.group(1):  # \newtheorem* -> unnumbered
                unnumbered.add(name)
    return envs, unnumbered, shared


def _resolve_theorem_counters(
    envs: dict[str, str], shared: dict[str, str]
) -> dict[str, str]:
    """Counter *display name* each theorem env numbers against.

    An env that shares another's counter (``LEM[THM]``) numbers against that
    env's display title, so they share one running sequence; otherwise it
    numbers against its own title.
    """
    counters: dict[str, str] = {}
    for name, display in envs.items():
        root, seen = name, {name}
        while root in shared and shared[root] not in seen:
            root = shared[root]
            seen.add(root)
        counters[name] = envs.get(root, display)
    return counters


def _build_context(extra_theorem_envs: tuple[str, ...] = ()):
    """Augment pylatexenc's default DB with arg signatures it lacks."""
    ctx = get_default_latex_context_db()
    ctx.add_context_category(
        "tex2word",
        macros=[
            # sectioning: \cmd*[short]{title} -- pylatexenc's defaults omit the
            # run-in \paragraph/\subparagraph, dropping their titles into the body
            MacroSpec("section", "*[{"),
            MacroSpec("subsection", "*[{"),
            MacroSpec("subsubsection", "*[{"),
            MacroSpec("paragraph", "*[{"),
            MacroSpec("subparagraph", "*[{"),
            MacroSpec("chapter", "*[{"),
            MacroSpec("part", "*[{"),
            MacroSpec("caption", "*[{"),
            # layout / front-matter commands: consume their args so they don't
            # leak as text (e.g. full-page cover \AddToShipoutPicture{\put...}).
            MacroSpec("AddToShipoutPicture", "*{"),
            MacroSpec("newcounter", "{["),
            MacroSpec("addtocounter", "{{"),
            MacroSpec("refstepcounter", "{"),
            MacroSpec("stepcounter", "{"),
            MacroSpec("textsuperscript", "{"),
            MacroSpec("textsubscript", "{"),
            MacroSpec("sout", "{"),
            MacroSpec("uline", "{"),
            MacroSpec("uuline", "{"),
            MacroSpec("xout", "{"),
            MacroSpec("st", "{"),
            MacroSpec("hl", "{"),
            MacroSpec("href", "{{"),
            MacroSpec("url", "{"),
            MacroSpec("hyperref", "[{"),
            MacroSpec("multicolumn", "{{{"),
            MacroSpec("multirow", "{{{"),
            MacroSpec("citep", "[[{"),
            MacroSpec("citet", "[[{"),
            MacroSpec("Citep", "[[{"),
            MacroSpec("Citet", "[[{"),
            MacroSpec("citealp", "[[{"),
            MacroSpec("citealt", "[[{"),
            MacroSpec("citeauthor", "[[{"),
            MacroSpec("Citeauthor", "[[{"),
            MacroSpec("citeyear", "[[{"),
            MacroSpec("citeyearpar", "[[{"),
            MacroSpec("citenum", "[[{"),
            MacroSpec("smartcite", "[[{"),
            MacroSpec("parencite", "[[{"),
            MacroSpec("textcite", "[[{"),
            MacroSpec("autocite", "[[{"),
            MacroSpec("Autocite", "[[{"),
            MacroSpec("Parencite", "[[{"),
            MacroSpec("Textcite", "[[{"),
            MacroSpec("Cite", "[[{"),
            MacroSpec("IEEEPARstart", "{{"),
            MacroSpec("autoref", "{"),
            MacroSpec("cref", "{"),
            MacroSpec("Cref", "{"),
            MacroSpec("crefrange", "{{"),
            MacroSpec("Crefrange", "{{"),
            MacroSpec("eqref", "{"),
            MacroSpec("hypersetup", "{"),
            MacroSpec("graphicspath", "{"),
            MacroSpec("definecolor", "{{{"),
            MacroSpec("colorlet", "{{"),
            MacroSpec("textcolor", "[{{"),
            MacroSpec("colorbox", "[{{"),
            MacroSpec("fcolorbox", "[{{{"),
            MacroSpec("color", "[{"),
            MacroSpec("cellcolor", "[{"),
            MacroSpec("rowcolor", "[{"),
            MacroSpec("pagenumbering", "{"),
            MacroSpec("keywords", "{"),
            MacroSpec("IEEEkeywords", "{"),
            MacroSpec("endnote", "{"),
            MacroSpec("index", "{"),
            MacroSpec("enquote", "*{"),
            MacroSpec("textquote", "*[[{"),
            MacroSpec("foreignquote", "*{{"),
            MacroSpec("hyphenquote", "*{{"),
            MacroSpec("blockquote", "*[[{"),
            MacroSpec("blockcquote", "*[[{{"),
            MacroSpec("foreignblockquote", "*{[[{"),
            MacroSpec("epigraph", "{{"),
            MacroSpec("thanks", "{"),
            MacroSpec("marginpar", "[{"),
            MacroSpec("sidenote", "[{"),
            MacroSpec("footnotemark", "["),
            MacroSpec("footnotetext", "[{"),
            MacroSpec("nicefrac", "{{"),
            MacroSpec("sfrac", "{{"),
            MacroSpec("numrange", "[{{"),
            MacroSpec("SIrange", "[{{{"),
            MacroSpec("qtyrange", "[{{{"),
            MacroSpec("numlist", "[{"),
            MacroSpec("SIlist", "[{{"),
            MacroSpec("qtylist", "[{{"),
            MacroSpec("institute", "{"),
            MacroSpec("affiliation", "[{"),
            MacroSpec("affil", "[{"),
            MacroSpec("address", "{"),
            MacroSpec("email", "{"),
            MacroSpec("orcid", "{"),
            MacroSpec("inst", "{"),
            MacroSpec("IEEEauthorrefmark", "{"),
            MacroSpec("IEEEauthorblockN", "{"),
            MacroSpec("IEEEauthorblockA", "{"),
            # review annotations -> Word comments (todonotes / changes)
            MacroSpec("todo", "[{"),
            MacroSpec("comment", "[{"),
            MacroSpec("note", "[{"),
            MacroSpec("bibitem", "[{"),
            MacroSpec("bibliography", "{"),
            MacroSpec("bibliographystyle", "{"),
            MacroSpec("addbibresource", "[{"),
            MacroSpec("printbibliography", "["),
            MacroSpec("setitemize", "{"),
            MacroSpec("setenumerate", "{"),
            MacroSpec("hyphenation", "{"),
            MacroSpec("cmidrule", "{"),
            MacroSpec("cline", "{"),
            MacroSpec("resizebox", "{{{"),
            MacroSpec("scalebox", "{{"),
            MacroSpec("setlength", "{{"),
            MacroSpec("phantom", "{"),
            MacroSpec("hphantom", "{"),
            MacroSpec("vphantom", "{"),
            MacroSpec("rule", "[{{"),
            MacroSpec("mbox", "{"),
            MacroSpec("fbox", "{"),
            MacroSpec("framebox", "[[{"),
            MacroSpec("makebox", "[[{"),
            MacroSpec("raisebox", "{[[{"),
            MacroSpec("fontsize", "{{"),
            MacroSpec("fontfamily", "{"),
            MacroSpec("si", "[{"),
            MacroSpec("unit", "[{"),
            MacroSpec("num", "[{"),
            MacroSpec("ang", "[{"),
            MacroSpec("SI", "[{{"),
            MacroSpec("qty", "[{{"),
            MacroSpec("newacronym", "[{{{"),
            MacroSpec("newglossaryentry", "{{"),
            MacroSpec("nocite", "{"),
            MacroSpec("lstinline", "[{"),
            MacroSpec("mintinline", "[{{"),
            MacroSpec("ensuremath", "{"),
            MacroSpec("ding", "{"),
            MacroSpec("shortstack", "[{"),
            # ACM affiliation sub-fields: consume the {…} so it isn't body text.
            MacroSpec("institution", "{"),
            MacroSpec("department", "{"),
            MacroSpec("city", "{"),
            MacroSpec("state", "{"),
            MacroSpec("country", "{"),
            MacroSpec("postcode", "{"),
            MacroSpec("streetaddress", "{"),
            MacroSpec("position", "{"),
            MacroSpec("authornote", "{"),
            MacroSpec("texorpdfstring", "{{"),
            MacroSpec("labelcref", "{"),
            MacroSpec("nameref", "{"),
            MacroSpec("Nameref", "{"),
            MacroSpec("title", "[{"),  # \title[running head]{full title}
            MacroSpec("markboth", "{{"),
            MacroSpec("markright", "{"),
            MacroSpec("runninghead", "[{"),
            MacroSpec("shorttitle", "{"),
            *(MacroSpec(m, "[{") for m in (
                "gls", "Gls", "glspl", "Glspl",
                "acrshort", "Acrshort", "acrshortpl", "Acrshortpl",
                "acrlong", "Acrlong", "acrlongpl", "Acrlongpl",
                "acrfull", "Acrfull", "acrfullpl", "Acrfullpl",
                "glsentryshort", "glsentrylong",
            )),
            *(MacroSpec(m, "{") for m in (  # acronym package references
                "ac", "Ac", "acp", "Acp", "acs", "Acs", "acsp", "Acsp",
                "acl", "Acl", "aclp", "Aclp", "acf", "Acf", "acfp", "Acfp",
            )),
            MacroSpec("acro", "{[{"),
            MacroSpec("acrodef", "{[{"),
            *(MacroSpec(m, "[") for m in _PRINTGLOSSARY_MACROS),
            MacroSpec("pagestyle", "{"),
            MacroSpec("thispagestyle", "{"),
            MacroSpec("settopmatter", "{"),
            MacroSpec("vspace", "*{"),
            MacroSpec("hspace", "*{"),
            MacroSpec("subfloat", "[{"),
            MacroSpec("subfigure", "[{"),
        ],
        environments=[
            EnvironmentSpec(name, "[")
            for name in (*_THEOREM_ENVS, "proof", *extra_theorem_envs)
        ] + [EnvironmentSpec("subfigure", "[{")] + [EnvironmentSpec("minipage", "[{")] + [
            EnvironmentSpec(name, "[")
            for name in ("algorithmic", "algorithmicx", "algpseudocode", "algpseudocodex")
        ] + [
            # tabularx/tabulary carry a leading {width}; supertabular/xtabular take
            # just the {colspec}. Declaring the args keeps them out of the body.
            EnvironmentSpec("tabularx", "{{"), EnvironmentSpec("tabulary", "{{"),
            EnvironmentSpec("supertabular", "{"), EnvironmentSpec("xtabular", "{"),
            EnvironmentSpec("mpsupertabular", "{"),
            # longtable: \begin{longtable}[pos]{colspec} (not in pylatexenc's
            # defaults). Declaring the args keeps the colspec out of the body,
            # where it would otherwise be parsed as the first table row.
            EnvironmentSpec("longtable", "[{"),
            # wrapfig: \begin{wrapfigure}[lines]{placement}{width} -- consume the
            # placement/width args so they don't leak into the float body.
            EnvironmentSpec("wrapfigure", "[{{"), EnvironmentSpec("wraptable", "[{{"),
            # boxed environments with an optional [options] argument
            EnvironmentSpec("mdframed", "["), EnvironmentSpec("tcolorbox", "["),
            EnvironmentSpec("leftbar", "["),
        ],
        prepend=True,
    )
    return ctx


def _split_document(source: str) -> tuple[str, str]:
    """Return (body, preamble).

    Only the content between ``\\begin{document}`` and ``\\end{document}`` is
    parsed: preamble macro/environment definitions (``\\newenvironment``,
    ``\\AtBeginDocument``, ...) routinely break a static parser's brace and
    \\begin/\\end matching. If there is no ``\\begin{document}`` the whole input
    is treated as body (used for fragments and tests).
    """
    begin = source.find(r"\begin{document}")
    if begin == -1:
        return source, ""
    preamble = source[:begin]
    body_start = begin + len(r"\begin{document}")
    end = source.rfind(r"\end{document}")
    body = source[body_start : end if end != -1 else len(source)]
    return body, preamble


def _running_head_from_preamble(preamble: str) -> str | None:
    """Recover a running head declared in the preamble (best effort, plain text)."""
    m = re.search(r"\\title\s*\[([^\]]*)\]", preamble)  # \title[short]{long}
    if m:
        return _normalize_ws(m.group(1)).strip() or None
    for macro in ("runninghead", "shorttitle", "markright"):
        content = _braced_content(preamble, macro)
        if content:
            return _normalize_ws(content).strip() or None
    mb = re.search(r"\\markboth\s*\{[^{}]*\}\s*\{([^{}]*)\}", preamble)  # \markboth{l}{r}
    if mb:
        return _normalize_ws(mb.group(1)).strip() or None
    return None


def _braced_content(source: str, name: str) -> str | None:
    """Extract the first ``\\name{...}`` argument from ``source`` (brace-aware).

    An optional ``[...]`` before the mandatory group (e.g. ``\\title[short]{…}``)
    is skipped so the mandatory argument is still found.
    """
    m = re.search(r"\\" + name + r"\s*(?:\[[^\]]*\])?\s*\{", source)
    if not m:
        return None
    depth = 0
    start = m.end() - 1
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : i]
    return None


_DEFINECOLOR_RE = re.compile(
    r"\\definecolor\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{([^}]*)\}"
)
_COLORLET_RE = re.compile(r"\\colorlet\s*\{([^}]*)\}\s*\{([^}]*)\}")


def _collect_color_defs(source: str, table: ColorTable) -> None:
    for m in _DEFINECOLOR_RE.finditer(source):
        table.define(m.group(1), m.group(2), m.group(3))
    for m in _COLORLET_RE.finditer(source):
        table.define_alias(m.group(1), m.group(2))


# glossaries acronym references; capitalised (\Gls) and plural (\glspl) variants
# are matched case-insensitively / by the "pl" suffix in _acronym_text.
_GLS_MACROS = {
    "gls", "glspl", "acrshort", "acrshortpl", "acrlong", "acrlongpl",
    "acrfull", "acrfullpl", "glsentryshort", "glsentrylong",
}
# acronym package: \ac/\acs/\acl/\acf (+ plural -p, + capitalised) map onto the
# glossaries expansion in _acronym_text.
# glossary/acronym list output -> a description list of the collected entries.
_PRINTGLOSSARY_MACROS = {
    "printglossaries", "printglossary", "printnoidxglossaries", "printnoidxglossary",
    "printacronyms", "printabbreviations",
}
_AC_TO_GLS = {
    "ac": "gls", "acp": "glspl",
    "acs": "acrshort", "acsp": "acrshortpl",
    "acl": "acrlong", "aclp": "acrlongpl",
    "acf": "acrfull", "acfp": "acrfullpl",
}
_NEWACRONYM_RE = re.compile(
    r"\\newacronym\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{([^}]*)\}"
)
# acronym package: \acro{KEY}[short]{long} (or \acrodef{KEY}[short]{long});
# the optional [short] overrides the displayed abbreviation (default: the key).
_ACRO_RE = re.compile(
    r"\\acro(?:def)?\s*\{([^}]*)\}\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}"
)


def _collect_acronyms(source: str, acronyms: dict[str, tuple[str, str]]) -> None:
    for m in _NEWACRONYM_RE.finditer(source):
        acronyms[m.group(1).strip()] = (m.group(2).strip(), m.group(3).strip())
    for m in _ACRO_RE.finditer(source):  # acronym package \acro/\acrodef
        key = m.group(1).strip()
        short = (m.group(2) or key).strip()
        acronyms.setdefault(key, (short, m.group(3).strip()))


_NEWGLOSSARYENTRY_RE = re.compile(r"\\newglossaryentry\s*\{([^}]*)\}\s*\{")
# name={...} | name=word inside a \newglossaryentry option list
_GLS_NAME_RE = re.compile(r"\bname\s*=\s*(?:\{([^{}]*)\}|([^,}]+))")


def _collect_glossary_entries(source: str, glossary: dict[str, str]) -> None:
    """Register \\newglossaryentry{key}{name=…, description=…} term names.

    Only the ``name`` (the display text \\gls prints) is needed; the option
    list is brace-balanced so a ``description={…}`` with commas is skipped over.
    """
    for m in _NEWGLOSSARYENTRY_RE.finditer(source):
        key = m.group(1).strip()
        i = m.end()  # just past the opening "{" of the options group
        depth, n = 1, len(source)
        j = i
        while j < n and depth:
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
            j += 1
        opts = source[i : j - 1]
        nm = _GLS_NAME_RE.search(opts)
        if nm:
            glossary[key] = (nm.group(1) or nm.group(2) or "").strip()


_BOOK_CLASS_RE = re.compile(
    r"\\documentclass(?:\[[^\]]*\])?\{(book|report|memoir|scrbook|scrreprt)\}"
)


def _is_book_class(source: str) -> bool:
    """True for a book/report-style document (top sectioning level is \\chapter)."""
    return bool(_BOOK_CLASS_RE.search(source)) or bool(re.search(r"\\chapter\b", source))


_DOCCLASS_OPTS_RE = re.compile(r"\\documentclass\s*\[([^\]]*)\]")
# \begin{multicols}{N} / \begin{multicols*}{N} (multicol package)
_MULTICOLS_RE = re.compile(r"\\begin\{multicols\*?\}\s*\{\s*(\d+)\s*\}")


def _detect_columns(source: str) -> int:
    """Body column count from the class options / `\\twocolumn` / `multicols`.

    ``\\documentclass[twocolumn]`` (or a later ``\\twocolumn``) -> 2; a
    ``multicols`` environment's ``{N}`` wins if larger. ``\\onecolumn`` after a
    ``\\twocolumn`` is not modelled -- the max column count seen is used.
    """
    cols = 1
    m = _DOCCLASS_OPTS_RE.search(source)
    if m and "twocolumn" in [o.strip() for o in m.group(1).split(",")]:
        cols = 2
    if re.search(r"\\twocolumn\b", source):
        cols = max(cols, 2)
    for mc in _MULTICOLS_RE.finditer(source):
        cols = max(cols, int(mc.group(1)))
    return cols


def parse_document(
    source: str, base_dir: str = ".", csl_path: str | None = None
) -> tuple[ir.Document, ConversionReport]:
    """Parse LaTeX ``source`` into an IR :class:`~tex2word.ir.Document`.

    ``csl_path`` is an optional ``.csl`` style; when set (and ``citeproc-py`` is
    installed) citations and the reference list are formatted by the real CSL
    engine instead of the built-in heuristic.
    """
    report = ConversionReport()
    expanded = replace_inline_tikz(expand_macros(preprocess(source, base_dir), base_dir))
    body, preamble = _split_document(expanded)
    # \newtheorem declarations may live in a \usepackage'd local .sty (e.g. a
    # paper's MyPreamble.sty), which macro expansion harvests but doesn't inline;
    # scan those sources too so the theorem environments are recognised.
    theorem_src = expanded + "\n" + local_package_sources(source, base_dir)
    custom_theorems, unnumbered_theorems, shared_counters = _collect_newtheorems(theorem_src)
    ctx = _build_context(tuple(custom_theorems))
    walker = LatexWalker(body, latex_context=ctx, tolerant_parsing=True)
    nodes, _, _ = walker.get_latex_nodes()

    builder = _Builder(report)
    builder.theorem_envs.update(custom_theorems)
    builder.unnumbered_theorems = unnumbered_theorems
    builder.theorem_counters = _resolve_theorem_counters(custom_theorems, shared_counters)
    builder.box_envs = _collect_tcolorbox_envs(theorem_src)  # \newtcolorbox callouts
    builder.box_styles = _collect_mdframed_envs(theorem_src)  # \newmdenv callouts (+colours)
    builder.box_envs |= set(builder.box_styles)
    builder.book_mode = _is_book_class(expanded)
    _collect_color_defs(expanded, builder.colors)  # \definecolor/\colorlet (preamble + body)
    _collect_acronyms(expanded, builder.acronyms)   # \newacronym (preamble + body)
    _collect_glossary_entries(expanded, builder.glossary)  # \newglossaryentry terms
    blocks = builder.blocks(nodes)
    doc = ir.Document(blocks=blocks, meta=builder.meta, book=builder.book_mode)

    _fill_meta_from_preamble(doc, preamble, ctx, report)
    _collect_bib_resources(preamble, builder)  # biblatex \addbibresource (preamble)
    _detect_bib_style(preamble, builder)        # biblatex/natbib author-year option
    if doc.meta.language is None:
        doc.meta.language = _detect_language(preamble)  # babel/polyglossia -> BCP-47
    _detect_fonts(doc, preamble)  # fontspec/xeCJK \setmainfont / \setCJK*font
    doc.meta.columns = _detect_columns(expanded)  # twocolumn / \twocolumn / multicols
    _resolve_bibliography(doc, builder, base_dir, report, csl_path)
    return doc, report


_BABEL_LANG = {
    "english": "en-US", "american": "en-US", "usenglish": "en-US", "usenglish ": "en-US",
    "british": "en-GB", "ukenglish": "en-GB", "australian": "en-AU", "canadian": "en-CA",
    "ngerman": "de-DE", "german": "de-DE", "austrian": "de-AT", "naustrian": "de-AT",
    "french": "fr-FR", "francais": "fr-FR", "canadien": "fr-CA",
    "spanish": "es-ES", "italian": "it-IT", "portuguese": "pt-PT", "portuges": "pt-PT",
    "brazil": "pt-BR", "brazilian": "pt-BR", "dutch": "nl-NL", "russian": "ru-RU",
    "polish": "pl-PL", "swedish": "sv-SE", "danish": "da-DK", "norsk": "nb-NO",
    "finnish": "fi-FI", "czech": "cs-CZ", "greek": "el-GR", "turkish": "tr-TR",
    "japanese": "ja-JP", "chinese": "zh-CN",
}


def _detect_fonts(doc: ir.Document, preamble: str) -> None:
    """Pick up XeLaTeX/fontspec + xeCJK font choices from the preamble.

    ``\\setmainfont{Times New Roman}`` -> the Latin (ascii/hAnsi) default;
    ``\\setCJKmainfont{SimSun}`` -> the East-Asian (eastAsia) default so Word
    renders CJK text in that font; ``\\setCJKsansfont`` -> headings; and
    ``\\setCJKmonofont`` -> code. The optional ``[options]`` form is tolerated.
    The name is stored verbatim (it must match a font installed on the machine
    that opens the .docx)."""

    def _font(cmd: str) -> str | None:
        m = re.search(r"\\" + cmd + r"\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", preamble)
        return m.group(1).strip() if m and m.group(1).strip() else None

    main = _font("setmainfont")
    cjk_main = _font("setCJKmainfont")
    cjk_sans = _font("setCJKsansfont")
    cjk_mono = _font("setCJKmonofont")
    if main:
        doc.meta.main_font = main
    if cjk_main:
        doc.meta.cjk_main_font = cjk_main
    if cjk_sans:
        doc.meta.cjk_sans_font = cjk_sans
    if cjk_mono:
        doc.meta.cjk_mono_font = cjk_mono


def _detect_language(preamble: str) -> str | None:
    """The main document language as a BCP-47 code from babel/polyglossia, or None."""
    # polyglossia: \setmainlanguage{...} / \setdefaultlanguage{...}
    m = re.search(r"\\set(?:main|default)language\{([^}]*)\}", preamble)
    if m and m.group(1).strip().lower() in _BABEL_LANG:
        return _BABEL_LANG[m.group(1).strip().lower()]
    # babel: \usepackage[...,lang]{babel} (main=lang wins, else the last known one)
    m = re.search(r"\\usepackage\[([^\]]*)\]\{babel\}", preamble)
    if m:
        opts = [o.strip().lower() for o in m.group(1).split(",")]
        main = next((o.split("=", 1)[1] for o in opts if o.startswith("main=")), None)
        if main and main in _BABEL_LANG:
            return _BABEL_LANG[main]
        known = [o for o in opts if o in _BABEL_LANG]
        if known:
            return _BABEL_LANG[known[-1]]  # babel's main language is the last option
    # \documentclass[...,lang,...]{...}
    m = re.search(r"\\documentclass\[([^\]]*)\]", preamble)
    if m:
        known = [o.strip().lower() for o in m.group(1).split(",")
                 if o.strip().lower() in _BABEL_LANG]
        if known:
            return _BABEL_LANG[known[-1]]
    return None


def _detect_bib_style(preamble: str, builder: _Builder) -> None:
    """Pick up the citation style from the biblatex/natbib package options when no
    ``\\bibliographystyle`` set it (so author-year biblatex/natbib renders right)."""
    if builder.bibstyle_set:
        return
    _AY = ("authoryear", "apa", "chicago", "harvard", "mla", "author-year")
    m = re.search(r"\\usepackage\[([^\]]*)\]\{biblatex\}", preamble)
    if m:
        opt = re.search(r"\bstyle\s*=\s*([A-Za-z0-9\-]+)", m.group(1))
        if opt:
            s = opt.group(1).lower()
            if any(a in s for a in _AY):
                builder.bib_style = "author-year"
            elif "numeric" in s or "ieee" in s:
                builder.bib_style = "numeric"
    nb = re.search(r"\\usepackage\[([^\]]*)\]\{natbib\}", preamble)
    if nb:
        nopt = nb.group(1).lower()
        if re.search(r"\bnumbers\b", nopt):
            builder.bib_style = "numeric"
        elif re.search(r"\bauthoryear\b", nopt):
            builder.bib_style = "author-year"


def _collect_bib_resources(preamble: str, builder: _Builder) -> None:
    """Pick up biblatex ``\\addbibresource{file.bib}`` declared in the preamble."""
    for m in re.finditer(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]*)\}", preamble):
        for name in m.group(1).split(","):
            if name.strip() and name.strip() not in builder.bib_files:
                builder.bib_files.append(name.strip())


def _fill_meta_from_preamble(
    doc: ir.Document, preamble: str, ctx, report: ConversionReport
) -> None:
    """Recover \\title/\\author/\\date/\\keywords defined in the preamble (best effort)."""
    if doc.meta.running_head is None:
        doc.meta.running_head = _running_head_from_preamble(preamble)
    for macro in ("title", "author", "date", "keywords", "institute", "affiliation"):
        if macro == "title" and doc.meta.title is not None:
            continue
        if macro == "author" and doc.meta.authors:
            continue
        if macro == "date" and doc.meta.date is not None:
            continue
        if macro == "keywords" and doc.meta.keywords is not None:
            continue
        if macro in ("institute", "affiliation") and doc.meta.affiliations:
            continue
        content = _braced_content(preamble, macro)
        if content is None:
            continue
        try:
            sub_nodes, _, _ = LatexWalker(
                content, latex_context=ctx, tolerant_parsing=True
            ).get_latex_nodes()
            if macro in ("author", "institute", "affiliation"):
                target = doc.meta.authors if macro == "author" else doc.meta.affiliations
                for seg in _split_on_and(sub_nodes):
                    inl = _Builder(report).inlines(seg)
                    if inl:
                        target.append(inl)
                continue
            inlines = _Builder(report).inlines(sub_nodes)
        except Exception:
            inlines = [ir.Text(content)]
        if macro == "title":
            doc.meta.title = inlines
        elif macro == "date":
            doc.meta.date = inlines
        elif macro == "keywords":
            doc.meta.keywords = inlines


def _resolve_bibliography(
    doc: ir.Document, builder: _Builder, base_dir: str, report: ConversionReport,
    csl_path: str | None = None,
) -> None:
    from ..bib.bibtex import parse_bibtex
    from ..bib.render import resolve_citations

    style = builder.bib_style
    nocite = builder.nocite_keys

    # A .bbl (BibTeX's formatted .bst output) is authoritative -- prefer it over
    # the heuristic .bib->CSL rendering when present.
    bbl_items = _load_bbl(base_dir) if builder.bib_files else {}
    if bbl_items:
        from ..bib.bbl import bbl_style

        bbl_items.update(builder.thebib_items)
        resolve_citations(doc, bbl_items, bbl_style(bbl_items), report,
                          csl_path=csl_path, nocite_keys=nocite)
        report.info("\\bibliography", "used the .bbl (formatted .bst output)")
        return

    items: dict[str, ir.CSLItem] = {}
    for name in builder.bib_files:
        candidates = [name, name + ".bib"] if not name.endswith(".bib") else [name]
        for cand in candidates:
            path = os.path.join(base_dir, cand)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    items.update(parse_bibtex(fh.read()))
                break
        else:
            report.warn("\\bibliography", f"bibliography file not found: {name}")
    items.update(builder.thebib_items)

    if items or builder.bib_files or builder.thebib_items or nocite:
        resolve_citations(doc, items, style, report,
                          csl_path=csl_path, nocite_keys=nocite)


def _load_bbl(base_dir: str) -> dict[str, ir.CSLItem]:
    """Find and parse a single ``.bbl`` in ``base_dir`` (if exactly one)."""
    import glob

    from ..bib.bbl import parse_bbl

    bbls = glob.glob(os.path.join(base_dir, "*.bbl"))
    if len(bbls) != 1:
        return {}
    try:
        with open(bbls[0], encoding="utf-8") as fh:
            return parse_bbl(fh.read())
    except OSError:
        return {}
