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
        Node::Nary {
            op,
            sub,
            sup,
            body,
            over_under,
        } => {
            let limloc = if *over_under { "undOvr" } else { "subSup" };
            let (sub_hide, sub_xml) = match sub {
                Some(n) => ("0", render(n)),
                None => ("1", String::new()),
            };
            let (sup_hide, sup_xml) = match sup {
                Some(n) => ("0", render(n)),
                None => ("1", String::new()),
            };
            format!(
                "<m:nary><m:naryPr><m:chr m:val=\"{}\"/><m:limLoc m:val=\"{}\"/>\
                 <m:subHide m:val=\"{}\"/><m:supHide m:val=\"{}\"/></m:naryPr>\
                 <m:sub>{}</m:sub><m:sup>{}</m:sup><m:e>{}</m:e></m:nary>",
                escape(op),
                limloc,
                sub_hide,
                sup_hide,
                sub_xml,
                sup_xml,
                cell(body)
            )
        }
        Node::Delim { open, close, body } => format!(
            "<m:d><m:dPr><m:begChr m:val=\"{}\"/><m:endChr m:val=\"{}\"/></m:dPr><m:e>{}</m:e></m:d>",
            escape(open),
            escape(close),
            cell(body)
        ),
        Node::Accent { chr, base } => format!(
            "<m:acc><m:accPr><m:chr m:val=\"{}\"/></m:accPr><m:e>{}</m:e></m:acc>",
            escape(&chr.to_string()),
            cell(base)
        ),
        Node::Bar { top, base } => format!(
            "<m:bar><m:barPr><m:pos m:val=\"{}\"/></m:barPr><m:e>{}</m:e></m:bar>",
            if *top { "top" } else { "bot" },
            cell(base)
        ),
        Node::Styled { sty, text } => {
            if text.is_empty() {
                String::new()
            } else {
                format!(
                    "<m:r><m:rPr><m:sty m:val=\"{}\"/></m:rPr><m:t xml:space=\"preserve\">{}</m:t></m:r>",
                    sty,
                    escape(text)
                )
            }
        }
        Node::Binom(num, den) => format!(
            "<m:d><m:dPr><m:begChr m:val=\"(\"/><m:endChr m:val=\")\"/></m:dPr><m:e>\
             <m:f><m:fPr><m:type m:val=\"noBar\"/></m:fPr><m:num>{}</m:num><m:den>{}</m:den></m:f>\
             </m:e></m:d>",
            cell(num),
            cell(den)
        ),
        Node::Matrix { rows, delim } => {
            let ncols = rows.iter().map(Vec::len).max().unwrap_or(0);
            let mut m = String::from("<m:m>");
            for row in rows {
                m.push_str("<m:mr>");
                for c in 0..ncols {
                    // pad short rows so every m:mr has ncols cells
                    let content = row.get(c).map_or_else(
                        || "<m:r><m:t></m:t></m:r>".to_string(),
                        cell,
                    );
                    m.push_str(&format!("<m:e>{content}</m:e>"));
                }
                m.push_str("</m:mr>");
            }
            m.push_str("</m:m>");
            match delim {
                Some((open, close)) => format!(
                    "<m:d><m:dPr><m:begChr m:val=\"{}\"/><m:endChr m:val=\"{}\"/></m:dPr><m:e>{}</m:e></m:d>",
                    escape(open),
                    escape(close),
                    m
                ),
                None => m,
            }
        }
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
    fn font_alphabets_binom_and_mod() {
        // blackboard-bold with a "hole" letter (ℝ from Letterlike Symbols)
        assert!(render(&parse(r"\mathbb{R}")).contains("ℝ"));
        assert!(render(&parse(r"\mathbb{Z}")).contains("ℤ"));
        assert!(render(&parse(r"\mathcal{L}")).contains("ℒ"));
        assert!(render(&parse(r"\mathfrak{g}")).contains("𝔤"));
        // \mathbf -> bold styled run
        let bf = render(&parse(r"\mathbf{v}"));
        assert!(bf.contains("m:sty m:val=\"b\"") && bf.contains(">v</m:t>"));
        // \binom -> parens + no-bar fraction
        let b = render(&parse(r"\binom{n}{k}"));
        assert!(b.contains("m:type m:val=\"noBar\"") && b.contains("m:begChr m:val=\"(\""));
        // \pmod
        assert!(render(&parse(r"\pmod{n}")).contains("mod"));
    }

    #[test]
    fn amp_is_escaped() {
        assert!(render(&Node::Run("a&b".into())).contains("a&amp;b"));
    }

    #[test]
    fn nary_sum_and_int() {
        let sum = render(&parse(r"\sum_{i=1}^{n} a_i"));
        assert!(sum.contains("<m:nary>"));
        assert!(sum.contains("m:chr m:val=\"∑\""));
        assert!(sum.contains("m:limLoc m:val=\"undOvr\"")); // sums: limits above/below
        assert!(sum.contains("m:subHide m:val=\"0\"") && sum.contains("m:supHide m:val=\"0\""));
        // integral: limits as scripts, only a lower limit here
        let int = render(&parse(r"\int_0 f"));
        assert!(int.contains("m:limLoc m:val=\"subSup\""));
        assert!(int.contains("m:supHide m:val=\"1\"")); // no upper limit
    }

    #[test]
    fn matrices() {
        let p = render(&parse(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}"));
        assert!(p.contains("<m:m>"));
        assert!(p.matches("<m:mr>").count() == 2); // two rows
        assert!(p.matches("<m:e>").count() >= 4); // 2x2 cells (+ the delim m:e)
        assert!(p.contains("m:begChr m:val=\"(\"") && p.contains("m:endChr m:val=\")\""));
        // cases: left brace only, ragged rows padded
        let c = render(&parse(r"\begin{cases} 1 & x>0 \\ 0 \end{cases}"));
        assert!(c.contains("m:begChr m:val=\"{\"") && c.contains("m:endChr m:val=\"\""));
        // bare matrix: no delimiter wrapper
        assert!(!render(&parse(r"\begin{matrix} a \\ b \end{matrix}")).contains("<m:d>"));
    }

    #[test]
    fn accents_and_bars() {
        let hat = render(&parse(r"\hat{x}"));
        assert!(hat.contains("<m:acc>") && hat.contains("m:chr m:val=\"\u{0302}\""));
        assert!(render(&parse(r"\vec{v}")).contains("m:chr m:val=\"\u{20D7}\""));
        assert!(render(&parse(r"\bar{y}")).contains("m:chr m:val=\"\u{0304}\""));
        let over = render(&parse(r"\overline{AB}"));
        assert!(over.contains("<m:bar>") && over.contains("m:pos m:val=\"top\""));
        assert!(render(&parse(r"\underline{z}")).contains("m:pos m:val=\"bot\""));
    }

    #[test]
    fn delimiters() {
        let d = render(&parse(r"\left( \frac{a}{b} \right)"));
        assert!(d.contains("<m:d>"));
        assert!(d.contains("m:begChr m:val=\"(\"") && d.contains("m:endChr m:val=\")\""));
        assert!(d.contains("<m:f>")); // the fraction inside
                                      // \left. … \right| (one-sided; . = no left delim, | = single bar)
        let one = render(&parse(r"\left. x \right|"));
        assert!(one.contains("m:begChr m:val=\"\"") && one.contains("m:endChr m:val=\"|\""));
        // \right\| gives a double bar ‖
        assert!(render(&parse(r"\left. x \right\|")).contains("m:endChr m:val=\"‖\""));
        assert!(
            render(&parse(r"\left(\left[x\right]\right)"))
                .matches("<m:d>")
                .count()
                == 2
        );
    }
}
