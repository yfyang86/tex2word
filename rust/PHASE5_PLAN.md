# Phase 5 — Parity layer (three-sprint plan)

Phase 5 closes the remaining fidelity and quality gaps before the Phase 6 cutover:
the content types real papers still lose (citations, footnotes, theorems), a
structural **OOXML validator** that fails CI on malformed output, a
**conversion report** that surfaces what was dropped, and a **round-trip**
IR→LaTeX writer that unlocks differential testing.

Reference oracle (Python, on this branch):
- `src/tex2word/validate.py` — the pragmatic OPC + content-model validator.
- `src/tex2word/bib/*`, `backend/fields.py` — citations/bibliography, field codes.
- `src/tex2word/backend/latex_writer.py` — the IR→LaTeX round-trip writer.
- `src/tex2word/ir.py` — `Cite`/`Footnote`/`Theorem`/`Bibliography`/`CSLItem`.

## Where the Rust port stands

Phases 0–4 are done: front-end core, OMML math, tables/figures/images, and live
fields/cross-references (`SEQ`/`REF`/`PAGEREF`/`HYPERLINK`/`TOC`, numbered
sections, multi-column). The IR has no citation, footnote, theorem, or
bibliography concept yet, and there is no output validator or `.tex` writer.

Dependency order: citations need the bibliography numbering (Sprint 1);
theorems reuse the Sprint-1 `SEQ`/bookmark plumbing; the validator (Sprint 2) is
independent but gates everything after it; the round-trip writer (Sprint 3)
reads the finished IR.

---

## Sprint 1 — Citations, bibliography, footnotes

**Goal:** a paper with `\cite` + a `thebibliography` and `\footnote`s converts
faithfully — numbered references, in-text `[n]` markers hyperlinked to them, and
real Word footnotes.

### 1.1 IR (`tex2word-ir`)
- `Inline::Cite { keys: Vec<String>, mode: CiteMode }` (`CiteMode` = Paren / Text
  / Author / Year / Num) with a `rendered: Option<String>` filled by the pass.
- `Inline::Footnote { inlines: Vec<Inline> }`.
- `Block::Bibliography { entries: Vec<BibEntry> }`, `BibEntry { key, label,
  inlines }` (`label` = the `[custom]` `\bibitem` marker or the auto number).

### 1.2 Frontend
- `\cite`/`\citep`/`\citet`/`\citeauthor`/`\citeyear`/`\citenum` (+ optional
  `[prefix]`/`[suffix]`) → `Inline::Cite` with the right `mode`; comma-split keys.
- `\footnote{…}` → `Inline::Footnote`.
- `thebibliography` env → `Block::Bibliography`; each `\bibitem[label]{key} …`
  (body up to the next `\bibitem`/env end) → a `BibEntry`.

### 1.3 Citation pass (`tex2word` crate, extend `crossref` or a `cite` module)
- Number the bibliography entries (1..N; honor explicit `[label]`).
- Register each entry's bookmark (`sanitize_bookmark("cite_"+key)`), add to
  `Document.labels`.
- Resolve each `Cite`: render the in-text marker (`[1]`, `[1, 3]`, author/year
  styles later) into `Cite.rendered`; warn on unknown keys.

### 1.4 Backend
- `footnotes.xml` part: a `MediaPart`-like extra part carrying `<w:footnotes>`
  with the separator/continuationSeparator pair (ids −1/0) + one `<w:footnote>`
  per note; body reference = `<w:rStyle FootnoteReference/> <w:footnoteReference
  w:id=…/>`. New content-type override + a `footnotes` relationship.
- `Cite` → the rendered marker as a run, hyperlinked (`HYPERLINK \l`) to the
  bib bookmark when resolved.
- `Bibliography` → a "References" `Heading1` + one numbered paragraph per entry,
  each wrapped in its bookmark, styled `Bibliography`/hanging-indent.
- Styles: add `FootnoteReference`, `FootnoteText`, `Bibliography`.

**Acceptance:** unit tests (cite parsing/modes, bibitem split, footnote
numbering, marker formatting) + a UAT: a doc with `\cite{a,b}`, two footnotes,
and a `thebibliography` opens in python-docx with a real `footnotes.xml`, `[1]`/
`[1, 2]` markers linked to numbered, bookmarked references; unknown `\cite` warns.

---

## Sprint 2 — OOXML validator, conversion report, theorems

**Goal:** malformed output can't ship, the user learns what was dropped, and
theorem-like environments render numbered.

