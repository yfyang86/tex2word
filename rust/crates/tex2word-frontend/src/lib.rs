//! LaTeX front-end: parse LaTeX source into the tex2word [`Document`] IR.
//!
//! A hand-rolled recursive scan (no external LaTeX library). Pipeline:
//! `strip_comments` → `\input`/`\include` flatten → macro expansion → parse.
//! Coverage so far (Phase 1): `\title`, sectioning, paragraphs, the
//! `itemize`/`enumerate`/`quote` environments, `\textbf`/`\emph`/`\textit`/
//! `\texttt`/`\underline`/`\textsc`/`\textsuperscript`/`\textsubscript`, escaped
//! literals, dashes/smart-quotes/`~`, a batch of text symbol macros, accents
//! (`\'e`/`\"o`/`\c c`/… -> precomposed Unicode), `\\` breaks and inline `$…$`
//! math. The roadmap tracks what still needs porting (preamble metadata, a
//! proper tokenizer, display math, …).

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
    let title = extract_braced_macro_arg(&src, "title")
        .map(|t| parse_inlines(t.trim()))
        .filter(|v| !is_blank_inlines(v));
    let authors: Vec<Vec<Inline>> = extract_braced_macro_arg(&src, "author")
        .map(|a| {
            split_and(&a)
                .iter()
                .map(|x| parse_inlines(x.trim()))
                .filter(|v| !is_blank_inlines(v))
                .collect()
        })
        .unwrap_or_default();
    let date = extract_braced_macro_arg(&src, "date")
        .map(|d| parse_inlines(d.trim()))
        .filter(|v| !is_blank_inlines(v));
    let body = extract_environment(&src, "document").unwrap_or_else(|| src.clone());
    Document {
        title,
        authors,
        date,
        blocks: parse_blocks(&body),
    }
}

fn is_blank_inlines(v: &[Inline]) -> bool {
    v.iter().all(is_blank_inline)
}

