//! User-macro expansion — `\newcommand` / `\renewcommand` / `\providecommand`
//! and `\def`. A bounded, pure scanner (not a TeX engine): it collects the
//! definitions, strips them, and substitutes calls (with `#1..#9` arguments and
//! one optional argument) before the document is parsed — mirroring the Python
//! `tex2word.frontend.macros`. It handles the braced form, the unbraced-name
//! form, and the unbraced single-token body idiom (`\newcommand\CAL\mathcal`).

use std::collections::HashMap;

struct Macro {
    nargs: usize,
    /// default for the (single) optional argument, if the macro takes one.
    default: Option<String>,
    body: String,
}

const MAX_DEPTH: usize = 32;

/// Collect user macros and expand every call in `source`.
pub fn expand_macros(source: &str) -> String {
    let (macros, stripped) = collect(source);
    expand(&stripped, &macros, 0)
}

fn is_letter(c: char) -> bool {
    c.is_ascii_alphabetic()
}

/// From a `\` at `i`, read the control-sequence name; returns (name, index-after).
/// A control *word* is a run of letters; a control *symbol* is one character.
/// Spaces are *not* gobbled (so a non-macro CS keeps its trailing space).
fn read_cs(s: &[char], i: usize) -> (String, usize) {
    let mut j = i + 1;
    if j < s.len() && is_letter(s[j]) {
        let start = j;
        while j < s.len() && is_letter(s[j]) {
            j += 1;
        }
        (s[start..j].iter().collect(), j)
    } else if j < s.len() {
        (s[j].to_string(), j + 1)
    } else {
        (String::new(), j)
    }
}

fn skip_ws(s: &[char], mut i: usize) -> usize {
    while i < s.len() && (s[i] == ' ' || s[i] == '\n' || s[i] == '\t' || s[i] == '\r') {
        i += 1;
    }
    i
}

/// Read a balanced `{ … }` at/after `i` (skipping leading ws); (inner, after).
/// Returns None-ish (empty, i unchanged) if no `{` is present.
fn read_group(s: &[char], i: usize) -> (String, usize, bool) {
    let j = skip_ws(s, i);
    if j >= s.len() || s[j] != '{' {
        return (String::new(), i, false);
    }
    let mut depth = 0;
    let start = j + 1;
    let mut k = j;
    while k < s.len() {
        match s[k] {
            '\\' => {
                k += 2;
                continue;
            }
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return (s[start..k].iter().collect(), k + 1, true);
                }
            }
            _ => {}
        }
        k += 1;
    }
    (s[start..].iter().collect(), s.len(), true)
}

/// Read an undelimited argument: a `{group}`, a `\cs`, or a single char.
fn read_arg(s: &[char], i: usize) -> (String, usize) {
    let j = skip_ws(s, i);
    if j >= s.len() {
        return (String::new(), j);
    }
    if s[j] == '{' {
        let (g, after, _) = read_group(s, j);
        return (g, after);
    }
    if s[j] == '\\' {
        let (name, after) = read_cs(s, j);
        return (format!("\\{name}"), after);
    }
    (s[j].to_string(), j + 1)
}

/// Read an optional `[ … ]` at/after `i`; (Some(inner)|None, index-after).
fn read_optional(s: &[char], i: usize) -> (Option<String>, usize) {
    let j = skip_ws(s, i);
    if j < s.len() && s[j] == '[' {
        let mut k = j + 1;
        while k < s.len() && s[k] != ']' {
            k += 1;
        }
        let inner: String = s[j + 1..k].iter().collect();
        return (Some(inner), (k + 1).min(s.len()));
    }
    (None, i)
}

/// Read the defined name after a `\newcommand`-family macro at `i`:
/// either `{\name}` or a bare `\name`. Returns (name-without-backslash, after).
fn read_defined_name(s: &[char], i: usize) -> Option<(String, usize)> {
    let j = skip_ws(s, i);
    if j >= s.len() {
        return None;
    }
    if s[j] == '{' {
        let (inner, after, _) = read_group(s, j);
        let name = inner.trim().trim_start_matches('\\').to_string();
        if name.is_empty() {
            None
        } else {
            Some((name, after))
        }
    } else if s[j] == '\\' {
        let (name, after) = read_cs(s, j);
        Some((name, after))
    } else {
        None
    }
}

/// Scan `source`, recording macro definitions and returning the source with the
/// definitions removed.
fn collect(source: &str) -> (HashMap<String, Macro>, String) {
    let s: Vec<char> = source.chars().collect();
    let n = s.len();
    let mut macros: HashMap<String, Macro> = HashMap::new();
    let mut out = String::new();
    let mut i = 0;
    while i < n {
        if s[i] == '\\' {
            let (cmd, after) = read_cs(&s, i);
            match cmd.as_str() {
                "newcommand" | "renewcommand" | "providecommand" | "DeclareRobustCommand" => {
                    if let Some(end) = parse_newcommand(&s, after, &mut macros) {
                        i = end;
                        continue;
                    }
                }
                "def" => {
                    if let Some(end) = parse_def(&s, after, &mut macros) {
                        i = end;
                        continue;
                    }
                }
                _ => {}
            }
            out.extend(&s[i..after]);
            i = after;
            continue;
        }
        out.push(s[i]);
        i += 1;
    }
    (macros, out)
}

