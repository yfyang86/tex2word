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
RefKind = Literal["generic", "equation", "figure", "table", "section", "theorem", "page"]


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


RefStyle = Literal["plain", "abbrev", "full"]


@dataclass
class Ref(Node):
    """A cross-reference (``\\ref``/``\\eqref``/``\\cref``/``\\pageref``).

    ``bookmark`` is filled in by the cross-reference IR pass (Sprint 4).
    ``style`` controls a cleveref-style type prefix: ``plain`` (bare number,
    ``\\ref``), ``abbrev`` (``fig. N``, ``\\cref``), ``full`` (``Figure N``,
    ``\\Cref``/``\\autoref``).
    """

    key: str
    ref_kind: RefKind = "generic"
    bookmark: str | None = None
    style: RefStyle = "plain"


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


@dataclass
class LineBreak(Node):
    pass


@dataclass
class Footnote(Node):
    inlines: list[Inline]


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
    original_format: str = ""
    scale: float | None = None   # \includegraphics[scale=]
    angle: float | None = None   # rotation in degrees (counter-clockwise)
    trim: list[float] | None = None  # [left, bottom, right, top] in EMU (trim=)
    clip: bool = False
    alt: str = ""                # alt-text / original source path (accessibility)


Inline = (
    Text | Emphasis | Math | Ref | Cite | Link | LineBreak | Footnote | Colored
    | FontSize | Image | RawInline | Comment
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


@dataclass
class Paragraph(Node):
    inlines: list[Inline]


@dataclass
class MathBlock(Node):
    """Display math. ``env`` is the originating environment name."""

    latex: str
    numbered: bool = False
    label: str | None = None
    env: str = "displaymath"


@dataclass
class ListItem(Node):
    blocks: list[Block]
    term: list[Inline] | None = None  # the \item[term] of a description list


@dataclass
class ItemList(Node):
    ordered: bool
    items: list[ListItem]
    description: bool = False  # a `description` list (term + definition)


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


@dataclass
class CodeBlock(Node):
    text: str
    lang: str | None = None


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


@dataclass
class Quote(Node):
    blocks: list[Block]


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


@dataclass
class TableOfContents(Node):
    """``\\tableofcontents``/``\\listoffigures``/``\\listoftables`` → Word TOC field.

    ``kind`` selects the field: ``contents`` (heading outline), ``figures`` or
    ``tables`` (a caption-sequence list, ``TOC \\c "Figure"``/``"Table"``).
    """

    kind: Literal["contents", "figures", "tables"] = "contents"


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
    keywords: list[Inline] | None = None
    affiliations: list[list[Inline]] = field(default_factory=list)


@dataclass
class LabelInfo(Node):
    kind: RefKind
    counter_name: str
    bookmark: str
    number: str | None = None


@dataclass
class Document(Node):
    blocks: list[Block]
    meta: DocumentMeta = field(default_factory=DocumentMeta)
    labels: dict[str, LabelInfo] = field(default_factory=dict)
    book: bool = False  # book/report class with \chapter (top level is chapter)

    # -- JSON serialisation ------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Document:
        node = _from_jsonable(data)
        assert isinstance(node, Document)
        return node


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
