# Changelog

All notable changes to **tex2word (Rust)** are recorded here. The Rust line
tracks the reference implementation and shares its version numbers; see
[`README.md`](README.md) for the feature overview.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.0.6 — problem sheets, cheatsheets & plain-TeX math

Brings the Rust implementation to parity with the 1.0.6 feature surface and
promotes the workspace to a standalone project.

### Added

- **`exam` document class.** `questions`/`parts`/`subparts` and
  `\question`/`\miquestion`/`\part`/`\subpart` (dropping an optional
  `[points]`) render as nested numbered lists, so exam's `\part` no longer
  collides with `\part` sectioning ("Part I D"). A question that leads straight
  into its `\parts` still gets its own number above the `(a)/(b)/(c)`
  sub-items; solutions are hidden unless `\printanswers`; the Oxford-style
  problem-sheet title is recovered from `\course`/`\sheetnumber`/`\oxfordterm`/
  `\sheettitle`.
- **Nested lists.** `Block::List` now stores depth-tagged `ListItem`s, so
  `itemize`/`enumerate` nest to arbitrary depth. The numbering definitions gain
  five multilevel levels (`1.` / `(a)` / `(i)` / …). Display math `\[ … \]` and
  inline `\( … \)` inside a list item now render.
- **Plain-TeX math.** `\halign` systems of equations inside `\[ … \]` (wrapped
  in `\centerline{\hbox{\vbox{\openup…\jot …}}}`) convert to an `array`; `\cr`
  is treated as a matrix/array row separator; the math-class wrappers
  `\mathbin`/`\mathrel`/`\mathop`/`\mathord`/`\mathopen`/`\mathclose`/
  `\mathpunct`/`\mathinner` render their content transparently.
- **Symbols.** Normal-subgroup relations (`\vartriangleleft`/`\trianglelefteq`/
  `\ntrianglelefteq`/…), `\nmid`/`\nparallel`/`\smallsetminus`, and the
  restriction/harpoon glyphs (`\restriction`/`\upharpoonright`/…). The `\/`
  italic correction is dropped.
- **TikZ "cheatsheet" content boxes.** `\node{…minipage…}` + `\node[fancytitle]`
  idioms have their text/math recovered (titles become headings) instead of
  being dropped; real diagrams still route to the image path.

### Project

- Standalone-ready workspace: version 1.0.6 across all crates, MSRV 1.82,
  `Cargo.lock` tracked, richer package metadata.
- End-to-end test suite for the 1.0.6 features (`crates/tex2word/tests/
  feature_1_0_6.rs`) with a vendored `oxmathproblems` fixture.
- Project documentation: `README.md`, `DEVELOPMENT.md`, `CONTRIBUTING.md`.

## Earlier

Phases 0–6 built the dependency-free end-to-end pipeline: the LaTeX front-end,
the OMML math engine, tables/figures/images, live fields & cross-references
(numbered sections, TOC, multi-column), citations/footnotes/theorems, the
structural OOXML validator, the conversion/coverage report, and the IR→LaTeX
round-trip writer. See `ROADMAP.md` and the `PHASE*_PLAN.md` documents for the
phase-by-phase history.
