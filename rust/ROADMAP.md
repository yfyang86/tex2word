# tex2word — Rust port roadmap

This document is the historical phase-by-phase roadmap of the **Rust
implementation** of tex2word. It was written while the port was developed
against the original Python implementation as the reference oracle (whose test
suite and arXiv UATs defined expected behaviour). The Rust project is now
standalone at **version 1.0.6**; this file is retained as design history.
For current usage and development, see [`README.md`](README.md),
[`DEVELOPMENT.md`](DEVELOPMENT.md), and [`CHANGELOG.md`](CHANGELOG.md).

## Status: Phases 0–6 complete ✅ (standalone at 1.0.6)

A dependency-free end-to-end path is working and CI-gated, now covering the
front-end core, the OMML math engine, tables/figures/images, live fields &
cross-references (numbered sections, TOC, multi-column), citations/footnotes/
theorems, a structural OOXML validator, a conversion/coverage report, and an
IR→LaTeX round-trip writer:

```
LaTeX ─► tex2word-frontend ─► IR ─► crossref ─► tex2word-backend ─► .docx
         (parser/macros)   (tex2word-ir)  (transforms)  (OOXML+fields+zip)
                                    │                          ▲
                            tex2word-latex (IR→LaTeX)   tex2word-validate
```

`cargo run -p tex2word-cli -- convert paper.tex -o paper.docx` produces a real,
deterministic `.docx` (a hand-written ZIP of WordprocessingML parts) covering:
title, `\section`/`\subsection`/`\subsubsection` headings, paragraphs,
`\textbf`/`\emph`/`\textit`/`\texttt`/`\underline`, escaped literals, `\\` breaks,
and inline `$…$` math (as a minimal `m:oMath` run).

## Workspace layout

| crate | mirrors (Python) | responsibility |
|-------|------------------|----------------|
| `tex2word-ir`       | `tex2word/ir.py`        | the IR types (front-end ⇄ back-end contract) |
| `tex2word-frontend` | `tex2word/frontend/*`   | LaTeX → IR (parse, macros, preprocess) |
| `tex2word-backend`  | `tex2word/backend/*`, `mathml/*` | IR → OOXML `.docx` (+ math, tables, figures) |
| `tex2word`          | `tex2word/pipeline.py`  | the one-call pipeline + public API |
| `tex2word-cli`      | `tex2word/cli.py`       | the `tex2word` binary |

## Dependency policy

The slice is intentionally **zero-dependency** (hand-rolled ZIP+CRC32, XML by
string building) so it builds and tests offline. As modules land we may adopt
vetted crates where they clearly pay off — candidates:

- `zip` (DEFLATE container), `quick-xml` (streaming XML read/write, needed for
  round-trip and reference-doc templates),
- `flate2`/`miniz_oxide` (compression), `image`/`pdfium`-binding (figure raster),
- a hand-written LaTeX lexer/parser (no mature `pylatexenc` equivalent exists —
  this is the largest single porting task).

## Phased plan

Each phase is validated against the Python output on the corpus + UATs.

- **Phase 0 — slice (done).** IR, minimal parser, OOXML writer, ZIP, CLI, CI.
- **Phase 1 — front-end core.** Macro expansion (`\newcommand`/`\def`), preamble
  handling, comment/`\input` flattening, environments, more inline macros, robust
  tokenizer. Port `frontend/macros.py`, `preprocess.py`, and the structural half
  of `parser.py`.
  - ✅ Environments: `itemize`/`enumerate` (real Word numbering via
    `numbering.xml`) and `quote`/`quotation` (nesting-aware `\begin…\end`).
  - ✅ Macro expansion: `\newcommand`/`\renewcommand`/`\providecommand`/`\def`
    (args + one optional arg, unbraced-name and unbraced single-token body),
    expanded before parsing.
  - ✅ `\input`/`\include` flattening: recursive, comment-stripped, resolved
    against the input file's directory; missing files dropped gracefully.
  - ✅ Inline richness: `\textsc`/`\textsuperscript`/`\textsubscript` (small caps,
    super/subscript runs), `--`/`---` dashes, `` `` ``/`''` smart quotes, `~`
    non-breaking space, and a batch of text symbol macros (`\S`/`\dag`/
    `\copyright`/`\LaTeX`/spacing/…).
  - ✅ Accents: `\'e`/`` \`a ``/`\^o`/`\"u`/`\~n`/`\=o`/`\.z`/`\c c`/`\v s`/`\u a`/
    `\H o`/`\r a`/`\k e` → precomposed Unicode (unknown combos fall back to the
    base letter), plus special letters `\o`/`\ss`/`\ae`/`\oe`/`\aa`/`\l`/….
  - ✅ Preamble metadata: `\title`/`\author` (split on `\and`)/`\date` → IR,
    rendered under the title in a centered `Subtitle` style.
  - Phase 1 is functionally complete for the common document core. **Phase 2 (the
    OMML math engine) is next** — the headline differentiator.
