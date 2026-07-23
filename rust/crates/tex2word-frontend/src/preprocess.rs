//! Source-level preprocessing transforms — run after comment stripping and
//! `\input` flattening, before macro expansion. A port of the high-value parts
//! of the Python `frontend/preprocess.py`:
//!
//! * the `exam` document class (`questions`/`parts`/`subparts` → nested
//!   `enumerate`; `\question`/`\miquestion`/`\part`/`\subpart` → `\item`;
//!   solutions hidden unless `\printanswers`; a recovered title block),
//! * plain-TeX `\halign` systems of equations inside `\[ … \]` → `array`,
//! * the TikZ "cheatsheet" content-box idiom (text/math recovered, not dropped),
//! * the `\/` italic correction (a no-op).

use std::path::Path;

use crate::{read_braced, read_command_name, read_optional};

/// The exam-class answer environments (shown only under `\printanswers`).
const SOLUTION_ENVS: [&str; 4] = [
    "solution",
    "solutionorbox",
    "solutionorlines",
    "solutionordottedlines",
];

/// Apply the preprocessing transforms in order.
pub(crate) fn preprocess(source: &str, base_dir: &Path) -> String {
    let mut s = source.to_string();
    if uses_exam_class(&s, base_dir) {
        s = rewrite_exam_class(&s);
        s = inject_exam_title(&s);
    }
    s = rewrite_halign(&s);
    s = recover_tikz_boxes(&s);
    s = s.replace(r"\/", ""); // italic correction -> nothing
    s
}

/// True if the document is (directly, or via a local `.cls`) the exam class.
fn uses_exam_class(source: &str, base_dir: &Path) -> bool {
    if let Some(cls) = documentclass_name(source) {
        if cls == "exam" {
            return true;
        }
        let path = base_dir.join(format!("{cls}.cls"));
        if let Ok(content) = std::fs::read_to_string(&path) {
            // \LoadClass[..]{exam} / \LoadClassWithOptions{exam}
            for kw in ["\\LoadClassWithOptions", "\\LoadClass"] {
                if let Some(arg) = braced_arg_after(&content, kw) {
                    if arg.trim() == "exam" {
                        return true;
                    }
                }
            }
        }
    }
    false
}

/// The name in `\documentclass[opts]{name}`.
fn documentclass_name(source: &str) -> Option<String> {
    braced_arg_after(source, "\\documentclass")
}

/// The first braced argument following `keyword` (skipping an optional `[..]`).
fn braced_arg_after(source: &str, keyword: &str) -> Option<String> {
    let s: Vec<char> = source.chars().collect();
    let kw: Vec<char> = keyword.chars().collect();
    let mut i = 0;
    while i + kw.len() <= s.len() {
        if s[i..i + kw.len()] == kw[..]
            && s.get(i + kw.len()).is_none_or(|c| !c.is_ascii_alphabetic())
        {
            let (_opt, after) = read_optional(&s, i + kw.len());
            let (arg, _) = read_braced(&s, after);
            if !arg.is_empty() {
                return Some(arg);
            }
        }
        i += 1;
    }
    None
}

/// Rewrite the exam structure into nested `enumerate`/`\item`.
fn rewrite_exam_class(source: &str) -> String {
    let mut s = source.to_string();
    // solutions print only under \printanswers; otherwise drop them so they
    // don't leak into the preceding question item.
    if !s.contains("\\printanswers") {
        for env in SOLUTION_ENVS {
            s = remove_env_spans(&s, env);
        }
    }
    for env in ["questions", "parts", "subparts"] {
        s = s.replace(&format!("\\begin{{{env}}}"), "\\begin{enumerate}");
        s = s.replace(&format!("\\end{{{env}}}"), "\\end{enumerate}");
    }
    rewrite_exam_item_markers(&s)
}

