# Changelog

All notable changes to **tex2word** are recorded here. tex2word converts LaTeX
to editable Word (`.docx`) with native OMML math and live fields; see
[`README.md`](README.md) for the feature overview.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.8.2 — rename to `tex2word`

- **Renamed the package `latex2word` → `tex2word`.** The import package
  (`import tex2word`), the CLI command (`tex2word convert`), and the source tree
  (`src/tex2word/`) are now all `tex2word`, matching the PyPI distribution —
  there is a separate, unrelated `latex2word` project on PyPI to avoid. The
  `[tool.uv.build-backend] module-name` override added in 0.8.1 is no longer
  needed and was removed.
- **Fixed `tex2word --help`.** An unescaped `%` in the `benchmark` subcommand's
  help text crashed argparse (`unsupported format character`); now escaped.

## 0.8.1 — PyPI packaging & release tooling

First public PyPI release. No functional changes to the converter — this release
makes the project installable from PyPI and publishable from CI.

- **Distribution published as `tex2word`.** The PyPI distribution name was set to
  `tex2word` (matching the repository); the import package and CLI command were
  still `latex2word` at this point, with `[tool.uv.build-backend] module-name`
  pointing the build backend at the module. The full rename lands in 0.8.2.
- **MIT licensed.** Added a top-level [`LICENSE`](LICENSE) and PEP 639 metadata
  (`license = "MIT"` + `license-files`).
- **Complete packaging metadata.** Author/maintainer, `readme`, keywords, trove
  classifiers, and project URLs (Homepage/Repository/Issues/Changelog).
- **Documented install extras.** `pip install "tex2word[pdf,mathml,csl,mathimg]"`.
- **CI workflow.** ruff + mypy + pytest on Python 3.12 and 3.13, plus an
  sdist/wheel build gated by `twine check`.
- **Release workflow.** Pushing a `vX.Y.Z` tag builds and publishes to PyPI via
  Trusted Publishing (OIDC — no stored token) and cuts a GitHub release. Actions
  pinned to the Node-24 majors (`actions/checkout@v5`, `astral-sh/setup-uv@v6`).
- **Docs.** Fixed broken internal links, corrected the author line, and added
  PyPI install instructions to the README.

## 0.8.0 — templates, collaboration round-trip & class breadth

The v3 arc's first cut: adopt Word templates, round-trip Word reviews (tracked
changes + comments), deepen reconcile, and broaden document-class/bibliography
support — plus a permissive (zero-GPL) dependency posture. 531 tests, ruff +
mypy clean.

- **biblatex support (V5-11).** `\addbibresource{refs.bib}` (preamble or body) +
  `\printbibliography` are now recognised alongside the classic
  `\bibliography`/`bibtex` flow, so biblatex documents get their citations and
  reference list resolved.
- **Structured title blocks: authors, affiliations, keywords (V5-10).**
  `\author{A \and B \and C}` yields **one author per `\and`**; `\institute` /
  `\affiliation` / `\affil` / `\address` / `\email` render as **affiliation
  lines**; `\inst{n}` / `\IEEEauthorrefmark{n}` become superscript markers;
  IEEEtran `\IEEEauthorblockN`/`\IEEEauthorblockA` content is preserved; and
  `\keywords` / `\IEEEkeywords` render a **Keywords** line. All work in the
  preamble or body and round-trip.
- **Semantic round-trip tags for bibliography & figures (V5-4).** The reference
  list and each figure are emitted inside tagged block content controls
  (`w:sdt`), so the round-trip reader recovers them as one `ir.Bibliography` /
  `ir.Figure` — a **sub-figure grid now round-trips as a Figure instead of a
  table** (closes root-cause C3), and the reference text is preserved. The reader
  also **descends into any Word content control**, so content inside
  template/field controls is no longer dropped.
- **Original label names restored on read-back (V5-5).** Sanitised Word bookmarks
  map back to the source label keys: with a manifest, `to_latex` builds an exact
  bookmark→key map (so `\ref` keys are the originals); without one, a heuristic
  reverses common cross-ref prefixes (`eq_e` → `eq:e`, `sec_intro` → `sec:intro`)
  and leaves unknown prefixes untouched.
