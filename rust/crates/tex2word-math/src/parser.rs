//! LaTeX math -> a small math AST (recursive-descent, char-based).
//!
//! Covers (this milestone): runs, groups `{…}`, `\frac`/`\dfrac`/`\tfrac`,
//! `^`/`_` scripts (either order), `\sqrt` and `\sqrt[n]`, symbol commands
//! (Greek/operators via [`crate::symbols`]) and upright function names.

use crate::symbols;

#[derive(Debug, Clone, PartialEq)]
pub enum Node {
    /// A literal run of (math-italic by default) text.
    Run(String),
    /// An upright run (function names, `\mathrm`-like).
    Upright(String),
    /// A sequence of nodes.
    Row(Vec<Node>),
    /// A fraction: numerator over denominator.
    Frac(Box<Node>, Box<Node>),
    Sup(Box<Node>, Box<Node>),
    Sub(Box<Node>, Box<Node>),
    SubSup(Box<Node>, Box<Node>, Box<Node>),
    /// A square root.
    Sqrt(Box<Node>),
    /// An nth root: (index, radicand).
    Root(Box<Node>, Box<Node>),
    /// A big/n-ary operator (∑/∫/∏/…) with optional lower/upper limits and an
    /// operand. `over_under` places the limits above/below (sums) vs. as scripts
    /// (integrals).
    Nary {
        op: String,
        sub: Option<Box<Node>>,
        sup: Option<Box<Node>>,
        body: Box<Node>,
        over_under: bool,
    },
    /// A `\left<d> … \right<d>` delimited group (empty delim = `\left.`).
    Delim {
        open: String,
        close: String,
        body: Box<Node>,
    },
    /// A math accent (`\hat`/`\vec`/`\tilde`/…): a combining char over the base.
    Accent {
        chr: char,
        base: Box<Node>,
    },
    /// An over/under bar (`\overline`/`\underline`).
    Bar {
        top: bool,
        base: Box<Node>,
    },
    /// A matrix / `aligned` / `cases` grid (rows of cells), optionally wrapped in
    /// delimiters (`pmatrix` → `()`, `bmatrix` → `[]`, `cases` → `{`).
    Matrix {
        rows: Vec<Vec<Node>>,
        delim: Option<(String, String)>,
    },
    /// A styled run: an OMML `m:sty` value (`b`/`i`/`bi`/`p`) over literal text.
    /// `\mathbf` → `b`; `\mathit` → `i`.
    Styled {
        sty: &'static str,
        text: String,
    },
    /// A binomial coefficient (`\binom{n}{k}`): parentheses over a bar-less
    /// fraction.
    Binom(Box<Node>, Box<Node>),
}

/// Parse a LaTeX math string into a [`Node::Row`].
pub fn parse(latex: &str) -> Node {
    let mut p = Parser {
        s: latex.chars().collect(),
        i: 0,
    };
    p.parse_row()
}

struct Parser {
    s: Vec<char>,
    i: usize,
}

impl Parser {
    fn peek(&self) -> Option<char> {
        self.s.get(self.i).copied()
    }

    fn skip_space(&mut self) {
        while matches!(self.peek(), Some(' ' | '\n' | '\t' | '\r')) {
            self.i += 1;
        }
    }

    fn parse_row(&mut self) -> Node {
        let mut items: Vec<Node> = Vec::new();
        loop {
            self.skip_space();
            match self.peek() {
                None | Some('}') => break,
                _ => {}
            }
            let atom = self.parse_atom();
            let atom = self.maybe_scripts(atom);
            push_merge(&mut items, atom);
        }
        Node::Row(items)
    }

    /// A single atom: a `{…}` group, a command, or one character.
    fn parse_atom(&mut self) -> Node {
        match self.peek() {
            Some('{') => {
                self.i += 1;
                let r = self.parse_row();
                if self.peek() == Some('}') {
                    self.i += 1;
                }
                r
            }
            Some('\\') => self.parse_command(),
            Some(c) => {
                self.i += 1;
                Node::Run(c.to_string())
            }
            None => Node::Run(String::new()),
        }
    }

