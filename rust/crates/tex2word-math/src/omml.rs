//! Math AST -> OMML (OfficeMath) XML — the `m:` namespace elements Word edits
//! natively. A subset of the Python `mathml/omml.py`.

use crate::parser::Node;

/// Escape XML text content.
fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(c),
        }
    }
    out
}

/// A run of math-italic text (`<m:r>`).
fn run(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }
    format!("<m:r><m:t>{}</m:t></m:r>", escape(s))
}

/// An upright run (`<m:nor/>` suppresses the default math italic).
fn upright(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }
    format!(
        "<m:r><m:rPr><m:nor/></m:rPr><m:t xml:space=\"preserve\">{}</m:t></m:r>",
        escape(s)
    )
}

/// Render a node's content as the children of a container (`m:e`/`m:num`/…),
/// guaranteeing at least one run so required elements are never empty.
fn cell(node: &Node) -> String {
    let r = render(node);
    if r.is_empty() {
        "<m:r><m:t></m:t></m:r>".to_string()
    } else {
        r
    }
}

/// Render a math node to OMML.
pub fn render(node: &Node) -> String {
    match node {
        Node::Run(s) => run(s),
        Node::Upright(s) => upright(s),
        Node::Row(items) => items.iter().map(render).collect(),
        Node::Frac(num, den) => format!(
            "<m:f><m:fPr><m:type m:val=\"bar\"/></m:fPr><m:num>{}</m:num><m:den>{}</m:den></m:f>",
            cell(num),
            cell(den)
        ),
        Node::Sup(base, sup) => format!(
            "<m:sSup><m:e>{}</m:e><m:sup>{}</m:sup></m:sSup>",
            cell(base),
            cell(sup)
        ),
        Node::Sub(base, sub) => format!(
            "<m:sSub><m:e>{}</m:e><m:sub>{}</m:sub></m:sSub>",
            cell(base),
            cell(sub)
        ),
        Node::SubSup(base, sub, sup) => format!(
            "<m:sSubSup><m:e>{}</m:e><m:sub>{}</m:sub><m:sup>{}</m:sup></m:sSubSup>",
            cell(base),
            cell(sub),
            cell(sup)
        ),
        Node::Sqrt(rad) => format!(
            "<m:rad><m:radPr><m:degHide m:val=\"1\"/></m:radPr><m:deg/><m:e>{}</m:e></m:rad>",
            cell(rad)
        ),
        Node::Root(index, rad) => format!(
            "<m:rad><m:radPr><m:degHide m:val=\"0\"/></m:radPr><m:deg>{}</m:deg><m:e>{}</m:e></m:rad>",
            cell(index),
            cell(rad)
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::parse;

    #[test]
    fn fraction_scripts_root() {
        let f = render(&parse(r"\frac{1}{2}"));
        assert!(f.contains("<m:f>") && f.contains("<m:num>") && f.contains("<m:den>"));
        assert!(render(&parse("x^2")).contains("<m:sSup>"));
        assert!(render(&parse("x_i^n")).contains("<m:sSubSup>"));
        assert!(render(&parse(r"\sqrt{2}")).contains("<m:rad>"));
    }

    #[test]
    fn function_is_upright() {
        assert!(render(&parse(r"\sin")).contains("<m:nor/>"));
    }

    #[test]
    fn amp_is_escaped() {
        assert!(render(&Node::Run("a&b".into())).contains("a&amp;b"));
    }
}
