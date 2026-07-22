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
  - ⏳ Next: matrices/`aligned`/`cases` (`m:m`), accents in math
    (`\hat`/`\bar`/`\vec`/`\tilde` → `m:acc`), `\text` runs, and more symbols.
- **Phase 3 — tables & figures.** `tabular`/`booktabs`, `\multicolumn`/`\multirow`
  (grid/vMerge), captions, `\includegraphics` (PNG/JPEG embed; PDF/TikZ raster).
- **Phase 4 — live fields & cross-refs.** `SEQ`/`REF`/`PAGEREF` fields, bookmarks,
  numbering, `transforms/crossref.py`, the multi-column section machinery.
- **Phase 5 — parity layer.** Reference-doc templates, bibliography/citations,
  round-trip manifest + `.docx`→LaTeX, coverage report, OOXML validator.
- **Phase 6 — cutover.** Differential-test Rust vs Python across the corpus/UATs;
  when green, make Rust the default and retire the Python tree.

## Testing strategy

- Unit tests per crate (present now).
- Golden/round-trip tests: convert corpus `.tex` and assert IR + `.docx`
  structure, cross-checked against the Python output.
- A structural `.docx` validator (Phase 5) mirroring `tex2word.validate`.
