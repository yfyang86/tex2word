//! tex2word intermediate representation (IR).
//!
//! The IR is the contract between the front-end (LaTeX -> IR) and the back-end
//! (IR -> OOXML `.docx`), mirroring the Python `tex2word.ir` module. This is the
//! initial faithful *subset* used by the vertical slice; it grows module by
//! module as the port proceeds (see `rust/ROADMAP.md`).

use std::collections::HashMap;

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
    /// An `\includegraphics[options]{path}` image. `path` is as written in the
    /// source; `options` is the raw option string (e.g. `width=0.5\textwidth`).
    /// Binary embedding is a later milestone — for now it renders as a labelled
    /// placeholder.
    Image { path: String, options: String },
    /// A cross-reference (`\ref`/`\eqref`/`\cref`/`\pageref`/…). `bookmark` is
    /// filled in by the cross-reference pass; the back-end then emits a live
    /// `REF`/`PAGEREF` field. `style` selects a cleveref-style type prefix.
    Ref {
        key: String,
        kind: RefKind,
        style: RefStyle,
        bookmark: Option<String>,
    },
    /// A hyperlink: an external `url`, or an internal `anchor` bookmark
    /// (`\hyperref[label]{…}`, resolved to a sanitized bookmark by the pass).
    Link {
        inlines: Vec<Inline>,
        url: String,
        anchor: Option<String>,
    },
}

/// What a cross-reference points at (drives the counter + cleveref prefix).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RefKind {
    #[default]
    Generic,
    Equation,
    Figure,
    Table,
    Section,
    Theorem,
    Page,
    Name,
    ListItem,
}

/// The cleveref-style prefix a reference carries: `Plain` (bare number, `\ref`),
/// `Abbrev` (`fig. N`, `\cref`), `Full` (`Figure N`, `\Cref`/`\autoref`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RefStyle {
    #[default]
    Plain,
    Abbrev,
    Full,
}

/// Block-level content.
#[derive(Debug, Clone, PartialEq)]
pub enum Block {
    /// `level` 1..=3 maps to Word `Heading1`..`Heading3`. `label` is a `\label`
    /// target attached to the heading (for `\ref`/`\nameref`). `numbered` is
    /// false for the starred forms (`\section*`).
    Heading {
        level: u8,
        inlines: Vec<Inline>,
        label: Option<String>,
        numbered: bool,
    },
    /// A body paragraph.
    Paragraph { inlines: Vec<Inline> },
    /// A display-math equation (`\[ … \]` / `equation`), a numberable target.
    /// `numbered` is true for the auto-numbered environments (`equation`,
    /// `align`, …) and false for `\[ … \]` / starred forms.
    MathBlock {
        latex: String,
        label: Option<String>,
        numbered: bool,
    },
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
    /// A `figure`/`table` float (content + an optional numbered caption).
    Float(Float),
    /// A `\tableofcontents`/`\listoffigures`/`\listoftables` → a Word `TOC` field.
    TableOfContents(TocKind),
}

/// Which list a `TableOfContents` renders (heading outline, or a caption series).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TocKind {
    Contents,
    Figures,
    Tables,
}

/// A `figure`/`table` float environment.
#[derive(Debug, Clone, PartialEq)]
pub struct Float {
    pub kind: FloatKind,
    /// The float's body (image/table/paragraphs), in source order.
    pub content: Vec<Block>,
    /// The `\caption{…}` text, if any (numbered `Figure N` / `Table N`).
    pub caption: Option<Vec<Inline>>,
    /// `\centering` was present.
    pub centered: bool,
    /// A `\label{…}` target (for `\ref`/`\autoref` to the float's number).
    pub label: Option<String>,
    /// A starred float (`figure*`/`table*`): spans all columns in a two-column
    /// document (rendered full-width between continuous section breaks).
    pub spanning: bool,
}

/// Which caption series a float belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FloatKind {
    Figure,
    Table,
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

/// A resolved `\label`: its Word bookmark, counter series, and display name.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LabelInfo {
    pub kind: RefKind,
    /// Word `SEQ` counter name (e.g. `Figure`, `Table`, `Equation`).
    pub counter_name: String,
    /// Sanitized Word bookmark the number lives in.
    pub bookmark: String,
    /// The target's title/caption text (for `\nameref`).
    pub name: Option<String>,
}

/// A whole document: title/author/date metadata plus a sequence of blocks.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Document {
    pub title: Option<Vec<Inline>>,
    /// One entry per author (split on `\and`).
    pub authors: Vec<Vec<Inline>>,
    pub date: Option<Vec<Inline>>,
    pub blocks: Vec<Block>,
    /// `\label` → resolved bookmark/counter, populated by the cross-reference
    /// pass (empty until then).
    pub labels: HashMap<String, LabelInfo>,
    /// Column count for the body (2 for a `twocolumn` document, else 1).
    /// `0` (the `Default`) is treated as 1 by the back-end.
    pub columns: usize,
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
        Block::MathBlock { latex, .. } => {
            out.push_str(latex);
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
        Block::Float(f) => {
            for b in &f.content {
                push_block_text(b, out);
            }
            if let Some(cap) = &f.caption {
                push_inline_text(cap, out);
                out.push('\n');
            }
        }
        Block::TableOfContents(kind) => {
            out.push_str(match kind {
                TocKind::Contents => "Contents",
                TocKind::Figures => "List of Figures",
                TocKind::Tables => "List of Tables",
            });
            out.push('\n');
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
            Inline::Image { .. } => {}
            Inline::Ref { key, bookmark, .. } => {
                // Cached display text is unknown pre-render; use the target name.
                out.push_str(bookmark.as_deref().unwrap_or(key));
            }
            Inline::Link { inlines, .. } => push_inline_text(inlines, out),
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
