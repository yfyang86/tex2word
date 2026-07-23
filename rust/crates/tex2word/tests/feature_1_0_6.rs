//! End-to-end tests for the 1.0.6 feature surface: the exam document class,
//! plain-TeX `\halign`/`\cr`, math-class wrappers, and the extra relation
//! symbols. Each asserts a structurally valid `.docx` plus the specific
//! rendering the 1.0.6 fixes guarantee.

use std::path::{Path, PathBuf};

use tex2word::{convert_file, convert_source, PageGeometry};

fn fixture(rel: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(rel)
}

/// Read `word/document.xml` out of a `.docx`. The backend writes uncompressed
/// (STORE) ZIP entries, so scanning local file headers is enough — no inflate.
fn document_xml(zip: &[u8]) -> String {
    let mut i = 0usize;
    while i + 30 <= zip.len() && zip[i..i + 4] == [0x50, 0x4b, 0x03, 0x04] {
        let comp =
            u32::from_le_bytes([zip[i + 18], zip[i + 19], zip[i + 20], zip[i + 21]]) as usize;
        let nlen = u16::from_le_bytes([zip[i + 26], zip[i + 27]]) as usize;
        let elen = u16::from_le_bytes([zip[i + 28], zip[i + 29]]) as usize;
        let name = std::str::from_utf8(&zip[i + 30..i + 30 + nlen]).unwrap_or("");
        let data_start = i + 30 + nlen + elen;
        if name == "word/document.xml" {
            return String::from_utf8_lossy(&zip[data_start..data_start + comp]).into_owned();
        }
        i = data_start + comp;
    }
    panic!("word/document.xml not found in docx");
}

/// The `w:ilvl` values, in document order.
fn ilvls(d: &str) -> Vec<String> {
    d.match_indices("<w:ilvl w:val=\"")
        .map(|(i, _)| {
            let s = &d[i + 15..];
            s[..s.find('"').unwrap()].to_string()
        })
        .collect()
}

#[test]
fn oxmathproblems_exam_sheet_is_valid_and_nested() {
    let (out, warnings, cov) = convert_file(
        &fixture("oxmathproblems/oxmathproblems.tex"),
        None,
        &PageGeometry::default(),
    )
    .expect("convert oxmathproblems");
    let docx = std::fs::read(&out).unwrap();
    let _ = std::fs::remove_file(&out);

    assert!(
        tex2word_validate::validate_docx(&docx).is_empty(),
        "oxmathproblems produced invalid docx"
    );

    let d = document_xml(&docx);
    // nested numbering: each question (ilvl 0) precedes its parts (1) / subparts (2)
    let lv = ilvls(&d);
    assert_eq!(&lv[..7], &["0", "1", "1", "1", "0", "1", "1"], "{lv:?}");
    assert!(lv.iter().any(|l| l == "2"), "subparts should reach ilvl 2");

    // exam's \part must not leak as sectioning ("Part I D"); solutions hide
    assert!(!d.contains(">Part "), "leaked \\part sectioning");
    assert!(
        !d.to_lowercase().contains("solution would go here"),
        "solution leaked"
    );
    // recovered Oxford title + real content survived + native math
    assert!(d.contains("Impossible Maths"), "title not recovered");
    assert!(d.contains("linearly independent"), "content missing");
    assert!(d.contains("<m:t"), "no math emitted");
    // only the known font-declaration warnings, no unexpected ones
    for w in &warnings {
        assert!(
            w.message.contains("is not supported"),
            "unexpected warning: {}",
            w.message
        );
    }
    assert!(
        cov.math_inline + cov.math_display > 0,
        "expected math content"
    );
}

#[test]
fn inline_exam_class_nesting_and_hidden_solutions() {
    let src = concat!(
        "\\documentclass{exam}\\begin{document}\\begin{questions}",
        "\\question First\\begin{parts}\\part[7] a\\part b\\end{parts}",
        "\\begin{solution}SECRET\\end{solution}",
        "\\question Second\\end{questions}\\end{document}"
    );
    let conv = convert_source(src);
    assert!(tex2word_validate::validate_docx(&conv.docx).is_empty());
    let d = document_xml(&conv.docx);
    assert!(!d.contains("SECRET"), "solution not hidden");
    assert!(!d.contains("[7]"), "points arg leaked");
    assert!(d.contains("First") && d.contains("Second"));
    // question(0) part(1) part(1) question(0)
    assert_eq!(ilvls(&d), vec!["0", "1", "1", "0"]);
}

#[test]
fn cr_matrix_and_math_class_wrappers_render() {
    let src = concat!(
        "\\begin{document}",
        "\\[ A=\\begin{pmatrix}a&b\\cr b&d\\cr\\end{pmatrix} \\]",
        "$\\mathbf{u}\\mathbin{\\land}\\mathbf{v}$ and $T{\\restriction} U$",
        "\\end{document}"
    );
    let conv = convert_source(src);
    assert!(tex2word_validate::validate_docx(&conv.docx).is_empty());
    let d = document_xml(&conv.docx);
    assert!(
        d.contains(">a<") && d.contains(">b<") && d.contains(">d<"),
        "\\cr cells missing"
    );
    assert!(d.contains('∧'), "math-class \\land content missing");
    assert!(d.contains('↾'), "\\restriction glyph missing");
}
