//! tex2word math engine — LaTeX math -> OMML (OfficeMath).
//!
//! Mirrors the Python `tex2word.mathml` package: a LaTeX-math parser
//! ([`parser`]) building a small AST, and an [`omml`] renderer producing the
//! `m:` elements Word edits as native equations. The public entry point wraps
//! the rendered content in an `<m:oMath>` element (the `m` namespace is declared
//! on the document root by the back-end).

mod omml;
mod parser;
mod symbols;

/// Render inline LaTeX math to a complete `<m:oMath>…</m:oMath>` element.
pub fn to_omath(latex: &str) -> String {
    format!("<m:oMath>{}</m:oMath>", omml::render(&parser::parse(latex)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wraps_in_omath() {
        let x = to_omath("x^2");
        assert!(x.starts_with("<m:oMath>") && x.ends_with("</m:oMath>"));
        assert!(x.contains("<m:sSup>"));
    }

    #[test]
    fn full_expression() {
        // E = mc^2 -> a leading text run (E=m, adjacent runs merge) + sSup for c^2
        let x = to_omath("E = mc^2");
        assert!(x.contains("<m:sSup>"));
        assert!(x.contains('E') && x.contains("<m:t>c</m:t>"));
    }
}
