"""LaTeX -> IR conversion built on pylatexenc's walker.

Macro expansion (``\\newcommand``/``\\def``) is done *before* walking, so custom
commands become standard content. Unknown constructs degrade gracefully into
``RawInline``/``RawPassthrough`` nodes plus a coverage-report entry -- never an
abort.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

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
from .counters import resolve_counters
from .frontmatter import FRONT_MATTER, FrontMatterMixin, preamble_calls
from .frontmatter import SPECS as _FRONT_SPECS
from .macros import expand_macros, local_package_sources
from .preprocess import normalize_spacing_and_icons, preprocess, replace_inline_tikz

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
_TRANSPARENT_BOX = {
    "mbox", "fbox", "framebox", "makebox", "raisebox", "rotatebox", "resizebox",
    "scalebox", "makecell", "thead", "parbox", "foreignlanguage", "otherlanguage",
}
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
    "ref": "generic", "eqref": "equation", "pageref": "page", "vpageref": "page",
    "subref": "subref",
    "cpageref": "page", "Cpageref": "page",
    "autoref": "generic", "cref": "generic", "Cref": "generic", "vref": "generic",
    "crefrange": "generic", "Crefrange": "generic", "labelcref": "generic",
    "nameref": "name", "Nameref": "name",
}
# cleveref-style commands carry a type name; \ref/\pageref stay bare and
# \eqref/\labelcref put an equation number in parentheses.
_REF_STYLE = {
    "eqref": "eqref", "labelcref": "eqref",
    "autoref": "auto", "cref": "abbrev", "Cref": "full", "vref": "full",
    "crefrange": "abbrev", "Crefrange": "full", "cpageref": "abbrev", "Cpageref": "full",
}
#: commands that take a comma-separated list of labels
_REF_LISTS = {"cref", "Cref", "cpageref", "Cpageref", "labelcref", "vref"}

_TEXT_SYMBOLS = {
    # non-ASCII letters (T1/OT1 text commands)
    "ss": "ß", "SS": "SS", "o": "ø", "O": "Ø", "aa": "å", "AA": "Å", "l": "ł", "L": "Ł",
    "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "i": "ı", "j": "ȷ", "dh": "ð", "DH": "Ð",
    "th": "þ", "TH": "Þ", "ng": "ŋ", "NG": "Ŋ", "dj": "đ", "DJ": "Đ",
    # babel/csquotes-style German and French quotes
    "glqq": "„", "grqq": "“", "glq": "‚", "grq": "‘", "flqq": "«", "frqq": "»",
    "flq": "‹", "frq": "›", "quotedblbase": "„", "quotesinglbase": "‚",
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
    # bbding dingbats (\greencheck-style macros expand to these)
    "Checkmark": "✓", "CheckmarkBold": "✔", "XSolid": "✗", "XSolidBold": "✘",
    "XSolidBrush": "✘", "Cross": "✗", "CrossBold": "✘", "HandRight": "☞",
    "HandLeft": "☜", "PencilRight": "✎", "Envelope": "✉", "Phone": "☎",
    # gensymb package text/math symbols
    "degree": "°", "celsius": "℃", "ohm": "Ω", "micro": "µ", "perthousand": "‰",
    "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}",
    " ": " ", ",": " ", ";": " ", ":": " ", "!": "", "@": "",
    # \quad = 1em, \qquad = 2em: em spaces, so "A \quad B" stays visibly apart
    "quad": " ", "qquad": "  ", "hfill": " ", "newline": "\n",
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
    # page/column layout and language switches: the content is all that matters
    "multicols", "landscape", "titlepage", "otherlanguage", "adjustbox", "fullwidth",
    "frontmatter", "columns", "column", "alltt",
}

#: tabular-like environments (all parsed by ``_tabular``)
_TABULAR_ENVS = frozenset({
    "tabular", "array", "tabularx", "tabulary", "longtable", "supertabular", "xtabular",
    "mpsupertabular",
})

#: environments whose content is not part of the document
_DROPPED_ENVS = {"comment", "CCSXML", "filecontents"}

#: acknowledgment environments -> an unnumbered heading over their content
_ACK_ENVS = {
    "acknowledgments": "Acknowledgments", "acknowledgements": "Acknowledgements",
    "acknowledgment": "Acknowledgment", "acknowledgement": "Acknowledgement",
    "acks": "Acknowledgments",
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
    "makeatletter", "makeatother", "selectlanguage", "addtolength", "settowidth",
    "settoheight", "settodepth", "deflength",
    "authornote", "authornotemark", "balance", "nobalance", "acmnote",
    "onecolumn", "twocolumn", "typeout",
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


def _algorithm_options(source: str) -> tuple[bool, bool]:
    """(algpseudocode/algorithmic ``noend``, algorithm2e numbers its lines)."""
    noend = numbered = False
    for opts, pkgs in re.findall(r"\\usepackage\s*\[([^\]]*)\]\s*\{([^}]*)\}", source):
        names = {p.strip() for p in pkgs.split(",")}
        flags = {o.strip() for o in opts.split(",")}
        if names & {"algpseudocode", "algorithmic", "algorithmicx"} and "noend" in flags:
            noend = True
        if "algorithm2e" in names and flags & {"linesnumbered", "linesnumberedhidden"}:
            numbered = True
    if re.search(r"\\LinesNumbered\b", source):
        numbered = True
    return noend, numbered


def _si_options(node: LatexMacroNode) -> dict[str, str] | None:
    """A siunitx command's own ``[key=value]`` options."""
    opt = _optional_group(node)
    return siunitx.parse_keyvals(_chars_of(opt)) if opt else None


def _sisetup(source: str) -> dict[str, str]:
    """The document's siunitx options: package options, then every \\sisetup."""
    opts: dict[str, str] = {}
    for o, pkgs in re.findall(r"\\usepackage\s*\[([^\]]*)\]\s*\{([^}]*)\}", source):
        if "siunitx" in [p.strip() for p in pkgs.split(",")]:
            opts.update(siunitx.parse_keyvals(o))
    for m in re.finditer(r"\\sisetup\s*\{", source):
        depth, i = 1, m.end()
        while i < len(source) and depth:
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            i += 1
        opts.update(siunitx.parse_keyvals(source[m.end():i - 1]))
    return opts


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


def _url_text(nodes: list) -> str:
    """A URL argument verbatim (``~``, ``#``, ``%`` are part of it), with TeX
    escapes such as ``\\#``, ``\\%``, ``\\_`` undone."""
    raw = "".join(n.latex_verbatim() for n in nodes).strip()
    return re.sub(r"\\([#%_&~$])", r"\1", raw)


def _flat_text(inlines: list) -> str:
    """Plain text of rendered inlines (styles dropped, a no-break space kept)."""
    out: list[str] = []
    for n in inlines:
        if isinstance(n, ir.Text):
            out.append(n.value)
        elif isinstance(n, ir.LineBreak):
            out.append(" ")
        elif hasattr(n, "inlines"):
            out.append(_flat_text(n.inlines))
    return "".join(out).strip()


def _chars_of(nodes: list) -> str:
    out: list[str] = []
    for n in nodes:
        if isinstance(n, LatexCharsNode):
            out.append(n.chars)
        elif isinstance(n, LatexGroupNode):
            out.append(_chars_of(n.nodelist))
    return "".join(out).strip()


def _today_text() -> str:
    """``\\today`` -> the current date in LaTeX's default English format
    (``Month D, YYYY``), engine-independent."""
    import datetime
    t = datetime.date.today()
    return f"{t:%B} {t.day}, {t.year}"


def _default_date(source: str, builder: _Builder) -> list[ir.Inline]:
    """The date \\maketitle shows when no \\date is given: the document's own
    ``\\today`` if it redefines it (``\\renewcommand{\\today}{2026-09-04}``),
    else the current date."""
    from .macros import collect_macros, expand

    macros, _ = collect_macros(source)
    if "today" in macros:
        text = expand("\\today", macros).strip()
        if text and "\\today" not in text:
            inl = builder._fragment_inlines(text)
            if inl:
                return inl
    return [ir.Text(_today_text())]


def _has_opaque_env(source: str) -> bool:
    """True if a figure source holds a drawing environment (TikZ & co.), which
    stays on the compile-to-image path rather than being parsed as text."""
    return any(f"\\begin{{{env}}}" in source for env in _OPAQUE_ENVS)


def _is_blank_paragraph(block: ir.Block) -> bool:
    """A paragraph with no visible content (only whitespace / line breaks)."""
    if not isinstance(block, ir.Paragraph):
        return False
    for node in block.inlines:
        if isinstance(node, ir.LineBreak):
            continue
        if isinstance(node, ir.Text) and not node.value.strip():
            continue
        return False
    return True


def _is_minipage(node: object) -> bool:
    return isinstance(node, LatexEnvironmentNode) and node.environmentname == "minipage"


#: math symbols that commonly serve as affiliation / footnote markers.
_MARKER_SYMBOLS = {
    "dagger": "†", "ddagger": "‡", "dag": "†", "ddag": "‡", "ast": "∗", "star": "⋆",
    "S": "§", "P": "¶", "natural": "♮", "sharp": "♯", "flat": "♭", "prime": "′",
    "bullet": "•", "diamond": "⋄", "triangle": "△", "clubsuit": "♣",
    "spadesuit": "♠", "heartsuit": "♡", "diamondsuit": "♢", "sim": "∼",
    "#": "#", "&": "&", "%": "%", ",": "", ";": "", "!": "",
}
#: font wrappers whose argument is just text (``^{\mathrm{th}}`` -> "th").
_MARKER_WRAPPERS = {"mathrm", "text", "textrm", "mathit", "mathbf", "textbf", "mathsf",
                    "textit", "textup", "mathnormal"}
_MARKER_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*,.;:+-()'/=|!? "
)


