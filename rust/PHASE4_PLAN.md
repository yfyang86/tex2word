# Phase 4 — Live fields & cross-references (two-sprint plan)

Phase 4 delivers the PRD's **headline differentiator**: cross-references that
become *live Word fields* (`SEQ`/`REF`/`PAGEREF`/`STYLEREF`/`TOC`) which
auto-renumber on field refresh — the thing every python-docx-based tool fails to
do. It also lands the multi-column section machinery.

Reference oracle (Python, on this branch):
- `src/tex2word/backend/fields.py` — the complex-field + bookmark primitives.
- `src/tex2word/transforms/crossref.py` — the IR→IR label-collection / ref-rewrite pass.
- `src/tex2word/ir.py` — `Ref` / `Link` / `LabelInfo` / `TableOfContents` / `RefKind`.
- `src/tex2word/backend/document.py` — TOC fields (`_TOC_SPEC`), `_sect_pr`, the
  continuous-section column machinery.

## Where the Rust port stands

The Rust IR today has **no** label/ref/link/field concepts. Captions are numbered
with *static* backend counters ("Figure 1:"), headings are unnumbered, and there
are no hyperlinks. So Phase 4 is largely additive, in this dependency order:

```
frontend: parse \label,\ref…,\hyperref,\url   ─┐
IR: Ref, Link, RefKind, label on blocks        ├─►  crossref pass (IR→IR)  ─►  backend fields
IR: TableOfContents block                      ─┘        (bookmarks, SEQ)      (fldChar/instrText)
```

A new **crossref transform** slots between frontend and backend, mirroring the
Python `transforms/` package. Cleanest home: a `transforms` module in the
`tex2word` pipeline crate (it needs both the IR and a place to run between parse
and emit); promote to a `tex2word-transforms` crate only if it grows.

---

## Sprint 1 — Bookmarks, complex fields, and cross-references

**Goal:** `\label` + the `\ref` family resolve to live `REF`/`PAGEREF` fields, and
figure/table/equation numbers become live `SEQ` fields that references point at.
This is the core differentiator; everything in Sprint 2 builds on these primitives.

### 1.1 IR additions (`tex2word-ir`)
- `Inline::Ref { key: String, kind: RefKind, style: RefStyle, bookmark: Option<String> }`.
- `Inline::Link { inlines: Vec<Inline>, url: String, anchor: Option<String> }`
  (external URL **or** internal `anchor` bookmark — we have no link support today).
- `enum RefKind { Generic, Equation, Figure, Table, Section, Theorem, Page, Name, ListItem }`
  and `enum RefStyle { Plain, Abbrev, Full }`.
- `label: Option<String>` on `Heading`, on `Float`, and on a new
  `Block::MathBlock { label: Option<String>, latex: String }` (display math must
  become a labelable/numberable target, replacing today's bare
  `Paragraph{[Math]}` for `\[ … \]` / `equation`).
- `struct LabelInfo { kind, counter_name, bookmark, name: Option<String> }` and
  `Document.labels: HashMap<String, LabelInfo>` (populated by the pass).
- `plain_text`/exhaustive matches updated for the new variants.

### 1.2 Frontend (`tex2word-frontend`)
- Parse `\label{key}` and attach it to the enclosing target (heading, float,
  display-math/equation, `\item`). Mirror the Python rule: the label attaches to
  the block it sits in, and a stray `\label` right after `\end{figure}` still
  binds to that float.
- Parse the ref family → `Inline::Ref` with the right `kind`/`style`:
  `\ref`(generic/plain), `\eqref`(equation), `\pageref`(page), `\autoref`(full),
  `\cref`(abbrev), `\Cref`(full), `\nameref`(name). Keep `\vref`,`\labelcref`,
  `\crefrange` as a stretch (map to generic first).
- Parse links: `\href{url}{text}` → external `Link`; `\url{u}` → `Link([u], u)`;
  `\hyperref[label]{text}` → internal `Link` with `anchor=label`.
- Promote `\[ … \]` and `equation`/`equation*` to `Block::MathBlock`.

### 1.3 Crossref pass (`tex2word` crate, `transforms::crossref`)
Port `resolve_crossrefs`:
- `_collect`: walk blocks (recursing quote/float/list), assign each label a
  `LabelInfo` — `sanitize_bookmark` (start with a letter, `[^A-Za-z0-9_]`→`_`,
  ≤40 chars, `ref_` prefix if needed) and a `counter_name` per kind.
