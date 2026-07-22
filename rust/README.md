# tex2word (Rust)

A **Rust rewrite** of [tex2word](../README.md) — LaTeX → Microsoft Word
(`.docx`). This is an in-progress port that lives on the `rust` branch alongside
the reference Python implementation. See [`ROADMAP.md`](ROADMAP.md) for the
module-by-module plan and current status (a working, dependency-free
**vertical slice**).

## Build & run

Requires a stable Rust toolchain (1.82+).

```bash
cd rust
cargo build
cargo test
cargo run -p tex2word-cli -- convert path/to/paper.tex -o paper.docx
```

The vertical slice converts titles, sectioning, paragraphs, character emphasis
(`\textbf`/`\emph`/`\textit`/`\texttt`/`\underline`), `\\` line breaks, escaped
literals and inline `$…$` math into a real, deterministic `.docx`. Math, tables,
figures, live fields and the rest are being ported phase by phase.

## Library API

```rust
let conv = tex2word::convert_source(r"\documentclass{article}\begin{document}Hi \textbf{there}.\end{document}");
std::fs::write("out.docx", &conv.docx).unwrap();
// conv.document is the parsed IR
```

## Layout

```
rust/
  Cargo.toml                 workspace
  crates/
    tex2word-ir/             IR types (front-end ⇄ back-end contract)
    tex2word-frontend/       LaTeX -> IR
    tex2word-backend/        IR -> OOXML .docx (+ zip, ooxml modules)
    tex2word/                pipeline + public API
    tex2word-cli/            `tex2word` binary
```

Zero external dependencies today (hand-written ZIP/CRC-32 and XML) so it builds
offline; production crates will be adopted as later phases warrant — see the
roadmap's dependency policy.
