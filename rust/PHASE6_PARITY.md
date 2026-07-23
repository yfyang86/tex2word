# Phase 6 — corpus parity report

The go/no-go artifact for cutover: the Python project's own test fixtures
(`tests/corpus/`) and arXiv UATs (`tests/uat/`) run through the **Rust**
converter, measured for structural validity (the in-house OOXML validator) and
feature coverage. Gated in CI by `crates/tex2word/tests/corpus_parity.rs`.

> A live two-converter diff against the Python implementation is **not** run in
> this environment — its `pylatexenc` dependency fails to build offline (a
> setuptools incompatibility). Parity is therefore measured Rust-side (validity +
> coverage); since the corpus *is* the Python project's own fixtures, passing it
> exercises the intended feature surface. A live diff can be added once Python
> runs (a venv with `pylatexenc`/`lxml`).

## Results (7/7 valid, 7/7 open in python-docx)

After the Sprint-2 fidelity fixes (colour/box/verb/paragraph/spacing macros +
the two-arg-macro brace bug), the dropped-macro list is down to genuine
out-of-scope features:

| File | Valid | Opens | Unsupported macros (dropped) |
|------|:-----:|:-----:|------------------------------|
| `corpus/article.tex` | ✅ | ✅ | `\bibliography`, `\bibliographystyle` |
| `corpus/features.tex` | ✅ | ✅ | algorithmic (`\STATE`/`\FOR`/`\REQUIRE`/`\RETURN`/`\ENDFOR`) |
| `corpus/longtable.tex` | ✅ | ✅ | `\endhead` |
| `corpus/macros.tex` | ✅ | ✅ | *(none)* |
| `corpus/tables.tex` | ✅ | ✅ | *(none)* |
| `uat/arXiv-2507.17026v2/main.tex` | ✅ | ✅ | *(none)* |
| `uat/arXiv-2605.23904v2/main.tex` | ✅ | ✅ | `\appendix` |

Every file produces a **structurally valid** `.docx` that opens in python-docx.
No malformed output; the remaining differences are a handful of *dropped*
out-of-scope macros, not broken documents.

## Fidelity fixes shipped (Sprint 2)

- `\paragraph`/`\subparagraph` → `Heading4`.
- `\textcolor{c}{text}`/`\color` → keep the text, drop the colour. Fixed the
  underlying bug where an unknown two-argument macro left its second `{…}` as
  literal `{text}` braces.
- `\mbox{x}`/`\hbox{x}` → passthrough content.
- `\verb|code|` → a typewriter run.
- `\raisebox{d}{text}` → keep the text; `\rule`/`\fontsize` → dropped.
- `\hphantom`/`\phantom`/`\hspace`/`\vspace` and the font-size/shape declarations
  (`\footnotesize`/`\selectfont`/`\bfseries`/…) → dropped cleanly and no longer
  reported.

## Gap analysis — remaining (out of scope for Phase 6, backlog)
- `\bibliography`/`\bibliographystyle` (BibTeX): the Rust port handles the
  LaTeX-native `thebibliography`; BibTeX resolution is a later CSL pass.
- `algorithmic`/`algorithm2e` environments (`\STATE`/`\FOR`/…): a dedicated
  algorithm block, not yet ported.
- `longtable` `\endhead`: multi-page header rows (Rust emits a normal `w:tbl`).
- `\appendix`: appendix section renumbering (`A`, `A.1`).

## Cutover readiness

- ✅ Structural validity across the corpus (CI-gated).
- ✅ Usability fixes shipped (Sprint 1): cross-ref/caption numbers are correct on
  first open; `\mathbb`/`\mathcal`/`\mathbf`/`\binom`/`\pmod` render.
- ⏳ Land the easy fidelity wins above to shrink the dropped-macro list, then flip
  the default to Rust and mark the Python tree deprecated (kept one release as
  the reference oracle).
