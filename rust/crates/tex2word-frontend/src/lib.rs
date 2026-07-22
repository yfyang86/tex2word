//! LaTeX front-end: parse LaTeX source into the tex2word [`Document`] IR.
//!
//! This is the **vertical-slice** parser — a hand-rolled recursive scan (no
//! external LaTeX library) covering the common structural and inline core:
//! `\title`, sectioning, paragraphs (blank-line separated), `\textbf`/`\emph`/
//! `\textit`/`\texttt`/`\underline`/`\textrm`, escaped literals, `\\` breaks and
//! inline `$…$` math. The Python front-end is far broader; the roadmap tracks
//! what still needs porting (macro expansion, environments, display math, …).

use std::path::Path;

use tex2word_ir::{Block, Document, EmphasisKind, Inline};

mod macros;

/// Parse a LaTeX document string into the IR (relative `\input`s resolved against
/// the current directory).
pub fn parse_document(source: &str) -> Document {
    parse_document_in(source, Path::new("."))
}

/// Parse a LaTeX document, resolving `\input`/`\include` files against `base_dir`.
pub fn parse_document_in(source: &str, base_dir: &Path) -> Document {
    // strip comments, flatten \input/\include, then expand macros, then parse.
    let flat = flatten_inputs(&strip_comments(source), base_dir, 0);
    let src = macros::expand_macros(&flat);
    let title = extract_braced_macro_arg(&src, "title").map(|t| parse_inlines(&t));
    let body = extract_environment(&src, "document").unwrap_or_else(|| src.clone());
    Document {
        title,
        blocks: parse_blocks(&body),
    }
}

const MAX_INPUT_DEPTH: usize = 16;

/// Inline `\input{file}` / `\include{file}` (recursively; each included file is
/// comment-stripped). A missing file is dropped (graceful degradation).
fn flatten_inputs(source: &str, base_dir: &Path, depth: usize) -> String {
    if depth > MAX_INPUT_DEPTH {
        return source.to_string();
    }
    let s: Vec<char> = source.chars().collect();
    let n = s.len();
    let mut out = String::new();
    let mut i = 0;
    while i < n {
        if s[i] == '\\' {
            let (name, after) = read_command_name(&s, i);
            if name == "input" || name == "include" {
                let (arg, after2) = read_braced(&s, after);
                if let Some(content) = read_included(base_dir, arg.trim()) {
                    out.push_str(&flatten_inputs(
                        &strip_comments(&content),
                        base_dir,
                        depth + 1,
                    ));
                }
                i = after2;
                continue;
            }
            out.extend(&s[i..after]);
            i = after;
            continue;
        }
        out.push(s[i]);
        i += 1;
    }
    out
}

