"""LaTeX-math command tables: symbols, operators, accents, delimiters.

These map (macro-expanded) LaTeX control sequences onto the Unicode code points
that OMML uses directly (OMML is a layout model over Unicode math glyphs, font
Cambria Math). Kept deliberately data-driven so coverage grows by editing
tables, not code.
"""

from __future__ import annotations

# Greek + symbols rendered as a single Unicode glyph.
SYMBOLS: dict[str, str] = {
    # lowercase greek
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω",
    # uppercase greek
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # relations
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "neq": "≠", "ne": "≠", "equiv": "≡", "approx": "≈",
    "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝",
    "ll": "≪", "gg": "≫", "subset": "⊂", "supset": "⊃",
    "subseteq": "⊆", "supseteq": "⊇", "in": "∈", "ni": "∋",
    "notin": "∉", "mid": "∣", "parallel": "∥", "perp": "⊥",
    "prec": "≺", "succ": "≻", "models": "⊨",
    "preceq": "⪯", "succeq": "⪰", "gtrsim": "≳", "lesssim": "≲",
    "gtrless": "≷", "lessgtr": "≶", "asymp": "≍", "doteq": "≐",
    "triangleq": "≜", "coloneqq": "≔", "eqqcolon": "≕", "approxeq": "≊",
    "sqsubseteq": "⊑", "sqsupseteq": "⊒", "vdash": "⊢", "dashv": "⊣",
    "lhd": "⊲", "rhd": "⊳", "unlhd": "⊴", "unrhd": "⊵",
    "vartriangleleft": "⊲", "vartriangleright": "⊳",
    "trianglelefteq": "⊴", "trianglerighteq": "⊵",
    "ntrianglelefteq": "⋬", "ntrianglerighteq": "⋭",
    "nmid": "∤", "nparallel": "∦", "smallsetminus": "∖",
    "restriction": "↾", "upharpoonright": "↾", "upharpoonleft": "↿",
    "downharpoonright": "⇂", "downharpoonleft": "⇃",
    # binary operators
    "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "cdot": "⋅", "ast": "∗", "star": "⋆", "circ": "∘",
    "bullet": "∙", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗",
    "oslash": "⊘", "odot": "⊙", "cap": "∩", "cup": "∪",
    "wedge": "∧", "land": "∧", "vee": "∨", "lor": "∨",
    "setminus": "∖", "uplus": "⊎", "sqcap": "⊓", "sqcup": "⊔",
    "dagger": "†", "ddagger": "‡",
    # arrows
    "rightarrow": "→", "to": "→", "leftarrow": "←",
    "gets": "←", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "mapsto": "↦",
    "longrightarrow": "⟶", "longleftarrow": "⟵", "implies": "⟹",
    "iff": "⟺", "uparrow": "↑", "downarrow": "↓", "hookrightarrow": "↪",
    # misc symbols
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀",
    "exists": "∃", "nexists": "∄", "emptyset": "∅", "varnothing": "∅",
    "neg": "¬", "lnot": "¬", "angle": "∠", "triangle": "△",
    "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ", "Im": "ℑ",
    "wp": "℘", "aleph": "ℵ", "prime": "′", "backslash": "\\",
    "dots": "…", "ldots": "…", "cdots": "⋯", "vdots": "⋮",
    "ddots": "⋱", "top": "⊤", "bot": "⊥", "surd": "√",
    "flat": "♭", "sharp": "♯", "natural": "♮", "clubsuit": "♣",
    "diamondsuit": "♦", "heartsuit": "♥", "spadesuit": "♠",
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋", "Box": "□", "checkmark": "✓",
    # named sets via \mathbb fallback handled separately
    "quad": " ", "qquad": "  ", "colon": ":",
    "lbrace": "{", "rbrace": "}", "vert": "|", "Vert": "‖",
}

# n-ary / big operators (rendered with limits via OMML m:nary).
NARY: dict[str, str] = {
    "sum": "∑", "prod": "∏", "coprod": "∐",
    "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "bigcup": "⋃", "bigcap": "⋂", "bigvee": "⋁", "bigwedge": "⋀",
    "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀",
    "biguplus": "⨄", "bigsqcup": "⨆", "lim": "lim",
}

# Accents: command -> combining/standalone accent character used by OMML m:acc.
ACCENTS: dict[str, str] = {
    "hat": "̂", "widehat": "̂", "tilde": "̃", "widetilde": "̃",
    "bar": "̄", "overline": "̄", "vec": "⃗", "dot": "̇",
    "ddot": "̈", "acute": "́", "grave": "̀", "check": "̌",
    "breve": "̆", "mathring": "̊",
    # wide arrow accents (over-arrows for vectors/segments)
    "overrightarrow": "⃗", "overleftarrow": "⃖", "overleftrightarrow": "⃡",
    "widearc": "⃐", "overparen": "⃔",
}

# Upright multi-letter function names (set with m:nor in their run properties).
FUNCTIONS: frozenset[str] = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc",
    "sinh", "cosh", "tanh", "coth",
    "arcsin", "arccos", "arctan",
    "exp", "log", "ln", "lg",
    "det", "dim", "ker", "deg", "gcd", "hom", "arg",
    "min", "max", "sup", "inf", "lim", "limsup", "liminf",
    "mod", "Pr",
})

# Delimiter commands -> the literal delimiter character.
DELIMITERS: dict[str, str] = {
    "(": "(", ")": ")", "[": "[", "]": "]", "lbrace": "{", "rbrace": "}",
    "\\{": "{", "\\}": "}", "|": "|", "Vert": "‖", "vert": "|",
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋", "uparrow": "↑", "downarrow": "↓",
    ".": "",
}

# Blackboard-bold (\mathbb) letters -> Unicode double-struck.
MATHBB: dict[str, str] = {
    "A": "\U0001d538", "B": "\U0001d539", "C": "ℂ", "D": "\U0001d53b",
    "E": "\U0001d53c", "F": "\U0001d53d", "G": "\U0001d53e", "H": "ℍ",
    "I": "\U0001d540", "J": "\U0001d541", "K": "\U0001d542", "L": "\U0001d543",
    "M": "\U0001d544", "N": "ℕ", "O": "\U0001d546", "P": "ℙ",
    "Q": "ℚ", "R": "ℝ", "S": "\U0001d54a", "T": "\U0001d54b",
    "U": "\U0001d54c", "V": "\U0001d54d", "W": "\U0001d54e", "X": "\U0001d54f",
    "Y": "\U0001d550", "Z": "ℤ",
}

# Spacing commands that produce (roughly) nothing / thin spaces.
SPACING: dict[str, str] = {
    ",": " ", ";": " ", ":": " ", "!": "", " ": " ",
    "thinspace": " ", "quad": " ", "qquad": "  ",
}
