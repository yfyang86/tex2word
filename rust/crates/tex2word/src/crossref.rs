//! Cross-reference resolution pass (IR → IR) — a Rust port of the Python
//! `transforms/crossref.py`.
//!
//! Two walks over the document: first collect every `\label` target, giving each
//! a sanitized Word bookmark and a `SEQ` counter name; then rewrite every
//! [`Inline::Ref`] to carry the matching bookmark (and inherit the target's kind
//! for a generic `\ref`). `\nameref` becomes an internal hyperlink to the
//! target's title text; `\hyperref[label]` anchors resolve to the sanitized
//! bookmark. Unresolved references are reported, not fatal.

use std::collections::HashMap;

use tex2word_ir::{Block, Document, Inline, LabelInfo, RefKind};

/// A non-fatal diagnostic collected during conversion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Warning {
    pub context: String,
    pub message: String,
}

/// Resolve cross-references in place: populate `doc.labels` and wire every
/// `Ref`/`Link` to its bookmark. Returns any unresolved-reference warnings.
pub fn resolve(doc: &mut Document) -> Vec<Warning> {
    let mut labels: HashMap<String, LabelInfo> = HashMap::new();
    collect(&doc.blocks, &mut labels);
    doc.labels = labels;
    let mut warnings = Vec::new();
    // Take the labels out to avoid borrowing doc immutably + mutably at once.
    let labels = std::mem::take(&mut doc.labels);
    rewrite_blocks(&mut doc.blocks, &labels, &mut warnings);
    doc.labels = labels;
    warnings
}

/// Word bookmark names must start with a letter, contain no spaces, and be
/// ≤ 40 chars.
pub fn sanitize_bookmark(key: &str) -> String {
    let mut cleaned: String = key
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if cleaned
        .chars()
        .next()
        .is_none_or(|c| !c.is_ascii_alphabetic())
    {
        cleaned = format!("ref_{cleaned}");
    }
    cleaned.chars().take(40).collect()
}

/// The `SEQ` counter name for a reference kind (mirrors Python `_COUNTER`).
fn counter_name(kind: RefKind) -> &'static str {
    match kind {
        RefKind::Equation => "Equation",
        RefKind::Figure => "Figure",
        RefKind::Table => "Table",
        RefKind::Section => "Section",
        RefKind::Theorem => "Theorem",
        _ => "Item",
    }
}

/// Flatten an inline list to plain text (for a `\nameref` display string).
fn inline_text(inlines: &[Inline]) -> String {
    let mut out = String::new();
    for n in inlines {
        match n {
            Inline::Text(t) => out.push_str(t),
            Inline::Emphasis { inlines, .. } | Inline::Link { inlines, .. } => {
                out.push_str(&inline_text(inlines))
            }
            _ => {}
        }
    }
    out.trim().to_string()
}

fn add_label(
    labels: &mut HashMap<String, LabelInfo>,
    key: &Option<String>,
    kind: RefKind,
    name: Option<String>,
) {
    let Some(key) = key else { return };
    labels.insert(
        key.clone(),
        LabelInfo {
            kind,
            counter_name: counter_name(kind).to_string(),
            bookmark: sanitize_bookmark(key),
            name,
        },
    );
}

fn collect(blocks: &[Block], labels: &mut HashMap<String, LabelInfo>) {
    for block in blocks {
        match block {
            Block::Heading { inlines, label, .. } => {
                add_label(labels, label, RefKind::Section, Some(inline_text(inlines)));
            }
            Block::MathBlock { label, .. } => {
                add_label(labels, label, RefKind::Equation, None);
            }
            Block::Float(f) => {
                let kind = match f.kind {
                    tex2word_ir::FloatKind::Figure => RefKind::Figure,
                    tex2word_ir::FloatKind::Table => RefKind::Table,
                };
                let name = f.caption.as_ref().map(|c| inline_text(c));
                add_label(labels, &f.label, kind, name);
                collect(&f.content, labels); // nested tables/labels
            }
            Block::Quote(bs) => collect(bs, labels),
            _ => {}
        }
    }
}

fn rewrite_blocks(
    blocks: &mut [Block],
    labels: &HashMap<String, LabelInfo>,
    warns: &mut Vec<Warning>,
) {
    for block in blocks {
        match block {
            Block::Heading { inlines, .. } | Block::Paragraph { inlines } => {
                rewrite_inlines(inlines, labels, warns)
            }
            Block::Quote(bs) => rewrite_blocks(bs, labels, warns),
            Block::Float(f) => {
                if let Some(cap) = &mut f.caption {
                    rewrite_inlines(cap, labels, warns);
                }
                rewrite_blocks(&mut f.content, labels, warns);
            }
            Block::Table(t) => {
                for row in &mut t.rows {
                    for cell in &mut row.cells {
                        rewrite_inlines(&mut cell.inlines, labels, warns);
                    }
                }
            }
            _ => {}
        }
    }
}