    /// After an atom, attach any `^`/`_` scripts (in either order).
    fn maybe_scripts(&mut self, base: Node) -> Node {
        let mut sub: Option<Box<Node>> = None;
        let mut sup: Option<Box<Node>> = None;
        loop {
            self.skip_space();
            match self.peek() {
                Some('^') => {
                    self.i += 1;
                    self.skip_space();
                    sup = Some(Box::new(self.parse_atom()));
                }
                Some('_') => {
                    self.i += 1;
                    self.skip_space();
                    sub = Some(Box::new(self.parse_atom()));
                }
                _ => break,
            }
        }
        match (sub, sup) {
            (None, None) => base,
            (Some(sb), None) => Node::Sub(Box::new(base), sb),
            (None, Some(sp)) => Node::Sup(Box::new(base), sp),
            (Some(sb), Some(sp)) => Node::SubSup(Box::new(base), sb, sp),
        }
    }

    /// Read a command name (letters), or a single non-letter control symbol.
    fn read_name(&mut self) -> String {
        self.i += 1; // consume '\'
        match self.peek() {
            Some(c) if c.is_ascii_alphabetic() => {
                let start = self.i;
                while matches!(self.peek(), Some(c) if c.is_ascii_alphabetic()) {
                    self.i += 1;
                }
                self.s[start..self.i].iter().collect()
            }
            Some(c) => {
                self.i += 1;
                c.to_string()
            }
            None => String::new(),
        }
    }

    fn parse_command(&mut self) -> Node {
        let name = self.read_name();
        match name.as_str() {
            "frac" | "dfrac" | "tfrac" | "cfrac" => {
                let num = self.parse_atom();
                let den = self.parse_atom();
                Node::Frac(Box::new(num), Box::new(den))
            }
            "sqrt" => {
                self.skip_space();
                if self.peek() == Some('[') {
                    let idx = self.read_bracket();
                    let rad = self.parse_atom();
                    Node::Root(Box::new(idx), Box::new(rad))
                } else {
                    Node::Sqrt(Box::new(self.parse_atom()))
                }
            }
            "mathrm" | "text" | "operatorname" | "mathsf" | "mathtt" => {
                // upright content (font nuances beyond upright are not modelled)
                Node::Upright(flatten_text(&self.parse_atom()))
            }
            "mathbf" | "boldsymbol" | "bm" => Node::Styled {
                sty: "b",
                text: flatten_text(&self.parse_atom()),
            },
            "mathit" => Node::Run(flatten_text(&self.parse_atom())), // italic = default
            // math-class wrappers only affect spacing -> render content transparently
            "mathbin" | "mathrel" | "mathop" | "mathord" | "mathopen" | "mathclose"
            | "mathpunct" | "mathinner" => self.parse_atom(),
            // script/blackboard/fraktur alphabets -> Unicode math-alphanumerics
            "mathbb" | "mathcal" | "mathscr" | "mathfrak" => {
                Node::Run(symbols::alphabet(&name, &flatten_text(&self.parse_atom())))
            }
            "binom" | "dbinom" | "tbinom" => {
                let n = self.parse_atom();
                let k = self.parse_atom();
                Node::Binom(Box::new(n), Box::new(k))
            }
            "pmod" => Node::Row(vec![
                Node::Run(" (".into()),
                Node::Upright("mod".into()),
                Node::Run(" ".into()),
                self.parse_atom(),
                Node::Run(")".into()),
            ]),
            "bmod" => Node::Upright("mod".into()),
            "left" => self.parse_delim(),
            "right" => Node::Run(String::new()), // stray \right (parse_delim owns it)
            "begin" => self.parse_environment(),
            "end" => {
                let _ = self.read_raw_group(); // stray \end{env}: consume its name
                Node::Run(String::new())
            }
            "overline" => Node::Bar {
                top: true,
                base: Box::new(self.parse_atom()),
            },
            "underline" => Node::Bar {
                top: false,
                base: Box::new(self.parse_atom()),
            },
            _ => {
                if let Some(chr) = math_accent(&name) {
                    Node::Accent {
                        chr,
                        base: Box::new(self.parse_atom()),
                    }
                } else if let Some((op, over_under)) = symbols::nary(&name) {
                    let (sub, sup) = self.parse_nary_limits();
                    let body = self.parse_operand();
                    Node::Nary {
                        op: op.to_string(),
                        sub,
                        sup,
                        body: Box::new(body),
                        over_under,
                    }
                } else if let Some(f) = symbols::function_name(&name) {
                    Node::Upright(f.to_string())
                } else if let Some(sym) = symbols::symbol(&name) {
                    Node::Run(sym.to_string())
                } else {
                    Node::Run(String::new()) // unknown command: drop
                }
            }
        }
    }

