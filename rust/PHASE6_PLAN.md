# Phase 6 — Usability parity & cutover (plan + gap investigation)

Phase 6 is the cutover: make the Rust port the default and retire the Python
tree. But a differential investigation (triggered by "`$\int$`/amsmath and
label/ref aren't usable") shows two **usability gaps** must close *first* — they
make correct output *look* broken in common viewers. So Phase 6 front-loads
gap-closure, then does the differential cutover.

## Investigation findings (evidence-based)

### 1. Cross-references: correct but invisible ⚠️ (the headline gap)

Every `SEQ`/`REF`/`PAGEREF` field is emitted **live** but with a cached result
of the literal `"1"`. Inspecting a generated `.docx`:

```
REF fig_w \h            cached "1"
REF eq_e \h             cached "1"
SEQ Figure \* ARABIC    cached "1"
SEQ Table  \* ARABIC    cached "1"     ← every figure/table/equation shows "1"
```

Consequence: the numbers are only correct *after* the reader runs **Update
Fields** (Word: Ctrl+A → F9). **LibreOffice Writer, Google Docs, Apple Pages,
and most preview panes never auto-update fields**, so a document with three
figures shows "Figure 1" three times and every `\ref` shows "1". The
cross-reference machinery is *structurally* correct (fields + bookmarks verified,
python-docx-openable) but **reads as broken** — exactly the report.

Citations are already fine — `render_cite` caches the real number (`[1]`,
`[XY]`). Only `SEQ`/`REF` inherit the `"1"` placeholder.

**Fix:** compute the real numbers during a numbering pass and cache *those*.
Fields stay live (renumber on edit) but display correctly on open, everywhere.

### 2. Math: strong core, specific amsmath gaps ⚠️

A 30-case probe confirms the OMML engine already handles a lot well:
`\int`/`\sum`/`\prod` n-ary with limits, `\frac`/`\dfrac`, sub/superscripts,
`\sqrt[n]`, `\lim`, `cases`/`align`/`pmatrix`, `\vec`/`\hat` accents,
`\left…\right` delimiters, `\text`/`\mathrm` upright, and a **broad symbol
table** (Greek, `\geq`/`\leq`/`\neq`/`\approx`, `\notin`/`\subseteq`, `\pm`,
`\emptyset`/`\forall`/`\exists`, `\cdots`/`\ldots`, `\partial`/`\nabla`,
`\hbar`/`\ell`/`\Re`, …). These are **not** the gap.

The real gaps (each shown wrong by the probe):

| Input | Current output | Should be |
|-------|----------------|-----------|
| `\mathbb{R}` | `R` | `ℝ` (double-struck) |
| `\mathcal{L}` | `L` | `ℒ` (script) |
| `\mathbf{v}` | upright `v` | **bold** `v` (`m:sty val="b"`) |
| `\binom{n}{k}` | `nk` | `(ⁿₖ)` — delimiter + no-bar fraction |
| `\pmod{n}` | `n` | `(mod n)` |

Plus lower-frequency misses: `\overset`/`\underset`/`\stackrel`, `\substack`,
`\xrightarrow`/`\xleftarrow`, `\overbrace`/`\underbrace`, `\boxed`; `align`
renders as an unaligned matrix (no `&` alignment); and the n-ary integrand scope
captures only the first atom (`\int f(x)\,dx` → body `f`, rest trails).

`\mathbb`/`\mathcal`/`\mathbf`/`\binom` are common in real papers, so these
**do** make math "look unusable" for that content, matching the report.

### 3. Other

- `\tableofcontents` emits a `TOC` field with an "Update Field" placeholder (no
  static entries) — same field-update caveat, lower priority.
- `PAGEREF` is inherently layout-dependent; its cache can't be pre-computed.

---

## Sprint 1 — Usability: static numbering + math font/binom

Goal: correct output that *looks* correct on first open in any viewer.

### 1.1 Static number caching (the headline)
- New numbering pass (extend `crossref`, or a `number` transform run right
  after it): walk blocks in document order maintaining counters for `Figure`,
  `Table`, `Equation`, `Theorem`, hierarchical `section` (1, 1.1, 1.1.1), and
  `enumerate` items. Assign each numbered target its display number.
- IR: add `number: Option<String>` to `LabelInfo` (populated for every labelled
  target).
- Back-end:
  - `SEQ` caption/equation/theorem fields cache the back-end's own in-document-
    order running counter (labelled or not) instead of `"1"`.
  - `REF <bm>` caches `labels[key].number`; `REF \r` (section/list) caches the
    hierarchical number.
  - `PAGEREF` keeps `"1"` (documented: page numbers need layout).
  - Fields remain live `SEQ`/`REF` — they still renumber on **Update Fields**.
- Determinism preserved (counting is in document order).

**Acceptance:** a 3-figure / 2-table / 2-equation doc opens in LibreOffice
(fields *not* updated) showing "Figure 1/2/3", "Table 1/2", refs pointing at the
right numbers; a unit test asserts the cached values are the computed numbers,
not `"1"`; the validator + python-docx checks still pass.

### 1.2 Math font styles & missing constructs
- `\mathbb`/`\mathcal`/`\mathscr`/`\mathfrak` → map ASCII letters to the Unicode
  math-alphanumeric blocks (ℝℤℕℂ…, 𝒜…, 𝔄…) via a small table; fall back to the
  plain letter when a glyph doesn't exist.
- `\mathbf`/`\mathsf`/`\mathtt`/`\mathit` → styled runs (`m:rPr` `m:sty`
  `val="b"/"p"/…`, or upright+font) so weight/shape survives.
- `\binom`/`\dbinom`/`\tbinom` → `m:d` (parens) wrapping an `m:f` with
  `m:type val="noBar"`.
- `\pmod{n}` → " (mod n)"; `\bmod` → "mod".
- Stretch: `\overset`/`\underset`/`\stackrel` (`m:limUpp`/`m:limLow`),
  `\substack`, `\overbrace`/`\underbrace` (`m:groupChr`), `\boxed` (`m:borderBox`),
  and `align` `&`-alignment via `m:eqArr` instead of `m:m`.

**Acceptance:** the probe table renders ℝ/ℒ/bold-v/binom/(mod n) correctly; new
`tex2word-math` unit tests cover each; no regression in the 43 existing math tests.

---

## Sprint 2 — Differential testing & cutover

Goal: prove Rust ≥ Python on the corpus, then flip the default.

### 2.1 Differential harness
- A workspace test (or a `xtask`/script) that converts the corpus `.tex` +
  arXiv UATs (already in the Python tree) with the Rust CLI and asserts:
  every output passes `tex2word-validate` with zero violations; opens in
  python-docx; and its **coverage report** has no unexpected unsupported macros.
- Where the Python converter is runnable, add a structural diff: compare the two
  `.docx` on a normalized feature vector (counts of headings/math/tables/figures/
  fields/bookmarks) and flag divergences for triage. (Byte-equality is not a
  goal; feature parity is.)
- Produce a **parity report** (per-file: Rust coverage vs Python, gaps) — the
  go/no-go artifact for cutover.

### 2.2 Cutover
- Address divergences the harness surfaces (feed back into Sprint 1's tables/
  passes as needed).
- Flip defaults: README/docs point at the Rust CLI; the Python tree is marked
  deprecated (kept for one release as the reference oracle, then retired).
- CI runs the differential harness on every push.

**Acceptance:** the harness is green across the corpus/UATs; the parity report
shows no feature regressions vs Python; docs updated; Python marked deprecated.

---

## Backlog (post-cutover, not blocking)

- Math polish: `\xrightarrow`/`\xleftarrow`, `\cfrac`, `\substack`, wide
  `\overrightarrow`/`\overbrace`, matrix/`align` fine alignment.
- Deferred Phase-5 items: docx **reference-doc** reading (needs a DEFLATE
  inflater — also upgrades the validator to inspect compressed foreign docx),
  endnotes/`\index`/`INDEX`, full CSL/BibTeX/Zotero citations, static `TOC`
  entry generation, `.docx`→LaTeX (needs a docx parser).

## Cross-cutting

- **Quality gate every commit:** `cargo fmt --all --check`,
  `cargo clippy --all-targets -- -D warnings`, `cargo test --all`, offline.
- **Validation:** every generated doc keeps passing `tex2word-validate` and
  opening in python-docx; from Sprint 1, cross-ref/caption numbers must be
  correct on open in a *non-updating* viewer (the real usability bar).
- **Sequencing:** Sprint 1 (usability) is a hard prerequisite for a credible
  cutover — shipping Rust as default while refs show "1" everywhere would
  regress perceived quality versus expectations.