/// Read an included file (`name` or `name.tex`) relative to `base_dir`.
fn read_included(base_dir: &Path, name: &str) -> Option<String> {
    if name.is_empty() {
        return None;
    }
    let candidates: Vec<String> = if name.ends_with(".tex") {
        vec![name.to_string()]
    } else {
        vec![name.to_string(), format!("{name}.tex")]
    };
    for cand in candidates {
        if let Ok(content) = std::fs::read_to_string(base_dir.join(&cand)) {
            return Some(content);
        }
    }
    None
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
            if name == "begin" {
                let (env, after_env) = read_braced(&s, after);
                let (body, after_body) = read_env_body(&s, after_env, &env);
                flush_paragraph(&mut blocks, &mut para);
                match env.as_str() {
                    "itemize" | "enumerate" => {
                        blocks.push(parse_list(&body, env == "enumerate"));
                    }
                    "quote" | "quotation" => {
                        blocks.push(Block::Quote(parse_blocks(&body)));
                    }
                    // unknown environment: descend transparently (keep content)
                    _ => blocks.extend(parse_blocks(&body)),
                }
                i = after_body;
                continue;
            }
            if name == "end" {
                // a stray \end{…}: consume its name and ignore
                let (_, after2) = read_braced(&s, after);
                i = after2;
                continue;
            }
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

/// True if `s[i..]` starts with `pat`.
fn matches_at(s: &[char], i: usize, pat: &[char]) -> bool {
    i + pat.len() <= s.len() && s[i..i + pat.len()] == *pat
}

/// From just after `\begin{env}` (at `i`), read the environment body up to the
/// matching `\end{env}`, tracking nested `\begin{env}` of the *same* name.
/// Returns (body, index-after-`\end{env}`).
fn read_env_body(s: &[char], i: usize, env: &str) -> (String, usize) {
    let begin_pat: Vec<char> = format!("\\begin{{{env}}}").chars().collect();
    let end_pat: Vec<char> = format!("\\end{{{env}}}").chars().collect();
    let start = i;
    let mut depth = 1;
    let mut j = i;
    while j < s.len() {
        if matches_at(s, j, &begin_pat) {
            depth += 1;
            j += begin_pat.len();
            continue;
        }
        if matches_at(s, j, &end_pat) {
            depth -= 1;
            if depth == 0 {
                return (s[start..j].iter().collect(), j + end_pat.len());
            }
            j += end_pat.len();
            continue;
        }
        j += 1;
    }
    (s[start..].iter().collect(), s.len())
}

/// Parse an `itemize`/`enumerate` body (split on top-level `\item`).
fn parse_list(body: &str, ordered: bool) -> Block {
    let s: Vec<char> = body.chars().collect();
    let n = s.len();
    let mut items: Vec<Vec<Inline>> = Vec::new();
    let mut buf = String::new();
    let mut started = false;
    let mut i = 0;
    while i < n {
        if s[i] == '\\' {
            let (name, after) = read_command_name(&s, i);
            if name == "item" {
                if started {
                    items.push(parse_inlines(buf.trim()));
                    buf.clear();
                }
                started = true;
                i = skip_optional_bracket(&s, after); // drop \item[label]
                continue;
            }
            if started {
                buf.extend(&s[i..after]);
            }
            i = after;
            continue;
        }
        if started {
            buf.push(s[i]);
        }
        i += 1;
    }
    if started {
        items.push(parse_inlines(buf.trim()));
    }
    Block::List { ordered, items }
}

/// Skip an optional `[ … ]` group (e.g. `\item[label]`); returns index-after.
fn skip_optional_bracket(s: &[char], i: usize) -> usize {
    let mut j = i;
    while j < s.len() && (s[j] == ' ' || s[j] == '\t') {
        j += 1;
    }
    if j < s.len() && s[j] == '[' {
        while j < s.len() && s[j] != ']' {
            j += 1;
        }
        if j < s.len() {
            j += 1; // consume ']'
        }
        return j;
    }
    i
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

    #[test]
    fn itemize_and_enumerate() {
        let doc = conv(
            r"\begin{document}\begin{itemize}\item first \item second\end{itemize}
\begin{enumerate}\item one \item two\end{enumerate}\end{document}",
        );
        assert_eq!(
            doc.blocks,
            vec![
                Block::List {
                    ordered: false,
                    items: vec![
                        vec![Inline::Text("first".into())],
                        vec![Inline::Text("second".into())],
                    ],
                },
                Block::List {
                    ordered: true,
                    items: vec![
                        vec![Inline::Text("one".into())],
                        vec![Inline::Text("two".into())],
                    ],
                },
            ]
        );
    }

    #[test]
    fn item_optional_label_dropped_and_markup_kept() {
        let doc = conv(
            r"\begin{document}\begin{itemize}\item[a)] with \textbf{bold}\end{itemize}\end{document}",
        );
        let Block::List { items, .. } = &doc.blocks[0] else {
            panic!("expected list");
        };
        assert_eq!(items[0][0], Inline::Text("with ".into()));
        assert!(matches!(
            &items[0][1],
            Inline::Emphasis {
                kind: EmphasisKind::Bold,
                ..
            }
        ));
    }

    #[test]
    fn quote_environment_holds_blocks() {
        let doc = conv(r"\begin{document}\begin{quote}A quoted line.\end{quote}\end{document}");
        let Block::Quote(blocks) = &doc.blocks[0] else {
            panic!("expected quote");
        };
        assert_eq!(
            blocks,
            &vec![Block::Paragraph {
                inlines: vec![Inline::Text("A quoted line.".into())]
            }]
        );
    }

    #[test]
    fn input_flattening_inlines_files() {
        use std::fs;
        let dir = std::env::temp_dir().join(format!("t2w_input_{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        fs::write(dir.join("sec.tex"), r"\section{Included}Body from file.").unwrap();
        // \input{sec} (no .tex) is resolved to sec.tex, recursively comment-stripped
        let main = r"\begin{document}Before.\input{sec}\end{document}";
        let doc = parse_document_in(main, &dir);
        let _ = fs::remove_dir_all(&dir);
        assert!(doc.blocks.iter().any(|b| matches!(
            b, Block::Heading { inlines, .. } if inlines == &vec![Inline::Text("Included".into())]
        )));
        assert!(doc.plain_text().contains("Body from file."));
    }

    #[test]
    fn missing_input_is_dropped_gracefully() {
        let doc = parse_document_in(
            r"\begin{document}Kept.\input{does_not_exist}\end{document}",
            Path::new("/nonexistent-dir-xyz"),
        );
        assert_eq!(doc.plain_text().trim(), "Kept.");
    }

    #[test]
    fn user_macros_expand_before_parsing() {
        let doc = conv(
            r"\newcommand{\kw}[1]{\textbf{#1}}\newcommand\prod{tex2word}
\begin{document}Use \kw{\prod} today.\end{document}",
        );
        let Block::Paragraph { inlines } = &doc.blocks[0] else {
            panic!("expected paragraph");
        };
        // \kw{\prod} -> \textbf{tex2word} -> a bold "tex2word"
        assert!(inlines.iter().any(|i| matches!(
            i,
            Inline::Emphasis { kind: EmphasisKind::Bold, inlines }
                if inlines == &vec![Inline::Text("tex2word".into())]
        )));
    }

    #[test]
    fn nested_same_name_environment_matches_correctly() {
        let doc = conv(
            r"\begin{document}\begin{itemize}\item outer\begin{itemize}\item inner\end{itemize}\end{itemize}after\end{document}",
        );
        // the inner \end{itemize} must not close the outer list early
        assert!(matches!(doc.blocks[0], Block::List { .. }));
        assert_eq!(
            doc.blocks.last(),
            Some(&Block::Paragraph {
                inlines: vec![Inline::Text("after".into())]
            })
        );
    }
}
