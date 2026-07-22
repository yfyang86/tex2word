//! LaTeX front-end: parse LaTeX source into the tex2word [`Document`] IR.
//!
//! This is the **vertical-slice** parser — a hand-rolled recursive scan (no
//! external LaTeX library) covering the common structural and inline core:
//! `\title`, sectioning, paragraphs (blank-line separated), `\textbf`/`\emph`/
//! `\textit`/`\texttt`/`\underline`/`\textrm`, escaped literals, `\\` breaks and
//! inline `$…$` math. The Python front-end is far broader; the roadmap tracks
//! what still needs porting (macro expansion, environments, display math, …).

use tex2word_ir::{Block, Document, EmphasisKind, Inline};

/// Parse a LaTeX document string into the IR.
pub fn parse_document(source: &str) -> Document {
    let src = strip_comments(source);
    let title = extract_braced_macro_arg(&src, "title").map(|t| parse_inlines(&t));
    let body = extract_environment(&src, "document").unwrap_or(src.clone());
    Document {
        title,
        blocks: parse_blocks(&body),
    }
}

/// Remove TeX line comments (`%` to end of line), preserving escaped `\%`.
fn strip_comments(src: &str) -> String {
    let mut out = String::with_capacity(src.len());
    let chars: Vec<char> = src.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' && i + 1 < chars.len() {
            out.push(c);
            out.push(chars[i + 1]);
            i += 2;
            continue;
        }
        if c == '%' {
            // skip to (but keep) the newline
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
            }
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

/// The inner text of `\begin{name} … \end{name}`, if present.
fn extract_environment(src: &str, name: &str) -> Option<String> {
    let begin = format!("\\begin{{{name}}}");
    let end = format!("\\end{{{name}}}");
    let start = src.find(&begin)? + begin.len();
    let stop = src[start..].find(&end)? + start;
    Some(src[start..stop].to_string())
}

/// The braced argument of the first `\macro{…}`, if present.
fn extract_braced_macro_arg(src: &str, macro_name: &str) -> Option<String> {
    let needle = format!("\\{macro_name}");
    let chars: Vec<char> = src.chars().collect();
    let pat: Vec<char> = needle.chars().collect();
    let mut i = 0;
    while i + pat.len() <= chars.len() {
        if chars[i..i + pat.len()] == pat[..]
            // ensure it's not a longer command name (\titlepage vs \title)
            && chars.get(i + pat.len()).is_none_or(|c| !c.is_ascii_alphabetic())
        {
            let (arg, _) = read_braced(&chars, i + pat.len());
            return Some(arg);
        }
        i += 1;
    }
    None
}

/// Map a sectioning macro name to a heading level (1..=3), if it is one.
fn section_level(name: &str) -> Option<u8> {
    match name {
        "section" => Some(1),
        "subsection" => Some(2),
        "subsubsection" => Some(3),
        _ => None,
    }
}

/// Split a document body into block-level units (headings + paragraphs).
fn parse_blocks(body: &str) -> Vec<Block> {
    let s: Vec<char> = body.chars().collect();
    let n = s.len();
    let mut blocks: Vec<Block> = Vec::new();
    let mut para = String::new();
    let mut i = 0;

    while i < n {
        let c = s[i];
        if c == '\n' {
            // a blank line (2+ newlines) ends the current paragraph
            let mut j = i;
            let mut newlines = 0;
            while j < n && (s[j] == '\n' || s[j] == ' ' || s[j] == '\t' || s[j] == '\r') {
                if s[j] == '\n' {
                    newlines += 1;
                }
                j += 1;
            }
            if newlines >= 2 {
                flush_paragraph(&mut blocks, &mut para);
            } else if !para.is_empty() && !para.ends_with(' ') {
                para.push(' '); // soft newline -> single space (no leading/double)
            }
            i = j;
            continue;
        }
        if c == '\\' {
            let (name, after) = read_command_name(&s, i);
            if let Some(level) = section_level(&name) {
                flush_paragraph(&mut blocks, &mut para);
                let (arg, after2) = read_braced(&s, after);
                blocks.push(Block::Heading {
                    level,
                    inlines: parse_inlines(&arg),
                });
                i = after2;
                continue;
            }
            if name == "maketitle" {
                i = after;
                continue;
            }
            // inline command: keep the command token in the paragraph buffer so
            // parse_inlines handles it together with its (following) argument.
            para.extend(&s[i..after]);
            i = after;
            continue;
        }
        para.push(c);
        i += 1;
    }
    flush_paragraph(&mut blocks, &mut para);
    blocks
}

fn flush_paragraph(blocks: &mut Vec<Block>, para: &mut String) {
    let inlines = parse_inlines(para.trim());
    para.clear();
    if inlines.iter().any(|i| !is_blank_inline(i)) {
        blocks.push(Block::Paragraph { inlines });
    }
}

fn is_blank_inline(i: &Inline) -> bool {
    matches!(i, Inline::Text(t) if t.trim().is_empty())
}

