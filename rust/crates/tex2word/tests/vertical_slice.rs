//! End-to-end vertical-slice test: real LaTeX -> a real, structurally-sane
//! `.docx`. Proves the front-end -> IR -> back-end pipeline is wired up.

use tex2word::ir::{Block, Inline};

const SRC: &str = r"\documentclass{article}
\title{Vertical Slice}
\begin{document}
\maketitle
\section{Introduction}
This is \textbf{bold} and \emph{italic} text with math $E = mc^2$.
\subsection{Details}
A second paragraph.\end{document}";

#[test]
fn converts_latex_to_docx_bytes() {
    let conv = tex2word::convert_source(SRC);

    // ---- IR shape ----
    assert_eq!(
        conv.document.title,
        Some(vec![Inline::Text("Vertical Slice".into())])
    );
    let headings: Vec<u8> = conv
        .document
        .blocks
        .iter()
        .filter_map(|b| match b {
            Block::Heading { level, .. } => Some(*level),
            _ => None,
        })
        .collect();
    assert_eq!(headings, vec![1, 2]);

    // ---- .docx bytes ----
    let d = &conv.docx;
    assert_eq!(&d[..2], b"PK", "not a ZIP");
    let text = String::from_utf8_lossy(d);
    for needle in [
        "[Content_Types].xml",
        "word/document.xml",
        "word/styles.xml",
        "Vertical Slice",
        "Introduction",
        "<w:b/>",    // bold run
        "<w:i/>",    // italic run
        "<m:oMath>", // inline math
        "E = mc^2",
    ] {
        assert!(text.contains(needle), "missing {needle:?} in .docx");
    }
}

#[test]
fn output_is_deterministic() {
    assert_eq!(
        tex2word::convert_source(SRC).docx,
        tex2word::convert_source(SRC).docx
    );
}