    /// Read an n-ary operator's `_lower`/`^upper` limits (in either order).
    fn parse_nary_limits(&mut self) -> (Option<Box<Node>>, Option<Box<Node>>) {
        let mut sub = None;
        let mut sup = None;
        loop {
            self.skip_space();
            match self.peek() {
                Some('_') => {
                    self.i += 1;
                    self.skip_space();
                    sub = Some(Box::new(self.parse_atom()));
                }
                Some('^') => {
                    self.i += 1;
                    self.skip_space();
                    sup = Some(Box::new(self.parse_atom()));
                }
                _ => break,
            }
        }
        (sub, sup)
    }

    /// The operand of an n-ary operator: the next atom (with its own scripts).
    /// Kept to a single atom so a trailing `+ c` / `=` is not swallowed.
    fn parse_operand(&mut self) -> Node {
        self.skip_space();
        match self.peek() {
            None | Some('}') => Node::Row(Vec::new()),
            _ => {
                let a = self.parse_atom();
                self.maybe_scripts(a)
            }
        }
    }

    /// True if a complete `\name` control word begins at the cursor.
    fn at_command(&self, name: &str) -> bool {
        if self.peek() != Some('\\') {
            return false;
        }
        let mut k = self.i + 1;
        for pc in name.chars() {
            if self.s.get(k) != Some(&pc) {
                return false;
            }
            k += 1;
        }
        !matches!(self.s.get(k), Some(c) if c.is_ascii_alphabetic())
    }

    /// Parse `\left<open> … \right<close>` (the `\left` is already consumed).
    fn parse_delim(&mut self) -> Node {
        let open = self.read_delim();
        let start = self.i;
        let mut depth = 1;
        while self.i < self.s.len() {
            if self.at_command("left") {
                depth += 1;
                self.i += 5; // "\left"
                continue;
            }
            if self.at_command("right") {
                depth -= 1;
                if depth == 0 {
                    let inner: String = self.s[start..self.i].iter().collect();
                    self.i += 6; // "\right"
                    let close = self.read_delim();
                    return Node::Delim {
                        open,
                        close,
                        body: Box::new(parse(&inner)),
                    };
                }
                self.i += 6;
                continue;
            }
            self.i += 1;
        }
        // no matching \right: take the rest as the body
        let inner: String = self.s[start..].iter().collect();
        self.i = self.s.len();
        Node::Delim {
            open,
            close: String::new(),
            body: Box::new(parse(&inner)),
        }
    }