/// Parse a run of inline LaTeX into IR inlines.
fn parse_inlines(src: &str) -> Vec<Inline> {
    let s: Vec<char> = src.chars().collect();
    let n = s.len();
    let mut out: Vec<Inline> = Vec::new();
    let mut text = String::new();
    let mut i = 0;

    macro_rules! flush_text {
        () => {
            if !text.is_empty() {
                out.push(Inline::Text(std::mem::take(&mut text)));
            }
        };
    }

    while i < n {
        let c = s[i];
        match c {
            '$' => {
                flush_text!();
                let (math, after) = read_until(&s, i + 1, '$');
                out.push(Inline::Math(math.trim().to_string()));
                i = after;
            }
            '\\' => {
                let (name, after) = read_command_name(&s, i);
                match name.as_str() {
                    "textbf" | "emph" | "textit" | "texttt" | "underline" | "textrm" => {
                        flush_text!();
                        let (arg, after2) = read_braced(&s, after);
                        let inner = parse_inlines(&arg);
                        match emphasis_kind(&name) {
                            Some(kind) => out.push(Inline::Emphasis {
                                kind,
                                inlines: inner,
                            }),
                            None => out.extend(inner), // \textrm -> transparent passthrough
                        }
                        i = after2;
                    }
                    "\\" | "newline" => {
                        flush_text!();
                        out.push(Inline::LineBreak);
                        i = after;
                    }
                    // escaped literals: \& \% \_ \# \{ \} \$
                    "&" | "%" | "_" | "#" | "{" | "}" | "$" => {
                        text.push(name.chars().next().unwrap());
                        i = after;
                    }
                    "textbackslash" => {
                        text.push('\\');
                        i = after;
                    }
                    "ldots" | "dots" => {
                        text.push('…');
                        i = after;
                    }
                    // unknown macro: drop it (transparent), skip a following {arg}
                    _ => {
                        let (_, after2) = read_braced(&s, after);
                        i = after2;
                    }
                }
            }
            '\n' | '\t' | '\r' => {
                if !text.ends_with(' ') {
                    text.push(' ');
                }
                i += 1;
            }
            _ => {
                text.push(c);
                i += 1;
            }
        }
    }
    flush_text!();
    out
}

fn emphasis_kind(name: &str) -> Option<EmphasisKind> {
    match name {
        "textbf" => Some(EmphasisKind::Bold),
        "emph" | "textit" => Some(EmphasisKind::Italic),
        "texttt" => Some(EmphasisKind::Typewriter),
        "underline" => Some(EmphasisKind::Underline),
        _ => None, // textrm: no emphasis
    }
}

/// From a `\` at `i`, read the command name; returns (name, index-after).
/// A control *word* is a run of ASCII letters (trailing spaces are gobbled);
/// a control *symbol* is the single following character.
fn read_command_name(s: &[char], i: usize) -> (String, usize) {
    debug_assert_eq!(s[i], '\\');
    let mut j = i + 1;
    if j < s.len() && s[j].is_ascii_alphabetic() {
        let start = j;
        while j < s.len() && s[j].is_ascii_alphabetic() {
            j += 1;
        }
        let name: String = s[start..j].iter().collect();
        while j < s.len() && s[j] == ' ' {
            j += 1; // gobble spaces after a control word
        }
        (name, j)
    } else if j < s.len() {
        (s[j].to_string(), j + 1)
    } else {
        ("".to_string(), j)
    }
}

/// Skip whitespace then read a balanced `{ … }` group; returns (inner, index-after).
/// If no `{` follows, returns ("", i) unchanged.
fn read_braced(s: &[char], i: usize) -> (String, usize) {
    let mut j = i;
    while j < s.len() && (s[j] == ' ' || s[j] == '\n' || s[j] == '\t' || s[j] == '\r') {
        j += 1;
    }
    if j >= s.len() || s[j] != '{' {
        return (String::new(), i);
    }
    let mut depth = 0;
    let start = j + 1;
    while j < s.len() {
        match s[j] {
            '\\' => {
                j += 2;
                continue;
            }
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    let inner: String = s[start..j].iter().collect();
                    return (inner, j + 1);
                }
            }
            _ => {}
        }
        j += 1;
    }
    // unbalanced: take the rest
    (s[start..].iter().collect(), s.len())
}

/// Read until the next unescaped `stop` char; returns (inner, index-after-stop).
fn read_until(s: &[char], i: usize, stop: char) -> (String, usize) {
    let mut j = i;
    let start = i;
    while j < s.len() {
        if s[j] == '\\' {
            j += 2;
            continue;
        }
        if s[j] == stop {
            let inner: String = s[start..j].iter().collect();
            return (inner, j + 1);
        }
        j += 1;
    }
    (s[start..].iter().collect(), s.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn conv(src: &str) -> Document {
        parse_document(src)
    }

    #[test]
    fn title_and_sections() {
        let doc = conv(
            r"\documentclass{article}\title{My Paper}\begin{document}\maketitle
\section{Intro}
Hello world.
\subsection{Sub}
More.\end{document}",
        );
        assert_eq!(doc.title, Some(vec![Inline::Text("My Paper".into())]));
        assert_eq!(
            doc.blocks,
            vec![
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Intro".into())]
                },
                Block::Paragraph {
                    inlines: vec![Inline::Text("Hello world.".into())]
                },
                Block::Heading {
                    level: 2,
                    inlines: vec![Inline::Text("Sub".into())]
                },
                Block::Paragraph {
                    inlines: vec![Inline::Text("More.".into())]
                },
            ]
        );
    }

    #[test]
    fn emphasis_and_math_and_break() {
        let doc = conv(r"\begin{document}a \textbf{b \emph{c}} $x^2$\\d\end{document}");
        let Block::Paragraph { inlines } = &doc.blocks[0] else {
            panic!("expected paragraph");
        };
        assert_eq!(inlines[0], Inline::Text("a ".into()));
        assert!(matches!(
            &inlines[1],
            Inline::Emphasis {
                kind: EmphasisKind::Bold,
                ..
            }
        ));
        assert!(inlines
            .iter()
            .any(|i| matches!(i, Inline::Math(m) if m == "x^2")));
        assert!(inlines.iter().any(|i| matches!(i, Inline::LineBreak)));
    }

    #[test]
    fn escaped_literals_and_comments() {
        let doc = conv(
            r"\begin{document}50\% \& more % this is a comment
end\end{document}",
        );
        assert_eq!(doc.plain_text().trim(), "50% & more end");
    }
}
