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
            "mathrm" | "mathbf" | "text" | "operatorname" | "mathsf" | "mathtt" => {
                // upright content (styling nuances are a later milestone)
                Node::Upright(flatten_text(&self.parse_atom()))
            }
            "left" => self.parse_delim(),
            "right" => Node::Run(String::new()), // stray \right (parse_delim owns it)
            _ => {
                if let Some((op, over_under)) = symbols::nary(&name) {
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
