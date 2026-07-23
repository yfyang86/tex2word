# Contributing & development rules

Thanks for working on tex2word (Rust). This document is the rulebook; the
[`DEVELOPMENT.md`](DEVELOPMENT.md) manual explains the architecture and how to
add features.

## Ground rules

1. **No new runtime dependencies without discussion.** The workspace is
   deliberately dependency-free so it builds and tests offline and
   deterministically. Adding a crate is a design decision — open an issue first
   and make the case (see the dependency policy in `ROADMAP.md`).
2. **Never abort on unsupported input.** Degrade gracefully: drop the construct,
   record a `Warning`, and keep converting. Aborting is only acceptable behind
   the caller's `--strict` opt-in.
3. **Every conversion must produce a structurally valid `.docx`.** Route new
   output through `tex2word-validate`; a validation failure is a bug.
4. **Deterministic output.** Identical input must yield byte-identical output.
   Don't introduce timestamps, hash-map iteration order, or other nondeterminism
   into the writer.
5. **The IR boundary is sacred.** Front-end produces IR; back-end consumes it.
   Don't smuggle LaTeX strings past the IR or reach back into source text from
   the back-end (math LaTeX carried inside `Inline::Math` is the one sanctioned
   exception).

## Before you commit

The following must all pass — CI enforces them:

```bash
cargo fmt --check
cargo clippy --all-targets    # warning-free
cargo test --workspace
```

- Keep `clippy` **warning-free** (not just error-free).
- Keep `rustfmt` clean (run `cargo fmt`).
- Add tests for anything you change: a unit test beside the code, and an
  end-to-end test for user-visible behaviour. Test fixtures go **inside**
  `crates/*/tests/fixtures/`.

## Commits & branches

- Work on a feature branch; do not commit directly to `main`.
- Write focused commits with a clear subject line (imperative mood) and a body
  explaining the *why*. Group a logical change into one commit where practical.
- Reference the issue you're addressing.

## Pull requests

- Describe what changed and why, and note any IR changes (they ripple across
  every consumer).
- Include the test evidence: what you added and that `fmt`/`clippy`/`test` are
  green.
- Keep PRs reviewably small; split unrelated changes.

## Versioning

The project follows [Semantic Versioning](https://semver.org) and shares its
version number with the reference implementation. The version is set once in the
workspace (`[workspace.package].version`) and inherited by every crate — bump it
there, and add a matching `CHANGELOG.md` entry.

## Code style

- Idiomatic Rust; let `rustfmt` and `clippy` decide the small stuff.
- Prefer exhaustive `match` over catch-alls when handling IR, so a new variant
  forces every consumer to consider it.
- Comment the *why*, not the *what*; the OOXML/OMML corners in particular
  benefit from a note on the schema constraint being satisfied.