- **Inline reconcile for mixed paragraphs (V5-5).** A prose edit in a paragraph
  that also contains inline **math** (or footnotes/images) is now merged
  *inline*: the edited words are taken from Word while the **exact manifest
  LaTeX** of the math/footnote/image is kept (no lossy OMML round-trip). It
  splits both paragraphs at their semantic nodes, takes a prose segment from Word
  only where it actually changed, and **falls back to the manifest** paragraph
  whenever it can't merge safely (a `Ref`/`Cite` whose rendering injects prose, a
  changed/extra semantic node) — so unedited paragraphs round-trip to identity.
- **`\todo` → Word comments (V5-3, forward).** `\todo{…}` (todonotes) and
  `\comment`/`\note` (changes) become native Word **review comments**
  (`comments.xml` + anchors), so notes written in LaTeX show up in the Word
  reviewing pane. Completes the comment round-trip loop (LaTeX `\todo` → Word
  comment → back to a `% comment:` line, without duplication through reconcile).
- **Recover Word comments (V5-3).** Review comments (`comments.xml`) are read at
  their anchors and surfaced in LaTeX as `% comment: [author] …` lines, so a
  reviewer's notes aren't lost on the way back. Comments are newline-wrapped so
  they never comment out real text, and they **survive reconcile** — a note on an
  otherwise-unchanged paragraph is grafted onto the kept manifest block.
- **Accept Word tracked changes on read (V5-3).** Reading a `.docx` now accepts
  Track Changes: inserted runs (`w:ins`/`w:moveTo`) are kept, deleted runs
  (`w:del`/`w:moveFrom`) are dropped. So a document a co-author reviewed in Word
  with Track Changes round-trips back to LaTeX as if every change were accepted —
  including through reconcile.
- **Reference Word templates (V5-1).** `tex2word convert … --reference-doc
  TEMPLATE.docx` adopts a journal's or organisation's Word template: the output
  uses the template's **styles** (its `Heading 1`/`Title`/`Caption`/… win;
  tex2word's custom styles like `SourceCode` are merged in so nothing renders
  unstyled), its **theme** (fonts/colours), its **page geometry** (size +
  margins), and its **headers/footers** (running titles + page numbers, **plus
  header/footer logos** — PNG/JPEG/EMF images are carried and namespaced under
  `media/tmpl/`; a part with an unsupported/missing sub-resource is skipped so no
  relationship dangles) — while keeping our live `SEQ`/`REF`/`TOC` fields intact.
  An unreadable reference warns and falls back to the built-in styles.
- **No GPL/AGPL dependencies.** The optional `pdf` extra's PDF rasteriser was
  swapped from **PyMuPDF (AGPL-3.0)** to **pypdfium2 (Apache-2.0/BSD, Google
  PDFium)** + Pillow — both permissive. `backend/raster.py` and the
  `render_check` PDF inspector now use PDFium; tests author fixture PDFs with
  matplotlib. tex2word is now MIT with only Apache-2.0/BSD/MIT/PSF/HPND deps on
  every install path.

## 0.7.0 — round-trip reconcile by default

Word→LaTeX reconcile is now the default, with a signature-stable + edit-safe
merge; the LaTeXML front-end runs end-to-end; the foreign-docx reader recovers
every structured block. 487 tests, ruff + mypy clean.

- **Round-trip reconcile is on by default.** `to_latex` now merges Word edits
  against the manifest by default (was opt-in). A **manifest-biased anchored
  merge** makes it both *signature-stable* — an unedited `.docx` reconciles to
  **identity** (byte-for-byte the original LaTeX; all 7 corpus/UAT docs, CI-gated)
  — and *edit-safe*: prose edits are picked up, but a lossless manifest block is
  never replaced by a lossy read-back. Supporting work: prose-only / synonym-
  folded / citation-artifact-stripped block signatures, `Table N:` caption and
  `Abstract` recovery in the reader, and a `book`-flag fix in the merge path.
  Pass `--no-reconcile` (CLI) / `reconcile=False` for the manifest verbatim.
