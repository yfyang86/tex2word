//! LaTeX math command -> Unicode symbol table (a subset of the Python
//! `mathml/symbols.py`): Greek letters, operators, relations, arrows, and set
//! notation. Grows as the math engine matures.

/// Map a math command name (without the leading backslash) to its Unicode text.
pub fn symbol(name: &str) -> Option<&'static str> {
    Some(match name {
        // ---- Greek (lowercase) ----
        "alpha" => "α",
        "beta" => "β",
        "gamma" => "γ",
        "delta" => "δ",
        "epsilon" => "ϵ",
        "varepsilon" => "ε",
        "zeta" => "ζ",
        "eta" => "η",
        "theta" => "θ",
        "vartheta" => "ϑ",
        "iota" => "ι",
        "kappa" => "κ",
        "lambda" => "λ",
        "mu" => "μ",
        "nu" => "ν",
        "xi" => "ξ",
        "pi" => "π",
        "varpi" => "ϖ",
        "rho" => "ρ",
        "varrho" => "ϱ",
        "sigma" => "σ",
        "varsigma" => "ς",
        "tau" => "τ",
        "upsilon" => "υ",
        "phi" => "ϕ",
        "varphi" => "φ",
        "chi" => "χ",
        "psi" => "ψ",
        "omega" => "ω",
        // ---- Greek (uppercase) ----
        "Gamma" => "Γ",
        "Delta" => "Δ",
        "Theta" => "Θ",
        "Lambda" => "Λ",
        "Xi" => "Ξ",
        "Pi" => "Π",
        "Sigma" => "Σ",
        "Upsilon" => "Υ",
        "Phi" => "Φ",
        "Psi" => "Ψ",
        "Omega" => "Ω",
        // ---- binary operators ----
        "times" => "×",
        "div" => "÷",
        "pm" => "±",
        "mp" => "∓",
        "cdot" => "⋅",
        "ast" => "∗",
        "star" => "⋆",
        "circ" => "∘",
        "bullet" => "∙",
        "oplus" => "⊕",
        "ominus" => "⊖",
        "otimes" => "⊗",
        "odot" => "⊙",
        "cup" => "∪",
        "cap" => "∩",
        "setminus" => "∖",
        "wedge" | "land" => "∧",
        "vee" | "lor" => "∨",
        "sqcup" => "⊔",
        "sqcap" => "⊓",
        // ---- relations ----
        "leq" | "le" => "≤",
        "geq" | "ge" => "≥",
        "neq" | "ne" => "≠",
        "equiv" => "≡",
        "approx" => "≈",
        "cong" => "≅",
        "sim" => "∼",
        "simeq" => "≃",
        "propto" => "∝",
        "ll" => "≪",
        "gg" => "≫",
        "subset" => "⊂",
        "supset" => "⊃",
        "subseteq" => "⊆",
        "supseteq" => "⊇",
        "in" => "∈",
        "notin" => "∉",
        "ni" => "∋",
        "perp" => "⊥",
        "parallel" => "∥",
        "mid" => "∣",
        "models" => "⊨",
        "vdash" => "⊢",
        "prec" => "≺",
        "succ" => "≻",
        // normal-subgroup relations + negated/harpoon relations
        "lhd" | "vartriangleleft" => "⊲",
        "rhd" | "vartriangleright" => "⊳",
        "unlhd" | "trianglelefteq" => "⊴",
        "unrhd" | "trianglerighteq" => "⊵",
        "ntrianglelefteq" => "⋬",
        "ntrianglerighteq" => "⋭",
        "nmid" => "∤",
        "nparallel" => "∦",
        "smallsetminus" => "∖",
        "restriction" | "upharpoonright" => "↾",
        "upharpoonleft" => "↿",
        "downharpoonright" => "⇂",
        "downharpoonleft" => "⇃",
        // ---- arrows ----
        "to" | "rightarrow" => "→",
        "leftarrow" | "gets" => "←",
        "leftrightarrow" => "↔",
        "Rightarrow" => "⇒",
        "Leftarrow" => "⇐",
        "Leftrightarrow" => "⇔",
        "mapsto" => "↦",
        "hookrightarrow" => "↪",
        "uparrow" => "↑",
        "downarrow" => "↓",
        "longrightarrow" => "⟶",
        "longleftarrow" => "⟵",
        "implies" => "⟹",
        "iff" => "⟺",
        // ---- logic / sets / misc symbols ----
        "forall" => "∀",
        "exists" => "∃",
        "nexists" => "∄",
        "neg" | "lnot" => "¬",
        "nabla" => "∇",
        "partial" => "∂",
        "infty" => "∞",
        "emptyset" | "varnothing" => "∅",
        "angle" => "∠",
        "triangle" => "△",
        "square" => "□",
        "diamond" => "⋄",
        "aleph" => "ℵ",
        "hbar" => "ℏ",
        "ell" => "ℓ",
        "Re" => "ℜ",
        "Im" => "ℑ",
        "wp" => "℘",
        "prime" => "′",
        "dagger" => "†",
        "ddagger" => "‡",
        "top" => "⊤",
        "bot" => "⊥",
        "surd" => "√",
        "flat" => "♭",
        "sharp" => "♯",
        // dots
        "cdots" => "⋯",
        "ldots" | "dots" => "…",
        "vdots" => "⋮",
        "ddots" => "⋱",
        // escaped literals in math
        "{" => "{",
        "}" => "}",
        "|" => "‖",
        "%" => "%",
        "&" => "&",
        "#" => "#",
        "_" => "_",
        "$" => "$",
        "backslash" => "\\",
        "langle" => "⟨",
        "rangle" => "⟩",
        "lceil" => "⌈",
        "rceil" => "⌉",
        "lfloor" => "⌊",
        "rfloor" => "⌋",
        // thin/med/thick/neg spaces and \  -> a (thin) space or nothing
        "," | ":" | ";" | " " | "quad" | "qquad" | "!" | "thinspace" => "\u{2009}",
        _ => return None,
    })
}