- `_rewrite_refs`: fill each `Ref.bookmark` from the label map; a `generic` ref
  inherits the target's kind; `\nameref` becomes a `Link` to the title text;
  resolve `\hyperref` anchors. **Warn (collect, don't panic) on unresolved refs**
  — surface via a returned `Vec<Warning>` (the start of a `ConversionReport`).

### 1.4 Backend fields (`tex2word-backend`, new `fields.rs`)
Port `fields.py` as string builders (we build XML by string, not lxml):
- `field(code, cached)` → the run sequence `fldChar begin` → `instrText` (code,
  `xml:space=preserve`) → `fldChar separate` → cached result run → `fldChar end`.
- `bookmark_start(id, name)` / `bookmark_end(id)` with a **deterministic** per-doc
  id counter (thread through `Ctx`).
- `seq_field`, `ref_field` (`\h`, and `\r` for paragraph/list numbers),
  `pageref_field`, `number_field` (flat `SEQ` or `STYLEREF 1 \s . SEQ \s 1`).
- Wire into rendering:
  - Wrap every labelled target in `bookmarkStart/End` around its number.
  - **Captions switch from static text to a `SEQ Figure/Table` field** inside the
    bookmark (numbers now live and referenceable) — updates `render_float`.
  - `MathBlock` → a right-tab-numbered equation paragraph: `(SEQ Equation)` in a
    bookmark, for `\eqref`.
  - `Inline::Ref` → `REF`/`PAGEREF` field (cached "1"); `\nameref`/`Link` →
    `w:hyperlink` (external ⇒ a rels entry with `TargetMode="External"`; internal
    ⇒ `w:anchor`).
- Content-types/rels already dynamic from Phase 3 — extend `doc_rels` for external
  hyperlink relationships.

### Sprint 1 acceptance
- Unit tests per crate (sanitize, collect/rewrite, field XML shape, bookmark
  pairing) + an end-to-end UAT: a doc with a labelled figure, table, and equation
  plus `\ref`/`\eqref`/`\pageref`/`\autoref` and an external `\href` produces a
  `.docx` where python-docx sees the `SEQ`/`REF`/`PAGEREF` field codes, matched
  `bookmarkStart`/`bookmarkEnd` ids, and a working hyperlink relationship — and
  every Phase 1–3 feature still renders (no regression).

---

## Sprint 2 — Numbered sections, TOC, cleveref prefixes, multi-column

**Goal:** documents read like the LaTeX original — numbered sections that refs can
target, a real Table of Contents, cleveref-style type prefixes, and multi-column
layout.

### 2.1 Numbered headings & section refs
- Numbered `Heading` output (`Section 1`, `1.1`, `1.1.1`) via Word list-style
  heading numbering (an `abstractNum` bound to the Heading styles) so numbers are
  live and `REF \r` can pull them.
- `\ref`/`\autoref`/`\cref`/`\Cref` to a section → `ref_field(paragraph_number=true)`.
- `\nameref` to a section → hyperlink carrying the heading's title text.

### 2.2 Table of contents (`\tableofcontents` / `\listoffigures` / `\listoftables`)
- IR: `Block::TableOfContents { kind: TocKind }`.
- Frontend: the three macros → the block.
- Backend: a `TOC` field per `_TOC_SPEC` (`TOC \o "1-3" \h \z \u`,
  `TOC \h \z \c "Figure"`, `… "Table"`) with a "right-click ▸ Update Field"
  cached placeholder + a heading ("Contents"/"List of Figures"/…).

### 2.3 cleveref / autoref type prefixes
- Render `Ref.style` × `kind` → the visible prefix before the `REF` field:
  `plain`=bare number, `abbrev`=`fig. N`/`eq. (N)`, `full`=`Figure N`/`Equation (N)`.
  `\eqref` keeps the `( )` wrapper. Prefix text is literal; the number stays a live field.

### 2.4 Multi-column layout
- Detect `\documentclass[twocolumn]` and `\twocolumn`/`\onecolumn`; `figure*` /
  `table*` span the full width.
- Backend: port `_sect_pr(columns, continuous)` + the continuous-section-break
  machinery from `document.py` — title/abstract full-width, body in N columns,
  starred floats break out to a one-column region and resume.
- Carry forward the **documented limitation**: mid-document `\onecolumn`/`\twocolumn`
  switches are modeled at region boundaries only (already noted in the Python docs).

### 2.5 Report surface
- Fold Sprint 1's warnings into a small `ConversionReport` returned from the
  pipeline (unresolved refs, dropped features) — mirrors `report.py`, sets up Phase 5.

### Sprint 2 acceptance
- Numbered-section UAT: `\section`+`\subsection` render numbered; `\cref`/`\autoref`
  to them show the right prefix + a `REF \r` field.
- TOC UAT: the three list fields emit valid `TOC` field codes; python-docx opens it.
- Two-column UAT: a `twocolumn` doc with a `figure*` yields the expected
  continuous-section `w:cols` structure (full-width title + spanning float).
- Full Phase 1–4 regression sweep (fmt + clippy `-D warnings` + all tests + the
  cumulative UAT `.docx` opening in python-docx with no lost features).

---

## Cross-cutting

- **Quality gate every commit:** `cargo fmt --all --check`,
  `cargo clippy --all-targets -- -D warnings`, `cargo test --all`, all offline.
- **Determinism:** bookmark ids and field order must be stable for byte-identical
  output (reset the id counter per document, like `reset_bookmark_ids`).
- **Validation:** keep using python-docx as an external OOXML consumer to confirm
  fields/bookmarks/hyperlinks are real, plus XML well-formedness of every part.
- **Sequencing:** Sprint 1 is a hard prerequisite for Sprint 2 (numbers-as-fields,
  bookmarks, and the ref-rewrite pass underpin section numbering, TOC, and cleveref).
- **Out of scope (→ Phase 5):** bibliography/citations (`\cite`), footnotes,
  theorem environments, round-trip `.docx`→LaTeX, and the OOXML validator.
