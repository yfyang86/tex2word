//! Differential/corpus harness (Phase 6 Sprint 2). Runs the Python project's own
//! test fixtures + arXiv UATs through the Rust converter and asserts each output
//! is structurally valid (the in-house OOXML validator, zero violations). This
//! is the go/no-go gate for cutover: a regression anywhere in the pipeline that
//! produces malformed output fails CI.
//!
//! A live two-converter diff against Python isn't run here — its `pylatexenc`
//! dependency doesn't build in this offline environment — so parity is measured
//! Rust-side (validity + coverage). The corpus is the Python project's own
//! fixtures, so passing them exercises the intended feature surface.

use std::path::{Path, PathBuf};

fn corpus_root() -> PathBuf {
    // rust/crates/tex2word → repo root → tests/
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests")
}

const CORPUS: &[&str] = &[
    "corpus/article.tex",
    "corpus/features.tex",
    "corpus/longtable.tex",
    "corpus/macros.tex",
    "corpus/tables.tex",
    "uat/arXiv-2507.17026v2/main.tex",
    "uat/arXiv-2605.23904v2/main.tex",
];

#[test]
fn corpus_converts_to_valid_docx() {
    let root = corpus_root();
    if !root.exists() {
        eprintln!("corpus not present at {}; skipping", root.display());
        return;
    }
    let tmp = std::env::temp_dir().join(format!("t2w_parity_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp);

    let mut checked = 0;
    let mut failures: Vec<String> = Vec::new();
    for rel in CORPUS {
        let input = root.join(rel);
        if !input.exists() {
            continue;
        }
        checked += 1;
        let out = tmp.join(format!("{}.docx", rel.replace('/', "_")));
        match tex2word::convert_file(&input, Some(&out), &tex2word::PageGeometry::default()) {
            Ok(_) => {
                let bytes = std::fs::read(&out).expect("read output");
                let violations = tex2word_validate::validate_docx(&bytes);
                if !violations.is_empty() {
                    failures.push(format!("{rel}:\n    {}", violations.join("\n    ")));
                }
            }
            Err(e) => failures.push(format!("{rel}: conversion failed: {e}")),
        }
    }
    let _ = std::fs::remove_dir_all(&tmp);

    assert!(
        checked > 0,
        "no corpus files found under {}",
        root.display()
    );
    assert!(
        failures.is_empty(),
        "corpus produced invalid/failed output:\n{}",
        failures.join("\n")
    );
}