### 2.1 Structural validator (`tex2word-validate`, new crate)
Port the pragmatic checks from `validate.py`:
- **OPC:** package opens, `_REQUIRED` parts exist (`[Content_Types].xml`,
  `_rels/.rels`, `word/document.xml`, `word/styles.xml`), every XML part is
  well-formed (a tiny pull-parser or `quick-xml` behind a feature — but keep the
  zero-dep default with a minimal well-formedness scanner), every part has a
  declared content type, every relationship target resolves.
- **Content model:** the child-order sequences for `rPr`/`pPr`/`tblPr`/`trPr`/
  `tcPr` (the "Word silently repairs" defect class) + a few enumerated-attr checks.
- **Fields/bookmarks:** every `fldChar begin` has a matching `end`; every
  `bookmarkStart` id has a `bookmarkEnd`.
- Return `Vec<String>` of violations. Wire into CI (a workspace test converts the
  corpus/UATs and asserts zero violations) and a `tex2word validate <docx>` CLI.

### 2.2 Conversion report
- Extend `Warning`/report: track unsupported macros/environments (the frontend's
  "unknown macro → dropped" path records them) and dropped features; expose a
  `--report` summary from the CLI (counts by category).

### 2.3 Theorem environments
- `Block::Theorem { kind, blocks, title, label, counter }`.
- Frontend: `theorem`/`lemma`/`proposition`/`corollary`/`definition`/`remark`/
  `example`/`proof` → `Theorem`; `[title]` optional arg; shared vs independent
  counters (`\newtheorem` sharing is a later refinement — start with a common
  "Theorem" series + unnumbered `proof`).
- Backend: a bold "Theorem N (Title). " run (live `SEQ Theorem` in a bookmark
  when labelled) + the body in an italic/normal style; `\ref` already routes
  `RefKind::Theorem` (Sprint-1/Phase-4 plumbing) — wire the counter.

**Acceptance:** the validator flags a deliberately-broken part in a unit test and
passes on every generated UAT; theorem UAT numbers/bookmarks correctly and
`\cref{thm:x}` shows "thm. N"; the report lists a planted unsupported macro.

---

## Sprint 3 — Round-trip writer + reference-doc templates

**Goal:** differential-testable round-trip and externally-styled output.

### 3.1 IR → LaTeX writer (`tex2word-latex`, new crate)
Port `latex_writer.py` (IR → `.tex`): emit a document reconstructing headings,
paragraphs, emphasis, math (`$…$`/`\[…\]`), lists, tables (`tabular`+`booktabs`),
figures (`\includegraphics`+`\caption`+`\label`), refs/cites/links, footnotes,
and the bibliography. Enables **round-trip tests**: `LaTeX → IR → LaTeX → IR`
should reach a stable IR (idempotent), catching lossy parsing.

### 3.2 Reference-doc templates
- `--reference-doc template.docx`: read the template's `styles.xml`, page
  geometry (`w:sectPr` `pgSz`/`pgMar`), and header/footer refs, and thread them
  through `build_package` (the Python `page_pgsz`/`page_pgmar`/`header_footer_refs`
  hooks already have a home in `_sect_pr`).

### 3.3 Coverage report artifact
- A machine-readable coverage summary (macros seen/handled/dropped across the
  corpus), the input to the Phase 6 differential-cutover decision.

**Acceptance:** round-trip idempotence tests on the corpus; a `--reference-doc`
run adopts the template's page size + a custom style; a coverage report generates.

---

## Cross-cutting

- **Quality gate every commit:** `cargo fmt --all --check`,
  `cargo clippy --all-targets -- -D warnings`, `cargo test --all`, all offline.
- **Determinism & validation:** every UAT keeps opening in python-docx *and*,
  from Sprint 2 on, passing the in-house validator with zero violations.
- **Zero-dependency default** stays the rule; any XML-reading for the validator/
  round-trip uses a minimal hand-rolled scanner unless a vetted crate is gated
  behind an off-by-default feature.
- **Scope discipline:** the full CSL/BibTeX/Zotero citation engine, endnotes, the
  index (`\index`/`INDEX`), and `.docx`→LaTeX (needs a docx *parser*) are
  explicitly **out of scope** for Phase 5 — candidates for a later pass. Sprint 1
  ships the LaTeX-native `thebibliography` path; Sprint 3 ships IR→LaTeX only.
- **Next:** Phase 6 — differential-test Rust vs Python across the corpus/UATs,
  then make Rust the default and retire the Python tree.