/// `\newcommand{\name}[nargs][default]{body}` (and unbraced-name / unbraced-body).
fn parse_newcommand(s: &[char], i: usize, macros: &mut HashMap<String, Macro>) -> Option<usize> {
    // optional leading `*` (\newcommand*)
    let i = {
        let j = skip_ws(s, i);
        if j < s.len() && s[j] == '*' {
            j + 1
        } else {
            i
        }
    };
    let (name, mut j) = read_defined_name(s, i)?;

    let mut nargs = 0;
    let mut default = None;
    // [nargs]
    let (n_opt, nj) = read_optional(s, j);
    if let Some(nstr) = n_opt {
        nargs = nstr.trim().parse().ok()?;
        j = nj;
        // [default] (makes the first arg optional)
        let (d_opt, dj) = read_optional(s, j);
        if let Some(d) = d_opt {
            default = Some(d);
            j = dj;
        }
    }

    // body: a braced group, or an unbraced single control-sequence/char.
    let k = skip_ws(s, j);
    if k < s.len() && s[k] == '{' {
        let (body, after, _) = read_group(s, k);
        macros.insert(
            name,
            Macro {
                nargs,
                default,
                body,
            },
        );
        Some(after)
    } else if k < s.len() && nargs == 0 {
        // unbraced single-token body: \newcommand\CAL\mathcal
        let (arg, after) = read_arg(s, k);
        macros.insert(
            name,
            Macro {
                nargs: 0,
                default: None,
                body: arg,
            },
        );
        Some(after)
    } else {
        None
    }
}

/// `\def\name<params>{body}` — count `#n` in the parameter text before `{`.
fn parse_def(s: &[char], i: usize, macros: &mut HashMap<String, Macro>) -> Option<usize> {
    let j = skip_ws(s, i);
    if j >= s.len() || s[j] != '\\' {
        return None;
    }
    let (name, mut k) = read_cs(s, j);
    // parameter text up to the body `{`
    let mut nargs = 0;
    while k < s.len() && s[k] != '{' {
        if s[k] == '#' {
            nargs += 1;
            k += 1;
        }
        k += 1;
    }
    if k >= s.len() || s[k] != '{' {
        return None;
    }
    let (body, after, _) = read_group(s, k);
    macros.insert(
        name,
        Macro {
            nargs,
            default: None,
            body,
        },
    );
    Some(after)
}

/// Expand macro calls in `source` (bounded recursion).
fn expand(source: &str, macros: &HashMap<String, Macro>, depth: usize) -> String {
    if depth >= MAX_DEPTH || macros.is_empty() {
        return source.to_string();
    }
    let s: Vec<char> = source.chars().collect();
    let n = s.len();
    let mut out = String::new();
    let mut i = 0;
    let mut changed = false;
    while i < n {
        if s[i] == '\\' {
            let (name, after) = read_cs(&s, i);
            if let Some(m) = macros.get(&name) {
                let mut j = after;
                let mut args: Vec<String> = Vec::with_capacity(m.nargs);
                let mut remaining = m.nargs;
                if let Some(def) = &m.default {
                    let (opt, nj) = read_optional(&s, j);
                    args.push(opt.unwrap_or_else(|| def.clone()));
                    j = nj;
                    remaining = remaining.saturating_sub(1);
                }
                for _ in 0..remaining {
                    let (a, nj) = read_arg(&s, j);
                    args.push(a);
                    j = nj;
                }
                let mut body = m.body.clone();
                for (k, a) in args.iter().enumerate() {
                    body = body.replace(&format!("#{}", k + 1), a);
                }
                out.push_str(&body);
                i = j;
                changed = true;
                continue;
            }
            out.extend(&s[i..after]);
            i = after;
            continue;
        }
        out.push(s[i]);
        i += 1;
    }
    if changed {
        expand(&out, macros, depth + 1)
    } else {
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newcommand_with_args() {
        assert_eq!(
            expand_macros(r"\newcommand{\greet}[1]{Hello #1!}\greet{World}"),
            "Hello World!"
        );
    }

    #[test]
    fn optional_arg_default_and_override() {
        assert_eq!(expand_macros(r"\newcommand{\x}[2][D]{#1-#2}\x{b}"), "D-b");
        assert_eq!(
            expand_macros(r"\newcommand{\x}[2][D]{#1-#2}\x[a]{b}"),
            "a-b"
        );
    }

    #[test]
    fn unbraced_name_and_single_token_body() {
        // \newcommand\BE\textbf ; \BE{x} -> \textbf{x}
        assert_eq!(
            expand_macros(r"\newcommand\BE\textbf \BE{x}"),
            " \\textbf{x}"
        );
    }

    #[test]
    fn def_with_params() {
        assert_eq!(expand_macros(r"\def\pair#1#2{(#1,#2)}\pair ab"), "(a,b)");
    }

    #[test]
    fn nested_macro_expansion() {
        assert_eq!(
            expand_macros(r"\newcommand{\a}{A}\newcommand{\b}{[\a]}\b"),
            "[A]"
        );
    }

    #[test]
    fn definitions_are_stripped() {
        let out = expand_macros(r"before\newcommand{\x}{X}after \x");
        assert_eq!(out, "beforeafter X");
    }
}
