//! tex2word (Rust) — LaTeX → Microsoft Word (`.docx`).
//!
//! This crate ties the front-end (LaTeX → IR) and back-end (IR → OOXML) into a
//! one-call pipeline, mirroring the Python `tex2word.pipeline` API. It is an
//! early **vertical slice**: it proves the architecture end-to-end (a real,
//! valid `.docx` from real LaTeX) while the feature surface is ported module by
//! module — see `rust/ROADMAP.md`.

pub use tex2word_ir as ir;

pub mod crossref;

use std::fs;
use std::io;
use std::path::Path;

pub use crossref::Warning;

/// The result of a conversion: the `.docx` bytes, the parsed IR, and any
/// non-fatal warnings (e.g. unresolved cross-references).
pub struct Conversion {
    pub docx: Vec<u8>,
    pub document: ir::Document,
    pub warnings: Vec<Warning>,
}

/// Convert LaTeX source to a `.docx` byte buffer (+ the IR + warnings).
pub fn convert_source(source: &str) -> Conversion {
    let (mut document, unsupported) =
        tex2word_frontend::parse_document_reporting(source, Path::new("."));
    let mut warnings = crossref::resolve(&mut document);
    warnings.extend(unsupported_warnings(&unsupported));
    let docx = tex2word_backend::to_docx(&document, Path::new("."));
    Conversion {
        docx,
        document,
        warnings,
    }
}

/// Map unsupported-macro names to warnings.
fn unsupported_warnings(macros: &[String]) -> Vec<Warning> {
    macros
        .iter()
        .map(|m| Warning {
            context: "unsupported".into(),
            message: format!("macro '\\{m}' is not supported (dropped)"),
        })
        .collect()
}

/// Convert a `.tex` file to a `.docx` on disk. Returns the output path used and
/// any conversion warnings. `\input`/`\include` files are resolved relative to
/// the input file's directory.
pub fn convert_file(
    input: &Path,
    output: Option<&Path>,
) -> io::Result<(std::path::PathBuf, Vec<Warning>)> {
    let source = fs::read_to_string(input)?;
    let base = input
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let (mut document, unsupported) = tex2word_frontend::parse_document_reporting(&source, base);
    let mut warnings = crossref::resolve(&mut document);
    warnings.extend(unsupported_warnings(&unsupported));
    let docx = tex2word_backend::to_docx(&document, base);
    let out = match output {
        Some(p) => p.to_path_buf(),
        None => input.with_extension("docx"),
    };
    fs::write(&out, &docx)?;
    Ok((out, warnings))
}
