//! `tex2word` CLI (Rust port, vertical slice).
//!
//! Usage:
//!   tex2word convert <input.tex> [-o <output.docx>]
//!   tex2word validate <file.docx>
//!
//! A dependency-free arg parser keeps the slice self-contained; a richer CLI
//! (--report, --reference-doc, …) is a later milestone.

use std::path::PathBuf;
use std::process::ExitCode;

fn usage() -> String {
    "tex2word (Rust) — LaTeX -> Word (.docx)\n\
     \n\
     USAGE:\n    \
     tex2word convert <input.tex> [-o <output.docx>] [--strict]\n    \
     tex2word validate <file.docx>\n"
        .to_string()
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(msg) => {
            println!("{msg}");
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("error: {err}");
            eprint!("\n{}", usage());
            ExitCode::FAILURE
        }
    }
}

fn run(args: &[String]) -> Result<String, String> {
    let mut it = args.iter();
    match it.next().map(String::as_str) {
        Some("convert") => run_convert(it),
        Some("validate") => run_validate(it),
        Some("-h") | Some("--help") | None => Ok(usage()),
        Some(other) => Err(format!("unknown command '{other}'")),
    }
}

fn run_convert<'a>(it: impl Iterator<Item = &'a String>) -> Result<String, String> {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut strict = false;
    let mut it = it;
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => {
                output = Some(PathBuf::from(it.next().ok_or("-o requires a path")?));
            }
            "--strict" => strict = true,
            _ if a.starts_with('-') => return Err(format!("unknown flag '{a}'")),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let input = input.ok_or("no input .tex file given")?;
    let (out, warnings) = tex2word::convert_file(&input, output.as_deref())
        .map_err(|e| format!("{}: {e}", input.display()))?;
    for w in &warnings {
        eprintln!("warning: {}: {}", w.context, w.message);
    }
    if strict && !warnings.is_empty() {
        return Err(format!(
            "{}: {} warning(s) with --strict",
            input.display(),
            warnings.len()
        ));
    }
    let note = if warnings.is_empty() {
        String::new()
    } else {
        format!(" ({} warning(s))", warnings.len())
    };
    Ok(format!("wrote {}{note}", out.display()))
}

fn run_validate<'a>(mut it: impl Iterator<Item = &'a String>) -> Result<String, String> {
    let path = PathBuf::from(it.next().ok_or("no .docx file given")?);
    let bytes = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let violations = tex2word_validate::validate_docx(&bytes);
    if violations.is_empty() {
        Ok(format!(
            "{}: valid ({} checks passed)",
            path.display(),
            "all"
        ))
    } else {
        let mut msg = format!("{}: {} violation(s):", path.display(), violations.len());
        for v in &violations {
            msg.push_str(&format!("\n  - {v}"));
        }
        Err(msg)
    }
}
