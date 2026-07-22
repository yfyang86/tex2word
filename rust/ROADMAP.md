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
  handling, comment/`\input` flattening, environments (`itemize`/`enumerate`,
  `quote`), more inline macros, robust tokenizer. Port `frontend/macros.py`,
  `preprocess.py`, and the structural half of `parser.py`.
- **Phase 2 — math (OMML).** The big one: port `mathml/latex_math.py` (LaTeX math
  AST) + `mathml/omml.py` (AST → OMML) + `symbols.py`. Fractions, scripts, roots,
  n-ary ops, matrices/aligned, delimiters, hundreds of symbols.
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
