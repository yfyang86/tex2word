//! tex2word (Rust) — LaTeX → Microsoft Word (`.docx`).
//!
//! This crate ties the front-end (LaTeX → IR) and back-end (IR → OOXML) into a
//! one-call pipeline, mirroring the Python `tex2word.pipeline` API. It is an
//! early **vertical slice**: it proves the architecture end-to-end (a real,
//! valid `.docx` from real LaTeX) while the feature surface is ported module by
//! module — see `rust/ROADMAP.md`.

pub use tex2word_ir as ir;

use std::fs;
use std::io;
use std::path::Path;

/// The result of a conversion: the `.docx` bytes and the parsed IR.
pub struct Conversion {
    pub docx: Vec<u8>,
    pub document: ir::Document,
}

/// Convert LaTeX source to a `.docx` byte buffer (+ the IR).
pub fn convert_source(source: &str) -> Conversion {
    let document = tex2word_frontend::parse_document(source);
    let docx = tex2word_backend::to_docx(&document);
    Conversion { docx, document }
}

/// Convert a `.tex` file to a `.docx` on disk. Returns the output path used.
pub fn convert_file(input: &Path, output: Option<&Path>) -> io::Result<std::path::PathBuf> {
    let source = fs::read_to_string(input)?;
    let conv = convert_source(&source);
    let out = match output {
        Some(p) => p.to_path_buf(),
        None => input.with_extension("docx"),
    };
    fs::write(&out, &conv.docx)?;
    Ok(out)
}