fn rewrite_inlines(
    inlines: &mut [Inline],
    labels: &HashMap<String, LabelInfo>,
    warns: &mut Vec<Warning>,
) {
    for node in inlines.iter_mut() {
        // \nameref -> an internal hyperlink to the target's title text.
        if let Inline::Ref {
            key,
            kind: RefKind::Name,
            ..
        } = node
        {
            if let Some(info) = labels.get(key) {
                let text = info.name.clone().unwrap_or_else(|| key.clone());
                let anchor = info.bookmark.clone();
                *node = Inline::Link {
                    inlines: vec![Inline::Text(text)],
                    url: String::new(),
                    anchor: Some(anchor),
                };
            } else {
                warns.push(Warning {
                    context: "\\nameref".into(),
                    message: format!("unresolved reference to '{key}'"),
                });
            }
            continue;
        }
        match node {
            Inline::Ref {
                key,
                kind,
                bookmark,
                ..
            } => match labels.get(key) {
                Some(info) => {
                    *bookmark = Some(info.bookmark.clone());
                    if *kind == RefKind::Generic {
                        *kind = info.kind;
                    }
                }
                None => warns.push(Warning {
                    context: "\\ref".into(),
                    message: format!("unresolved reference to '{key}'"),
                }),
            },
            Inline::Link {
                inlines, anchor, ..
            } => {
                if let Some(a) = anchor {
                    match labels.get(a) {
                        Some(info) => *a = info.bookmark.clone(),
                        None => warns.push(Warning {
                            context: "\\hyperref".into(),
                            message: format!("unresolved \\hyperref to '{a}'"),
                        }),
                    }
                }
                rewrite_inlines(inlines, labels, warns);
            }
            Inline::Emphasis { inlines, .. } | Inline::Footnote { inlines } => {
                rewrite_inlines(inlines, labels, warns)
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tex2word_ir::{Float, FloatKind, RefStyle};

    #[test]
    fn sanitize_rules() {
        assert_eq!(sanitize_bookmark("fig:plot 1"), "fig_plot_1");
        assert_eq!(sanitize_bookmark("2eq"), "ref_2eq"); // must start with a letter
        assert_eq!(sanitize_bookmark("").len(), 4); // "ref_"
    }

    #[test]
    fn collect_and_rewrite() {
        let mut doc = Document {
            blocks: vec![
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Intro".into())],
                    label: Some("sec:intro".into()),
                    numbered: true,
                },
                Block::Paragraph {
                    inlines: vec![
                        Inline::Ref {
                            key: "fig:a".into(),
                            kind: RefKind::Generic,
                            style: RefStyle::Plain,
                            bookmark: None,
                        },
                        Inline::Ref {
                            key: "missing".into(),
                            kind: RefKind::Generic,
                            style: RefStyle::Plain,
                            bookmark: None,
                        },
                    ],
                },
                Block::Float(Float {
                    kind: FloatKind::Figure,
                    content: vec![],
                    caption: Some(vec![Inline::Text("A plot".into())]),
                    centered: false,
                    label: Some("fig:a".into()),
                    spanning: false,
                }),
            ],
            ..Default::default()
        };
        let warns = resolve(&mut doc);
        // labels collected
        assert_eq!(doc.labels["sec:intro"].kind, RefKind::Section);
        assert_eq!(doc.labels["fig:a"].bookmark, "fig_a");
        assert_eq!(doc.labels["fig:a"].name.as_deref(), Some("A plot"));
        // generic ref to a figure inherits Figure kind + bookmark
        let Block::Paragraph { inlines } = &doc.blocks[1] else {
            panic!()
        };
        assert!(matches!(&inlines[0],
            Inline::Ref { kind: RefKind::Figure, bookmark: Some(b), .. } if b == "fig_a"));
        // the unresolved ref stays bookmark-less and is reported
        assert!(matches!(&inlines[1], Inline::Ref { bookmark: None, .. }));
        assert_eq!(warns.len(), 1);
        assert!(warns[0].message.contains("missing"));
    }

    #[test]
    fn nameref_becomes_link() {
        let mut doc = Document {
            blocks: vec![
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Methods".into())],
                    label: Some("sec:m".into()),
                    numbered: true,
                },
                Block::Paragraph {
                    inlines: vec![Inline::Ref {
                        key: "sec:m".into(),
                        kind: RefKind::Name,
                        style: RefStyle::Plain,
                        bookmark: None,
                    }],
                },
            ],
            ..Default::default()
        };
        resolve(&mut doc);
        let Block::Paragraph { inlines } = &doc.blocks[1] else {
            panic!()
        };
        assert!(matches!(&inlines[0],
            Inline::Link { inlines, anchor: Some(a), .. }
                if a == "sec_m" && inlines == &vec![Inline::Text("Methods".into())]));
    }
}
