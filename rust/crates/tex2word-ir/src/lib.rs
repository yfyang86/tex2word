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
}

/// A whole document: an optional title plus a sequence of blocks.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Document {
    pub title: Option<Vec<Inline>>,
    pub blocks: Vec<Block>,
}

impl Document {
    /// Concatenated plain text of the whole document (useful for tests/telemetry).
    pub fn plain_text(&self) -> String {
        let mut out = String::new();
        if let Some(t) = &self.title {
            push_inline_text(t, &mut out);
            out.push('\n');
        }
        for b in &self.blocks {
            match b {
                Block::Heading { inlines, .. } | Block::Paragraph { inlines } => {
                    push_inline_text(inlines, &mut out);
                    out.push('\n');
                }
            }
        }
        out
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
        };
        assert_eq!(doc.plain_text(), "Title\na b\n");
    }
}
