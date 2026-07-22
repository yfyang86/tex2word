//! IR → LaTeX writer — the round-trip counterpart of the front-end parser.
//!
//! Reconstructs a `.tex` document from the [`Document`] IR. It is not meant to
//! reproduce the *original* source byte-for-byte, but to be **idempotent at the
//! IR level**: `parse → to_latex → parse` reaches an equal `Document` for the
//! constructs the port handles, which is the basis of round-trip/differential
//! testing (see `rust/PHASE5_PLAN.md`). Math is passed through verbatim (the
//! math engine's input is LaTeX already).

use tex2word_ir::{
    BibEntry, Block, CiteMode, Document, EmphasisKind, Float, FloatKind, Inline, RefKind, RefStyle,
    Table, TableAlign, Theorem, TocKind,
};

/// Render an IR document to a LaTeX source string.
pub fn to_latex(doc: &Document) -> String {
    let mut o = String::new();
    let opts = if doc.columns >= 2 { "[twocolumn]" } else { "" };
    o.push_str(&format!("\\documentclass{opts}{{article}}\n"));
    if let Some(t) = &doc.title {
        o.push_str(&format!("\\title{{{}}}\n", inlines(t)));
    }
    if !doc.authors.is_empty() {
        let authors: Vec<String> = doc.authors.iter().map(|a| inlines(a)).collect();
        o.push_str(&format!("\\author{{{}}}\n", authors.join(" \\and ")));
    }
    if let Some(d) = &doc.date {
        o.push_str(&format!("\\date{{{}}}\n", inlines(d)));
    }
    o.push_str("\\begin{document}\n");
    if doc.title.is_some() {
        o.push_str("\\maketitle\n");
    }
    for b in &doc.blocks {
        block(b, &mut o);
    }
    o.push_str("\\end{document}\n");
    o
}

fn block(b: &Block, o: &mut String) {
    match b {
        Block::Heading {
            level,
            inlines: inl,
            label,
            numbered,
        } => {
            let cmd = match level {
                1 => "section",
                2 => "subsection",
                _ => "subsubsection",
            };
            let star = if *numbered { "" } else { "*" };
            o.push_str(&format!("\\{cmd}{star}{{{}}}", inlines(inl)));
            push_label(label, o);
            o.push('\n');
        }
        Block::Paragraph { inlines: inl } => {
            o.push_str(&inlines(inl));
            o.push_str("\n\n");
        }
        Block::MathBlock {
            latex,
            label,
            numbered,
        } => {
            if *numbered {
                o.push_str("\\begin{equation}");
                push_label(label, o);
                o.push_str(&format!(" {latex} \\end{{equation}}\n"));
            } else {
                o.push_str(&format!("\\[ {latex} \\]"));
                push_label(label, o);
                o.push('\n');
            }
        }
        Block::List { ordered, items } => {
            let env = if *ordered { "enumerate" } else { "itemize" };
            o.push_str(&format!("\\begin{{{env}}}\n"));
            for it in items {
                o.push_str(&format!("\\item {}\n", inlines(it)));
            }
            o.push_str(&format!("\\end{{{env}}}\n"));
        }
        Block::Quote(blocks) => {
            o.push_str("\\begin{quote}\n");
            for b in blocks {
                block(b, o);
            }
            o.push_str("\\end{quote}\n");
        }
        Block::Table(t) => table(t, o),
        Block::Float(f) => float(f, o),
        Block::TableOfContents(k) => o.push_str(match k {
            TocKind::Contents => "\\tableofcontents\n",
            TocKind::Figures => "\\listoffigures\n",
            TocKind::Tables => "\\listoftables\n",
        }),
        Block::Bibliography { entries } => bibliography(entries, o),
        Block::Theorem(t) => theorem(t, o),
    }
}