def _marker_text(body: str) -> str | None:
    """Plain text for a script body made only of marker characters/symbols, or
    None if it holds real math structure (fractions, nested scripts, …)."""
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", body[i:])
            name = m.group(1) if m else ""
            i += m.end() if m else 1
            if name in _MARKER_SYMBOLS:
                out.append(_MARKER_SYMBOLS[name])
            elif name in _MARKER_WRAPPERS:
                while i < n and body[i] == " ":
                    i += 1
                if i < n and body[i] == "{":
                    inner, end = _braced_group(body, i)
                    sub = _marker_text(inner)
                    if sub is None:
                        return None
                    out.append(sub)
                    i = end + 1
            else:
                return None
        elif c in "{}":
            i += 1
        elif c in _MARKER_CHARS:
            out.append("−" if c == "-" else c)
            i += 1
        else:
            return None
    text = "".join(out).strip()
    return text or None


def _script_marker(latex: str) -> tuple[str, str] | None:
    """``^{*1}`` -> ("superscript", "*1"); ``_{a}`` -> ("subscript", "a");
    ``^\\circ`` -> ("plain", "°"). None unless the math is *only* a base-less
    script whose content is marker text."""
    s = latex.strip()
    if len(s) < 2 or s[0] not in "^_":
        return None
    kind = "superscript" if s[0] == "^" else "subscript"
    rest = s[1:].lstrip()
    if rest.startswith("{"):
        body, end = _braced_group(rest, 0)
        tail = rest[end + 1:]
    else:
        m = re.match(r"\\[A-Za-z]+|\\.|.", rest)
        if m is None:
            return None
        body, tail = m.group(0), rest[m.end():]
    if tail.strip():  # more after the script (^a_b, ^1 x): leave it as math
        return None
    if kind == "superscript" and body.strip() in ("\\circ", "{\\circ}"):
        return ("plain", "°")  # $^\circ$ is a degree sign, already raised
    text = _marker_text(body)
    return (kind, text) if text is not None else None


def _has_captionof(nodes: list, kind: str) -> bool:
    """True if ``nodes`` (one level, plus groups) hold ``\\captionof{kind}``."""
    for n in nodes:
        if isinstance(n, LatexMacroNode) and n.macroname == "captionof":
            groups = [
                a for a in (n.nodeargd.argnlist if n.nodeargd else [])
                if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "{"
            ]
            if groups and _chars_of(groups[0].nodelist).strip() == kind:
                return True
        elif isinstance(n, LatexGroupNode) and _has_captionof(n.nodelist, kind):
            return True
    return False


def _unwrap_table_layout(nodes: list) -> list:
    """The children of a ``table`` float with layout wrappers opened up.

    ``\\rotatebox``/``\\resizebox``/``\\scalebox`` contribute their content,
    and a lone ``minipage`` (the landscape idiom
    ``\\rotatebox{90}{\\begin{minipage}...}``) its body, so the float's
    caption, label and tabular are found inside.
    """
    minipages = sum(
        1 for n in nodes
        if isinstance(n, LatexEnvironmentNode) and n.environmentname == "minipage"
    )
    out: list = []
    for n in nodes:
        if isinstance(n, LatexMacroNode) and n.macroname in _BOX_WRAPPERS:
            groups = _brace_groups(n)
            out.extend(_unwrap_table_layout(groups[-1]) if groups else [])
        elif isinstance(n, LatexEnvironmentNode) and n.environmentname in _TABLE_WRAP_ENVS:
            # threeparttable / adjustbox / center inside a float: the caption,
            # label and tabular are the float's
            out.extend(_unwrap_table_layout(n.nodelist))
        elif (
            minipages == 1 and isinstance(n, LatexEnvironmentNode)
            and n.environmentname == "minipage"
        ):
            out.extend(_unwrap_table_layout(n.nodelist))
        else:
            out.append(n)
    return out


#: bibliography commands that may sit in a size group ({\small \bibliography{x}})
_BIB_BLOCK_MACROS = frozenset({
    "bibliography", "bibliographystyle", "printbibliography", "nocite",
})


#: amsart \@namedef{subjclassname@JEL}{JEL classification}
_SUBJCLASS_NAME_RE = re.compile(r"\\@namedef\s*\{subjclassname@([^}]*)\}\s*\{([^{}]*)\}")


def _has_block_content(nodes: list) -> bool:
    """True if ``nodes`` hold an environment or a paragraph break."""
    for n in nodes:
        if isinstance(n, LatexEnvironmentNode):
            return True
        if isinstance(n, LatexCharsNode) and re.search(r"\n[ \t]*\n", n.chars):
            return True
        if isinstance(n, LatexMacroNode) and n.macroname == "par":
            return True
        if isinstance(n, LatexGroupNode) and _has_block_content(n.nodelist):
            return True
    return False


#: environments a table float's caption/label/tabular may sit in
_TABLE_WRAP_ENVS = frozenset({
    "threeparttable", "threeparttablex", "adjustbox", "center", "small", "footnotesize",
    "scriptsize",
})


def _list_start(node: LatexEnvironmentNode) -> int:
    """First number of an ordered list: enumitem ``[start=5]``, or a
    ``\\setcounter{enumi}{4}`` before the first ``\\item`` (LaTeX steps the
    counter before printing, so that also starts at 5)."""
    for a in node.nodeargd.argnlist if node.nodeargd else []:
        if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
            m = re.search(r"\bstart\s*=\s*(\d+)", a.latex_verbatim())
            if m:
                return int(m.group(1))
    m = re.search(r"\\setcounter\s*\{enum[iv]+\}\s*\{\s*(\d+)\s*\}",
                  node.latex_verbatim().split("\\item", 1)[0])
    return int(m.group(1)) + 1 if m else 1


def _has_caption(nodes: list) -> bool:
    for n in nodes:
        if isinstance(n, LatexMacroNode) and n.macroname in ("caption", "captionof"):
            return True
        if isinstance(n, LatexGroupNode | LatexEnvironmentNode) and _has_caption(n.nodelist):
            return True
    return False


#: scaling/rotation wrappers whose last {} argument is their content
_BOX_WRAPPERS = ("resizebox", "scalebox", "rotatebox")


#: horizontal glue that can sit between side-by-side minipages without breaking
#: the row (they don't produce content of their own).
_LAYOUT_GLUE_MACROS = {
    "hfill", "hspace", "hskip", "quad", "qquad", "enspace", "thinspace", "centering",
    "noindent", "hss", "hfil", ",", " ", "~",
}


def _is_layout_glue(node: object) -> bool:
    if isinstance(node, LatexCharsNode):
        return not node.chars.strip()
    if isinstance(node, LatexCommentNode):
        return True
    return isinstance(node, LatexMacroNode) and node.macroname in _LAYOUT_GLUE_MACROS


def _latex_of(nodes: list) -> str:
    """The verbatim LaTeX source of a node list (for \\ensuremath bodies)."""
    return "".join(n.latex_verbatim() for n in nodes).strip()


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


