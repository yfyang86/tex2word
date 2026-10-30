"""Intermediate Representation (IR) for the LaTeX -> Word pipeline.

The IR is the contract between the front-end (LaTeX parsing) and the back-ends
(OOXML generation). It is a typed, format-neutral document tree that keeps
original LaTeX source on non-trivial nodes for alt-text / round-trip, exactly
as the PRD requires.

Every node is a frozen-ish dataclass and is JSON-serialisable via
``to_dict``/``from_dict`` on :class:`Document`. The JSON form is used by golden
tests and, in a later sprint, as the seed for the round-trip manifest embedded
in the ``.docx``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

# --------------------------------------------------------------------------- #
# Node base + registry (for JSON (de)serialisation)
# --------------------------------------------------------------------------- #

_NODE_REGISTRY: dict[str, type[Node]] = {}


class Node:
    """Base for all IR nodes.

    Subclasses are dataclasses. A ``kind`` string (the class name) is written
    into the JSON form so the tree can be reconstructed without ambiguity.
    """

    #: filled in by ``__init_subclass__`` -- the discriminator used in JSON.
    node_kind: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.node_kind = cls.__name__
        _NODE_REGISTRY[cls.__name__] = cls


# --------------------------------------------------------------------------- #
# Inline nodes
# --------------------------------------------------------------------------- #

EmphasisKind = Literal[
    "italic", "bold", "underline", "smallcaps", "typewriter", "superscript",
    "subscript", "strike", "highlight",
]
CiteMode = Literal["paren", "text", "foot", "author", "year", "num"]
RefKind = Literal[
    "generic", "equation", "figure", "table", "section", "theorem", "page", "name",
    "listitem", "listing", "subref",
]


@dataclass
class Text(Node):
    value: str


@dataclass
class Emphasis(Node):
    inlines: list[Inline]
    kind_: EmphasisKind = "italic"


@dataclass
class Math(Node):
    """Inline math. Carries the raw (macro-expanded) LaTeX source."""

    latex: str


RefStyle = Literal["plain", "abbrev", "full", "eqref", "auto"]


@dataclass
class Ref(Node):
    """A cross-reference (``\\ref``/``\\eqref``/``\\cref``/``\\pageref``).

    ``bookmark`` is filled in by the cross-reference IR pass (Sprint 4).
    ``style``: ``plain`` (bare number, ``\\ref``), ``eqref`` (an equation
    number in parentheses: ``\\eqref``, ``\\labelcref``), ``abbrev``
    (cleveref's ``\\cref`` names, "fig. 1", "section 2"), ``full``
    (``\\Cref``: "Figure 1"), ``auto`` (hyperref's ``\\autoref``).
    ``more`` holds the further keys of a ``\\cref{a,b,c}``; ``is_range`` marks a
    ``\\crefrange{a}{b}`` (``more`` is ``[b]``).
    """

    key: str
    ref_kind: RefKind = "generic"
    bookmark: str | None = None
    style: RefStyle = "plain"
    more: list[str] = field(default_factory=list)
    is_range: bool = False


@dataclass
class Cite(Node):
    keys: list[str]
    mode: CiteMode = "paren"
    prefix: str | None = None
    suffix: str | None = None
    #: formatted in-text marker, filled by the citation pass (Sprint 5).
    rendered: str | None = None


@dataclass
class Link(Node):
    inlines: list[Inline]
    url: str
    anchor: str | None = None  # \hyperref[label]: internal bookmark target (raw label
    #: until resolved by the cross-reference transform, then the sanitized bookmark)


@dataclass
class LineBreak(Node):
    pass


@dataclass
class Footnote(Node):
    inlines: list[Inline]
    #: block content (lists, quotes, tables, several paragraphs); when set, the
    #: note is these blocks and ``inlines`` is empty
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Endnote(Node):
    inlines: list[Inline]


@dataclass
class IndexEntry(Node):
    """An ``\\index{term}`` marker -> a hidden Word ``XE`` index-entry field."""

    term: str


@dataclass
class Colored(Node):
    """Coloured inline content: ``fg`` text colour and/or ``bg`` shading.

    Both are 6-hex ``RRGGBB`` strings (``\\textcolor``/``\\color`` set ``fg``;
    ``\\colorbox`` sets ``bg``). ``None`` means "inherit / not set".
    """

    inlines: list[Inline]
    fg: str | None = None
    bg: str | None = None


@dataclass
class FontSize(Node):
    """A font-size span (``\\large`` … ``\\tiny``). ``half_points`` is ``w:sz``."""

    inlines: list[Inline]
    half_points: int = 24


@dataclass
class RawInline(Node):
    """Graceful-degradation escape hatch for inline constructs we can't model."""

    latex: str
    reason: str = "unsupported"


@dataclass
class Comment(Node):
    """A Word review comment, recovered from ``comments.xml`` at its anchor.

    Surfaced in LaTeX as a ``%`` line so a reviewer's note isn't lost on the way
    back (it carries no visible body text).
    """

    text: str
    author: str = ""


@dataclass
class Image(Node):
    """A raster/vector image. Used both as a block (in a Figure) and inline."""

    path: str
    width: float | None = None   # target width in EMU (from width=/scale=)
    height: float | None = None  # target height in EMU
    rel_width: float | None = None   # width as a fraction of the text column (0.5\textwidth)
    rel_height: float | None = None  # height as a fraction of the text height (0.3\textheight)
    keep_aspect: bool = False    # \includegraphics[...,keepaspectratio]
    original_format: str = ""
    scale: float | None = None   # \includegraphics[scale=]
    angle: float | None = None   # rotation in degrees (counter-clockwise)
    trim: list[float] | None = None  # [left, bottom, right, top] in EMU (trim=)
    clip: bool = False
    alt: str = ""                # alt-text / original source path (accessibility)


Inline = (
    Text | Emphasis | Math | Ref | Cite | Link | LineBreak | Footnote | Endnote
    | Colored | FontSize | Image | RawInline | Comment | IndexEntry
)


# --------------------------------------------------------------------------- #
# Block nodes
# --------------------------------------------------------------------------- #


@dataclass
class Heading(Node):
    level: int  # 0 = title, 1 = top section/chapter, 2 = subsection, ...
    inlines: list[Inline]
    label: str | None = None
    numbered: bool = True  # False for starred (\section*) and run-in headings
    appendix: bool = False  # after \appendix -> letter (A, B, ...) numbering
    part: bool = False  # \part -> "Part I" upper-roman, counter independent of sections
    #: \setcounter{section}{4} before this heading: the heading counters from
    #: here on, top level first ([5] -> "5"; [2, 4] -> "2.4")
    number_start: list[int] | None = None


@dataclass
class Paragraph(Node):
    inlines: list[Inline]
    align: str | None = None  # "center"/"left"/"right" from center/flushleft/flushright


@dataclass
class MathBlock(Node):
    """Display math. ``env`` is the originating environment name."""

    latex: str
    numbered: bool = False
    label: str | None = None
    env: str = "displaymath"
    #: per rendered line, the line's ``\label`` (or None), aligned with the
    #: numbered lines of a multi-line ``align``/``eqnarray``. Empty for a single
    #: equation (``label`` carries it).
    line_labels: list[str | None] = field(default_factory=list)
    #: per rendered line, what replaces its number: None = the next equation
    #: number, "" = none (\notag/\nonumber), else the tag as printed:
    #: "(A)" for \tag{A}, "A" for \tag*{A}. Empty when no line has a tag.
    line_tags: list[str | None] = field(default_factory=list)


@dataclass
class ListItem(Node):
    blocks: list[Block]
    term: list[Inline] | None = None  # the \item[term] of a description list
    label: str | None = None  # \item\label{...} -> referenceable list number


@dataclass
class ItemList(Node):
    ordered: bool
    items: list[ListItem]
    description: bool = False  # a `description` list (term + definition)
    start: int = 1  # first number of an ordered list (enumitem start=, \setcounter{enumi})


TableAlign = Literal["left", "center", "right"]


@dataclass
class TableCell(Node):
    blocks: list[Block]
    colspan: int = 1
    rowspan: int = 1
    align: TableAlign = "left"
    shade: str | None = None  # \cellcolor/\rowcolor background as RRGGBB
    border_bottom: bool = False  # partial \cmidrule/\cline under this cell


@dataclass
class TableRow(Node):
    cells: list[TableCell]
    is_header: bool = False
    rule_above: bool = False
    rule_below: bool = False


@dataclass
class Table(Node):
    rows: list[TableRow]
    colspec: list[TableAlign] = field(default_factory=list)
    booktabs: bool = False
    caption: list[Inline] | None = None
    label: str | None = None
    colwidths: list[float | None] = field(default_factory=list)  # per-column EMU (p{})
    caption_numbered: bool = True  # False for \caption* (unnumbered caption)
    #: \caption came before the tabular -> the caption goes above the table
    caption_above: bool = False
    #: a panel's own caption line ("(a) ...") in a table of subtables
    subcaption: list[Inline] | None = None
    subcaption_above: bool = False
    spanning: bool = False  # table* -> span the full page width in a multi-column body
    #: a borderless, full-width layout grid (side-by-side minipages), not a data
    #: table: no rules, equal-width columns across the text column.
    layout: bool = False


@dataclass
class SubFigure(Node):
    image: Image | None
    caption: list[Inline] | None = None
    label: str | None = None


@dataclass
class Figure(Node):
    image: Image | None
    caption: list[Inline] | None = None
    label: str | None = None
    source: str = ""
    subfigures: list[SubFigure] = field(default_factory=list)
    caption_numbered: bool = True  # False for \caption* (unnumbered caption)
    spanning: bool = False  # figure* -> span the full page width in a multi-column body
    #: non-graphic body content (boxes, text, tabulars, …) for a figure with no
    #: \includegraphics and no drawing environment; rendered above the caption.
    blocks: list[Block] = field(default_factory=list)


@dataclass
class CodeBlock(Node):
    text: str
    lang: str | None = None
    #: a listing's caption (lstlisting caption=, a listing float) and label
    caption: list[Inline] | None = None
    label: str | None = None
    caption_numbered: bool = True


@dataclass
class AlgLine(Node):
    """One line of pseudocode: an indentation depth + inline content."""

    indent: int
    inlines: list[Inline]
    number: bool = True  # whether the line gets a line number


@dataclass
class Algorithm(Node):
    lines: list[AlgLine]
    caption: list[Inline] | None = None
    label: str | None = None
    numbered: bool = True
    #: line numbers: 0 = none, n = every n-th line (``\\begin{algorithmic}[n]``)
    line_numbers: int = 1


@dataclass
class Quote(Node):
    blocks: list[Block]
    #: background fill (6-hex, no ``#``) for a coloured callout box, or None for a
    #: plain set-off quote. Captured from a ``\newmdenv`` ``backgroundcolor``.
    shade: str | None = None
    #: border colour (6-hex) for a callout box, or None. From ``linecolor``.
    border: str | None = None
    #: a callout's title bar (tcolorbox ``title=``), and its background colour.
    title: list[Inline] | None = None
    title_shade: str | None = None


@dataclass
class Theorem(Node):
    """A theorem-like environment (theorem/lemma/proof/...).

    ``kind`` is the display name ("Theorem", "Lemma", "Proof", ...). ``counter``
    is the SEQ counter name for numbered kinds (None for unnumbered, e.g. proof).
    """

    kind: str
    blocks: list[Block]
    title: list[Inline] | None = None
    label: str | None = None
    counter: str | None = None
    #: the counter resets within this division (``\newtheorem{thm}{Theorem}[section]``)
    #: -> numbered "section.n"
    within: str | None = None


@dataclass
class TableOfContents(Node):
    """``\\tableofcontents``/``\\listoffigures``/``\\listoftables`` → Word TOC field.

    ``kind`` selects the field: ``contents`` (heading outline), ``figures`` or
    ``tables`` (a caption-sequence list, ``TOC \\c "Figure"``/``"Table"``).
    """

    kind: Literal["contents", "figures", "tables"] = "contents"


@dataclass
class Index(Node):
    """``\\printindex`` -> a Word ``INDEX`` field (built from the ``XE`` entries)."""


@dataclass
class CSLItem(Node):
    id: str
    type: str
    csl_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bibliography(Node):
    entries: list[CSLItem]
    style: str = "numeric"


@dataclass
class RawPassthrough(Node):
    latex: str
    reason: str = "unsupported"


Block = (
    Heading
    | Paragraph
    | MathBlock
    | ItemList
    | Table
    | Figure
    | CodeBlock
    | Quote
    | Theorem
    | Algorithm
    | Bibliography
    | TableOfContents
    | Index
    | RawPassthrough
)


# --------------------------------------------------------------------------- #
# Document + metadata
# --------------------------------------------------------------------------- #


@dataclass
class DocumentMeta(Node):
    title: list[Inline] | None = None
    authors: list[list[Inline]] = field(default_factory=list)
    date: list[Inline] | None = None
    abstract: list[Block] | None = None
    #: the heading the class prints with the abstract ("Abstract", or
    #: \abstractname / the babel language's word) and its form: "block" (a
    #: heading line above it), "runin" ("Abstract." before the text), "dash"
    #: (IEEEtran's "Abstract—"), or "none"
    abstract_name: str = "Abstract"
    abstract_form: str = "block"
    keywords: list[Inline] | None = None
    affiliations: list[list[Inline]] = field(default_factory=list)
    #: a subtitle (KOMA \subtitle, beamer, a CV's job title)
    subtitle: list[Inline] | None = None
    #: further title-page lines: dedications, corresponding-author notes,
    #: KOMA \subject/\publishers, contact details
    front_notes: list[list[Inline]] = field(default_factory=list)
    language: str | None = None  # BCP-47 document language (from babel/polyglossia)
    running_head: str | None = None  # \markboth/\markright/\title[short] running head
    columns: int = 1  # body column count (\documentclass[twocolumn]/\twocolumn)
    # XeLaTeX/fontspec + xeCJK font selection (from the preamble).
    main_font: str | None = None  # \setmainfont -> Latin ascii/hAnsi default
    cjk_main_font: str | None = None  # \setCJKmainfont -> East-Asian default (eastAsia)
    cjk_sans_font: str | None = None  # \setCJKsansfont -> East-Asian font for headings
    cjk_mono_font: str | None = None  # \setCJKmonofont -> East-Asian font for code


@dataclass
class LabelInfo(Node):
    kind: RefKind
    counter_name: str
    bookmark: str
    number: str | None = None
    name: str | None = None  # target's title/caption text (for \nameref)
    #: a sub-figure's letter ("a"): \subref prints "(a)", \ref "1a"
    sub: str | None = None
    #: the target's counter type as cleveref/hyperref name it: "section",
    #: "subsection", "chapter", "appendix", "equation", "figure", "table",
    #: "theorem", "algorithm", "listing", "enumi"
    ref_type: str | None = None
    #: a theorem-like target's display name ("Lemma"), for its reference name
    type_name: str | None = None


@dataclass
class Document(Node):
    blocks: list[Block]
    meta: DocumentMeta = field(default_factory=DocumentMeta)
    labels: dict[str, LabelInfo] = field(default_factory=dict)
    book: bool = False  # book/report class with \chapter (top level is chapter)
    #: extra ``\label``s on an already-labelled target -> the label it kept
    #: (``\label{sec:a}\label{sec:b}`` makes ``sec:b`` an alias of ``sec:a``).
    label_aliases: dict[str, str] = field(default_factory=dict)
    #: a panel's label -> [the overall float's label, the panel's letter]
    #: (``\ref`` to a subtable prints "1a")
    sub_labels: dict[str, list[str]] = field(default_factory=dict)
    #: cleveref set-up from the preamble: {"options": [...], "crefname": {type:
    #: [singular, plural]}, "Crefname": {...}}
    cref: dict[str, Any] = field(default_factory=dict)

    # -- JSON serialisation ------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Document:
        node = _from_jsonable(data)
        assert isinstance(node, Document)
        return node


# --------------------------------------------------------------------------- #
# Generic traversal
# --------------------------------------------------------------------------- #


def _child_values(node: Node) -> list[Any]:
    """A node's field values in reading order.

    Fields come in declaration order, except that a table's caption (set above
    the tabular in LaTeX) is read before its rows, and a figure's caption after
    its body.
    """
    values = vars(node)
    if isinstance(node, Table):
        first = ["caption"]
    else:
        first = []
    last = ["caption"] if isinstance(node, Figure) else []
    names = first + [n for n in values if n not in first and n not in last] + last
    return [values[n] for n in names if n in values]


def node_lists(root: Any) -> Iterator[list[Any]]:
    """Yield every list of nodes reachable from ``root``, in reading order.

    Each list is yielded before its elements are descended into, so a caller
    can replace items in place (e.g. a ``Ref`` by a ``Link``). Covers every
    container -- table cells, captions, theorem bodies, styled spans, notes and
    the document metadata -- so passes over ``Ref``/``Cite`` leaves never miss
    one.
    """
    if isinstance(root, list):
        if any(isinstance(v, Node) for v in root):
            yield root
        for v in list(root):
            yield from node_lists(v)
    elif isinstance(root, Node):
        for value in _child_values(root):
            if isinstance(value, list | Node):
                yield from node_lists(value)


def iter_nodes(root: Any) -> Iterator[Node]:
    """Every node below ``root`` (not ``root`` itself), depth-first in reading
    order: a node comes right before its own children."""
    values = root if isinstance(root, list) else (
        _child_values(root) if isinstance(root, Node) else []
    )
    for v in values:
        if isinstance(v, Node):
            yield v
            yield from iter_nodes(v)
        elif isinstance(v, list):
            yield from iter_nodes(v)


# --------------------------------------------------------------------------- #
# Generic (de)serialisation over the dataclass registry
# --------------------------------------------------------------------------- #


# Discriminator key in the JSON form. Uses a non-identifier character so it can
# never collide with a dataclass field name (e.g. Theorem.kind, LabelInfo.kind).
_TYPE_KEY = "@type"


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Node):
        out: dict[str, Any] = {_TYPE_KEY: obj.node_kind}
        for f_name, f_value in vars(obj).items():
            out[f_name] = _to_jsonable(f_value)
        return out
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def _from_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict) and obj.get(_TYPE_KEY) in _NODE_REGISTRY:
        cls = _NODE_REGISTRY[obj[_TYPE_KEY]]
        kwargs = {k: _from_jsonable(v) for k, v in obj.items() if k != _TYPE_KEY}
        return cls(**kwargs)  # type: ignore[call-arg]
    if isinstance(obj, list):
        return [_from_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _from_jsonable(v) for k, v in obj.items()}
    return obj