- **LaTeXML front-end now runs end-to-end (V4-3).** Fixed the silent fallback:
  `run_latexml` wrote to `--dest=-`, which this LaTeXML treats as a *filename*
  (not stdout), so it captured 0 bytes and always fell back to the pure parser.
  It now writes to a temp file and reads it back; the advisory `real-tool` CI
  lane confirms `--frontend latexml` converts all five corpus docs
  (`latexml-ok`), each schema-valid. Still **experimental** (the pure parser
  stays the validated default).
- **Reader recovers algorithm boxes and description lists (V4-16).** The
  foreign-docx reader now maps an `Algorithm N:` ruled box (single-cell table of
  `SourceCode` lines) back to `ir.Algorithm` (caption/label, per-line indent and
  line numbers recovered), and an indented bold-term + definition paragraph back
  to a `description` `ir.ItemList`. With **every structured block now
  recovered**, the round-trip reconcile path is ready to flip on by default.

## 0.6.2 — round-trip depth, perf, tooling

The v2 "tail": reader recovery, performance, citations, packaging, and a
quantitative baseline. 470 tests, ruff + mypy clean.

- **Reader recovery (V4-16/17).** The foreign-docx reader now recovers
  **theorems/proofs** (in addition to figures/quotes/code), and field-based
  citations from **Zotero**, **Mendeley** and **EndNote** map back to `\cite`
  (foreign Word equations and tables already round-tripped).
- **Performance (V4-19).** Identical images are embedded once (content-hash media
  dedup), and the image-math fallback is memoised.
- **Quantitative benchmark (V4-4).** `tex2word benchmark <dir>` reports
  math-OMML %, validity, warnings and aborts (text + JSON), with
  `--fail-on-regression`; CI-gated over the corpus + UATs. Baseline: **100%
  native-OMML math, 100% valid, 0 aborts.**
- **Reproducible builds (V4-18).** The manifest timestamp honours
  `SOURCE_DATE_EPOCH` → byte-identical output.
- **Packaging (V4-20).** `.pre-commit-config.yaml` and a tag-driven PyPI
  `Release` workflow (Trusted Publishing).
- **Front-end honesty.** The default **`pure`** parser is the validated engine;
  `--frontend latexml` is marked **experimental** — an advisory `real-tool` CI
  lane (V4-3) showed it silently falls back, so it is not yet proven end-to-end.

## 0.6.1 — fidelity fixes (real-paper driven)

A patch of forward-conversion fidelity fixes, several driven by a third
real-paper UAT (arXiv:2605.23904v2). 452 tests, ruff + mypy clean.

- **Nested table grids.** A `table*` whose tabular(s) sit inside
  `\resizebox{…}{…}{\begin{minipage}…}` (the "grid of sub-tables" layout) is now
  recovered as real tables instead of dumped as raw LaTeX. `\resizebox`/
  `\scalebox`/`minipage` are transparent containers; block environments inside a
  `{…}` group (e.g. `{\footnotesize \begin{verbatim}…}`) are descended into.
- **`\hphantom`/box macros.** `\phantom`/`\hphantom`/`\vphantom`/`\rule` print
  nothing (no more raw leaks from delta-cell macros); `\mbox`/`\fbox`/`\raisebox`
  emit their content; `\fontsize`/`\selectfont`/`\FloatBarrier`/… are no-ops.
- **`verbatim` bodies.** Fixed an empty-`CodeBlock` bug — code/prompt listings
  (incl. inside a font-size group) now carry their content.
- **Colour `!`-mixes.** `blue!8` is computed (light blue) instead of collapsing
  to base `blue`; `red!40!blue` left-folded.
- **Inline images.** An `\includegraphics` in running text embeds inline (icon/
  logo) instead of forcing a block figure; standalone images stay figures.
- **Round-trip reader.** The foreign-docx reader recovers `Figure`/`Quote`/
  `CodeBlock` blocks (was: flattened to paragraphs).
- **Reproducible builds.** The manifest timestamp honours `SOURCE_DATE_EPOCH`;
  with it set, output is byte-identical (the ZIP was already deterministic).

## 0.6.0 — v2 "trust & depth"

The v2 arc: earn the fidelity claims with real verification, then deepen math,
document, and citation features. 425 tests, ruff + mypy clean.