fn table(t: &Table, o: &mut String) {
    let spec: String = t
        .colspec
        .iter()
        .map(|a| match a {
            TableAlign::Left => 'l',
            TableAlign::Center => 'c',
            TableAlign::Right => 'r',
        })
        .collect();
    o.push_str(&format!("\\begin{{tabular}}{{{spec}}}\n\\toprule\n"));
    let mut header_done = false;
    for row in &t.rows {
        let cells: Vec<String> = row
            .cells
            .iter()
            .map(|c| {
                let mut inner = inlines(&c.inlines);
                if c.rowspan > 1 {
                    inner = format!("\\multirow{{{}}}{{*}}{{{}}}", c.rowspan, inner);
                }
                if c.colspan > 1 {
                    let a = match c.align {
                        TableAlign::Left => 'l',
                        TableAlign::Center => 'c',
                        TableAlign::Right => 'r',
                    };
                    inner = format!("\\multicolumn{{{}}}{{{a}}}{{{}}}", c.colspan, inner);
                }
                inner
            })
            .collect();
        o.push_str(&format!("{} \\\\\n", cells.join(" & ")));
        // a \midrule right after the (single) header row
        if row.is_header && !header_done {
            o.push_str("\\midrule\n");
            header_done = true;
        }
    }
    o.push_str("\\bottomrule\n\\end{tabular}\n");
}

fn float(f: &Float, o: &mut String) {
    let (env, star) = match (f.kind, f.spanning) {
        (FloatKind::Figure, false) => ("figure", ""),
        (FloatKind::Figure, true) => ("figure", "*"),
        (FloatKind::Table, false) => ("table", ""),
        (FloatKind::Table, true) => ("table", "*"),
    };
    o.push_str(&format!("\\begin{{{env}{star}}}\n"));
    if f.centered {
        o.push_str("\\centering\n");
    }
    for b in &f.content {
        block(b, o);
    }
    if let Some(cap) = &f.caption {
        o.push_str(&format!("\\caption{{{}}}", inlines(cap)));
        push_label(&f.label, o);
        o.push('\n');
    } else {
        push_label(&f.label, o);
        if f.label.is_some() {
            o.push('\n');
        }
    }
    o.push_str(&format!("\\end{{{env}{star}}}\n"));
}

fn bibliography(entries: &[BibEntry], o: &mut String) {
    o.push_str("\\begin{thebibliography}{9}\n");
    for e in entries {
        match &e.label {
            Some(l) => o.push_str(&format!(
                "\\bibitem[{l}]{{{}}} {}\n",
                e.key,
                inlines(&e.inlines)
            )),
            None => o.push_str(&format!("\\bibitem{{{}}} {}\n", e.key, inlines(&e.inlines))),
        }
    }
    o.push_str("\\end{thebibliography}\n");
}

fn theorem(t: &Theorem, o: &mut String) {
    let env = t.kind.to_lowercase();
    o.push_str(&format!("\\begin{{{env}}}"));
    if let Some(title) = &t.title {
        o.push_str(&format!("[{}]", inlines(title)));
    }
    push_label(&t.label, o);
    o.push('\n');
    for b in &t.blocks {
        block(b, o);
    }
    o.push_str(&format!("\\end{{{env}}}\n"));
}

fn push_label(label: &Option<String>, o: &mut String) {
    if let Some(l) = label {
        o.push_str(&format!("\\label{{{l}}}"));
    }
}

/// Render an inline slice to LaTeX.
fn inlines(inl: &[Inline]) -> String {
    let mut o = String::new();
    for n in inl {
        inline(n, &mut o);
    }
    o
}