/// Split an `\author{…}` argument on top-level `\and` into per-author strings.
fn split_and(arg: &str) -> Vec<String> {
    let s: Vec<char> = arg.chars().collect();
    let mut parts: Vec<String> = Vec::new();
    let mut buf = String::new();
    let mut depth = 0;
    let mut i = 0;
    while i < s.len() {
        match s[i] {
            '{' => {
                depth += 1;
                buf.push('{');
                i += 1;
            }
            '}' => {
                depth -= 1;
                buf.push('}');
                i += 1;
            }
            '\\' if depth == 0 => {
                let (name, after) = read_command_name(&s, i);
                if name == "and" {
                    parts.push(std::mem::take(&mut buf));
                } else {
                    buf.extend(&s[i..after]);
                }
                i = after;
            }
            c => {
                buf.push(c);
                i += 1;
            }
        }
    }
    parts.push(buf);
    parts
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
            if name == "[" {
                // display math \[ … \] -> its own paragraph of math
                flush_paragraph(&mut blocks, &mut para);
                let (math, after2) = read_display_math(&s, after);
                blocks.push(Block::Paragraph {
                    inlines: vec![Inline::Math(math.trim().to_string())],
                });
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
                    "textbf" | "emph" | "textit" | "texttt" | "underline" | "textrm" | "textsc"
                    | "textsuperscript" | "textsubscript" | "textnormal" => {
                        flush_text!();
                        let (arg, after2) = read_braced(&s, after);
                        let inner = parse_inlines(&arg);
                        match emphasis_kind(&name) {
                            Some(kind) => out.push(Inline::Emphasis {
                                kind,
                                inlines: inner,
                            }),
                            None => out.extend(inner), // \textrm/\textnormal -> passthrough
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
                    // accents: \'e \`a \^o \"u \~n \=o \.z \c{c} \v{s} \u{a}
                    // \H{o} \r{a} \k{e} … -> a precomposed Unicode letter.
                    "'" | "`" | "^" | "\"" | "~" | "=" | "." | "c" | "v" | "u" | "H" | "r"
                    | "k" | "d" | "b" | "t" => {
                        let (base, after2) = read_accent_base(&s, after);
                        if let Some(b) = base {
                            text.push(apply_accent(&name, b).unwrap_or(b));
                        }
                        i = after2;
                    }
                    _ => {
                        if let Some(sym) = text_symbol(&name) {
                            text.push_str(sym);
                            i = after;
                        } else {
                            // unknown macro: drop it, skip a following {arg}
                            let (_, after2) = read_braced(&s, after);
                            i = after2;
                        }
                    }
                }
            }
            '~' => {
                text.push('\u{00A0}'); // non-breaking space
                i += 1;
            }
            '-' => {
                // -- -> en dash, --- -> em dash, otherwise literal hyphen(s)
                let mut k = i;
                while k < n && s[k] == '-' {
                    k += 1;
                }
                match k - i {
                    3 => text.push('\u{2014}'),
                    2 => text.push('\u{2013}'),
                    run => (0..run).for_each(|_| text.push('-')),
                }
                i = k;
            }
            '`' => {
                if i + 1 < n && s[i + 1] == '`' {
                    text.push('\u{201C}'); // ``  -> left double quote
                    i += 2;
                } else {
                    text.push('\u{2018}'); // `   -> left single quote
                    i += 1;
                }
            }
            '\'' => {
                if i + 1 < n && s[i + 1] == '\'' {
                    text.push('\u{201D}'); // ''  -> right double quote
                    i += 2;
                } else {
                    text.push('\u{2019}'); // '   -> right single quote / apostrophe
                    i += 1;
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
        "textsc" => Some(EmphasisKind::SmallCaps),
        "textsuperscript" => Some(EmphasisKind::Superscript),
        "textsubscript" => Some(EmphasisKind::Subscript),
        _ => None, // textrm/textnormal: no emphasis
    }
}

/// Text-mode symbol macros -> their Unicode text (no argument).
fn text_symbol(name: &str) -> Option<&'static str> {
    Some(match name {
        "S" => "§",
        "P" => "¶",
        "dag" | "dagger" | "textdagger" => "†",
        "ddag" | "ddagger" | "textdaggerdbl" => "‡",
        "copyright" | "textcopyright" => "©",
        "textregistered" => "®",
        "texttrademark" => "™",
        "pounds" | "textsterling" => "£",
        "texteuro" => "€",
        "textcent" => "¢",
        "textyen" => "¥",
        "textbullet" => "•",
        "textdegree" | "degree" => "°",
        "textpm" => "±",
        "texttimes" => "×",
        "textdiv" => "÷",
        "textellipsis" => "…",
        "textquotedblleft" => "\u{201C}",
        "textquotedblright" => "\u{201D}",
        "textquoteleft" => "\u{2018}",
        "textquoteright" => "\u{2019}",
        "textendash" => "\u{2013}",
        "textemdash" => "\u{2014}",
        "LaTeX" | "LaTeXe" => "LaTeX",
        "TeX" => "TeX",
        // special letters
        "o" => "ø",
        "O" => "Ø",
        "l" => "ł",
        "L" => "Ł",
        "ss" => "ß",
        "ae" => "æ",
        "AE" => "Æ",
        "oe" => "œ",
        "OE" => "Œ",
        "aa" => "å",
        "AA" => "Å",
        "i" => "ı",
        "j" => "ȷ",
        "dh" => "ð",
        "DH" => "Ð",
        "th" => "þ",
        "TH" => "Þ",
        // spacing commands -> a space, or nothing for the negative/discretionary ones
        "," | ";" | ":" | " " | "quad" | "qquad" | "enspace" | "thinspace" => " ",
        "!" | "@" | "/" | "-" => "",
        _ => return None,
    })
}

/// Read an accent's base letter: `{x}` (or `{\i}`), `\i`/`\j`, or a bare char.
fn read_accent_base(s: &[char], i: usize) -> (Option<char>, usize) {
    let mut j = i;
    while j < s.len() && (s[j] == ' ' || s[j] == '\t') {
        j += 1;
    }
    if j >= s.len() {
        return (None, j);
    }
    if s[j] == '{' {
        let (inner, after) = read_braced(s, j);
        (base_char(&inner), after)
    } else if s[j] == '\\' {
        let (name, after) = read_command_name(s, j);
        (dotless_base(&name), after)
    } else {
        (Some(s[j]), j + 1)
    }
}

fn base_char(inner: &str) -> Option<char> {
    let t = inner.trim();
    if let Some(rest) = t.strip_prefix('\\') {
        return dotless_base(rest.trim());
    }
    t.chars().next()
}

/// `\i`/`\j` (dotless i/j, used under accents) resolve to the plain letter.
fn dotless_base(name: &str) -> Option<char> {
    match name {
        "i" => Some('i'),
        "j" => Some('j'),
        other => other.chars().next(),
    }
}

/// Map (accent command, base letter) to the precomposed Unicode character.
/// Unknown combinations return `None` (the caller keeps the base letter).
fn apply_accent(accent: &str, base: char) -> Option<char> {
    Some(match (accent, base) {
        // acute \'
        ("'", 'a') => 'á',
        ("'", 'e') => 'é',
        ("'", 'i') => 'í',
        ("'", 'o') => 'ó',
        ("'", 'u') => 'ú',
        ("'", 'y') => 'ý',
        ("'", 'n') => 'ń',
        ("'", 'c') => 'ć',
        ("'", 's') => 'ś',
        ("'", 'z') => 'ź',
        ("'", 'r') => 'ŕ',
        ("'", 'l') => 'ĺ',
        ("'", 'A') => 'Á',
        ("'", 'E') => 'É',
        ("'", 'I') => 'Í',
        ("'", 'O') => 'Ó',
        ("'", 'U') => 'Ú',
        ("'", 'N') => 'Ń',
        // grave \`
        ("`", 'a') => 'à',
        ("`", 'e') => 'è',
        ("`", 'i') => 'ì',
        ("`", 'o') => 'ò',
        ("`", 'u') => 'ù',
        ("`", 'A') => 'À',
        ("`", 'E') => 'È',
        ("`", 'O') => 'Ò',
        ("`", 'U') => 'Ù',
        // circumflex \^
        ("^", 'a') => 'â',
        ("^", 'e') => 'ê',
        ("^", 'i') => 'î',
        ("^", 'o') => 'ô',
        ("^", 'u') => 'û',
        ("^", 'A') => 'Â',
        ("^", 'E') => 'Ê',
        ("^", 'O') => 'Ô',
        ("^", 'w') => 'ŵ',
        ("^", 'y') => 'ŷ',
        // diaeresis \"
        ("\"", 'a') => 'ä',
        ("\"", 'e') => 'ë',
        ("\"", 'i') => 'ï',
        ("\"", 'o') => 'ö',
        ("\"", 'u') => 'ü',
        ("\"", 'y') => 'ÿ',
        ("\"", 'A') => 'Ä',
        ("\"", 'E') => 'Ë',
        ("\"", 'O') => 'Ö',
        ("\"", 'U') => 'Ü',
        // tilde \~
        ("~", 'a') => 'ã',
        ("~", 'n') => 'ñ',
        ("~", 'o') => 'õ',
        ("~", 'A') => 'Ã',
        ("~", 'N') => 'Ñ',
        ("~", 'O') => 'Õ',
        // macron \=
        ("=", 'a') => 'ā',
        ("=", 'e') => 'ē',
        ("=", 'i') => 'ī',
        ("=", 'o') => 'ō',
        ("=", 'u') => 'ū',
        // dot above \.
        (".", 'z') => 'ż',
        (".", 'e') => 'ė',
        (".", 'c') => 'ċ',
        (".", 'g') => 'ġ',
        // cedilla \c
        ("c", 'c') => 'ç',
        ("c", 'C') => 'Ç',
        ("c", 's') => 'ş',
        ("c", 'S') => 'Ş',
        ("c", 'g') => 'ģ',
        // caron \v
        ("v", 'c') => 'č',
        ("v", 's') => 'š',
        ("v", 'z') => 'ž',
        ("v", 'r') => 'ř',
        ("v", 'e') => 'ě',
        ("v", 'n') => 'ň',
        ("v", 'd') => 'ď',
        ("v", 't') => 'ť',
        ("v", 'C') => 'Č',
        ("v", 'S') => 'Š',
        ("v", 'Z') => 'Ž',
        // breve \u
        ("u", 'a') => 'ă',
        ("u", 'g') => 'ğ',
        ("u", 'G') => 'Ğ',
        // double acute \H
        ("H", 'o') => 'ő',
        ("H", 'u') => 'ű',
        ("H", 'O') => 'Ő',
        ("H", 'U') => 'Ű',
        // ring \r
        ("r", 'a') => 'å',
        ("r", 'A') => 'Å',
        ("r", 'u') => 'ů',
        // ogonek \k
        ("k", 'a') => 'ą',
        ("k", 'e') => 'ę',
        ("k", 'A') => 'Ą',
        ("k", 'E') => 'Ę',
        _ => return None,
    })
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
/// Read display-math content from just after `\[` up to `\]`; (inner, index-after).
fn read_display_math(s: &[char], from: usize) -> (String, usize) {
    let mut j = from;
    while j + 1 < s.len() {
        if s[j] == '\\' && s[j + 1] == ']' {
            return (s[from..j].iter().collect(), j + 2);
        }
        j += 1;
    }
    (s[from..].iter().collect(), s.len())
}

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
    fn author_and_date_metadata() {
        let doc = conv(
            r"\title{T}\author{Ada Lovelace \and Alan Turing}\date{1936}
\begin{document}\maketitle Body.\end{document}",
        );
        assert_eq!(doc.authors.len(), 2);
        assert_eq!(doc.authors[0], vec![Inline::Text("Ada Lovelace".into())]);
        assert_eq!(doc.authors[1], vec![Inline::Text("Alan Turing".into())]);
        assert_eq!(doc.date, Some(vec![Inline::Text("1936".into())]));
        // \maketitle does not leak, body still parses
        assert!(doc.plain_text().contains("Body."));
    }

    #[test]
    fn empty_date_is_none() {
        let doc = conv(r"\title{T}\date{}\begin{document}x\end{document}");
        assert_eq!(doc.date, None);
        assert!(doc.authors.is_empty());
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
    fn small_caps_super_sub_and_symbols() {
        let doc = conv(
            r"\begin{document}\textsc{Acme} x\textsuperscript{2} H\textsubscript{2}O \S \copyright\end{document}",
        );
        let Block::Paragraph { inlines } = &doc.blocks[0] else {
            panic!("expected paragraph");
        };
        assert!(inlines.iter().any(|i| matches!(
            i,
            Inline::Emphasis {
                kind: EmphasisKind::SmallCaps,
                ..
            }
        )));
        assert!(inlines.iter().any(|i| matches!(
            i,
            Inline::Emphasis {
                kind: EmphasisKind::Superscript,
                ..
            }
        )));
        assert!(inlines.iter().any(|i| matches!(
            i,
            Inline::Emphasis {
                kind: EmphasisKind::Subscript,
                ..
            }
        )));
        let t = doc.plain_text();
        assert!(t.contains('§') && t.contains('©'));
    }

    #[test]
    fn dashes_quotes_and_nbsp() {
        let doc = conv(r"\begin{document}pages 1--5, dash---here, ``q'' and Fig.~1\end{document}");
        let t = doc.plain_text();
        assert!(t.contains('\u{2013}'), "en dash"); // 1--5
        assert!(t.contains('\u{2014}'), "em dash"); // ---
        assert!(
            t.contains('\u{201C}') && t.contains('\u{201D}'),
            "curly quotes"
        );
        assert!(t.contains('\u{00A0}'), "nbsp from ~");
    }

    #[test]
    fn accents_and_special_letters() {
        // \"i needs a hashed raw string (it contains a double quote)
        let doc = conv(
            r#"\begin{document}Caf\'e na\"ive \c{c}a \^o \~n Erd\H{o}s stra\ss e \o \ae\end{document}"#,
        );
        let t = doc.plain_text();
        for ch in ['é', 'ï', 'ç', 'ô', 'ñ', 'ő', 'ß', 'ø', 'æ'] {
            assert!(t.contains(ch), "missing {ch:?} in {t:?}");
        }
        // unknown accent combo falls back to the base letter (no crash, no drop)
        assert!(conv(r"\begin{document}\'q\end{document}")
            .plain_text()
            .contains('q'));
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