    /// Read a balanced `{ … }` group's inner text and advance past it.
    fn read_raw_group(&mut self) -> String {
        self.skip_space();
        if self.peek() != Some('{') {
            return String::new();
        }
        self.i += 1;
        let start = self.i;
        let mut depth = 1;
        while self.i < self.s.len() {
            match self.s[self.i] {
                '\\' => {
                    self.i += 2;
                    continue;
                }
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        let inner: String = self.s[start..self.i].iter().collect();
                        self.i += 1;
                        return inner;
                    }
                }
                _ => {}
            }
            self.i += 1;
        }
        self.s[start..].iter().collect()
    }

    fn matches(&self, pat: &[char]) -> bool {
        self.i + pat.len() <= self.s.len() && self.s[self.i..self.i + pat.len()] == *pat
    }

    /// Parse `\begin{env} … \end{env}` (the `\begin` is already consumed).
    fn parse_environment(&mut self) -> Node {
        let raw = self.read_raw_group();
        let env = raw.trim().trim_end_matches('*').to_string();
        // array/alignat carry a column-spec argument we don't need.
        if env == "array" || env == "alignat" {
            self.skip_space();
            if self.peek() == Some('{') {
                let _ = self.read_raw_group();
            }
        }
        let body = self.read_env_body(&env);
        Node::Matrix {
            rows: split_matrix(&body),
            delim: matrix_delim(&env),
        }
    }

    /// Read the body up to the matching `\end{env}` (nesting-aware).
    fn read_env_body(&mut self, env: &str) -> String {
        let bpat: Vec<char> = format!("\\begin{{{env}}}").chars().collect();
        let epat: Vec<char> = format!("\\end{{{env}}}").chars().collect();
        let start = self.i;
        let mut depth = 1;
        while self.i < self.s.len() {
            if self.matches(&bpat) {
                depth += 1;
                self.i += bpat.len();
                continue;
            }
            if self.matches(&epat) {
                depth -= 1;
                if depth == 0 {
                    let inner: String = self.s[start..self.i].iter().collect();
                    self.i += epat.len();
                    return inner;
                }
                self.i += epat.len();
                continue;
            }
            self.i += 1;
        }
        let inner: String = self.s[start..].iter().collect();
        self.i = self.s.len();
        inner
    }

    /// Read a delimiter after `\left`/`\right`: a char, a `\cmd`, or `.` (none).
    fn read_delim(&mut self) -> String {
        self.skip_space();
        match self.peek() {
            Some('\\') => {
                let name = self.read_name();
                delim_symbol(&name).to_string()
            }
            Some('.') => {
                self.i += 1;
                String::new()
            }
            Some(c) => {
                self.i += 1;
                c.to_string()
            }
            None => String::new(),
        }
    }

    /// Read a `[ … ]` optional group and parse its content as math.
    fn read_bracket(&mut self) -> Node {
        self.i += 1; // consume '['
        let start = self.i;
        while self.peek().is_some() && self.peek() != Some(']') {
            self.i += 1;
        }
        let inner: String = self.s[start..self.i].iter().collect();
        if self.peek() == Some(']') {
            self.i += 1;
        }
        parse(&inner)
    }
}

/// Drop empty runs and merge adjacent plain runs into one.
fn push_merge(items: &mut Vec<Node>, atom: Node) {
    if let Node::Run(s) = &atom {
        if s.is_empty() {
            return;
        }
        if let Some(Node::Run(prev)) = items.last_mut() {
            prev.push_str(s);
            return;
        }
    }
    items.push(atom);
}

/// Flatten a node to its plain text (for `\mathrm`/`\text` upright content).
fn flatten_text(node: &Node) -> String {
    match node {
        Node::Run(s) | Node::Upright(s) => s.clone(),
        Node::Row(items) => items.iter().map(flatten_text).collect(),
        _ => String::new(),
    }
}

/// Split a matrix/aligned body into rows (top-level `\\`) of cells (top-level
/// `&`), parsing each cell as math. Trailing empty rows (from a final `\\`) drop.
fn split_matrix(body: &str) -> Vec<Vec<Node>> {
    let s: Vec<char> = body.chars().collect();
    let n = s.len();
    let mut rows: Vec<Vec<String>> = vec![vec![String::new()]];
    let mut depth = 0;
    let mut i = 0;
    while i < n {
        let c = s[i];
        if c == '\\' {
            if i + 1 < n && s[i + 1] == '\\' {
                // row break; skip an optional [spacing] argument
                let mut j = i + 2;
                while j < n && matches!(s[j], ' ' | '\n' | '\t' | '\r') {
                    j += 1;
                }
                if j < n && s[j] == '[' {
                    while j < n && s[j] != ']' {
                        j += 1;
                    }
                    if j < n {
                        j += 1;
                    }
                }
                rows.push(vec![String::new()]);
                i = j;
                continue;
            }
            // a command: copy `\` + its name so an `&`/`\\` inside doesn't split
            let start = i;
            let mut j = i + 1;
            if j < n && s[j].is_ascii_alphabetic() {
                while j < n && s[j].is_ascii_alphabetic() {
                    j += 1;
                }
            } else if j < n {
                j += 1;
            }
            let cmd: String = s[start + 1..j].iter().collect();
            if cmd == "cr" {
                // plain-TeX row separator, equivalent to `\\`
                rows.push(vec![String::new()]);
                i = j;
                continue;
            }
            rows.last_mut()
                .unwrap()
                .last_mut()
                .unwrap()
                .extend(&s[start..j]);
            i = j;
            continue;
        }
        match c {
            '{' => {
                depth += 1;
                rows.last_mut().unwrap().last_mut().unwrap().push(c);
            }
            '}' => {
                depth -= 1;
                rows.last_mut().unwrap().last_mut().unwrap().push(c);
            }
            '&' if depth == 0 => rows.last_mut().unwrap().push(String::new()),
            _ => rows.last_mut().unwrap().last_mut().unwrap().push(c),
        }
        i += 1;
    }
    rows.into_iter()
        .filter(|row| row.iter().any(|cell| !cell.trim().is_empty()))
        .map(|row| row.iter().map(|cell| parse(cell.trim())).collect())
        .collect()
}

