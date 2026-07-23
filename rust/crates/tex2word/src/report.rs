//! Conversion coverage report — a machine-readable tally of the constructs a
//! document exercised, plus the macros that were dropped. It answers "what did
//! this conversion actually cover?", the input to the Phase-6 differential
//! cutover (see `rust/PHASE5_PLAN.md`).

use tex2word_ir::{Block, Document, FloatKind, Inline};

/// Per-construct counts for one conversion.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Coverage {
    pub headings: usize,
    pub paragraphs: usize,
    pub math_inline: usize,
    pub math_display: usize,
    pub lists: usize,
    pub tables: usize,
    pub figures: usize,
    pub table_floats: usize,
    pub images: usize,
    pub refs: usize,
    pub links: usize,
    pub cites: usize,
    pub footnotes: usize,
    pub theorems: usize,
    pub bib_entries: usize,
    /// Macros the front-end could not handle (dropped from the output).
    pub unsupported: Vec<String>,
}

/// Compute the coverage of a document (plus a pre-scanned unsupported-macro list).
pub fn coverage(doc: &Document, unsupported: &[String]) -> Coverage {
    let mut c = Coverage {
        unsupported: unsupported.to_vec(),
        ..Coverage::default()
    };
    count_blocks(&doc.blocks, &mut c);
    c
}

fn count_blocks(blocks: &[Block], c: &mut Coverage) {
    for b in blocks {
        match b {
            Block::Heading { inlines, .. } => {
                c.headings += 1;
                count_inlines(inlines, c);
            }
            Block::Paragraph { inlines } => {
                c.paragraphs += 1;
                count_inlines(inlines, c);
            }
            Block::MathBlock { .. } => c.math_display += 1,
            Block::List { items, .. } => {
                c.lists += 1;
                for it in items {
                    count_inlines(it, c);
                }
            }
            Block::Quote(bs) => count_blocks(bs, c),
            Block::Table(t) => {
                c.tables += 1;
                for row in &t.rows {
                    for cell in &row.cells {
                        count_inlines(&cell.inlines, c);
                    }
                }
            }
            Block::Float(f) => {
                match f.kind {
                    FloatKind::Figure => c.figures += 1,
                    FloatKind::Table => c.table_floats += 1,
                }
                count_blocks(&f.content, c);
                if let Some(cap) = &f.caption {
                    count_inlines(cap, c);
                }
            }
            Block::TableOfContents(_) => {}
            Block::Bibliography { entries } => c.bib_entries += entries.len(),
            Block::Theorem(t) => {
                c.theorems += 1;
                if let Some(title) = &t.title {
                    count_inlines(title, c);
                }
                count_blocks(&t.blocks, c);
            }
        }
    }
}

fn count_inlines(inl: &[Inline], c: &mut Coverage) {
    for n in inl {
        match n {
            Inline::Text(_) | Inline::LineBreak => {}
            Inline::Emphasis { inlines, .. } => count_inlines(inlines, c),
            Inline::Math(_) => c.math_inline += 1,
            Inline::Image { .. } => c.images += 1,
            Inline::Ref { .. } => c.refs += 1,
            Inline::Link { inlines, .. } => {
                c.links += 1;
                count_inlines(inlines, c);
            }
            Inline::Cite { .. } => c.cites += 1,
            Inline::Footnote { inlines } => {
                c.footnotes += 1;
                count_inlines(inlines, c);
            }
        }
    }
}

impl Coverage {
    /// A human-readable multi-line summary (for `--report`).
    pub fn summary(&self) -> String {
        let rows = [
            ("headings", self.headings),
            ("paragraphs", self.paragraphs),
            ("inline math", self.math_inline),
            ("display math", self.math_display),
            ("lists", self.lists),
            ("tables", self.tables),
            ("figures", self.figures),
            ("table floats", self.table_floats),
            ("images", self.images),
            ("cross-refs", self.refs),
            ("links", self.links),
            ("citations", self.cites),
            ("footnotes", self.footnotes),
            ("theorems", self.theorems),
            ("bib entries", self.bib_entries),
        ];
        let mut s = String::from("coverage report:\n");
        for (name, n) in rows {
            if n > 0 {
                s.push_str(&format!("  {name:>14}: {n}\n"));
            }
        }
        if self.unsupported.is_empty() {
            s.push_str("  unsupported macros: none\n");
        } else {
            s.push_str(&format!(
                "  unsupported macros ({}): {}\n",
                self.unsupported.len(),
                self.unsupported
                    .iter()
                    .map(|m| format!("\\{m}"))
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tex2word_ir::{EmphasisKind, RefKind, RefStyle};

    #[test]
    fn counts_constructs_and_recurses() {
        let doc = Document {
            blocks: vec![
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("H".into())],
                    label: None,
                    numbered: true,
                },
                Block::Paragraph {
                    inlines: vec![
                        Inline::Math("x".into()),
                        Inline::Ref {
                            key: "a".into(),
                            kind: RefKind::Generic,
                            style: RefStyle::Plain,
                            bookmark: None,
                        },
                        Inline::Footnote {
                            inlines: vec![Inline::Emphasis {
                                kind: EmphasisKind::Bold,
                                inlines: vec![Inline::Cite {
                                    keys: vec!["k".into()],
                                    mode: tex2word_ir::CiteMode::Paren,
                                    rendered: None,
                                }],
                            }],
                        },
                    ],
                },
            ],
            ..Default::default()
        };
        let c = coverage(&doc, &["foobar".to_string()]);
        assert_eq!(c.headings, 1);
        assert_eq!(c.paragraphs, 1);
        assert_eq!(c.math_inline, 1);
        assert_eq!(c.refs, 1);
        assert_eq!(c.footnotes, 1);
        assert_eq!(c.cites, 1); // counted inside the footnote's emphasis
        assert_eq!(c.unsupported, vec!["foobar".to_string()]);
        assert!(c.summary().contains("unsupported macros (1): \\foobar"));
    }
}