/// N-ary/big operators: `(glyph, over_under)` where `over_under` places the
/// limits above/below (sums) rather than as scripts (integrals).
pub fn nary(name: &str) -> Option<(&'static str, bool)> {
    Some(match name {
        "sum" => ("∑", true),
        "prod" => ("∏", true),
        "coprod" => ("∐", true),
        "bigcup" => ("⋃", true),
        "bigcap" => ("⋂", true),
        "bigsqcup" => ("⨆", true),
        "bigvee" => ("⋁", true),
        "bigwedge" => ("⋀", true),
        "bigoplus" => ("⨁", true),
        "bigotimes" => ("⨂", true),
        "bigodot" => ("⨀", true),
        "int" => ("∫", false),
        "iint" => ("∬", false),
        "iiint" => ("∭", false),
        "oint" => ("∮", false),
        _ => return None,
    })
}

/// Math function names that render upright (e.g. `\sin` -> upright "sin").
pub fn function_name(name: &str) -> Option<&'static str> {
    Some(match name {
        "sin" => "sin",
        "cos" => "cos",
        "tan" => "tan",
        "cot" => "cot",
        "sec" => "sec",
        "csc" => "csc",
        "sinh" => "sinh",
        "cosh" => "cosh",
        "tanh" => "tanh",
        "coth" => "coth",
        "arcsin" => "arcsin",
        "arccos" => "arccos",
        "arctan" => "arctan",
        "log" => "log",
        "ln" => "ln",
        "lg" => "lg",
        "exp" => "exp",
        "lim" => "lim",
        "limsup" => "lim sup",
        "liminf" => "lim inf",
        "max" => "max",
        "min" => "min",
        "inf" => "inf",
        "sup" => "sup",
        "det" => "det",
        "gcd" => "gcd",
        "deg" => "deg",
        "dim" => "dim",
        "ker" => "ker",
        "hom" => "hom",
        "arg" => "arg",
        "Pr" => "Pr",
        "mod" => "mod",
        "bmod" => "mod",
        _ => return None,
    })
}

/// Map ASCII letters/digits to a Unicode math-alphanumeric style
/// (`\mathbb`/`\mathcal`/`\mathscr`/`\mathfrak`), leaving other characters as-is.
/// Blackboard-bold and Fraktur have "holes" filled from the Letterlike Symbols
/// block (ℂ ℍ ℕ ℙ ℚ ℝ ℤ, ℭ ℌ ℑ ℜ ℨ), so uppercase is looked up in an explicit
/// table; lowercase/digits use plane arithmetic.
pub fn alphabet(style: &str, s: &str) -> String {
    s.chars()
        .map(|c| alpha_char(style, c).unwrap_or(c))
        .collect()
}

fn nth(table: &str, i: usize) -> Option<char> {
    table.chars().nth(i)
}

fn alpha_char(style: &str, c: char) -> Option<char> {
    let upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let idx = upper.find(c); // ASCII table -> byte index == char index
    match style {
        "mathbb" => {
            if let Some(i) = idx {
                return nth("𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ", i);
            }
            if c.is_ascii_lowercase() {
                return char::from_u32(0x1D552 + (c as u32 - 'a' as u32));
            }
            if c.is_ascii_digit() {
                return char::from_u32(0x1D7D8 + (c as u32 - '0' as u32));
            }
            None
        }
        "mathcal" | "mathscr" => idx.and_then(|i| nth("𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵", i)),
        "mathfrak" => {
            if let Some(i) = idx {
                return nth("𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ", i);
            }
            if c.is_ascii_lowercase() {
                return char::from_u32(0x1D51E + (c as u32 - 'a' as u32));
            }
            None
        }
        _ => None,
    }
}