/// Delimiters that wrap a given matrix environment (`None` = bare `m:m`).
fn matrix_delim(env: &str) -> Option<(String, String)> {
    let (o, c) = match env {
        "pmatrix" => ("(", ")"),
        "bmatrix" => ("[", "]"),
        "Bmatrix" => ("{", "}"),
        "vmatrix" => ("|", "|"),
        "Vmatrix" => ("‖", "‖"),
        "cases" => ("{", ""),
        _ => return None, // matrix, smallmatrix, array, aligned, align, gathered…
    };
    Some((o.to_string(), c.to_string()))
}

/// Map a math accent command to its combining character (`m:acc` chr).
fn math_accent(name: &str) -> Option<char> {
    Some(match name {
        "hat" | "widehat" => '\u{0302}',
        "tilde" | "widetilde" => '\u{0303}',
        "bar" => '\u{0304}',
        "vec" | "overrightarrow" => '\u{20D7}',
        "dot" => '\u{0307}',
        "ddot" => '\u{0308}',
        "dddot" => '\u{20DB}',
        "check" => '\u{030C}',
        "breve" => '\u{0306}',
        "acute" => '\u{0301}',
        "grave" => '\u{0300}',
        "mathring" => '\u{030A}',
        _ => return None,
    })
}

/// Map a `\left`/`\right` delimiter command name to its glyph.
fn delim_symbol(name: &str) -> &'static str {
    match name {
        "{" | "lbrace" => "{",
        "}" | "rbrace" => "}",
        "|" | "Vert" | "lVert" | "rVert" => "‖",
        "langle" => "⟨",
        "rangle" => "⟩",
        "lceil" => "⌈",
        "rceil" => "⌉",
        "lfloor" => "⌊",
        "rfloor" => "⌋",
        "backslash" => "\\",
        "uparrow" => "↑",
        "downarrow" => "↓",
        other => symbols::symbol(other).unwrap_or(""),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scripts_either_order() {
        assert_eq!(
            parse("x^2"),
            Node::Row(vec![Node::Sup(
                Box::new(Node::Run("x".into())),
                Box::new(Node::Run("2".into()))
            )])
        );
        // x_i^n and x^n_i both -> SubSup
        assert!(matches!(
            &parse("x_i^n"),
            Node::Row(v) if matches!(v[0], Node::SubSup(..))
        ));
        assert!(matches!(
            &parse("x^n_i"),
            Node::Row(v) if matches!(v[0], Node::SubSup(..))
        ));
    }

    #[test]
    fn frac_and_sqrt_and_root() {
        assert!(matches!(&parse(r"\frac{1}{2}"), Node::Row(v) if matches!(v[0], Node::Frac(..))));
        assert!(matches!(&parse(r"\sqrt{2}"), Node::Row(v) if matches!(v[0], Node::Sqrt(..))));
        assert!(matches!(&parse(r"\sqrt[3]{x}"), Node::Row(v) if matches!(v[0], Node::Root(..))));
    }

    #[test]
    fn symbols_and_functions() {
        assert_eq!(parse(r"\alpha"), Node::Row(vec![Node::Run("α".into())]));
        assert_eq!(parse(r"\sin"), Node::Row(vec![Node::Upright("sin".into())]));
    }

    #[test]
    fn adjacent_runs_merge() {
        assert_eq!(parse("abc"), Node::Row(vec![Node::Run("abc".into())]));
    }
}
