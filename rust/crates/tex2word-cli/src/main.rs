//! `tex2word` CLI (Rust port, vertical slice).
//!
//! Usage:
//!   tex2word convert <input.tex> [-o <output.docx>]
//!
//! A dependency-free arg parser keeps the slice self-contained; a richer CLI
//! (subcommands, --report, --reference-doc, …) is a later milestone.

use std::path::PathBuf;
use std::process::ExitCode;

fn usage() -> String {
    "tex2word (Rust) — LaTeX -> Word (.docx)\n\
     \n\
     USAGE:\n    \
     tex2word convert <input.tex> [-o <output.docx>]\n"
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
        Some("convert") => {}
        Some("-h") | Some("--help") | None => return Ok(usage()),
        Some(other) => return Err(format!("unknown command '{other}'")),
    }

    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => {
                output = Some(PathBuf::from(it.next().ok_or("-o requires a path")?));
            }
            _ if a.starts_with('-') => return Err(format!("unknown flag '{a}'")),
            _ => input = Some(PathBuf::from(a)),
        }
    }

    let input = input.ok_or("no input .tex file given")?;
    let out = tex2word::convert_file(&input, output.as_deref())
        .map_err(|e| format!("{}: {e}", input.display()))?;
    Ok(format!("wrote {}", out.display()))
}