- **Phase 2 — math (OMML).** The big one: `crates/tex2word-math` ports
  `mathml/latex_math.py` (AST) + `omml.py` (AST → OMML) + `symbols.py`.
  - ✅ Core: `tex2word-math` crate — recursive-descent LaTeX-math parser + AST +
    structured OMML for fractions (`m:f`), sub/superscripts (`m:sSup`/`m:sSub`/
    `m:sSubSup`), roots (`m:rad`, incl. `\sqrt[n]`), Greek + operator/relation/
    arrow symbol table, and upright function names (`\sin` → `m:nor`). Wired into
    the back-end (`Inline::Math` now emits structured OMML).
  - ✅ N-ary operators: `\sum`/`\prod`/`\int`/`\oint`/`\bigcup`/… with `_`/`^`
    limits → `m:nary` (limits above/below for sums, as scripts for integrals).
  - ✅ Delimiters: `\left<d>…\right<d>` → `m:d` (nesting-aware; `\left.` = none).
  - ✅ Accents: `\hat`/`\tilde`/`\bar`/`\vec`/`\dot`/`\ddot`/`\check`/`\breve`/… →
    `m:acc` (combining char); `\overline`/`\underline` → `m:bar` (top/bot).
  - ✅ Matrices: `matrix`/`pmatrix`/`bmatrix`/`Bmatrix`/`vmatrix`/`Vmatrix`/`cases`/
    `aligned`/`array`/… → `m:m` (row/cell split on `\\`/`&`, ragged rows padded),
    wrapped in the right delimiters. `\text`/`\mathrm` → upright runs. Front-end:
    display math `\[ … \]` → its own math paragraph.
  - **Phase 2 complete.** UAT (quadratic formula, `e^{iπ}+1=0`, `\sum`/`\int` with
    limits, a limit, accents, `pmatrix`, `cases`, a norm) converts to well-formed
    OMML in a valid `.docx`. Optional later polish: column-justified `aligned`,
    more symbols, `$$…$$` display, numbered equations.
