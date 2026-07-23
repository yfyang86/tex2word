# Development manual

How tex2word (Rust) is put together and how to work on it. For the rules of
engagement (branching, commits, review), see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Prerequisites

- A stable Rust toolchain, **1.82 or newer** (the workspace MSRV). Install via
  [rustup](https://rustup.rs).
- No system libraries, no network: the build is fully offline and
  dependency-free.

```bash
cargo build --workspace
cargo test  --workspace
cargo clippy --all-targets   # must be warning-free
cargo fmt --check            # must be clean
```

## Architecture

Conversion is a straight pipeline from LaTeX to a `.docx` byte buffer:

```
LaTeX ─► tex2word-frontend ─► IR ─► crossref ─► tex2word-backend ─► .docx
         (preprocess/         (tex2word-ir)   (numbering,   (OOXML + fields
          macros/parse)            │           refs)         + math + zip)
                                   │                              ▲
                          tex2word-latex (IR→LaTeX)       tex2word-validate
                          round-trip writer               structural checker
```

The **IR** (`tex2word-ir`) is the contract between halves: a tree of `Block`s
(headings, paragraphs, `MathBlock`, `List`, `Table`, `Float`, `Quote`,
`Theorem`, `Bibliography`, …) whose leaves are `Inline`s (text, emphasis,
`Math`, links, refs, …). Everything upstream produces IR; everything downstream
consumes it. Keeping this boundary clean is the single most important rule.

### Crates and responsibilities

| crate | responsibility |
|-------|----------------|
| `tex2word-ir`       | IR types only — no logic. Change here ripples both ways. |
| `tex2word-frontend` | LaTeX → IR. `strip_comments` → `flatten_inputs` → **`preprocess`** → `macros::expand_macros` → `parse_*`. |
| `tex2word-math`     | LaTeX math → OMML. A recursive-descent parser (`parser.rs`) builds a math `Node` AST; `omml.rs` renders it; `symbols.rs` is the command/symbol table. |
| `tex2word-backend`  | IR → OOXML. `ooxml.rs` emits `word/document.xml` and the numbering/styles parts; `fields.rs` builds `SEQ`/`REF`/`PAGEREF` complex fields; `zip.rs` is the STORE-method ZIP writer; `image.rs` handles rasters. |
| `tex2word-latex`    | IR → LaTeX round-trip writer (basis of differential testing). |
| `tex2word-validate` | Structural OOXML/OPC validation of a produced `.docx`. |
| `tex2word`          | The public API (`convert_source`, `convert_file`, `to_latex_source`), plus `crossref` (numbering/reference resolution) and `report` (coverage). |
| `tex2word-cli`      | Arg parsing and the `tex2word` binary (`convert`/`latex`/`validate`). |

### The front-end pipeline (order matters)

`tex2word-frontend`'s `parse_document_in` runs, in order:

1. `strip_comments` — remove `%` line comments (preserving `\%`).
2. `flatten_inputs` — inline `\input`/`\include` (recursively).
3. **`preprocess`** (`preprocess.rs`) — source-level rewrites that must happen
   *before* macro expansion and parsing: the exam document class, plain-TeX
   `\halign` → `array`, the TikZ cheatsheet idiom, `\/`.
4. `macros::expand_macros` — user `\newcommand`/`\def` expansion.
5. `parse_*` — split into blocks and inlines, building IR.

If you are adding support for a **document class or a source idiom** (something
that is better rewritten than parsed natively), it belongs in `preprocess.rs`.
If you are adding a **macro or environment** with real IR meaning, it belongs in
the parser.

## How to add a feature

Work outside-in and let the IR guide you.

1. **Model it in the IR** if no existing `Block`/`Inline` fits. Add the smallest
   variant/field that captures the semantics, then follow the compiler errors —
   every `match` on the changed type (front-end, back-end, latex writer, report,
   IR text dump) must be updated. This is deliberate: exhaustive matches are how
   we guarantee no consumer silently ignores new content.
2. **Produce it in the front-end** — parse the macro/environment (or rewrite it
   in `preprocess.rs`) into the IR.
3. **Render it in the back-end** — emit the OOXML. Mind element ordering: Word's
   schema is order-sensitive (e.g. `w:pPr` before runs, `tblPr` order). The
   validator (`tex2word-validate`) exists to catch violations — add or run it.
4. **Round-trip it** in `tex2word-latex` if the construct should survive
   `parse → to_latex → parse`.
5. **Cover it** — a unit test next to the code and, for anything user-visible,
   an end-to-end test asserting a valid `.docx` and the specific rendering.

### Worked example: math

A new math command is usually a one-line addition to `tex2word-math`:

- a plain symbol → an arm in `symbols.rs::symbol`,
- an n-ary operator → `symbols.rs::nary`,
- structural syntax (a new accent, wrapper, or environment) → an arm in
  `parser.rs::parse_command` (and, if it renders differently, `omml.rs`).

`\mathbin`/`\mathop`/… are examples of *transparent* wrappers: they parse their
argument and return it unchanged (they only affect spacing).

## Testing

- **Unit tests** live inline (`#[cfg(test)] mod tests`) beside the code they
  exercise — the parser, the math engine, the OOXML writer.
- **Integration tests** live in `crates/tex2word/tests/`:
  - `feature_1_0_6.rs` — the exam class, `\cr` matrices, math-class wrappers,
    asserting valid `.docx` and the exact rendering (uses the vendored
    `tests/fixtures/oxmathproblems` sheet).
  - `validate_output.rs` — a broad sample must validate cleanly.
  - `roundtrip.rs` — `parse → to_latex → parse` equality.
  - `corpus_parity.rs` — runs an external corpus if present, else skips.
- **Golden rule:** every conversion must produce a **structurally valid**
  `.docx`. `tex2word-validate` is the gate; wire new output through it.

Fixtures for tests must live **inside** `crates/*/tests/fixtures/` so the suite
is self-contained (no dependency on paths outside the repo).

## Conventions

- **Zero runtime dependencies.** The workspace has no external crates and should
  stay that way unless a dependency clearly pays for itself; discuss first (see
  the dependency policy in `ROADMAP.md`).
- **Never abort on unsupported input.** Drop it, record a `Warning`, keep going.
  `--strict` is how a caller opts into treating degradation as failure.
- **`clippy` clean and `rustfmt` clean** before every commit.
- **Deterministic output.** The same input yields byte-identical `.docx`
  (STORE-method ZIP, no timestamps) — keep it that way; tests rely on it.
