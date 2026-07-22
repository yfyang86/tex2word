# tex2word — Rust port roadmap

This directory holds the **Rust rewrite** of tex2word. It lives alongside the
Python implementation on the `rust` branch: the Python code is the **reference
oracle** (its test suite and the arXiv UATs define expected behaviour) and stays
in place until the Rust port reaches parity; only then is Python retired.

## Status: vertical slice ✅

A minimal, dependency-free end-to-end path is working and CI-gated:

```
LaTeX  ──►  tex2word-frontend  ──►  IR  ──►  tex2word-backend  ──►  .docx
            (parser)             (tex2word-ir)   (OOXML + zip)
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
  Planned across three sprints — see [`PHASE5_PLAN.md`](PHASE5_PLAN.md):
  **Sprint 1** = citations + `thebibliography` + footnotes; **Sprint 2** =
  structural OOXML validator + conversion report + theorem environments;
  **Sprint 3** = IR→LaTeX round-trip writer + reference-doc templates + coverage
  report. (Full CSL/BibTeX/Zotero, endnotes/index, and `.docx`→LaTeX are out of
  scope for Phase 5.)
- **Phase 6 — cutover.** Differential-test Rust vs Python across the corpus/UATs;
  when green, make Rust the default and retire the Python tree.

## Testing strategy

- Unit tests per crate (present now).
- Golden/round-trip tests: convert corpus `.tex` and assert IR + `.docx`
  structure, cross-checked against the Python output.
- A structural `.docx` validator (Phase 5) mirroring `tex2word.validate`.