class _Builder(FrontMatterMixin):
    def __init__(self, report: ConversionReport) -> None:
        self.report = report
        self.meta = ir.DocumentMeta()
        self.doc_class = "article"
        self._fm_init()
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
        #: extra \label -> the label its target already carries
        self.label_aliases: dict[str, str] = {}
        #: subtable panel labels -> [overall table label, panel letter]
        self.sub_labels: dict[str, list[str]] = {}
        #: numbered heading counters by level (1-based index - 1), and a value
        #: \setcounter{section}{n} gave a level's counter for the next heading
        self.heading_counts: list[int] = [0] * 6
        self.heading_set: dict[int, int] = {}
        #: levels the current heading numbering instance overrides (Word
        #: reapplies a level's start override whenever that level restarts)
        self.heading_override_depth = 0
        #: algpseudocode/algorithmic [noend]: no "end if" lines
        self.alg_noend = False
        #: algorithm2e numbers its lines ([linesnumbered], \LinesNumbered)
        self.alg2e_numbered = False
        #: (label, caption, numbered) of an lstlisting, for the next code block
        self._pending_listing: tuple[str | None, list[ir.Inline] | None, bool] | None = None
        self._title_done = False  # past \maketitle: a \thanks is a plain footnote
        #: amsart \subjclass labels from \@namedef{subjclassname@X}{label}
        self.subjclass_names: dict[str, str] = {}
        self.in_appendix = False  # seen \appendix -> later sections use letters
        # \footnotemark placeholders awaiting their \footnotetext{...} content
        self._pending_footmarks: list[ir.Footnote] = []
        # theorem-like environment name -> display title (built-ins + \newtheorem)
        self.theorem_envs: dict[str, str] = dict(_THEOREM_ENVS)
        self.unnumbered_theorems: set[str] = set()  # \newtheorem*-defined names
        # env name -> counter display title (shared counters resolve here)
        self.theorem_counters: dict[str, str] = {}
        self.theorem_within: dict[str, str] = {}  # env -> division its counter resets in
        # user \newtcolorbox / \newmdenv callout environments -> Quote blocks
        self.box_envs: set[str] = set()
        #: \newtcolorbox definitions and \tcbset{name/.style=...} styles, used to
        #: give tcolorbox callouts their colours and title bar.
        self.tcb_envs: dict[str, _TcbEnv] = {}
        self.tcb_styles: dict[str, str] = {}
        #: the pylatexenc context (for parsing option fragments such as a title)
        self.ctx = None
        #: True while parsing a graphic-less figure body (its \caption is the
        #: figure's, already collected -> suppress it there).
        self._in_figure_body = False
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
            marker = _script_marker(latex) if node.displaytype == "inline" else None
            if marker is not None:
                # $^{*1}$ / $^\dagger$ / 1$^{st}$: a base-less script is a text
                # marker, not math -- an empty-base OMML superscript is dropped by
                # LibreOffice and other importers, a superscript run is not.
                kind, text = marker
                if kind == "plain":
                    out.append(ir.Text(text))
                elif kind == "subscript":
                    out.append(ir.Emphasis([ir.Text(text)], "subscript"))
                else:
                    out.append(ir.Emphasis([ir.Text(text)], "superscript"))
                return
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
        if isinstance(node, LatexEnvironmentNode):
            self._inline_env(node, out)
            return

    def _inline_env(self, node: LatexEnvironmentNode, out: list[ir.Inline]) -> None:
        """An environment inside a macro argument (a caption, a heading, \\fbox,
        \\textbf, ...). Word cannot put a table inside a run, so a tabular keeps
        its text: rows on separate lines, cells separated by spaces. Any other
        environment contributes its content."""
        base = node.environmentname.rstrip("*")
        if base in _TABULAR_ENVS:
            table = self._tabular(node)
            for ri, row in enumerate(table.rows):
                if ri:
                    out.append(ir.LineBreak())
                for ci, cell in enumerate(row.cells):
                    if ci:
                        out.append(ir.Text("  "))
                    for b in cell.blocks:
                        if isinstance(b, ir.Paragraph):
                            out.extend(b.inlines)
            return
        if base in _OPAQUE_ENVS or base in _DROPPED_ENVS:
            return
        out.extend(self._scoped_inlines(node.nodelist))

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
        if self.front_inline(node, out):
            return
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
                out.append(ir.Ref(_chars_of(groups[0]).strip(), kind, style=style,  # type: ignore[arg-type]
                                  more=[_chars_of(groups[1]).strip()], is_range=True))
            elif groups:
                out.append(ir.Ref(_chars_of(groups[-1]).strip(), kind, style=style))  # type: ignore[arg-type]
            return
        if name in _REF_KINDS:
            kind = _REF_KINDS[name]
            style = _REF_STYLE.get(name, "plain")
            keys = [k.strip() for k in _chars_of(_group_nodes(node)).split(",") if k.strip()]
            if name in _REF_LISTS and keys:
                # one reference to several labels: the backend writes cleveref's
                # grouped form ("sections 1 and 2 and fig. 3")
                out.append(ir.Ref(keys[0], kind, style=style, more=keys[1:]))  # type: ignore[arg-type]
                return
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
            self._set_label(_chars_of(_group_nodes(node)))
            return
        if self._in_figure_body and name in ("caption", "captionof"):
            return  # the enclosing figure's caption, collected separately
        if name in ("href", "url"):
            self._inline_link(node, out)
            return
        if name in ("path", "nolinkurl"):  # url-style path, not a link: monospace
            groups = _brace_groups(node)
            text = "".join(n.latex_verbatim() for n in groups[-1]) if groups else ""
            if text:
                out.append(ir.Emphasis([ir.Text(text)], "typewriter"))
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
        if name in ("footnote", "thanks", "marginpar", "sidenote", "marginnote"):
            # \thanks (title/author note), \marginpar/\sidenote (margin asides)
            # all degrade to a Word footnote -- the closest aside Word offers.
            out.append(self._note(_group_nodes(node)))
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
            num = siunitx.num_to_text(_chars_of(groups[0]), _si_options(node)) if groups else ""
            unit = siunitx.units_to_text(groups[1]) if len(groups) > 1 else ""
            out.append(ir.Text(f"{num}{siunitx.THIN}{unit}".strip()))
            return
        if name == "num":
            out.append(ir.Text(siunitx.num_to_text(_chars_of(_group_nodes(node)),
                                                   _si_options(node))))
            return
        if name == "ang":
            out.append(ir.Text(siunitx.ang_to_text(_chars_of(_group_nodes(node)))))
            return
        if name in ("numrange", "SIrange", "qtyrange"):  # a to b [unit]
            groups = _brace_groups(node)
            if len(groups) >= 2:
                a = siunitx.num_to_text(_chars_of(groups[0]), _si_options(node))
                b = siunitx.num_to_text(_chars_of(groups[1]), _si_options(node))
                unit = siunitx.units_to_text(groups[2]) if len(groups) > 2 else ""
                out.append(ir.Text(f"{a} to {b}" + (f"{siunitx.THIN}{unit}" if unit else "")))
            return
        if name in ("numlist", "SIlist", "qtylist"):  # a, b and c [unit]
            groups = _brace_groups(node)
            if groups:
                items = [siunitx.num_to_text(x.strip(), _si_options(node))
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
        if name in ("inst", "IEEEauthorrefmark", "tnote"):  # markers -> superscript
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
        if name == "today":  # \today -> the current date (LaTeX default format)
            out.append(ir.Text(_today_text()))
            return
        if name in _TEXT_SYMBOLS:
            out.append(ir.Text(_TEXT_SYMBOLS[name]))
            return
        if name in _IGNORE_MACROS:
            return
        if _accent_char(name) is not None:
            # render the base: \"{\i} has a macro (dotless i) as its base
            base = _flat_text(self.inlines(_group_nodes(node)))
            out.append(ir.Text(_apply_text_accent(name, base)))
            return
        if name in ("MakeUppercase", "MakeLowercase", "uppercase", "lowercase",
                    "MakeTextUppercase", "MakeTextLowercase"):
            inner = self.inlines(_group_nodes(node))
            _change_case(inner, upper="pper" in name)
            out.extend(inner)
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
            url = _url_text(groups[0].nodelist)
            out.append(ir.Link([ir.Text(url)], url))
        elif len(groups) >= 2:
            url = _url_text(groups[0].nodelist)
            out.append(ir.Link(self.inlines(groups[1].nodelist), url))
        elif groups:
            url = _url_text(groups[0].nodelist)
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
                isinstance(c, LatexEnvironmentNode)
                or (isinstance(c, LatexMacroNode) and c.macroname in _BIB_BLOCK_MACROS)
                for c in node.nodelist
            ):
                flush()
                out.extend(self.blocks(node.nodelist))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "label":
                self._set_label(_chars_of(_group_nodes(node)))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in ("appendix", "beginappendix"):
                # \appendix (and class wrappers like fairmeta's \beginappendix)
                # switch later sections to lettered numbering.
                self.in_appendix = True
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in (
                "setcounter", "addtocounter"
            ) and self._heading_counter(node):
                continue
            if isinstance(node, LatexMacroNode) and node.macroname.rstrip("*") in _SECTION_LEVELS:
                flush()
                self._heading(node, out)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _TOC_MACROS:
                flush()
                out.append(ir.TableOfContents(kind=_TOC_MACROS[node.macroname]))  # type: ignore[arg-type]
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in FRONT_MATTER:
                fm = self.front_matter(node)
                if fm is not None:
                    if fm:
                        flush()
                        out.extend(fm)
                    continue
            if isinstance(node, LatexMacroNode) and node.macroname in (
                "title", "date", "IEEEkeywords",
                "markboth", "markright", "runninghead", "shorttitle",
            ):
                self._meta_macro(node)
                continue
            if (
                isinstance(node, LatexMacroNode) and node.macroname == "thanks"
                and self.meta.title and not self._title_done
            ):
                # amsart-style \thanks between \author and \maketitle: a
                # first-page note on the title, not a mark on a line of its own
                self.meta.title.append(ir.Footnote(self.inlines(_group_nodes(node))))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "maketitle":
                self._title_done = True
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "twlistingcaption":
                # lstlisting caption=/label= (see preprocess): for the next code block
                g = _brace_groups(node)
                if len(g) == 3:
                    self._pending_listing = (
                        _chars_of(g[0]).strip() or None,
                        self.inlines(g[1]) or None,
                        _chars_of(g[2]).strip() != "0",
                    )
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "twocolumn":
                # \twocolumn[full-width header]: the optional argument is content
                flush()
                for a in node.nodeargd.argnlist if node.nodeargd else []:
                    if isinstance(a, LatexGroupNode):
                        out.extend(self.blocks(a.nodelist))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname == "subjclass":
                flush()
                out.append(self._subjclass(node))
                continue
            if (
                isinstance(node, LatexMacroNode) and node.macroname == "parbox"
                and _brace_groups(node) and _has_block_content(_brace_groups(node)[-1])
            ):
                flush()
                out.extend(self.blocks(_brace_groups(node)[-1]))
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _BOX_WRAPPERS:
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
        if numbered and not is_part and not heading.appendix and 1 <= level <= 6:
            counts = self.heading_counts
            if level in self.heading_set:  # \setcounter before this heading
                counts[level - 1] = self.heading_set.pop(level) + 1
                heading.number_start = counts[:level]
                self.heading_override_depth = level
            else:
                counts[level - 1] += 1
                if level < self.heading_override_depth:
                    # leave an instance whose deeper start override would make
                    # every later sub-level restart at it ("2.4" for "2.1")
                    heading.number_start = counts[:level]
                    self.heading_override_depth = level
            for deeper in range(level, len(counts)):
                counts[deeper] = 0
            for deeper in [k for k in self.heading_set if k > level]:
                del self.heading_set[deeper]  # a higher heading resets them
        out.append(heading)
        self._labelable = heading

    def _heading_counter(self, node: LatexMacroNode) -> bool:
        """``\\setcounter``/``\\addtocounter`` on a sectioning counter: the next
        heading of that level is numbered from the new value. True if handled."""
        groups = _brace_groups(node)
        if len(groups) < 2:
            return False
        name = _chars_of(groups[0]).strip()
        levels = _SECTION_LEVELS_BOOK if self.book_mode else _SECTION_LEVELS
        if name not in levels or name == "part" or (name == "chapter" and not self.book_mode):
            return False
        try:
            value = int(_chars_of(groups[1]).strip())
        except ValueError:
            return False
        level = levels[name]
        current = self.heading_set.get(level, self.heading_counts[level - 1])
        self.heading_set[level] = value if node.macroname == "setcounter" else current + value
        return True

    def _math_block(self, verbatim: str, env: str, numbered: bool) -> ir.MathBlock:
        from ..mathml.omml import _split_top_level

        latex = _strip_math_delims(verbatim, env)
        # Per-line labels, aligned with the lines the math engine renders: it
        # drops \label/\tag then splits on top-level "\\" and keeps non-empty
        # lines, so mirror that here (one entry per rendered, numbered line).
        line_labels: list[str | None] = []
        line_tags: list[str | None] = []
        if re.search(r"\\(?:label|tag|nonumber|notag)\b", latex):
            for seg in _split_top_level(latex, "\\\\"):
                if _LABEL_TAG_RE.sub("", seg).strip():
                    line_labels.append(_extract_label(seg) if "\\label" in seg else None)
                    line_tags.append(_line_tag(seg))
        if "\\label" not in latex:
            line_labels = []
        if all(t is None for t in line_tags):
            line_tags = []
        label = next((lb for lb in line_labels if lb), None)
        latex = _LABEL_TAG_RE.sub("", latex).strip()
        block = ir.MathBlock(
            latex=latex, numbered=numbered, env=env, label=label, line_labels=line_labels,
            line_tags=line_tags,
        )
        self._labelable = block
        return block

    _labelable: (
        ir.Heading | ir.MathBlock | ir.Figure | ir.Table | ir.Theorem
        | ir.Algorithm | ir.ListItem | None
    ) = None

    def _subjclass(self, node: LatexMacroNode) -> ir.Paragraph:
        """amsart ``\\subjclass[scheme]{codes}`` -> "<label>: codes".

        The label comes from ``\\@namedef{subjclassname@scheme}{...}`` when the
        document declares one, else amsart's default for a year scheme.
        """
        scheme = ""
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
                scheme = _chars_of(a.nodelist).strip()
        label = self.subjclass_names.get(scheme)
        if label is None:
            if scheme == "JEL":
                label = "JEL classification"
            elif scheme.isdigit():
                label = f"{scheme} Mathematics Subject Classification"
            else:
                label = "Mathematics Subject Classification"
        groups = _brace_groups(node)
        codes = self.inlines(groups[-1]) if groups else []
        return ir.Paragraph([ir.Emphasis([ir.Text(f"{label}: ")], "bold"), *codes])

    def _note(self, nodes: list) -> ir.Footnote:
        """A footnote; lists, quotes, tables or paragraph breaks inside it make
        it a block note (inline parsing would drop the environments)."""
        if not _has_block_content(nodes):
            return ir.Footnote(self.inlines(nodes))
        saved = self._labelable
        try:
            blocks = self.blocks(nodes)
        finally:
            self._labelable = saved
        return ir.Footnote([], blocks=blocks)

    def _set_label(self, label: str) -> None:
        """Attach ``\\label{label}`` to the current target.

        A target keeps its first label; any further one (``\\label{a}\\label{b}``,
        or a stray ``\\label`` after ``\\end{figure}``) becomes an alias, so
        ``\\ref`` to either resolves to the same number, as in LaTeX.
        """
        target = self._labelable
        if target is None or not label:
            return
        if target.label is None:
            target.label = label
        elif target.label != label:
            self.label_aliases.setdefault(label, target.label)

    def _environment(self, node: LatexEnvironmentNode, out: list[ir.Block]) -> None:  # noqa: C901
        name = node.environmentname
        if self.front_env(node, out):
            return
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
        if base in ("figure", "wrapfigure", "sidewaysfigure"):
            self._figure(node, out, spanning=starred)
            return
        if base in ("table", "wraptable", "sidewaystable", "threeparttable"):
            self._table_float(node, out, spanning=starred or base == "sidewaystable")
            return
        if base in _TABULAR_ENVS:
            out.append(self._tabular(node))
            return
        if base == "tcolorbox" or base in self.tcb_envs:
            out.append(self._tcolorbox_quote(node, base))
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
            block = ir.CodeBlock(_verbatim_inner(node), lang=None)
            if self._pending_listing is not None:
                block.label, block.caption, block.caption_numbered = self._pending_listing
                self._pending_listing = None
            out.append(block)
            return
        if base == "listing":  # minted's float: code + \caption + \label
            self._listing_float(node, out)
            return
        if base == "abstract":
            self.meta.abstract = self.blocks(node.nodelist)
            return
        if base in ("center", "flushleft", "flushright", "minipage") and _has_captionof(
            node.nodelist, "figure"
        ):
            # a non-floating figure: \includegraphics + \captionof{figure}{…}
            # inside a center/minipage is numbered and captioned like a figure.
            self._figure(node, out)
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
        if base in _DROPPED_ENVS:
            return
        if base in ("IEEEbiography", "IEEEbiographynophoto"):
            # \begin{IEEEbiography}[photo]{Name} text -> a bold run-in name
            groups = [
                a for a in (node.nodeargd.argnlist if node.nodeargd else [])
                if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "{"
            ]
            body = self.blocks(node.nodelist)
            if groups:
                lead: list[ir.Inline] = [ir.Emphasis(self.inlines(groups[-1].nodelist), "bold"),
                                         ir.Text(" ")]
                if body and isinstance(body[0], ir.Paragraph):
                    body[0].inlines[:0] = lead
                else:
                    body.insert(0, ir.Paragraph(lead))
            out.extend(body)
            return
        if base in _ACK_ENVS:
            out.append(ir.Heading(1, [ir.Text(_ACK_ENVS[base])], numbered=False))
            out.extend(self.blocks(node.nodelist))
            return
        if base in ("IEEEkeywords", "keyword", "keywords"):
            # IEEEtran / elsarticle keyword blocks (elsarticle separates with \sep)
            parts: list[list] = [[]]
            for n in node.nodelist:
                if isinstance(n, LatexMacroNode) and n.macroname == "sep":
                    parts.append([])
                else:
                    parts[-1].append(n)
            keywords: list[ir.Inline] = []
            for i, part in enumerate(parts):
                if i:
                    keywords.append(ir.Text("; "))
                keywords.extend(self.inlines(part))
            self.meta.keywords = _clean_inlines(keywords, trim=True)
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
        theorem = ir.Theorem(kind=display, blocks=[], title=title, counter=counter,
                             within=self.theorem_within.get(base) if counter else None)
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
        from .algorithms import algorithmic_numbering

        lines = parse_algorithm_body(node.nodelist, self.inlines,
                                     end_lines=not self.alg_noend)
        numbering = algorithmic_numbering(node.nodelist)
        if numbering is None:  # algorithm2e: numbered with linesnumbered/\LinesNumbered
            numbering = 1 if self.alg2e_numbered else 0
        alg = ir.Algorithm(lines=lines, caption=caption, label=label, line_numbers=numbering)
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
        return ir.ItemList(ordered=ordered, items=items, description=description,
                           start=_list_start(node) if ordered else 1)

    def _cite_locators(self, node: LatexMacroNode) -> tuple[str | None, str | None]:
        """Extract ``\\citep[pre][post]{key}`` locators.

        natbib: a single optional is the *post*-note (suffix); two optionals are
        (pre, post).
        """
        argd = node.nodeargd
        # rendered, not raw: p.~3 -> "p. 3", \S~2 -> "§ 2"
        opts = [
            _flat_text(self.inlines(a.nodelist))
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

    def _figure(self, node: LatexEnvironmentNode, out: list, spanning: bool = False) -> None:
        fig = ir.Figure(image=None, source=node.latex_verbatim(), spanning=spanning)
        # panels: one entry per top-level \includegraphics (plus a possible
        # leading caption-only entry), each [image, caption, label, numbered].
        panels: list[list] = []
        self._collect_figure_parts(node.nodelist, fig, top=True, panels=panels)
        img_panels = [p for p in panels if p[0] is not None]
        if fig.subfigures or len(img_panels) <= 1:
            if fig.image is None and not fig.subfigures and not _has_opaque_env(fig.source):
                # No graphic and no drawing env: the figure *is* its body
                # (tcolorboxes, minipage text, a tabular, a listing, …). Render
                # that content above the caption instead of dropping it.
                fig.blocks = self._figure_body_blocks(node.nodelist)
            if fig.image is None and not fig.subfigures and not fig.blocks:
                if _has_opaque_env(fig.source):
                    # a drawing: the writer compiles it, and warns (with the
                    # reason) only when it cannot
                    self.report.info("figure", "figure drawn with TikZ/PGF")
                else:
                    self.report.warn("figure", "figure without convertible graphics")
            self._labelable = fig
            out.append(fig)
            return
        # Several \includegraphics in one figure: LaTeX steps the figure counter
        # at each \caption, so emit one numbered figure per image+caption panel
        # (each with its own \label) instead of silently keeping only the last.
        for image, caption, label, numbered in panels:
            if image is None and caption is None:
                continue
            out.append(ir.Figure(
                image=image, source="", spanning=spanning,
                caption=caption, label=label, caption_numbered=numbered,
            ))
        self._labelable = None  # a trailing \label would be ambiguous across panels

    def _figure_body_blocks(self, nodes: list) -> list[ir.Block]:
        """Parse a graphic-less figure body into blocks. The caption/label were
        already collected, so ``\\caption`` is suppressed and the label target is
        detached (a body ``\\label`` must not re-attach to an earlier block);
        layout-only paragraphs (``\\\\[4pt]``, ``\\hfill``) are dropped."""
        prev_flag, prev_target = self._in_figure_body, self._labelable
        self._in_figure_body, self._labelable = True, None
        try:
            blocks: list[ir.Block] = []
            segment: list = []
            i, n = 0, len(nodes)
            while i < n:
                if _is_minipage(nodes[i]):
                    # a run of sibling minipages (joined only by \hfill & co.)
                    # sits side by side in LaTeX -> one borderless layout row.
                    run, k, last = [nodes[i]], i + 1, i
                    while k < n and (_is_minipage(nodes[k]) or _is_layout_glue(nodes[k])):
                        if _is_minipage(nodes[k]):
                            run.append(nodes[k])
                            last = k
                        k += 1
                    if len(run) >= 2:
                        blocks.extend(self.blocks(segment))
                        segment = []
                        blocks.append(self._minipage_row(run))
                        i = last + 1
                        continue
                segment.append(nodes[i])
                i += 1
            blocks.extend(self.blocks(segment))
        finally:
            self._in_figure_body, self._labelable = prev_flag, prev_target
        return [b for b in blocks if not _is_blank_paragraph(b)]

    def _minipage_row(self, minipages: list) -> ir.Table:
        """Side-by-side minipages -> a one-row borderless layout table, one cell
        per minipage holding its parsed body."""
        cells = [
            ir.TableCell(blocks=[b for b in self.blocks(mp.nodelist) if not _is_blank_paragraph(b)])
            for mp in minipages
        ]
        return ir.Table(rows=[ir.TableRow(cells)], colspec=["left"] * len(cells), layout=True)

    def _tcolorbox_quote(self, node: LatexEnvironmentNode, base: str) -> ir.Quote:
        """A ``tcolorbox`` (or a ``\\newtcolorbox`` env) -> a coloured callout.

        Options are resolved in tcolorbox order: the env definition (with its
        ``#1..#n`` replaced by the ``\\begin{box}{…}`` arguments), then any
        ``\\begin{tcolorbox}[…]`` options; bare keys naming a ``\\tcbset`` style
        expand that style. Unset colours fall back to tcolorbox's defaults."""
        texts: list[str] = []
        env = self.tcb_envs.get(base)
        if env is not None:
            opts = env.opts
            for k, arg in enumerate(self._env_arg_texts(node, env), 1):
                opts = opts.replace(f"#{k}", arg)
            texts.append(opts)
        if base == "tcolorbox":
            texts.append(_graphics_option_text(node))
        eff = self._tcb_resolve(texts)

        def colour(key: str, default: str) -> str | None:
            spec = eff.get(key) or default
            return self.colors.resolve(spec, None)

        shade = colour("colback", "black!5!white")
        border = colour("colframe", "black!75!white")
        if _length_to_emu(eff.get("boxrule", "1pt")) == 0:
            border = shade  # boxrule=0pt: no visible frame
        title = None
        title_shade = None
        if eff.get("title"):
            title = self._fragment_inlines(eff["title"])
            if "\\bfseries" in eff.get("fonttitle", ""):
                title = [ir.Emphasis(title, "bold")]
            title = [ir.Colored(title, fg=colour("coltitle", "white"))]
            title_shade = colour("colbacktitle", eff.get("colframe") or "black!75!white")
        return ir.Quote(
            self.blocks(node.nodelist), shade=shade, border=border,
            title=title, title_shade=title_shade,
        )

    def _env_arg_texts(self, node: LatexEnvironmentNode, env: _TcbEnv) -> list[str]:
        """Raw LaTeX of a user env's ``\\begin`` arguments (optional first arg
        falls back to its declared default)."""
        args = list(node.nodeargd.argnlist) if node.nodeargd else []
        texts: list[str] = []
        for a in args[: env.nargs]:
            if a is None:
                texts.append("")
                continue
            v = a.latex_verbatim().strip()
            if v[:1] in "{[" and v[-1:] in "}]":
                v = v[1:-1]
            texts.append(v)
        if env.default is not None and (not texts or not texts[0]):
            texts[:1] = [env.default]
        return texts

    def _tcb_resolve(self, texts: list[str]) -> dict[str, str]:
        eff: dict[str, str] = {}

        def apply(raw: str, depth: int) -> None:
            if depth > 8:  # guard against self-referencing styles
                return
            for key, val in _kv_list(raw):
                if val is None:
                    if key in self.tcb_styles:
                        apply(self.tcb_styles[key], depth + 1)
                elif key in _TCB_KEYS:
                    eff[key] = _strip_braces(val)

        for t in texts:
            if t:
                apply(t, 0)
        return eff

    def _fragment_inlines(self, latex: str) -> list[ir.Inline]:
        """Parse a LaTeX fragment (e.g. a box title) into inlines."""
        try:
            nodes, _, _ = LatexWalker(
                latex, latex_context=self.ctx, tolerant_parsing=True
            ).get_latex_nodes()
        except Exception:  # never let a title abort the conversion
            return [ir.Text(latex)]
        return _clean_inlines(self.inlines(nodes), trim=True)

    def _collect_figure_parts(
        self, nodes: list, fig: ir.Figure, top: bool, panels: list | None = None
    ) -> None:
        """Walk a figure body, pulling out the parent image/caption/label and
        any ``subfigure`` environments / ``\\subfloat`` commands. Top-level
        ``\\includegraphics``/``\\caption``/``\\label`` are also recorded, in order,
        into ``panels`` so a multi-image figure keeps every panel."""
        for child in nodes:
            if isinstance(child, LatexEnvironmentNode):
                if child.environmentname.rstrip("*") == "subfigure":
                    fig.subfigures.append(self._subfigure_from_env(child))
                elif child.environmentname.rstrip("*") in _OPAQUE_ENVS:
                    # a drawing's own macros are not the figure's: TikZ's
                    # \foreach \label/\value in {...} must not become its label
                    continue
                else:
                    self._collect_figure_parts(child.nodelist, fig, top=False, panels=panels)
            elif isinstance(child, LatexGroupNode):
                self._collect_figure_parts(child.nodelist, fig, top=False, panels=panels)
            elif isinstance(child, LatexMacroNode):
                if child.macroname in ("subfloat", "subfigure"):
                    fig.subfigures.append(self._subfigure_from_macro(child))
                elif child.macroname == "includegraphics":
                    img = _make_image(child)
                    fig.image = img
                    if panels is not None:
                        panels.append([img, None, None, True])
                elif child.macroname in ("caption", "captionof"):
                    cap = self.inlines(_group_nodes(child))
                    numbered = not _has_star(child)
                    fig.caption = cap
                    fig.caption_numbered = numbered
                    if panels is not None:
                        if panels and panels[-1][1] is None:
                            panels[-1][1] = cap
                            panels[-1][3] = numbered
                        else:
                            panels.append([None, cap, None, numbered])
                elif child.macroname == "label":
                    lab = _chars_of(_group_nodes(child))
                    if fig.label is None:
                        fig.label = lab
                    if panels is not None and panels:
                        panels[-1][2] = lab

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
        # \subfloat[Caption\label{fig:a}]{...}: the label sits in the caption
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
                for child in _walk_macros(a.nodelist):
                    if child.macroname == "label":
                        sub.label = _chars_of(_group_nodes(child))
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
        panels = [
            n for n in node.nodelist
            if isinstance(n, LatexEnvironmentNode)
            and n.environmentname in ("minipage", "subtable") and _has_caption(n.nodelist)
        ]
        if len(panels) >= 2:
            self._table_panels(node, panels, out, spanning)
            return
        caption: list[ir.Inline] | None = None
        caption_numbered = True
        caption_above = False
        label: str | None = None
        content: list = []
        for child in _unwrap_table_layout(node.nodelist):
            if isinstance(child, LatexMacroNode) and child.macroname == "caption":
                caption = self.inlines(_group_nodes(child))
                caption_numbered = not _has_star(child)
                caption_above = not any(_is_table_body(c) for c in content)
            elif (
                isinstance(child, LatexMacroNode) and child.macroname == "captionof"
                and caption is None and _has_captionof([child], "table")
            ):
                # \captionof{table}{...} inside the float (the rotated-minipage
                # landscape idiom) is the float's caption
                caption = self.inlines(_group_nodes(child))
                caption_numbered = not _has_star(child)
            elif isinstance(child, LatexMacroNode) and child.macroname == "label":
                lab = _chars_of(_group_nodes(child))
                if label is None:
                    label = lab
                elif lab and lab != label:
                    self.label_aliases.setdefault(lab, label)
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
        tables[0].caption_above = caption is not None and caption_above
        tables[0].label = label
        tables[0].spanning = spanning
        self._labelable = tables[0]
        out.extend(sub_blocks)

    def _listing_float(self, node: LatexEnvironmentNode, out: list[ir.Block]) -> None:
        """minted's ``listing`` float: its caption and label go to the code."""
        caption: list[ir.Inline] | None = None
        numbered = True
        label: str | None = None
        content = []
        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "caption":
                caption, numbered = self.inlines(_group_nodes(child)), not _has_star(child)
            elif isinstance(child, LatexMacroNode) and child.macroname == "label":
                label = label or _chars_of(_group_nodes(child))
            else:
                content.append(child)
        blocks = self.blocks(content)
        code = next((b for b in blocks if isinstance(b, ir.CodeBlock)), None)
        if code is not None:
            code.caption, code.label, code.caption_numbered = caption, label, numbered
        out.extend(blocks)

    def _table_panels(
        self, node: LatexEnvironmentNode, panels: list, out: list[ir.Block], spanning: bool
    ) -> None:
        """Several captioned minipages/subtables in one ``table``: each panel is
        a table with its own caption and label. With an overall caption too
        (subtables), that caption numbers the first panel and the panels'
        own captions become "(a) ..." lines."""
        outer_caption: list[ir.Inline] | None = None
        outer_label: str | None = None
        outer_above = False
        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "caption":
                outer_caption = self.inlines(_group_nodes(child))
                # written before the first panel -> printed above the panels
                outer_above = panels[0] not in node.nodelist[: node.nodelist.index(child)]
            elif isinstance(child, LatexMacroNode) and child.macroname == "label":
                outer_label = outer_label or _chars_of(_group_nodes(child))
        first_table: ir.Table | None = None
        for i, panel in enumerate(panels):
            sub: list[ir.Block] = []
            self._table_float(panel, sub, spanning)
            tables = [b for b in sub if isinstance(b, ir.Table)]
            if outer_caption is not None and tables:
                t = tables[0]
                letter = chr(ord("a") + i)
                if t.caption:  # the panel's caption becomes its "(a) ..." line
                    t.subcaption = [ir.Text(f"({letter}) "), *t.caption]
                    t.subcaption_above = t.caption_above
                t.caption = None
                t.caption_above = False
                if t.label and outer_label:  # \ref{sub-label} -> "1a"
                    self.sub_labels.setdefault(t.label, [outer_label, letter])
                t.label = None
            if first_table is None and tables:
                first_table = tables[0]
            out.extend(sub)
        if outer_caption is not None and first_table is not None:
            first_table.caption = outer_caption
            first_table.caption_above = outer_above
            first_table.label = outer_label
            self._labelable = first_table

    def _tabular(self, node: LatexEnvironmentNode) -> ir.Table:
        # column spec is the first mandatory group argument of the environment
        colspec, colwidths = _parse_colspec(_env_colspec(node))
        booktabs = "\\toprule" in node.latex_verbatim() or "\\midrule" in node.latex_verbatim()
        nodes = node.nodelist
        caption: list[ir.Inline] | None = None
        label: str | None = None
        if getattr(node, "environmentname", "") == "longtable":
            nodes, caption, label = self._longtable_prep(nodes)
        rows = self._tabular_rows(nodes, len(colspec) or 1, colspec)
        _format_numeric_cells(rows, _numeric_columns(_env_colspec(node)))
        return ir.Table(
            rows=rows, colspec=colspec, booktabs=booktabs, colwidths=colwidths,
            caption=caption, label=label,
        )

    def _longtable_prep(
        self, nodes: list
    ) -> tuple[list, list[ir.Inline] | None, str | None]:
        """Prepare a ``longtable`` body for the generic row parser.

        Pull out the ``\\caption``/``\\label`` (so the caption doesn't leak as a
        row of literal text), and split on the header/footer markers
        ``\\endfirsthead``/``\\endhead``/``\\endfoot``/``\\endlastfoot`` — keeping a
        single header block (the repeatable ``\\endhead`` one, else the
        ``\\endfirsthead`` one) plus the body rows, and dropping the duplicate
        first-page header and the foot rows.
        """
        marker = {
            "endfirsthead": "firsthead", "endhead": "head",
            "endfoot": "foot", "endlastfoot": "lastfoot",
        }
        sections: dict[str, list] = {}
        markers: dict[str, object] = {}  # the delimiter node that closed each section
        caption: list[ir.Inline] | None = None
        label: str | None = None
        buf: list = []
        for child in nodes:
            if isinstance(child, LatexMacroNode) and child.macroname in marker:
                sections[marker[child.macroname]] = buf
                markers[marker[child.macroname]] = child
                buf = []
                continue
            if isinstance(child, LatexMacroNode) and child.macroname == "caption":
                if caption is None:
                    caption = self.inlines(_group_nodes(child))
                continue  # never keep the caption node among the table rows
            if isinstance(child, LatexMacroNode) and child.macroname == "label":
                if label is None:
                    label = _chars_of(_group_nodes(child)).strip()
                continue
            buf.append(child)
        sections["body"] = buf
        src = "head" if "head" in sections else "firsthead" if "firsthead" in sections else None
        if src is None:
            return sections["body"], caption, label
        # re-append the section's delimiter so the row parser marks the header
        # rows (the header block may carry no \midrule of its own).
        return sections[src] + [markers[src]] + sections["body"], caption, label

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


#: classes whose \maketitle prints no date at all (\date is ignored)
_NO_DATE_CLASSES = {"IEEEtran", "ieeeconf", "llncs", "acmart", "sn-jnl"}
#: classes that print a date only when \date is given (no default \today)
_NO_DEFAULT_DATE_CLASSES = {"amsart", "amsproc", "amsbook"}
#: classes that set the abstract's name run-in ("Abstract." before the text)
_ABSTRACT_RUNIN = {"amsart", "amsproc", "amsbook", "llncs", "svjour3", "svmult", "lipics-v2021",
                   "smfart"}
#: classes whose abstract has no heading of its own
_ABSTRACT_NONE = {"letter", "moderncv", "beamer", "revtex4", "revtex4-1", "revtex4-2"}
#: \abstractname under babel/polyglossia/ctex, by BCP-47 language
_ABSTRACT_NAMES = {
    "de": "Zusammenfassung", "fr": "Résumé", "es": "Resumen", "it": "Sommario",
    "pt": "Resumo", "nl": "Samenvatting", "ru": "Аннотация", "pl": "Streszczenie",
    "zh": "摘要", "ja": "概要", "ko": "요약",
}


def _abstract_heading(doc_class: str, source: str, language: str | None) -> tuple[str, str]:
    """The abstract's name and how the class prints it."""
    m = re.search(r"\\(?:re)?newcommand\*?\s*\{?\\abstractname\}?\s*\{([^{}]*)\}", source) \
        or re.search(r"\\def\\abstractname\s*\{([^{}]*)\}", source)
    if m:
        name = m.group(1).strip()
    elif doc_class.startswith("ctex"):
        name = "摘要"
    else:
        name = _ABSTRACT_NAMES.get((language or "").split("-")[0].lower(), "Abstract")
    if doc_class in _ABSTRACT_NONE:
        return name, "none"
    if doc_class == "IEEEtran":
        return name, "dash"
    if doc_class in _ABSTRACT_RUNIN:
        return name, "runin"
    return name, "block"


_CREFNAME_RE = re.compile(r"\\(crefname|Crefname)\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}")


def _cleveref_setup(preamble: str) -> dict:
    """cleveref's package options and ``\\crefname``/``\\Crefname`` overrides."""
    options: list[str] = []
    for opts, pkgs in re.findall(r"\\usepackage\s*\[([^\]]*)\]\s*\{([^}]*)\}", preamble):
        if "cleveref" in [p.strip() for p in pkgs.split(",")]:
            options += [o.strip() for o in opts.split(",") if o.strip()]
    names: dict[str, dict[str, list[str]]] = {"crefname": {}, "Crefname": {}}
    for cmd, kind, singular, plural in _CREFNAME_RE.findall(preamble):
        names[cmd][kind.strip()] = [singular.strip(), plural.strip()]
    return {"options": options, **names}


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


_LABEL_TAG_RE = re.compile(r"\\(?:label|tag|nonumber|notag)\b\*?\s*(?:\{[^{}]*\})?")
_TAG_RE = re.compile(r"\\tag(\*?)\s*\{([^{}]*)\}")


def _line_tag(segment: str) -> str | None:
    """What replaces a display line's number: None (numbered as usual), ""
    (\\notag/\\nonumber), "(A)" for \\tag{A}, "A" for \\tag*{A}."""
    m = _TAG_RE.search(segment)
    if m:
        text = m.group(2).strip()
        return text if m.group(1) else f"({text})"
    if re.search(r"\\(?:nonumber|notag)\b", segment):
        return ""
    return None


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


def _is_table_body(node) -> bool:
    """A float child that is (or wraps) the table itself, not caption material."""
    if isinstance(node, LatexEnvironmentNode):
        return True
    return isinstance(node, LatexMacroNode) and node.macroname in (
        "resizebox", "scalebox", "adjustbox", "rotatebox", "input", "include")


def _format_numeric_cells(rows: list[ir.TableRow], columns: set[int]) -> None:
    """siunitx ``S`` columns print their numbers formatted (``12345`` -> ``12 345``);
    header text in braces stays as written."""
    if not columns:
        return
    for row in rows:
        col = 0
        for cell in row.cells:
            if col in columns and len(cell.blocks) == 1 and isinstance(cell.blocks[0],
                                                                       ir.Paragraph):
                inl = cell.blocks[0].inlines
                if len(inl) == 1 and isinstance(inl[0], ir.Text):
                    inl[0].value = siunitx.num_to_text(inl[0].value)
            col += cell.colspan


def _colspec_columns(spec: str) -> list[tuple[str, str, float | None]]:
    """The columns of a tabular spec as ``(type, alignment, EMU width or None)``.

    ``type`` is the column letter (``l``, ``p``, ``X``, ``S``, ...). ``@{..}``,
    ``!{..}``, ``<{..}`` and option brackets are skipped (their contents are
    not columns: ``@{\hspace{1cm}}``, ``S[table-format=2.2]``), and
    ``*{n}{spec}`` repeats ``spec``."""
    out: list[tuple[str, str, float | None]] = []
    pending_align: str | None = None  # set by a >{...} column processor
    i = 0
    while i < len(spec):
        c = spec[i]
        nxt = spec[i + 1] if i + 1 < len(spec) else ""
        if c == ">" and nxt == "{":
            body, i = _braced_group(spec, i + 1)
            for key, al in _COL_PROCESSOR_ALIGN.items():
                if f"\\{key}" in body:
                    pending_align = al
            i += 1
            continue
        if c in "@!<" and nxt == "{":
            _, i = _braced_group(spec, i + 1)
            i += 1
            continue
        if c == "*" and nxt == "{":
            count, i = _braced_group(spec, i + 1)
            if i + 1 < len(spec) and spec[i + 1] == "{":
                inner, i = _braced_group(spec, i + 1)
                out.extend(_colspec_columns(inner) * max(0, _int_or_default(count, 1)))
            i += 1
            continue
        if c == "[":  # options of the previous column (S[...], X[...])
            close = spec.find("]", i)
            i = len(spec) if close < 0 else close + 1
            continue
        if c in "lcr":
            out.append((c, pending_align or {"l": "left", "c": "center", "r": "right"}[c], None))
            pending_align = None
        elif c == "X":
            # tabularx flexible column: a paragraph column that fills the
            # remaining width. Count it (so cells line up) with an auto width;
            # a >{\raggedright}X etc. supplies the alignment.
            out.append((c, pending_align or "left", None))
            pending_align = None
        elif c in "LCRJ":
            # tabulary auto-width columns (L/C/R = left/centre/right, J = justify)
            out.append((c, pending_align or {"L": "left", "C": "center", "R": "right",
                                             "J": "left"}[c], None))
            pending_align = None
        elif c == "S":  # siunitx number column (aligned on the decimal marker)
            out.append((c, pending_align or "center", None))
            pending_align = None
        elif c == "D" and nxt == "{":  # dcolumn: D{sep}{out}{places}
            for _ in range(3):
                if i + 1 < len(spec) and spec[i + 1] == "{":
                    _, i = _braced_group(spec, i + 1)
            out.append((c, pending_align or "center", None))
            pending_align = None
        elif c in "pmb" and nxt == "{":
            body, i = _braced_group(spec, i + 1)
            out.append((c, pending_align or "left", _length_to_emu(body)))
            pending_align = None
        # ignore |, spaces, unknown letters
        i += 1
    return out


def _parse_colspec(spec: str) -> tuple[list, list[float | None]]:
    """Parse a column spec into (alignments, per-column EMU widths or None)."""
    cols = _colspec_columns(spec)
    return [a for _, a, _ in cols], [w for _, _, w in cols]


def _numeric_columns(spec: str) -> set[int]:
    """Indices of siunitx ``S`` columns (their numbers are formatted)."""
    return {i for i, (t, _, _) in enumerate(_colspec_columns(spec)) if t == "S"}


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


# Lengths expressed relative to the running document's text box. The parser has
# no LaTeX run, so these resolve against the output page geometry in the backend.
_REL_WIDTH_REFS = ("\\textwidth", "\\linewidth", "\\columnwidth", "\\hsize")
_REL_HEIGHT_REFS = ("\\textheight", "\\paperheight", "\\vsize")


def _length_spec(value: str) -> tuple[float | None, float | None, float | None]:
    """Parse an ``\\includegraphics`` width/height value into
    ``(abs_emu, rel_width_fraction, rel_height_fraction)``. A relative length such
    as ``0.5\\textwidth`` yields ``rel_width_fraction=0.5``; a bare ``\\linewidth``
    yields ``1.0``; an absolute length yields ``abs_emu``."""
    value = value.strip()

    def frac(ref: str) -> float:
        num = value.replace(ref, "").strip()
        if num in ("", "+", "-"):
            return 1.0
        try:
            return float(num)
        except ValueError:
            return 1.0

    for ref in _REL_WIDTH_REFS:
        if ref in value:
            return (None, frac(ref), None)
    for ref in _REL_HEIGHT_REFS:
        if ref in value:
            return (None, None, frac(ref))
    return (_length_to_emu(value), None, None)


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
            abs_emu, rw, _ = _length_spec(parsed["width"])
            image.width = abs_emu
            image.rel_width = rw
        if "height" in parsed:
            abs_emu, _, rh = _length_spec(parsed["height"])
            image.height = abs_emu
            image.rel_height = rh
        if "keepaspectratio" in parsed:
            image.keep_aspect = True
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
    # \"{\i} is an i with a diaeresis: the dotless form exists only to take one
    first = {"ı": "i", "ȷ": "j"}.get(base[0], base[0])
    return unicodedata.normalize("NFC", first + comb + base[1:])


def _change_case(inlines: list, *, upper: bool) -> None:
    """Upper-/lower-case the text of ``inlines`` in place (math is left alone)."""
    for n in inlines:
        if isinstance(n, ir.Text):
            n.value = n.value.upper() if upper else n.value.lower()
        elif hasattr(n, "inlines") and not isinstance(n, ir.Footnote):
            _change_case(n.inlines, upper=upper)


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


@dataclass
class _TcbEnv:
    """A ``\\newtcolorbox{name}[nargs][default]{options}`` definition."""

    nargs: int = 0
    default: str | None = None  # default of an optional first argument
    opts: str = ""              # raw option text (may reference #1..#n)


_NEWTCB_HEAD_RE = re.compile(r"\\(?:re)?newtcolorbox(?![A-Za-z])")
#: tcolorbox keys that shape the rendered callout; everything else is layout.
_TCB_KEYS = frozenset({
    "colback", "colframe", "colbacktitle", "coltitle", "title", "fonttitle", "boxrule",
})


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _read_bracket(s: str, i: int) -> tuple[str, int]:
    """Read a brace-aware ``[...]`` group at ``s[i] == '['``; (inner, index-after)."""
    depth = 0
    for j in range(i + 1, len(s)):
        c = s[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "]" and depth == 0:
            return s[i + 1:j], j + 1
    return s[i + 1:], len(s)


def _strip_braces(value: str) -> str:
    """Drop one level of braces wrapping a whole value (``{#1}`` -> ``#1``)."""
    v = value.strip()
    if len(v) >= 2 and v[0] == "{" and v[-1] == "}":
        inner, end = _braced_group(v, 0)
        if end == len(v) - 1:
            return inner.strip()
    return v


def _kv_list(opts: str) -> list[tuple[str, str | None]]:
    """Split a ``key=value,flag,...`` option list on top-level commas,
    preserving order and case (later keys override earlier ones)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in opts:
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
    out: list[tuple[str, str | None]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, _, val = part.partition("=")
            out.append((key.strip(), val.strip()))
        else:
            out.append((part, None))
    return out


def _collect_tcolorbox_defs(source: str) -> tuple[dict[str, _TcbEnv], dict[str, str]]:
    """``\\newtcolorbox`` environments and ``\\tcbset{name/.style={...}}`` styles."""
    envs: dict[str, _TcbEnv] = {}
    for m in _NEWTCB_HEAD_RE.finditer(source):
        i = _skip_ws(source, m.end())
        if i < len(source) and source[i] == "[":  # [init options]
            _, i = _read_bracket(source, i)
            i = _skip_ws(source, i)
        if i >= len(source) or source[i] != "{":
            continue
        name, end = _braced_group(source, i)
        i = _skip_ws(source, end + 1)
        nargs, default = 0, None
        if i < len(source) and source[i] == "[":
            n, i = _read_bracket(source, i)
            i = _skip_ws(source, i)
            try:
                nargs = int(n.strip())
            except ValueError:
                nargs = 0
            if i < len(source) and source[i] == "[":
                default, i = _read_bracket(source, i)
                i = _skip_ws(source, i)
        opts = _braced_group(source, i)[0] if i < len(source) and source[i] == "{" else ""
        if name.strip():
            envs[name.strip()] = _TcbEnv(nargs, default, opts)
    styles: dict[str, str] = {}
    for m in re.finditer(r"\\tcbset\s*\{", source):
        body, _ = _braced_group(source, m.end() - 1)
        for key, val in _kv_list(body):
            if key.endswith("/.style") and val is not None:
                styles[key[: -len("/.style")].strip()] = _strip_braces(val)
    return envs, styles


def _tcb_argspec(env: _TcbEnv) -> str:
    """pylatexenc argument spec for a user tcolorbox env (``[`` = optional)."""
    if env.nargs <= 0:
        return ""
    if env.default is not None:
        return "[" + "{" * (env.nargs - 1)
    return "{" * env.nargs


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
    r"\{((?:[^{}]|\{[^{}]*\})*)\}(?:[ \t]*\[([^\]]*)\])?"
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


def _collect_theorem_within(source: str) -> dict[str, str]:
    """Theorem env -> the division its counter resets in
    (``\\newtheorem{thm}{Theorem}[section]`` -> ``{"thm": "section"}``); an env
    sharing another's counter inherits its reset."""
    within: dict[str, str] = {}
    shared: dict[str, str] = {}
    for m in _NEWTHEOREM_RE.finditer(source):
        name = m.group(2).strip()
        if m.group(3):
            shared[name] = m.group(3).strip()
        elif m.group(5):
            within[name] = m.group(5).strip()
    for name, root in shared.items():
        seen = {name}
        while root in shared and root not in seen:
            seen.add(root)
            root = shared[root]
        if root in within:
            within[name] = within[root]
    return within


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


def _build_context(
    extra_theorem_envs: tuple[str, ...] = (),
    extra_env_specs: tuple[tuple[str, str], ...] = (),
):
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
            # \captionof*{type}[short]{long} (caption / capt-of packages)
            MacroSpec("captionof", "*{[{"),
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
            # \pageref (and the cleveref/varioref page/label variants) had no
            # spec: the label was left behind as text and the ref unresolved
            MacroSpec("pageref", "*{"), MacroSpec("vref", "*{"), MacroSpec("vpageref", "*{"),
            MacroSpec("cpageref", "{"), MacroSpec("Cpageref", "{"),
            MacroSpec("labelcref", "{"),
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
            MacroSpec("inst", "{"),
            MacroSpec("tnote", "{"),
            MacroSpec("subref", "*{"),
            MacroSpec("twlistingcaption", "{{{"),  # emitted by preprocess (listings)
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
            MacroSpec("scalebox", "{[{"),
            MacroSpec("rotatebox", "[{{"),
            MacroSpec("parbox", "[[[{{"),
            MacroSpec("foreignlanguage", "[{{"),
            MacroSpec("selectlanguage", "{"),
            MacroSpec("MakeUppercase", "{"), MacroSpec("MakeLowercase", "{"),
            MacroSpec("MakeTextUppercase", "{"), MacroSpec("MakeTextLowercase", "{"),
            MacroSpec("makecell", "[{"),
            MacroSpec("thead", "[{"),
            MacroSpec("path", "{"),
            MacroSpec("nolinkurl", "{"),
            MacroSpec("typeout", "{"),
            MacroSpec("twocolumn", "["),
            MacroSpec("subjclass", "[{"),
            MacroSpec("setlength", "{{"), MacroSpec("addtolength", "{{"),
            MacroSpec("settowidth", "{{"), MacroSpec("settoheight", "{{"),
            MacroSpec("settodepth", "{{"), MacroSpec("deflength", "{{"),
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
            MacroSpec("authornote", "{"),
            MacroSpec("texorpdfstring", "{{"),
            MacroSpec("labelcref", "{"),
            MacroSpec("nameref", "{"),
            MacroSpec("Nameref", "{"),
            MacroSpec("title", "[{"),  # \title[running head]{full title}
            # journal-class front matter (frontend/frontmatter.py)
            *(MacroSpec(n, a) for n, a in _FRONT_SPECS),
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
        ] + [
            EnvironmentSpec("subfigure", "[{"), EnvironmentSpec("subtable", "[{")
        ] + [EnvironmentSpec("minipage", "[{")] + [
            EnvironmentSpec(name, "[")
            for name in ("algorithmic", "algorithmicx", "algpseudocode", "algpseudocodex")
        ] + [
            # tabularx/tabulary carry a leading {width}; supertabular/xtabular take
            # just the {colspec}. Declaring the args keeps them out of the body.
            EnvironmentSpec("tabularx", "{[{"), EnvironmentSpec("tabulary", "{[{"),
            # \begin{tabular}[t]{..}: the [pos] argument (pylatexenc knows only
            # {colspec}, so "[t]" leaked into the first cell as "t]")
            EnvironmentSpec("tabular", "[{"), EnvironmentSpec("tabular*", "{[{"),
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
            # adjustbox env: \begin{adjustbox}{width=\textwidth} -- the keys are
            # not content; multicols: \begin{multicols}{2}[heading]
            EnvironmentSpec("adjustbox", "{"), EnvironmentSpec("multicols", "{["),
            EnvironmentSpec("multicols*", "{["), EnvironmentSpec("otherlanguage", "{"),
            EnvironmentSpec("otherlanguage*", "{"), EnvironmentSpec("IEEEbiography", "[{"),
            EnvironmentSpec("IEEEbiographynophoto", "{"),
        ] + [
            # user \newtcolorbox envs that take arguments (\begin{box}{title}):
            # declare them so the args are consumed, not parsed as body text.
            EnvironmentSpec(name, spec) for name, spec in extra_env_specs if spec
        ],
        prepend=True,
    )
    return ctx


_KERNEL_COMMANDS = frozenset({
    "LaTeX", "TeX", "LaTeXe", "today", "textbf", "textit", "emph", "texttt", "textrm",
    "textsf", "textsc", "underline", "footnote", "caption", "label", "ref", "cite", "url",
    "href", "item", "section", "includegraphics", "maketitle", "title", "author", "date",
    "frac", "sqrt", "mathbb", "mathbf", "mathrm", "mathcal", "text", "hspace", "vspace",
    "newline", "par", "quad", "qquad", "ldots", "dots", "cdots", "alpha", "beta", "gamma",
})


def _known_commands() -> frozenset[str]:
    """Commands the converter itself handles (``\\providecommand`` keeps them)."""
    return _KERNEL_COMMANDS | frozenset(
        [*_SECTION_LEVELS, *_EMPHASIS, *_EMPHASIS_DECL, *_FONT_SIZE_HP, *_CITE_MODES,
         *_REF_KINDS, *_TEXT_SYMBOLS, *_IGNORE_MACROS, *_TRANSPARENT_BOX]
    )


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


#: preamble commands some classes use to place a captioned teaser figure on the
#: title page (thuc3i's \pretitlefigure, a few arXiv templates' \teaserfigure).
_TEASER_MACROS = ("pretitlefigure", "teaserfigure", "titlefigure")


def _preamble_teaser_blocks(preamble: str, ctx, builder: _Builder) -> list[ir.Block]:
    """Parse a preamble teaser-figure command's body into blocks (best effort)."""
    out: list[ir.Block] = []
    for macro in _TEASER_MACROS:
        content = _braced_content(preamble, macro)
        if not content:
            continue
        try:
            nodes, _, _ = LatexWalker(content, latex_context=ctx, tolerant_parsing=True
                                      ).get_latex_nodes()
        except Exception:  # never let a class-specific teaser abort the conversion
            continue
        out.extend(b for b in builder.blocks(nodes) if not _is_blank_paragraph(b))
    return out


def _running_head_from_preamble(preamble: str) -> str | None:
    """Recover a running head declared in the preamble (best effort, plain text)."""
    m = re.search(r"\\title\s*\[([^\]]*)\]", preamble)  # \title[short]{long}
    if m:
        return _normalize_ws(m.group(1)).strip() or None
    for macro in ("runninghead", "shorttitle", "markright", "setheadertext",
                  "titlerunning", "runningtitle"):
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
    expanded = replace_inline_tikz(
        expand_macros(preprocess(source, base_dir), base_dir, known=_known_commands())
    )
    expanded = resolve_counters(expanded)  # \newcounter values: \arabic{c}, \thec, ...
    # after expansion, so macro-generated \vskip/\faX are cleaned up too
    expanded = normalize_spacing_and_icons(expanded)
    body, preamble = _split_document(expanded)
    # \newtheorem declarations may live in a \usepackage'd local .sty (e.g. a
    # paper's MyPreamble.sty), which macro expansion harvests but doesn't inline;
    # scan those sources too so the theorem environments are recognised.
    theorem_src = expanded + "\n" + local_package_sources(source, base_dir)
    custom_theorems, unnumbered_theorems, shared_counters = _collect_newtheorems(theorem_src)
    tcb_envs, tcb_styles = _collect_tcolorbox_defs(theorem_src)
    ctx = _build_context(
        tuple(custom_theorems),
        tuple((name, _tcb_argspec(env)) for name, env in tcb_envs.items()),
    )
    walker = LatexWalker(body, latex_context=ctx, tolerant_parsing=True)
    nodes, _, _ = walker.get_latex_nodes()

    builder = _Builder(report)
    builder.ctx = ctx
    builder.theorem_envs.update(custom_theorems)
    builder.unnumbered_theorems = unnumbered_theorems
    builder.theorem_counters = _resolve_theorem_counters(custom_theorems, shared_counters)
    builder.theorem_within = _collect_theorem_within(theorem_src)
    builder.box_envs = _collect_tcolorbox_envs(theorem_src)  # \newtcolorbox callouts
    builder.tcb_envs, builder.tcb_styles = tcb_envs, tcb_styles
    builder.box_styles = _collect_mdframed_envs(theorem_src)  # \newmdenv callouts (+colours)
    builder.box_envs |= set(builder.box_styles)
    siunitx.configure(_sisetup(expanded))  # number format for \num/\SI/S columns
    builder.alg_noend, builder.alg2e_numbered = _algorithm_options(expanded)
    builder.book_mode = _is_book_class(expanded)
    cls = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", expanded)
    builder.doc_class = cls.group(1).strip() if cls else "article"
    if builder.doc_class in ("letter", "moderncv"):
        # sender address / signature / CV contact lines live in the preamble
        _fill_meta_from_preamble_calls(preamble, ctx, builder, only=(
            "address", "signature", "name", "title", "phone", "mobile", "homepage",
            "social", "extrainfo", "email"))
    for m in _SUBJCLASS_NAME_RE.finditer(source):  # before \@namedef is expanded
        builder.subjclass_names[m.group(1).strip()] = m.group(2).strip()
    _collect_color_defs(expanded, builder.colors)  # \definecolor/\colorlet (preamble + body)
    _collect_acronyms(expanded, builder.acronyms)   # \newacronym (preamble + body)
    _collect_glossary_entries(expanded, builder.glossary)  # \newglossaryentry terms
    # A class-level teaser figure declared in the preamble (\pretitlefigure{…}):
    # it is page-1 content, so parse it first and lead the body with it.
    teaser = _preamble_teaser_blocks(preamble, ctx, builder)
    blocks = teaser + builder.blocks(nodes)
    doc = ir.Document(blocks=blocks, meta=builder.meta, book=builder.book_mode,
                      label_aliases=builder.label_aliases, sub_labels=builder.sub_labels,
                      cref=_cleveref_setup(preamble))

    _fill_meta_from_preamble(doc, preamble, ctx, report, builder)
    # LaTeX's \maketitle defaults an omitted \date to \today; mirror that when a
    # title is present but no \date was given (an explicit \date{} stays empty).
    if builder.doc_class in _NO_DATE_CLASSES:
        doc.meta.date = None  # their \maketitle never prints \date
    elif (doc.meta.date is None and doc.meta.title
          and builder.doc_class not in ("moderncv", *_NO_DEFAULT_DATE_CLASSES)):
        doc.meta.date = _default_date(source, builder)
    _collect_bib_resources(preamble, builder)  # biblatex \addbibresource (preamble)
    _detect_bib_style(preamble, builder)        # biblatex/natbib author-year option
    if doc.meta.language is None:
        doc.meta.language = _detect_language(preamble)  # babel/polyglossia -> BCP-47
    doc.meta.abstract_name, doc.meta.abstract_form = _abstract_heading(
        builder.doc_class, source, doc.meta.language)
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
    ``\\bibliographystyle`` set it (so author-year biblatex/natbib renders right).

    natbib's ``[numbers]`` option wins even over an author-year ``.bst`` such as
    ``plainnat``, as in LaTeX.
    """
    nb = re.search(r"\\usepackage\[([^\]]*)\]\{natbib\}", preamble)
    if nb and re.search(r"\bnumbers\b", nb.group(1).lower()):
        builder.bib_style = "numeric"
        return
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
    if nb and re.search(r"\bauthoryear\b", nb.group(1).lower()):
        builder.bib_style = "author-year"


def _collect_bib_resources(preamble: str, builder: _Builder) -> None:
    """Pick up biblatex ``\\addbibresource{file.bib}`` declared in the preamble."""
    for m in re.finditer(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]*)\}", preamble):
        for name in m.group(1).split(","):
            if name.strip() and name.strip() not in builder.bib_files:
                builder.bib_files.append(name.strip())


def _fill_meta_from_preamble(
    doc: ir.Document, preamble: str, ctx, report: ConversionReport, builder: _Builder,
) -> None:
    """Recover the title-page commands given in the preamble (best effort).

    Every call counts (authblk lists several ``\\author``/``\\affil`` lines);
    a kind of metadata the body already set is not overridden.
    """
    if doc.meta.running_head is None:
        doc.meta.running_head = _running_head_from_preamble(preamble)
    if builder.doc_class in ("letter", "moderncv"):
        return  # read before the body (see parse_document)
    meta = doc.meta
    skip = set()
    if meta.title is not None:
        skip.add("title")
    if meta.authors:
        skip.add("author")
    if meta.date is not None:
        skip.add("date")
    if meta.keywords is not None:
        skip.add("keywords")
    if meta.affiliations:
        skip |= {"institute", "affiliation", "affil", "address", "email", "orcid"}
    if meta.subtitle is not None:
        skip.add("subtitle")
    _fill_meta_from_preamble_calls(preamble, ctx, builder, skip=skip)


def _fill_meta_from_preamble_calls(
    preamble: str, ctx, builder: _Builder, *, skip: set[str] | frozenset[str] = frozenset(),
    only: tuple[str, ...] | None = None,
) -> None:
    for name, call in preamble_calls(preamble):
        if name in skip or (only is not None and name not in only):
            continue
        try:
            nodes, _, _ = LatexWalker(call, latex_context=ctx, tolerant_parsing=True
                                      ).get_latex_nodes()
        except Exception:  # never let a preamble oddity abort the conversion
            continue
        node = next((n for n in nodes if isinstance(n, LatexMacroNode)), None)
        if node is None:
            continue
        try:
            if builder.front_matter(node) is None:
                builder._meta_macro(node)
        except Exception:  # noqa: BLE001 - metadata is best effort
            builder.report.warn(f"\\{name}", "could not read the preamble command")


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
