"""Round-trip support: persist the IR as a manifest inside the .docx.

The PRD makes the IR the round-trip linchpin: embedding it (plus the original
LaTeX retained on each math/figure node, the label->bookmark map, and citation
keys) lets a future Word->LaTeX reader reconcile edits against the source
instead of regenerating from scratch.

V1 ships the *write* side (this manifest) and a reader that recovers the IR
from a generated .docx. The full OOXML->IR reverse path is post-V1.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import replace
from datetime import UTC, datetime

from . import ir
from .backend.package import MANIFEST_PART

MANIFEST_VERSION = 1


def _generated_timestamp() -> str:
    """The manifest ``generated`` time. Honours ``SOURCE_DATE_EPOCH`` (the
    reproducible-builds convention) so a fixed value yields byte-identical
    output; otherwise the current UTC time."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.strip().isdigit():
        return datetime.fromtimestamp(int(epoch), UTC).replace(microsecond=0).isoformat()
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_manifest(doc: ir.Document) -> bytes:
    """Serialise the IR + provenance into the manifest JSON bytes."""
    payload = {
        "tool": "tex2word",
        "manifest_version": MANIFEST_VERSION,
        "generated": _generated_timestamp(),
        "labels": {
            key: {"bookmark": info.bookmark, "kind": info.kind, "counter": info.counter_name}
            for key, info in doc.labels.items()
        },
        "ir": doc.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def read_manifest(docx_bytes: bytes) -> dict | None:
    """Return the parsed manifest payload from a .docx, or None if absent."""
    zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    if MANIFEST_PART not in zf.namelist():
        return None
    return json.loads(zf.read(MANIFEST_PART).decode("utf-8"))


def recover_ir(docx_bytes: bytes) -> ir.Document | None:
    """Reconstruct the IR :class:`~tex2word.ir.Document` from the manifest."""
    payload = read_manifest(docx_bytes)
    if payload is None or "ir" not in payload:
        return None
    return ir.Document.from_dict(payload["ir"])


def to_latex(docx_bytes: bytes, reconcile: bool = True) -> str | None:
    """Convert a ``.docx`` back to LaTeX.

    Prefers the embedded tex2word manifest (exact IR, original math/figure
    source). With ``reconcile=True`` (the default) the manifest IR is merged with
    the freshly-read document IR by a **manifest-biased anchored merge**
    (:func:`reconcile_blocks`): an unedited document reconciles to *identity*
    (byte-for-byte the original LaTeX), while prose edited in Word is picked up;
    a lossless manifest block is never replaced by its lossy read-back. Pass
    ``reconcile=False`` to emit the manifest verbatim and ignore the body. For a
    *foreign* ``.docx`` (no manifest) it always reads ``document.xml``
    structurally. Returns ``None`` only if the document can't be read at all.

    See ``reconcile/`` for the investigation, the Go/No-go, and the design.
    """
    from .backend.latex_writer import write_latex
    from .frontend.docx_reader import read_docx

    manifest_doc = recover_ir(docx_bytes)
    if manifest_doc is None:
        try:
            return write_latex(read_docx(docx_bytes))
        except Exception:
            return None
    if not reconcile:
        return write_latex(manifest_doc)
    # map sanitised bookmarks back to the original label keys for the read-back
    label_map = {info.bookmark: key for key, info in manifest_doc.labels.items()}
    try:
        current = read_docx(docx_bytes, label_map=label_map)
    except Exception:
        return write_latex(manifest_doc)
    merged = reconcile_blocks(manifest_doc.blocks, current.blocks)
    # keep every document-level attribute from the manifest (meta, labels, the
    # book flag, ...) -- only the block list is reconciled.
    merged_doc = replace(manifest_doc, blocks=merged)
    return write_latex(merged_doc)


# --------------------------------------------------------------------------- #
# Block-level reconciliation (manifest = exact source, current = Word edits)
# --------------------------------------------------------------------------- #

_WS = re.compile(r"[\s{}]+")

# Inline math, citations and refs are recovered by the docx reader in a form that
# is *textually* different from the manifest (OMML->LaTeX synonyms, the rendered
# "[1]" of a citation, sanitised bookmark keys), even when nothing was edited. So
# a block's reconcile signature is built from its **stable prose only** -- the
# text the reader reproduces verbatim -- so an unedited block still matches.


def _prose_text(inlines: list) -> str:
    """Stable prose: ``Text`` (through styling wrappers), excluding inline math,
    citations, refs and footnotes (which the reader renders differently)."""
    out: list[str] = []
    for n in inlines:
        if isinstance(n, ir.Text):
            out.append(n.value)
        elif isinstance(n, ir.Emphasis | ir.Link | ir.Colored | ir.FontSize):
            out.append(_prose_text(n.inlines))
    return "".join(out)


# A typeset static citation reads back as literal "[1]" / "[1, 2]" / "[1, p. 5]"
# text and an empty \cite/\ref as "()"; the manifest holds an ir.Cite/ir.Ref
# (excluded from the prose key), so strip these artifacts (any bracket group that
# starts with a digit, plus empty parens) to keep an unedited cite paragraph
# signature-stable.
_CITE_ARTIFACT = re.compile(r"\[\d[^\]]*\]|\(\s*\)")


def _norm(s: str) -> str:
    s = _CITE_ARTIFACT.sub("", s)
    return _WS.sub("", s).lower().replace(":", "").replace("_", "")


_MATH_SYNONYMS = [
    (r"\displaystyle", ""), (r"\rightarrow", r"\to"), (r"\colon", ":"),
    (r"\begin{matrix}", ""), (r"\end{matrix}", ""),
    (r"\left\|", r"\left|"), (r"\right\|", r"\right|"), (r"\|", "|"),
]


def _math_sig(latex: str) -> str:
    """A display-math fingerprint stable across the reader's OMML->LaTeX spelling
    (``\\to``/``\\rightarrow``, dropped ``\\displaystyle``, ``matrix`` scaffolding)."""
    for a, b in _MATH_SYNONYMS:
        latex = latex.replace(a, b)
    return _norm(latex)


def _block_signature(block: ir.Block) -> tuple[str, str]:
    """A normalised (kind, text) key robust to lossy round-tripping.

    Built from stable prose / a synonym-folded math fingerprint so an *unchanged*
    block matches between the exact manifest IR and the lossy document-read IR;
    blocks the reader can't represent (e.g. ``Bibliography``) fall back to a
    type-only key so they align by position rather than spuriously mismatch.
    """
    if isinstance(block, ir.MathBlock):
        return ("math", _math_sig(block.latex))
    if isinstance(block, ir.Heading):
        return (f"h{block.level}", _norm(_prose_text(block.inlines)))
    if isinstance(block, ir.Paragraph):
        return ("p", _norm(_prose_text(block.inlines)))
    if isinstance(block, ir.ItemList):
        text = " ".join(
            _prose_text(b.inlines)
            for it in block.items for b in it.blocks if isinstance(b, ir.Paragraph)
        )
        return ("list", _norm(text))
    if isinstance(block, ir.Table):
        text = " ".join(
            _prose_text(b.inlines)
            for r in block.rows for c in r.cells for b in c.blocks
            if isinstance(b, ir.Paragraph)
        )
        return ("table", _norm(text))
    if isinstance(block, ir.Figure):
        cap = _norm(_prose_text(block.caption or []))
        img = block.image.path if block.image else ""
        return ("figure", cap + img)
    return (type(block).__name__, "")


def reconcile_blocks(original: list[ir.Block], current: list[ir.Block]) -> list[ir.Block]:
    """Merge the exact ``original`` (manifest) blocks with ``current`` (edited).

    **Manifest-biased anchored merge** — both signature-stable (an unedited
    document reconciles to identity) and edit-safe (a lossless manifest block is
    never replaced by its lossy read-back). Per ``difflib`` opcode:

    - ``equal`` → the exact ``original`` block (with any review *comments* the
      reviewer added to the matching read-back paragraph grafted on, so notes on
      otherwise-unchanged text survive).
    - ``replace`` of a single paragraph by a single paragraph → ``current`` (a
      genuine prose edit; the reader is faithful for prose).
    - any other ``replace`` (math/table/figure/bibliography, or N:M block
      counts) → keep ``original`` — the lossless side; the read-back is the lossy
      one, and an edit *inside* such a block can't be recovered faithfully anyway.
    - ``insert`` → take an insertion only when the whole run is paragraphs (a
      genuine prose insertion); a run mixing a non-paragraph block in is a lossy
      read-back artifact (bibliography entries, figure-as-table, an align-split
      equation + its "where …" continuation) and is dropped.
    - ``delete`` → drop paragraphs the user removed; keep non-paragraph manifest
      blocks (a "missing" complex block is a reader miss, not a deletion).

    See ``reconcile/`` for the investigation and the design rationale.
    """
    import difflib

    def _is_para(b: ir.Block) -> bool:
        return isinstance(b, ir.Paragraph)

    def _pure_prose(b: ir.Block) -> bool:
        # a paragraph whose read-back is trustworthy: no inline the reader renders
        # differently (math, citations, cross-refs, footnotes, images). Those
        # paragraphs are kept from the manifest until inline reconcile lands.
        return isinstance(b, ir.Paragraph) and not _has_unreliable_inline(b.inlines)

    osig = [_block_signature(b) for b in original]
    csig = [_block_signature(b) for b in current]
    matcher = difflib.SequenceMatcher(a=osig, b=csig, autojunk=False)
    out: list[ir.Block] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_run, cur_run = original[i1:i2], current[j1:j2]
        if tag == "equal":
            out.extend(_graft_comments(o, c) for o, c in zip(orig_run, cur_run, strict=True))
        elif tag == "delete":
            out.extend(b for b in orig_run if not _is_para(b))
        elif tag == "insert":
            # a genuine prose insertion is paragraphs-only; a run mixing in a
            # non-paragraph block is a lossy read-back artifact -> drop it.
            if cur_run and all(_is_para(b) for b in cur_run):
                out.extend(cur_run)
        else:  # replace
            if len(orig_run) == 1 and len(cur_run) == 1 \
                    and _is_para(orig_run[0]) and _is_para(cur_run[0]):
                if _pure_prose(orig_run[0]):
                    out.append(cur_run[0])  # pure-prose paragraph: take Word's text
                else:
                    # mixed paragraph: merge the prose edit while keeping the exact
                    # manifest math/footnote/image (inline reconcile); falls back to
                    # the manifest when it can't merge safely.
                    out.append(_reconcile_inline(orig_run[0], cur_run[0]))
            else:
                out.extend(orig_run)  # mixed/lossy region: keep the lossless manifest
    return out


# inline nodes whose exact manifest form we preserve and which inject no prose of
# their own when rendered (so prose segments line up across manifest / read-back).
_MERGE_SEMANTIC = (ir.Math, ir.Footnote, ir.Endnote, ir.Image)
# inline nodes whose rendering injects prose (cite "[1]", cref "alg. ") or is
# otherwise unmergeable -> keep the whole manifest paragraph.
_INLINE_OPAQUE = (ir.Cite, ir.Ref, ir.RawInline)


def _reconcile_inline(original: ir.Block, current: ir.Block) -> ir.Block:
    """Merge a prose edit into a mixed paragraph, keeping exact manifest semantics.

    Splits both paragraphs at their ``Math``/``Footnote``/``Image`` nodes; if the
    semantic skeletons match, each prose segment is taken from ``current`` only
    when it actually changed (else the exact manifest prose is kept), and the
    semantic nodes are always the manifest's. Anything risky (a ``Ref``/``Cite``
    whose rendering injects prose, a changed/extra semantic node) -> keep the
    manifest paragraph unchanged. Guarantees an unedited paragraph -> itself.
    """
    if not (isinstance(original, ir.Paragraph) and isinstance(current, ir.Paragraph)):
        return original
    if _contains(original.inlines, _INLINE_OPAQUE):
        return original
    o_prose, o_sem = _split_semantic(original.inlines)
    c_prose, c_sem = _split_semantic(current.inlines)
    if len(o_sem) != len(c_sem) or len(o_prose) != len(c_prose):
        return original
    if any(_sem_key(a) != _sem_key(b) for a, b in zip(o_sem, c_sem, strict=True)):
        return original
    merged: list = []
    for i, o_seg in enumerate(o_prose):
        c_seg = c_prose[i]
        merged.extend(o_seg if _norm(_prose_text(o_seg)) == _norm(_prose_text(c_seg)) else c_seg)
        if i < len(o_sem):
            merged.append(o_sem[i])
    return replace(original, inlines=merged)


def _contains(inlines: list, types: tuple) -> bool:
    for n in inlines:
        if isinstance(n, types):
            return True
        if isinstance(n, ir.Emphasis | ir.Link | ir.Colored | ir.FontSize) \
                and _contains(n.inlines, types):
            return True
    return False


def _split_semantic(inlines: list) -> tuple[list[list], list]:
    """Partition inlines into prose segments around top-level semantic nodes.

    Returns ``(prose_segments, semantic_nodes)`` with
    ``len(prose_segments) == len(semantic_nodes) + 1``."""
    segments: list[list] = [[]]
    sem: list = []
    for n in inlines:
        if isinstance(n, _MERGE_SEMANTIC):
            sem.append(n)
            segments.append([])
        else:
            segments[-1].append(n)
    return segments, sem


def _sem_key(n) -> tuple:
    if isinstance(n, ir.Math):
        return ("math", _math_sig(n.latex))
    if isinstance(n, ir.Image):
        return ("img", n.path)
    return ("fn", _norm(_prose_text(n.inlines)))  # Footnote


_UNRELIABLE = (
    ir.Math, ir.Cite, ir.Ref, ir.Footnote, ir.Endnote, ir.Image, ir.RawInline, ir.IndexEntry,
)


def _has_unreliable_inline(inlines: list) -> bool:
    """True if any inline (recursively) is one the docx reader renders differently
    (math/citations/cross-refs/footnotes/images) -- making prose-edit pickup unsafe."""
    for n in inlines:
        if isinstance(n, _UNRELIABLE):
            return True
        if isinstance(n, ir.Emphasis | ir.Link | ir.Colored | ir.FontSize) \
                and _has_unreliable_inline(n.inlines):
            return True
    return False


def _graft_comments(original: ir.Block, current: ir.Block) -> ir.Block:
    """Keep the exact ``original`` block, but carry over any review ``Comment``s the
    reviewer left on the matching ``current`` paragraph (notes on unchanged text)."""
    if not (isinstance(original, ir.Paragraph) and isinstance(current, ir.Paragraph)):
        return original
    # dedup by text: a comment the manifest already carries (e.g. our own \todo)
    # must not be added twice when the read-back recovers it from comments.xml.
    have = {n.text for n in original.inlines if isinstance(n, ir.Comment)}
    notes = [
        n for n in current.inlines
        if isinstance(n, ir.Comment) and n.text not in have
    ]
    if not notes:
        return original  # comment-free (or already present) -> identity preserved
    return replace(original, inlines=[*original.inlines, *notes])

