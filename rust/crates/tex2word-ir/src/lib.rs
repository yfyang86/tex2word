//! tex2word intermediate representation (IR).
//!
//! The IR is the contract between the front-end (LaTeX -> IR) and the back-end
//! (IR -> OOXML `.docx`), mirroring the Python `tex2word.ir` module. This is the
//! initial faithful *subset* used by the vertical slice; it grows module by
//! module as the port proceeds (see `rust/ROADMAP.md`).

/// Character-level emphasis applied to a run of inlines.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmphasisKind {
    Bold,
    Italic,
    Typewriter,
    Underline,
    SmallCaps,
    Superscript,
    Subscript,
}

/// Inline-level content (the leaves of a paragraph/heading).
#[derive(Debug, Clone, PartialEq)]
pub enum Inline {
    /// A run of literal text.
    Text(String),
    /// A styled span; styles nest (bold inside italic, …).
    Emphasis {
        kind: EmphasisKind,
        inlines: Vec<Inline>,
    },
    /// Inline math carrying the raw (macro-expanded) LaTeX. The back-end wraps it
    /// in an OMML `m:oMath` run; *structured* OMML (fractions, scripts, …) is a
    /// later milestone — see the roadmap.
    Math(String),
    /// An explicit line break (`\\`).
    LineBreak,
}

/// Block-level content.
#[derive(Debug, Clone, PartialEq)]
pub enum Block {
    /// `level` 1..=3 maps to Word `Heading1`..`Heading3`.
    Heading { level: u8, inlines: Vec<Inline> },
    /// A body paragraph.
    Paragraph { inlines: Vec<Inline> },
    /// An `itemize` (unordered) / `enumerate` (ordered) list; each item is an
    /// inline run (multi-block items are a later milestone).
    List {
        ordered: bool,
        items: Vec<Vec<Inline>>,
    },
    /// A `quote`/`quotation` set-off block.
    Quote(Vec<Block>),
    /// A `tabular`/`array` table.
    Table(Table),
}

/// Horizontal cell alignment (from a column spec like `{lcr}`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TableAlign {
    #[default]
    Left,
    Center,
    Right,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableCell {
    pub inlines: Vec<Inline>,
    /// `\multicolumn` horizontal span (1 = normal).
    pub colspan: usize,
    /// `\multirow` vertical span (1 = normal). The cell starts a vertical merge
    /// that covers this many rows; the covered rows carry an empty placeholder
    /// cell at the same grid position (LaTeX convention).
    pub rowspan: usize,
    pub align: TableAlign,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableRow {
    pub cells: Vec<TableCell>,
    /// A header row (repeated on each page; e.g. above a `\midrule`).
    pub is_header: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Table {
    pub rows: Vec<TableRow>,
    /// Per-column default alignment (from the column spec).
    pub colspec: Vec<TableAlign>,
}

/// A whole document: title/author/date metadata plus a sequence of blocks.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Document {
    pub title: Option<Vec<Inline>>,
    /// One entry per author (split on `\and`).
    pub authors: Vec<Vec<Inline>>,
    pub date: Option<Vec<Inline>>,
    pub blocks: Vec<Block>,
}

impl Document {
    /// Concatenated plain text of the whole document (useful for tests/telemetry).
    pub fn plain_text(&self) -> String {
        let mut out = String::new();
        let line = |inlines: &[Inline], out: &mut String| {
            push_inline_text(inlines, out);
            out.push('\n');
        };
        if let Some(t) = &self.title {
            line(t, &mut out);
        }
        for a in &self.authors {
            line(a, &mut out);
        }
        if let Some(d) = &self.date {
            line(d, &mut out);
        }
        for b in &self.blocks {
            push_block_text(b, &mut out);
        }
        out
    }
}

fn push_block_text(b: &Block, out: &mut String) {
    match b {
        Block::Heading { inlines, .. } | Block::Paragraph { inlines } => {
            push_inline_text(inlines, out);
            out.push('\n');
        }
        Block::List { items, .. } => {
            for item in items {
                push_inline_text(item, out);
                out.push('\n');
            }
        }
        Block::Quote(blocks) => {
            for b in blocks {
                push_block_text(b, out);
            }
        }
        Block::Table(t) => {
            for row in &t.rows {
                for (idx, cell) in row.cells.iter().enumerate() {
                    if idx > 0 {
                        out.push('\t');
                    }
                    push_inline_text(&cell.inlines, out);
                }
                out.push('\n');
            }
        }
    }
}

fn push_inline_text(inlines: &[Inline], out: &mut String) {
    for i in inlines {
        match i {
            Inline::Text(t) => out.push_str(t),
            Inline::Emphasis { inlines, .. } => push_inline_text(inlines, out),
            Inline::Math(m) => out.push_str(m),
            Inline::LineBreak => out.push(' '),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_text_flattens_nested_emphasis() {
        let doc = Document {
            title: Some(vec![Inline::Text("Title".into())]),
            blocks: vec![Block::Paragraph {
                inlines: vec![
                    Inline::Text("a ".into()),
                    Inline::Emphasis {
                        kind: EmphasisKind::Bold,
                        inlines: vec![Inline::Text("b".into())],
                    },
                ],
            }],
            ..Default::default()
        };
        assert_eq!(doc.plain_text(), "Title\na b\n");
    }
}