/// Replace `\miquestion`/`\question`/`\subpart`/`\part` (dropping an optional
/// `[points]`) with `\item`.
fn rewrite_exam_item_markers(source: &str) -> String {
    let s: Vec<char> = source.chars().collect();
    let n = s.len();
    let mut out = String::with_capacity(source.len());
    let mut i = 0;
    while i < n {
        if s[i] == '\\' {
            let (name, after) = read_command_name(&s, i);
            if matches!(
                name.as_str(),
                "miquestion" | "question" | "subpart" | "part"
            ) {
                let (_opt, after_opt) = read_optional(&s, after);
                out.push_str("\\item ");
                i = after_opt;
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

/// Remove every `\begin{env} … \end{env}` span (non-nested; first-match greedy
/// per pair), used to drop hidden solutions.
fn remove_env_spans(source: &str, env: &str) -> String {
    let begin = format!("\\begin{{{env}}}");
    let end = format!("\\end{{{env}}}");
    let mut s = source.to_string();
    while let Some(b) = s.find(&begin) {
        if let Some(rel) = s[b..].find(&end) {
            let e = b + rel + end.len();
            s.replace_range(b..e, "");
        } else {
            break;
        }
    }
    s
}

/// Recover the Oxford-style problem-sheet title (the class puts it in a fancyhdr
/// header we don't render) from `\course`/`\sheetnumber`/`\oxfordterm`/
/// `\sheettitle`, injecting a centred block after `\begin{document}`.
fn inject_exam_title(source: &str) -> String {
    let val = |cmd: &str| braced_arg_after(source, &format!("\\{cmd}")).unwrap_or_default();
    let (course, num, term, title) = (
        val("course"),
        val("sheetnumber"),
        val("oxfordterm"),
        val("sheettitle"),
    );
    if course.trim().is_empty() && title.trim().is_empty() {
        return source.to_string();
    }
    let mut lines: Vec<String> = Vec::new();
    if !course.trim().is_empty() {
        lines.push(format!("{{\\Large\\bfseries {}}}", course.trim()));
    }
    let mut sheet = if num.trim().is_empty() {
        String::new()
    } else {
        format!("Sheet {}", num.trim())
    };
    if !term.trim().is_empty() {
        sheet = if sheet.is_empty() {
            term.trim().to_string()
        } else {
            format!("{sheet} --- {}", term.trim())
        };
    }
    if !sheet.is_empty() {
        lines.push(sheet);
    }
    if !title.trim().is_empty() {
        lines.push(title.trim().to_string());
    }
    let block = format!(
        "\n\\begin{{center}}\n{}\n\\end{{center}}\n",
        lines.join("\\\\")
    );
    source.replacen(
        "\\begin{document}",
        &format!("\\begin{{document}}{block}"),
        1,
    )
}

/// Convert a plain-TeX `\halign` system inside `\[ … \]` into an `array`. The
/// whole display (including `\centerline{\hbox{\vbox{\openup…\jot …}}}`) is
/// replaced, so those box/glue primitives never reach the parser.
fn rewrite_halign(source: &str) -> String {
    let s: Vec<char> = source.chars().collect();
    let n = s.len();
    let mut out = String::with_capacity(source.len());
    let mut i = 0;
    while i < n {
        if i + 1 < n && s[i] == '\\' && s[i + 1] == '[' {
            // find the closing \]
            if let Some(end) = find_seq(&s, i + 2, &['\\', ']']) {
                let inner: String = s[i + 2..end].iter().collect();
                if inner.contains("\\halign") {
                    out.push_str("\\[");
                    out.push_str(&halign_to_array(&inner));
                    out.push_str("\\]");
                    i = end + 2;
                    continue;
                }
            }
        }
        out.push(s[i]);
        i += 1;
    }
    out
}

/// The `\halign{ template \cr rows… }` body → an `array` (template dropped, rows
/// split on `\cr`, cells on `&`).
fn halign_to_array(inner: &str) -> String {
    let s: Vec<char> = inner.chars().collect();
    let Some(h) = find_seq(&s, 0, &['\\', 'h', 'a', 'l', 'i', 'g', 'n']) else {
        return inner.to_string();
    };
    // the { … } group after \halign
    let (body, _) = read_braced(&s, h + "\\halign".len());
    // template precedes the first \cr; the rest are data rows
    let data = match body.find("\\cr") {
        Some(pos) => &body[pos + 3..],
        None => &body,
    };
    let rows: Vec<&str> = data
        .split("\\cr")
        .map(str::trim)
        .filter(|r| !r.is_empty())
        .collect();
    if rows.is_empty() {
        return inner.to_string();
    }
    let ncols = rows
        .iter()
        .map(|r| r.matches('&').count() + 1)
        .max()
        .unwrap_or(1);
    format!(
        "\\begin{{array}}{{{}}}{}\\end{{array}}",
        "c".repeat(ncols),
        rows.join(" \\\\ ")
    )
}

/// TikZ drawing primitives — their presence means a real diagram (left for the
/// image path, not text recovery).
fn has_draw_primitive(body: &str) -> bool {
    for kw in [
        "\\draw",
        "\\fill",
        "\\filldraw",
        "\\path",
        "\\clip",
        "\\shade",
        "\\shadedraw",
        "\\pgf",
        "\\coordinate",
        "\\foreach",
        "\\pic",
    ] {
        if body.contains(kw) {
            return true;
        }
    }
    false
}

/// Recover content from the "cheatsheet" TikZ idiom — a `tikzpicture` that is
/// just `\node{…minipage…}` content boxes plus a `\node[fancytitle]{Title}`,
/// with no drawing. A `title`-styled node becomes a `\subsection*`; the rest is
/// emitted inline. Pictures with drawing primitives are left untouched.
fn recover_tikz_boxes(source: &str) -> String {
    let begin = "\\begin{tikzpicture}";
    let end = "\\end{tikzpicture}";
    let mut out = String::with_capacity(source.len());
    let mut rest = source;
    while let Some(b) = rest.find(begin) {
        out.push_str(&rest[..b]);
        let after_begin = b + begin.len();
        let Some(rel) = rest[after_begin..].find(end) else {
            out.push_str(&rest[b..]);
            return out;
        };
        let body = &rest[after_begin..after_begin + rel];
        let whole = &rest[b..after_begin + rel + end.len()];
        // only recover the content-box idiom (a minipage or a title node) with no drawing
        let is_box_idiom = (body.contains("\\begin{minipage}")
            || body.to_lowercase().contains("title"))
            && !has_draw_primitive(body);
        if is_box_idiom {
            out.push_str(&extract_tikz_nodes(body));
        } else {
            out.push_str(whole);
        }
        rest = &rest[after_begin + rel + end.len()..];
    }
    out.push_str(rest);
    out
}

/// Emit each `\node[style] … {content}`'s content — a `title`-styled node as a
/// `\subsection*`, the rest inline.
fn extract_tikz_nodes(body: &str) -> String {
    let s: Vec<char> = body.chars().collect();
    let n = s.len();
    let mut out = String::new();
    let mut i = 0;
    while i < n {
        if s[i] == '\\' {
            let (name, after) = read_command_name(&s, i);
            if name == "node" {
                let (style, after_style) = read_optional(&s, after);
                // skip to the first { … } content group (past coords like (a) at (0,0))
                let mut j = after_style;
                while j < n && s[j] != '{' {
                    j += 1;
                }
                if j >= n {
                    i = after_style;
                    continue;
                }
                let (content, after_content) = read_braced(&s, j);
                if style.to_lowercase().contains("title") {
                    let t = content.trim();
                    if !t.is_empty() {
                        out.push_str(&format!("\n\n\\subsection*{{{t}}}\n"));
                    }
                } else {
                    out.push_str(&content);
                    out.push('\n');
                }
                i = after_content;
                continue;
            }
            i = after;
            continue;
        }
        i += 1;
    }
    out
}

/// Find the first occurrence of `seq` in `s` at or after `from`; returns its
/// start index.
fn find_seq(s: &[char], from: usize, seq: &[char]) -> Option<usize> {
    if seq.is_empty() || s.len() < seq.len() {
        return None;
    }
    let mut i = from;
    while i + seq.len() <= s.len() {
        if s[i..i + seq.len()] == *seq {
            return Some(i);
        }
        i += 1;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn halign_display_becomes_array() {
        let src = r"\[\centerline{\hbox{\vbox{\openup1.5\jot\halign{\hss$#$\hss&&$#$\cr x&=&5\cr y&=&7\cr}}}}\]";
        let out = rewrite_halign(src);
        assert!(!out.contains("\\halign") && !out.contains("\\centerline"));
        assert!(out.contains("\\begin{array}") && out.contains("\\end{array}"));
        assert!(out.contains('x') && out.contains('5') && out.contains('7'));
    }

    #[test]
    fn exam_markers_and_solutions() {
        let src = concat!(
            "\\begin{questions}\\question q1",
            "\\begin{parts}\\part[7] a\\part b\\end{parts}",
            "\\begin{solution}secret\\end{solution}\\end{questions}"
        );
        let out = rewrite_exam_class(src);
        assert!(!out.contains("\\part") && !out.contains("\\question"));
        assert!(!out.contains("[7]") && !out.contains("secret"));
        assert_eq!(out.matches("\\item").count(), 3); // question + 2 parts
        assert!(out.contains("\\begin{enumerate}"));
    }

    #[test]
    fn title_block_recovered() {
        let src = concat!(
            "\\course{Impossible Maths I}\\sheetnumber{3}\\oxfordterm{MT18}",
            "\\sheettitle{First topic questions}\\begin{document}body\\end{document}"
        );
        let out = inject_exam_title(src);
        assert!(out.contains("\\begin{center}"));
        assert!(out.contains("Impossible Maths I"));
        assert!(out.contains("Sheet 3") && out.contains("MT18"));
        assert!(out.contains("First topic questions"));
    }
}
