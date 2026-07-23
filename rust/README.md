# tex2word (Rust)

Convert **LaTeX** to editable **Microsoft Word** (`.docx`) with native
OfficeMath (OMML) equations and live Word fields — a dependency-free Rust
implementation.

`tex2word` parses a LaTeX document into an intermediate representation (IR) and
emits WordprocessingML: real headings, paragraphs, lists, tables, figures,
citations, footnotes, cross-references, and math that Word edits natively (not
images). It builds and runs **offline with zero external crates** — the ZIP
container, CRC-32, XML, and the LaTeX→OMML math engine are all hand-written.

> **Version 1.0.6.** This is the Rust line of tex2word; it mirrors the behaviour
> of the reference implementation at the same version number.

## Install & build

Requires a stable Rust toolchain (**1.82+**, the declared MSRV).

```bash
git clone https://github.com/yfyang86/tex2word
cd tex2word          # (or the rust/ subtree if building from the combined repo)
cargo build --release
```

The `tex2word` binary is produced at `target/release/tex2word`.

## Command-line usage

```bash
# LaTeX -> .docx
tex2word convert paper.tex -o paper.docx

# with a page preset and a coverage report on stderr
tex2word convert paper.tex --page a4 --report

# fail the run if anything degraded (unsupported macro dropped, etc.)
tex2word convert paper.tex --strict

# IR round-trip: reconstruct a .tex from the parsed IR
tex2word latex paper.tex -o roundtrip.tex

# structurally validate a generated .docx (in-house OOXML validator)
tex2word validate paper.docx
```

`\input`/`\include` files are resolved relative to the input file's directory.

## Library usage

```rust
use tex2word::{convert_source, convert_file, PageGeometry};

// from a string
let conv = convert_source(r"\documentclass{article}\begin{document}Hi \textbf{there}, $x^2$.\end{document}");
std::fs::write("out.docx", &conv.docx).unwrap();
// conv.document is the parsed IR; conv.warnings / conv.coverage describe the run

// or straight from a file
let (path, warnings, coverage) =
    convert_file(std::path::Path::new("paper.tex"), None, &PageGeometry::default()).unwrap();
```

## What it converts

- **Structure** — title/author/date, `\section`…`\subsubsection` (numbered +
  starred), paragraphs, `\\` line breaks, escaped literals.
- **Text** — `\textbf`/`\emph`/`\textit`/`\texttt`/`\underline`/`\textsc`,
  `\textcolor`, hyperlinks (`\href`/`\url`).
- **Lists** — `itemize`/`enumerate` with **arbitrary nesting** (numbered
  `1.` / `(a)` / `(i)` multilevel), `description`, custom `\item[label]`.
- **Math** — inline `$…$` / `\(…\)` and display `\[…\]` / `equation` / `align`
  / `gather` / matrices, rendered as native **OMML**: fractions, roots, scripts,
  n-ary operators with limits, accents, delimiters, function names, Greek and a
  broad symbol table, `\mathbb`/`\mathcal`/`\mathfrak` alphabets, `\binom`,
  `\pmod`. Plain-TeX `\halign` systems and `\cr` rows are handled too.
- **Tables** — `tabular`/`array`/`longtable`, booktabs rules, `\multicolumn`
  and `\multirow` spans, column alignment.
- **Floats** — `figure`/`table` (and full-width `figure*`/`table*`), `\caption`
  with live `SEQ` numbers, `\includegraphics`.
- **Live fields & cross-references** — numbered sections/figures/tables/
  equations with cached `SEQ`/`REF`/`PAGEREF` fields, `\ref`/`\eqref`/`\cref`/
  `\autoref`/`\nameref`/`\pageref`, `\tableofcontents`, multi-column layout.
- **Scholarly** — `\cite` family, `thebibliography`, `\footnote`, theorem-like
  environments.
- **Document classes & idioms** — the `exam` class (`questions`/`parts`/
  `subparts` as nested numbered lists; solutions hidden unless `\printanswers`;
  recovered problem-sheet title), and the TikZ "cheatsheet" content-box idiom
  (text/math recovered rather than dropped).

Unsupported constructs degrade gracefully (dropped with a recorded warning),
never aborting the conversion; `--strict` turns any such degradation into a
non-zero exit.

## Workspace layout

```
Cargo.toml                    workspace (version 1.0.6, MSRV 1.82)
crates/
  tex2word-ir/                IR types — the front-end ⇄ back-end contract
  tex2word-frontend/          LaTeX -> IR (parse, macros, preprocess)
  tex2word-math/              LaTeX math -> OMML engine
  tex2word-backend/           IR -> OOXML .docx (+ fields, zip, images)
  tex2word-latex/             IR -> LaTeX (round-trip writer)
  tex2word-validate/          structural OOXML/OPC validator
  tex2word/                   the one-call pipeline + public API
  tex2word-cli/               the `tex2word` binary
```

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for the build/test workflow and
architecture, [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development rules,
and [`CHANGELOG.md`](CHANGELOG.md) for release history.

## Testing

```bash
cargo test --workspace      # unit + integration tests
cargo clippy --all-targets  # lints (kept warning-free)
cargo fmt --check           # formatting
```

## License

MIT © Yifan Yang. See [`LICENSE`](LICENSE).