fn inline(n: &Inline, o: &mut String) {
    match n {
        Inline::Text(t) => o.push_str(&escape(t)),
        Inline::Emphasis { kind, inlines: inl } => {
            let cmd = match kind {
                EmphasisKind::Bold => "textbf",
                EmphasisKind::Italic => "emph",
                EmphasisKind::Typewriter => "texttt",
                EmphasisKind::Underline => "underline",
                EmphasisKind::SmallCaps => "textsc",
                EmphasisKind::Superscript => "textsuperscript",
                EmphasisKind::Subscript => "textsubscript",
            };
            o.push_str(&format!("\\{cmd}{{{}}}", inlines(inl)));
        }
        Inline::Math(m) => o.push_str(&format!("${m}$")),
        Inline::LineBreak => o.push_str("\\\\"),
        Inline::Image { path, options } => {
            if options.is_empty() {
                o.push_str(&format!("\\includegraphics{{{path}}}"));
            } else {
                o.push_str(&format!("\\includegraphics[{options}]{{{path}}}"));
            }
        }
        Inline::Ref {
            key, kind, style, ..
        } => {
            let cmd = ref_macro(*kind, *style);
            o.push_str(&format!("\\{cmd}{{{key}}}"));
        }
        Inline::Link {
            inlines: inl,
            url,
            anchor,
        } => match anchor {
            Some(a) => o.push_str(&format!("\\hyperref[{a}]{{{}}}", inlines(inl))),
            None if inl.len() == 1 && matches!(&inl[0], Inline::Text(t) if t == url) => {
                o.push_str(&format!("\\url{{{url}}}"))
            }
            None => o.push_str(&format!("\\href{{{url}}}{{{}}}", inlines(inl))),
        },
        Inline::Cite { keys, mode, .. } => {
            let cmd = match mode {
                CiteMode::Paren => "citep",
                CiteMode::Text => "citet",
                CiteMode::Author => "citeauthor",
                CiteMode::Year => "citeyear",
                CiteMode::Num => "citenum",
            };
            o.push_str(&format!("\\{cmd}{{{}}}", keys.join(",")));
        }
        Inline::Footnote { inlines: inl } => {
            o.push_str(&format!("\\footnote{{{}}}", inlines(inl)));
        }
    }
}

/// The reference macro that re-parses to `(kind, style)`.
fn ref_macro(kind: RefKind, style: RefStyle) -> &'static str {
    match (kind, style) {
        (RefKind::Page, _) => "pageref",
        (RefKind::Equation, RefStyle::Plain) => "eqref",
        (RefKind::Name, _) => "nameref",
        (_, RefStyle::Abbrev) => "cref",
        (_, RefStyle::Full) => "autoref",
        _ => "ref",
    }
}

/// Escape the LaTeX special characters (Unicode text is emitted verbatim).
fn escape(s: &str) -> String {
    let mut o = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '\\' => o.push_str("\\textbackslash{}"),
            '{' => o.push_str("\\{"),
            '}' => o.push_str("\\}"),
            '$' => o.push_str("\\$"),
            '&' => o.push_str("\\&"),
            '#' => o.push_str("\\#"),
            '%' => o.push_str("\\%"),
            '_' => o.push_str("\\_"),
            '~' => o.push_str("\\textasciitilde{}"),
            '^' => o.push_str("\\textasciicircum{}"),
            _ => o.push(c),
        }
    }
    o
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_core_constructs() {
        let doc = Document {
            title: Some(vec![Inline::Text("T".into())]),
            blocks: vec![
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Intro".into())],
                    label: Some("s".into()),
                    numbered: true,
                },
                Block::Paragraph {
                    inlines: vec![
                        Inline::Emphasis {
                            kind: EmphasisKind::Bold,
                            inlines: vec![Inline::Text("b".into())],
                        },
                        Inline::Math("x^2".into()),
                    ],
                },
            ],
            ..Default::default()
        };
        let tex = to_latex(&doc);
        assert!(tex.contains("\\documentclass{article}"));
        assert!(tex.contains("\\title{T}") && tex.contains("\\maketitle"));
        assert!(tex.contains("\\section{Intro}\\label{s}"));
        assert!(tex.contains("\\textbf{b}") && tex.contains("$x^2$"));
    }

    #[test]
    fn escapes_specials() {
        assert_eq!(escape("a & b_c %"), "a \\& b\\_c \\%");
    }
}