- **Phase 3 — tables & figures.** `tabular`/`booktabs`, `\multicolumn`/`\multirow`
  (grid/vMerge), captions, `\includegraphics` (PNG/JPEG embed; PDF/TikZ raster).
  - ✅ Tables: `tabular`/`tabular*`/`array`/`longtable` → native Word `w:tbl`
    (bordered `TableGrid` style, auto grid). Column spec (`l`/`c`/`r`, `p`/`m`/`b`
    fixed-width → left, `|`/`@{}`/`<{}`/`>{}` inserts ignored, `*{n}{cols}`
    expansion) sets per-column `w:jc`. Booktabs (`\toprule`/`\midrule`/
    `\bottomrule`/`\cmidrule`) and `\hline`/`\cline` rules drop out; rows above the
    first `\midrule`/`\hline` become repeated header rows (`w:tblHeader`).
    `\multicolumn{n}{spec}{…}` → `w:gridSpan` with an alignment override.
  - ✅ `\multirow[pos]{n}{width}{…}` → `w:vMerge` (restart + continue on the
    covered rows' placeholder cells); nests with `\multicolumn`.
  - ✅ Floats: `figure`/`figure*`/`table`/`table*` → the float's content followed
    by a numbered `\caption` paragraph ("Figure N: …" / "Table N: …", independent
    counters, `Caption` style). `\centering` centers the content (paragraphs and
    the wrapped `tabular`); `[htbp]` placement and `\label`/`\captionsetup` are
    dropped. `\includegraphics[opts]{path}` → `Inline::Image` (path + raw opts).
  - ✅ Image embedding: `\includegraphics` reads the file (relative to the input's
    directory), detects PNG/JPEG/GIF from magic bytes, reads intrinsic pixel size
    from the header, and emits an inline `w:drawing` (`pic:pic`/`a:blip`) plus a
    `word/media/imageN.*` part, an image relationship, and the content-type
    default. Size from the graphicx option (`width=`/`height=`/`scale=`, with
    `\textwidth` fractions and `cm`/`mm`/`in`/`pt`/`bp`/`px` units; aspect ratio
    preserved). Missing/unsupported files (PDF, EPS, TikZ) fall back to a
    `[image: path]` placeholder — raster conversion of those is a later step.
  - **Phase 3 complete.** UAT: a document with macros, accents, lists, inline +
    display math (`\sum`/`\frac`/`\sqrt`/`pmatrix`), a captioned figure, an inline
    image, and a booktabs table with `\multicolumn`/`\multirow` converts to a
    valid `.docx` that `python-docx` opens — both images recognised as embedded
    PICTURE shapes with correct EMU sizes, the table read as 4×3.
- **Phase 4 — live fields & cross-refs.** `SEQ`/`REF`/`PAGEREF` fields, bookmarks,
  numbering, `transforms/crossref.py`, the multi-column section machinery.
  Planned across two sprints — see [`PHASE4_PLAN.md`](PHASE4_PLAN.md).
  - ✅ **Sprint 1 — bookmarks, complex fields, cross-references.** IR gained
    `Ref`/`Link`/`RefKind`/`RefStyle`, labels on headings/floats, `MathBlock`, and
    `Document.labels`. The `crossref` pass (in the pipeline crate) collects labels
    → sanitized bookmarks → `SEQ` counters, rewrites `Ref`s to bookmarks (generic
    refs inherit the target kind), turns `\nameref` into an internal hyperlink,
    and warns on unresolved refs. Back-end `fields.rs` emits complex fields
    (`fldChar`/`instrText`) + bookmarks: captions and equations are live `SEQ`
    numbers in bookmarks; `\ref`/`\eqref`/`\pageref`/`\autoref` → `REF`/`PAGEREF`
    (`\r` for sections); `\href`/`\url`/`\hyperref`/`\nameref` → `HYPERLINK`
    fields. UAT: a labelled figure/table/equation + the ref family + links opens
    in python-docx with correct field codes and paired bookmarks.
  - ✅ **Sprint 2 — numbered sections, TOC, cleveref, multi-column.** Numbered
    heading output (`1`, `1.1`, `1.1.1` via a multilevel `numId`; `\section*`
    stays unnumbered) so `REF \r` cites real section numbers; `\tableofcontents`/
    `\listoffigures`/`\listoftables` → heading + live `TOC` field; cleveref/autoref
    type prefixes (`fig. `/`Figure `, `sec. `/`Section `, …) precede the `REF`
    field. Multi-column: `[twocolumn]` (or a preamble `\twocolumn`) sets a
    2-column body; `figure*`/`table*` are full-width, bracketed by continuous
    section breaks (`w:cols`), with the title full-width above. Mid-document
    `\onecolumn`/`\twocolumn` switches remain unmodeled (documented limitation).
  - **Phase 4 complete.** UAT: a `twocolumn` paper with title/TOC, numbered
    sections, math, a labelled equation/figure*/table, the full `\ref` family +
    `\href`/`\nameref`, and a list converts to a valid `.docx` that python-docx
    opens — with `w:cols`, continuous breaks around the spanning float, and live
    `TOC`/`SEQ`/`REF`/`PAGEREF`/`HYPERLINK` field codes, no Phase 1–3 regression.
- **Phase 5 — parity layer.** Reference-doc templates, bibliography/citations,
  round-trip manifest + `.docx`→LaTeX, coverage report, OOXML validator.
  Planned across three sprints — see [`PHASE5_PLAN.md`](PHASE5_PLAN.md).
  - ✅ **Sprint 1 — citations, bibliography, footnotes.** IR: `Inline::Cite`/
    `CiteMode`, `Inline::Footnote`, `Block::Bibliography`/`BibEntry`. Front-end
    parses the `\cite` family, `\footnote`/`\thanks`, and `thebibliography`
    (`\bibitem[label]{key}`). The citation pass registers each entry under
    `cite:<key>` (auto number or explicit `[label]`) with a bookmark and warns on
    unknown keys. Back-end: citations render as their reference number(s),
    hyperlinked to the bookmark (`\citenum` bare, else `[…]`); `\footnote`s lift
    into a real `word/footnotes.xml` (separator/continuation pair + a superscript
    reference mark), with content-type + relationship wired; the bibliography is a
    "References" heading + bookmarked, hanging-indent entries. UAT: a doc with
    `\citep`/`\citet`/`\citenum` + two footnotes + `thebibliography` opens in
    python-docx with a real footnotes part and clickable citations.
  - ✅ **Sprint 2 — validator, theorems, report.** A zero-dep `tex2word-validate`
    crate (STORE zip reader + checks: required parts, XML well-formedness,
    content-type coverage, relationship-target resolution, `rPr`/`pPr`/`tblPr`/
    `trPr`/`tcPr` child-order, and field/bookmark pairing) wired into CI and a
    `tex2word validate <docx>` CLI — it caught a real `tblPr` order bug on first
    run. Theorem-like environments (`theorem`/`lemma`/`proof`/…) render numbered
    (live `SEQ Theorem`, `\cref`-able) with italic statements and a proof QED.
    A conversion report scans the expanded body (outside math) for unhandled
    macros and folds them, with the cross-reference warnings, into
    `Conversion.warnings`; `tex2word convert --strict` fails on any warning.
  - ✅ **Sprint 3 — round-trip writer, page geometry, coverage.** A `tex2word-latex`
    crate reconstructs `.tex` from the IR (`to_latex`), IR-idempotent under
    `parse → to_latex → parse` (4 round-trip tests); exposed via `tex2word latex`.
    `PageGeometry` presets (`--page letter|a4|legal`) drive `w:pgSz`/`w:pgMar`. A
    coverage report (`--report`) tallies every converted construct + dropped
    macros. Full docx **reference-doc** adoption (an arbitrary template's styles/
    geometry) is deferred — it needs DEFLATE inflation the zero-dep STORE reader
    lacks; presets cover the common page-setup need.
  - **Phase 5 complete.** Final UAT: a twocolumn paper with title/TOC, numbered
    sections, math, a labelled equation/figure*/table, the full `\ref` family +
    `\href`/`\nameref`, a list, `\citep` + a bibliography, a footnote, and a
    theorem+proof converts to a `.docx` that passes the in-house validator, opens
    in python-docx, and reports full coverage with zero unsupported macros.
    (Full CSL/BibTeX/Zotero, endnotes/index, docx reference-doc reading, and
    `.docx`→LaTeX remain out of scope — candidates for a later pass.)
- **Phase 6 — usability parity & cutover.** See [`PHASE6_PLAN.md`](PHASE6_PLAN.md).
  A differential investigation found two usability gaps that make correct output
  *look* broken and must close before cutover: (1) every `SEQ`/`REF` field caches
  the literal `"1"`, so figure/ref numbers show as "1" until a reader runs *Update
  Fields* — invisible in LibreOffice/Google Docs/Preview which never auto-update;
  (2) math misses `\mathbb`/`\mathcal` (double-struck/script), `\mathbf` (bold),
  `\binom`, and `\pmod` (the core symbol table and `\int`/`\sum`/`\frac`/matrices
  are fine).
  - ✅ **Sprint 1 — usability.** A numbering pass computes each labelled target's
    real number (Figure 2, section 1.3, …) and the back-end caches it into the
    `SEQ`/`REF` fields, so numbers show correctly on first open in any viewer
    while the fields stay live. Math: `\mathbb`/`\mathcal`/`\mathscr`/`\mathfrak`
    → Unicode math-alphanumerics (holes ℂℝℤ… handled), `\mathbf` → bold styled
    run, `\binom` → parens over a no-bar fraction, `\pmod`/`\bmod`.
  - ✅ **Sprint 2 (harness + fidelity).** A CI-gated corpus harness
    (`crates/tex2word/tests/corpus_parity.rs`) runs the Python project's own
    fixtures + arXiv UATs through the Rust converter — all 7 produce
    validator-clean, python-docx-openable `.docx`. The parity report
    ([`PHASE6_PARITY.md`](PHASE6_PARITY.md)) drove the fidelity fixes (colour/box/
    verb/`\paragraph`/spacing macros + the two-arg-macro brace bug), shrinking
    the dropped-macro list to genuine out-of-scope features (BibTeX
    `\bibliography`, algorithmic envs, `\appendix`, longtable `\endhead`). A live
    two-converter diff isn't run here (Python's `pylatexenc` won't build offline).
  - ⏳ **Cutover (awaiting go-ahead).** Flipping the published default to Rust and
    deprecating the Python tree is an outward-facing governance decision (it
    affects the PyPI package + users) — left for the maintainer to greenlight,
    then: merge `rust` → default, point docs at the Rust CLI, mark Python
    deprecated (kept one release as the reference oracle).

## Testing strategy

- Unit tests per crate (present now).
- Golden/round-trip tests: convert corpus `.tex` and assert IR + `.docx`
  structure, cross-checked against the Python output.
- A structural `.docx` validator (Phase 5) mirroring `tex2word.validate`.