### Verification (the v2 headline)
- **ECMA-376 content-model validation (V4-2).** `validate.py` now checks the
  child-ordering of the run/paragraph/table property elements (`w:rPr`/`w:pPr`/
  `w:tblPr`/`w:trPr`/`w:tcPr`) against the schema sequence, plus key enum and
  integer attribute values — offline and CI-gated. It immediately caught and
  fixed 6 real ordering bugs in the shipped `styles.xml`.
- **Visual rendering gate (V4-1).** A blocking CI lane renders the corpus through
  LibreOffice and smoke-checks the PDFs (page count + text) via PyMuPDF —
  appearance-level verification, not just structure. `tex2word.render_check`.

### Math
- **`align`/`aligned` alignment (V4-9).** Multi-line aligned math lines up at the
  `&` (a column-justified matrix); single-numbered `equation`+`aligned` keeps one
  number; numbered top-level `align` keeps per-line numbers.
- **Colour and size on math runs.** `\textcolor{red}{$x$}` and `{\large $x$}` now
  style the equation.
- **`mathtools`/`physics` built-ins (V4-11).** `\abs`/`\norm`/`\ceil`/`\floor`/
  `\set`/`\ket`/`\bra`/`\braket`, `\dv`/`\pdv`/`\dd` — used when not user-defined.
- **`siunitx` (V4-11).** `\si`/`\unit`/`\SI`/`\qty`/`\num`/`\ang` → Unicode units
  and numbers (`\SI{9.81}{\meter\per\second\squared}` → `9.81 m/s²`).

### Document structure
- **Table of contents (V4-12).** `\tableofcontents`/`\listoffigures`/
  `\listoftables` → live Word `TOC` fields.
- **Book structure (V4-15).** Book/report documents make `\chapter` the top
  numbered level (sections nest `1.1.1.1`, `Heading1`–`Heading5`); `\appendix`
  switches to lettered headings (`A`, `A.1`); `\part`, `\frontmatter`/
  `\mainmatter`/`\backmatter` accepted.
- **Glossaries/acronyms (V4-15).** `\newacronym` + `\gls`/`\acrshort`/`\acrlong`/
  `\acrfull` (capitalised/plural variants, first-use full form).
- **Table polish (V4-13).** `\cmidrule`/`\cline` partial rules (incl. the `(lr)`
  trim) → per-cell borders; `>{}` column-alignment processors; nested tables.

### Citations
- **Real CSL engine (V4-14).** Optional `csl` extra (`citeproc-py`): `--csl
  STYLE.csl` formats citations and the reference list against a CSL style, with
  the built-in heuristic as a graceful fallback. `\nocite{key}`/`\nocite{*}`.

### Meta
- `csl` packaging extra; this changelog.

## 0.5.0 — V4 inline/table/math fidelity

The fidelity layer real papers need, on top of the V1–V3 pipeline.

- **Colour.** `\textcolor`/`\color`/`\colorbox`/`\fcolorbox`/`\definecolor`/
  `\colorlet`; `rgb`/`RGB`/`HTML`/`gray`/`cmyk` models + `!`-mixes; composes with
  emphasis; group-scoped.
- **`\includegraphics` options.** `width`/`height`/`scale` (extent), `angle`
  (rotation), `trim`+`clip` (crop); source path as image alt-text.
- **Text spans.** `\textsuperscript`/`\textsubscript` (`w:vertAlign`),
  `\sout`/`\xout` (`w:strike`), `\uline` (underline), `\hl` (`w:highlight`),
  font-size groups `\tiny`…`\Huge` (`w:sz`).
- **Tables.** `\cellcolor`/`\rowcolor` shading (`w:shd`), `p{}` column widths.

Everything round-trips (IR ↔ LaTeX ↔ docx).

## 0.1.0 – 0.4.x — foundation (V1–V3)

Pre-changelog. The `front-end → IR → OOXML` pipeline: native OMML math, live
`SEQ`/`REF`/`PAGEREF`/`STYLEREF` fields, BibTeX→CSL and live Zotero citations,
figures (incl. PDF rasterisation + subfigures), theorems and algorithms, the
Word→LaTeX round-trip, the math decision-cascade + image fallback, the LaTeXML
front-end option, and the embedded round-trip manifest.
