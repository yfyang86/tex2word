# Synthetic probe harness

`tools/synth` finds conversion bugs with small, synthetic LaTeX documents
(*probes*), and keeps them fixed. It grew out of issue #44, where constructs
that worked in a paragraph broke inside table cells, captions and theorems.
The core of the harness puts every construct into every container on purpose.

Run every command from the repository root (`PYTHONPATH=src` if tex2word
isn't installed, or `uv run`):

```sh
python -m tools.synth verify            # the gate: exit 1 on NEW or FIXED findings
python -m tools.synth triage --out r.md # clustered Markdown report of all findings
python -m tools.synth repro <probe-id>  # one probe as a folder + test stub + diagnosis
python -m tools.synth update            # prune fixed entries from the baseline
python -m tools.synth fuzz --save       # random nestings; promote minimal failures
python -m tools.synth generate --out d  # write the corpus (e.g. for the Rust port)
python -m tools.synth list --tier smoke
```

Common options: `--filter REGEX` (probe ids), `--tier smoke`, `--jobs N`,
`--tikz` (compile TikZ with the local TeX engine; off by default so runs are
fast and deterministic), and `--render` (also check the text in a LibreOffice
PDF render; slow, so combine it with `--filter`).

## The loop: generate → verify → fix → update

1. **Generate.** `catalog/` builds about 8,000 probes:
   - `matrix.py`: about 100 inline *constructs* (`\textbf`, `\citet`, `\ref`,
     accents, siunitx, `\footnote`, `\verb`, …) × about 70 *contexts* (paragraph,
     heading, captions, table cells, `\multicolumn`, theorem title, footnote,
     tcolorbox, minipage, title/abstract, …), keeping only legal LaTeX: no
     `\verb` in arguments, no fragile commands in moving arguments, cell-only
     commands only in cells.
   - `math.py`: about 190 expressions (inline and display) and 23 display
     environments.
   - `documents.py`: macros, conditionals, `\input` and friends, structure,
     lists, tables, figures, verbatim, bibliographies, cross-references, and
     robustness (bad input, control characters, deep nesting, big documents).
   - `classes.py`: front matter of IEEEtran, acmart, llncs, elsarticle, revtex,
     Springer Nature, amsart, KOMA, memoir, beamer, moderncv, exam, letter,
     authblk, NeurIPS/ICML styles, ctexart and tufte.
   - `found.json`: nested cases promoted by `fuzz --save`.
2. **Verify.** `oracles.py` checks every conversion:

   | finding | meaning |
   |---|---|
   | `crash:…`, `timeout`, `invalid-docx` | the conversion failed or produced a broken package |
   | `dropped`, `duplicated` | the probe's sentinel (`Qx7k`) or token occurs fewer/more times than in the source |
   | `tex-leak:\cmd`, `brace-leak`, `dim-leak` | markup, braces or lengths (`2pt`) reached the visible text |
   | `raw-ir:\cmd` | the IR kept raw LaTeX |
   | `unresolved-ref`, `raw-cite:key` | `??` or a raw citation key in the text |
   | `warning:<construct>`, `error:…` | the conversion report complained |
   | `math-raw`, `math-missing`, `math-empty-nary`, `math-leak` | math fell back to TeX, vanished, lost a sum's operand, or leaked markup |
   | `math-roundtrip` | OMML → LaTeX → OMML changed the text |
   | `expect-…`, `label:…`, `style:w:b` | probe-specific expectations: texts, absent texts, XML, labels, run formatting |
   | `render-missing` | (`--render`) the token is not in the LibreOffice PDF |

   `baseline.json` lists known failures per probe. `verify` reports a finding
   that isn't in the baseline as **NEW**, and a baseline finding that no longer
   occurs as **FIXED**. Either one fails the gate.
3. **Fix.** Start with `triage --out report.md`. It reads the matrix three ways:
   - a *broken construct* fails in most contexts;
   - a *broken context* fails for most constructs;
   - an *interaction* fails only in some contexts (the #44 kind).

   Then run `repro <probe-id>`. It writes the probe as a standalone folder and
   prints the findings, warnings, IR outline and visible text. It also writes a
   self-contained pytest stub you can move into `tests/` once the bug is fixed.
4. **Update.** After a fix, `verify` shows FIXED. `update` drops those entries,
   and you commit `baseline.json`. `update --accept` records NEW findings as
   known instead (for a deliberate decision, never to silence a regression).
   `fuzz --save` appends minimised multi-layer failures to
   `catalog/found.json`, so each new discovery becomes a permanent probe.

## Environment

Optional packages change results (`latex2mathml` rescues math the direct OMML
path can't handle; `pypdfium2`/Pillow embed PDF figures). The baseline is made
with every extra installed (`uv sync --all-extras`), as in CI, and records
which ones were present. `verify` warns when your environment differs, and
the pytest gate skips itself rather than report false failures. TikZ
compilation is off unless you pass `--tikz`.

## Gates

- `tests/test_synth_probes.py` runs the smoke tier in the normal test suite
  (a few seconds). With `T2W_SYNTH_FULL=1` it runs every probe.
- The `synthetic-probes` CI job runs the full `verify` and uploads the triage
  report as an artifact.

## Adding probes

- **Construct or context:** add a `Construct(...)` or `Context(...)` in
  `matrix.py`. Put the sentinel `S` in the construct's visible text and the
  slot `%X` in the context. Declare `verbatim`, `fragile`, `cell_only` or
  `no_cell` so only legal combinations are generated.
- **Document probe:** call `D(name, body, pre=..., texts=[...], absent=[...], ...)`
  in `documents.py`. Use `KEEPn` for text that must survive and `DROPn` for text
  that must not.
- **Class template:** add it with `C(name, source)` in `classes.py`. Every
  `K…` token must reach the document, and no `DROP…` token may appear.

Then run `verify`: real defects show up as NEW. Fix them, or record them with
`update --accept` and add an issue/note to their baseline entry.
