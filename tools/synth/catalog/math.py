"""Math probes: expressions rendered inline and as display math.

Oracles: no raw-TeX fallback, no warnings, no empty n-ary bodies, no leaked
markup in ``m:t``, the expected glyphs present, and a stable round trip
(OMML -> LaTeX -> OMML keeps the same text and structure).
"""

from __future__ import annotations

from ..model import Expect, Probe

PREAMBLE = r"""\documentclass{article}
\usepackage{amsmath,amssymb,amsthm,mathtools,bm,cancel,physics,braket,siunitx}
\newcommand{\R}{\mathbb{R}}
\newcommand{\E}{\mathbb{E}}
\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}
\DeclareMathOperator*{\argmax}{arg\,max}
\DeclareMathOperator{\Var}{Var}
\DeclarePairedDelimiter{\ceil}{\lceil}{\rceil}
\begin{document}
"""

# (name, latex, expected glyphs/text in m:t or attributes)
EXPRESSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # -- basics -------------------------------------------------------------- #
    ("frac", r"\frac{a+b}{c}", ()),
    ("dfrac-tfrac", r"\dfrac{1}{2} + \tfrac{3}{4}", ()),
    ("cfrac", r"\cfrac{1}{1+\cfrac{1}{x}}", ()),
    ("nested-frac", r"\frac{\frac{1}{x}+1}{\frac{1}{y}}", ()),
    ("sqrt", r"\sqrt{x^2+1}", ()),
    ("sqrt-n", r"\sqrt[3]{8}", ()),
    ("sup-sub", r"x_i^2 + a_{ij}^{(k)}", ()),
    ("tower", r"a^{b^{c}}", ()),
    ("prescript-empty", r"{}^{14}\mathrm{C}", ("14",)),
    ("prime", r"f'(x) + f''(x)", ("′",)),
    ("prime-sup", r"f^{\prime}(x)", ("′",)),
    ("transpose", r"A^\top A + B^T", ("⊤",)),
    ("dagger", r"A^\dagger", ("†",)),
    ("binom", r"\binom{n}{k} = \frac{n!}{k!(n-k)!}", ()),
    ("dbinom", r"\dbinom{n}{2}", ()),
    ("genfrac", r"\genfrac{(}{)}{0pt}{}{n}{k}", ()),
    ("choose-primitive", r"{n \choose k}", ()),
    ("over-primitive", r"{a \over b}", ()),
    ("atop", r"{a \atop b}", ()),
    # -- operators and limits ----------------------------------------------- #
    ("sum-limits", r"\sum_{i=1}^{n} x_i", ("∑",)),
    ("sum-operand", r"\sum_i e_i \sigma + 1", ("∑",)),
    ("sum-substack", r"\sum_{\substack{i<n\\ j<m}} a_{ij}", ("∑",)),
    ("sum-limits-cmd", r"\sum\limits_{k} k", ("∑",)),
    ("prod", r"\prod_{p} \frac{1}{1-p^{-s}}", ("∏",)),
    ("coprod", r"\coprod_i X_i", ("∐",)),
    ("bigcup-cap", r"\bigcup_{i} A_i \cap \bigcap_j B_j", ("⋃", "⋂")),
    ("bigoplus-otimes", r"\bigoplus_i V_i \otimes \bigotimes_j W_j", ("⨁", "⨂")),
    ("int", r"\int_0^\infty e^{-x^2}\,dx", ("∫", "∞")),
    ("iint-oint", r"\iint_D f\,dA + \oint_C \omega", ("∬", "∮")),
    ("iiint", r"\iiint_V \rho\, dV", ("∭",)),
    ("int-limits", r"\int\limits_a^b f", ("∫",)),
    ("lim", r"\lim_{x\to 0} \frac{\sin x}{x} = 1", ("lim", "sin", "→")),
    ("limsup", r"\limsup_{n\to\infty} a_n", ("lim",)),
    ("max-min", r"\max_{x\in X} f(x) - \min_y g(y)", ("max", "min")),
    ("sup-inf", r"\sup_n a_n \ge \inf_n a_n", ("sup", "inf")),
    ("argmax-star", r"\argmax_{\theta} L(\theta)", ("arg",)),
    ("operatorname-star", r"\operatorname*{argmin}_x f(x)", ("argmin",)),
    ("operatorname", r"\operatorname{tr}(A) + \operatorname{rank} B", ("tr", "rank")),
    ("declared-op", r"\Var(X)", ("Var",)),
    ("functions", r"\sin x + \cos y + \tan z + \log n + \ln x + \exp(t)",
     ("sin", "cos", "tan", "log", "ln", "exp")),
    ("det-gcd-Pr", r"\det(A) \gcd(a,b) \Pr(E)", ("det", "gcd", "Pr")),
    ("mod", r"a \equiv b \pmod{n},\ a \bmod n", ("mod",)),
    ("arg-dim", r"\arg z + \dim V + \ker f + \deg p", ("arg", "dim", "ker", "deg")),
    # -- delimiters ----------------------------------------------------------- #
    ("left-right", r"\left( \frac{a}{b} \right)", ()),
    ("left-right-brackets", r"\left[ x \right] \left\{ y \right\}", ()),
    ("left-dot", r"\left.\frac{df}{dx}\right|_{x=0}", ()),
    ("middle", r"\left\{ x \;\middle|\; x>0 \right\}", ()),
    ("big", r"\big( \Big[ \bigg\{ \Bigg| x \Bigg| \bigg\} \Big] \big)", ()),
    ("bigl-bigr", r"\bigl( a \bigr)", ()),
    ("angle", r"\langle x, y \rangle", ("⟨", "⟩")),
    ("floor-ceil", r"\lfloor x \rfloor + \lceil y \rceil", ("⌊", "⌉")),
    ("norm-bars", r"\lVert x \rVert_2 + \lvert y \rvert", ("‖",)),
    ("norm-macro", r"\norm{x}", ("‖",)),
    ("paired-delim", r"\ceil{x/2}", ("⌈",)),
    ("set-builder", r"\{x \in \R \mid x > 0\}", ("∈", "∣")),
    ("abs-physics", r"\abs{x}", ("|",)),
    # -- accents and fonts ------------------------------------------------------ #
    ("accents", r"\hat{a}\bar{b}\tilde{c}\vec{d}\dot{e}\ddot{f}\check{g}\breve{h}", ()),
    ("wide-accents", r"\widehat{abc} + \widetilde{xyz} + \overline{AB}", ()),
    ("overright-arrow", r"\overrightarrow{AB} + \overleftarrow{CD}", ()),
    ("underline-math", r"\underline{x+y}", ()),
    ("overbrace", r"\overbrace{a+b}^{n} + \underbrace{c+d}_{m}", ()),
    ("mathbb", r"\mathbb{R}^n \times \mathbb{N}", ()),
    ("mathcal-frak-scr", r"\mathcal{L} + \mathfrak{g} + \mathscr{F}", ()),
    ("mathbf-bm", r"\mathbf{x} + \bm{\alpha} + \boldsymbol{\mu}", ()),
    ("mathrm-word", r"\mathrm{KL}(p \,\|\, q)", ("KL",)),
    ("mathsf-tt-it", r"\mathsf{A} \mathtt{b} \mathit{c}", ()),
    ("text-in-math", r"x = 1 \text{ if } y > 0", (" if ",)),
    ("text-hyphen", r"\text{well-known} - x", ("well-known", "−")),
    ("mbox-math", r"\mbox{for all } x", ("for all",)),
    ("user-macro-bb", r"x \in \R^n, \E[X]", ()),
    # -- symbols ----------------------------------------------------------------- #
    ("greek", r"\alpha\beta\gamma\delta\epsilon\varepsilon\theta\vartheta\lambda\mu\pi\sigma"
     r"\varphi\omega\Gamma\Delta\Theta\Lambda\Sigma\Phi\Psi\Omega", ("α", "ε", "Ω")),
    ("relations", r"a \le b \ge c \ne d \approx e \equiv f \sim g \simeq h \cong i \propto j",
     ("≤", "≥", "≠", "≈", "≡", "∼", "≃", "≅", "∝")),
    ("ll-gg", r"a \ll b \gg c \lesssim d \gtrsim e", ("≪", "≫", "≲", "≳")),
    ("sets", r"A \subset B \subseteq C \supset D \in E \notin F \ni x \emptyset \varnothing",
     ("⊂", "⊆", "⊃", "∈", "∉", "∋", "∅")),
    ("not-combos", r"a \not= b, x \not\in A, B \not\subset C", ()),
    ("logic", r"\forall x \exists y \nexists z \neg p \land q \lor r \implies s \iff t",
     ("∀", "∃", "∄", "¬", "∧", "∨", "⟹", "⟺")),
    ("arrows", r"a \to b \mapsto c \Rightarrow d \Leftarrow e \leftrightarrow f "
     r"\hookrightarrow g \longrightarrow h \uparrow \downarrow", ("→", "↦", "⇒", "↪", "⟶")),
    ("xarrow", r"A \xrightarrow{f} B \xleftarrow[g]{h} C", ("→", "←")),
    ("misc-symbols", r"\infty \partial \nabla \hbar \ell \Re \Im \aleph \angle \triangle \prime",
     ("∞", "∂", "∇", "ℏ", "ℓ", "ℵ")),
    ("binary-ops", r"a \pm b \mp c \cdot d \times e \div f \ast g \star h \circ i \bullet j",
     ("±", "∓", "⋅", "×", "÷", "∗", "⋆", "∘", "∙")),
    ("oplus-otimes", r"a \oplus b \otimes c \odot d \ominus e", ("⊕", "⊗", "⊙", "⊖")),
    ("dots", r"1, 2, \ldots, n \quad a + \cdots + z \quad \vdots \quad \ddots", ("…", "⋯")),
    ("mid-parallel-perp", r"a \mid b, c \parallel d, e \perp f, g \nmid h", ("∣", "∥", "⊥")),
    ("setminus", r"A \setminus B \cup C \cap D", ("∖", "∪", "∩")),
    ("colon-defs", r"f \colon X \to Y, \quad a \coloneqq b", (":", "≔")),
    ("triangleq-stackrel", r"a \triangleq b, \quad c \stackrel{\text{def}}{=} d", ("≜",)),
    ("overset-underset", r"\overset{!}{=} \quad \underset{x}{\operatorname{arg\,min}}", ()),
    ("therefore-because", r"\therefore a \because b", ("∴", "∵")),
    ("vdash-models", r"\Gamma \vdash \phi, \quad M \models \psi", ("⊢", "⊨")),
    ("top-bot", r"\top \bot", ("⊤", "⊥")),
    ("qed-box", r"\square \blacksquare \Box", ()),
    ("degree", r"90^\circ", ("∘",)),
    ("percent-hash", r"50\% + \#x + \$3 + \&", ("%", "#", "$", "&")),
    ("backslash-setminus", r"A \backslash B", ("∖",)),
    ("imath-jmath", r"\imath + \jmath", ("ı", "ȷ")),
    # -- spacing ----------------------------------------------------------------- #
    ("spaces", r"a\,b\:c\;d\!e\quad f\qquad g\ h~i", ()),
    ("hspace-math", r"a \hspace{1em} b", ()),
    ("phantom", r"a \phantom{xx} b \hphantom{y} c \vphantom{z}", ()),
    ("styles", r"\displaystyle\sum_i x_i \textstyle\int f \scriptstyle y", ()),
    # -- environments --------------------------------------------------------- #
    ("pmatrix", r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", ()),
    ("bmatrix-vmatrix", r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix} "
     r"\begin{vmatrix} a & b \\ c & d \end{vmatrix}", ()),
    ("Bmatrix-Vmatrix", r"\begin{Bmatrix} x \end{Bmatrix} \begin{Vmatrix} y \end{Vmatrix}", ()),
    ("smallmatrix", r"\left(\begin{smallmatrix} a & b \\ c & d \end{smallmatrix}\right)", ()),
    ("matrix-dots", r"\begin{pmatrix} a_{11} & \cdots & a_{1n} \\ \vdots & \ddots & \vdots \\"
     r" a_{m1} & \cdots & a_{mn} \end{pmatrix}", ("⋯", "⋮", "⋱")),
    ("array", r"\begin{array}{c|c} a & b \\ \hline c & d \end{array}", ()),
    ("array-left-brace", r"f(x) = \left\{ \begin{array}{ll} 1 & x > 0 \\ 0 & \text{else}"
     r" \end{array} \right.", ()),
    ("cases", r"|x| = \begin{cases} x & x \ge 0 \\ -x & x < 0 \end{cases}", ()),
    ("cases-text", r"f = \begin{cases} 1, & \text{if } a \\[2pt] 0, & \text{otherwise}"
     r" \end{cases}", ("otherwise",)),
    ("dcases", r"\begin{dcases} \frac{1}{2} & a \\ 0 & b \end{dcases}", ()),
    ("rcases", r"\begin{rcases} a & b \\ c & d \end{rcases} \Rightarrow e", ()),
    ("aligned", r"\begin{aligned} a &= b + c \\ &= d \end{aligned}", ()),
    ("gathered", r"\begin{gathered} a = b \\ c = d \end{gathered}", ()),
    ("split-in-eq", r"\begin{split} a &= b \\ &= c \end{split}", ()),
    ("boxed", r"\boxed{E = mc^2}", ()),
    ("cancel", r"\cancel{x} + \bcancel{y} + \xcancel{z} + \cancelto{0}{w}", ()),
    ("color-math", r"\color{red} x + \textcolor{blue}{y}", ()),
    ("substack-only", r"\sum_{\substack{0 \le i \le m \\ 0 < j < n}} P(i,j)", ()),
    ("sideset", r"\sideset{}{'}\sum_{n<k} a_n", ()),
    # -- physics / braket / siunitx ----------------------------------------- #
    ("physics-derivatives", r"\dv{f}{x} + \pdv{f}{x}{y} + \dd x", ("d", "∂")),
    ("physics-qty", r"\qty(\frac{a}{b}) + \qty[x]", ()),
    ("physics-expval", r"\expval{A} + \ev{B}", ("⟨", "⟩")),
    ("physics-trace", r"\tr(\rho) + \Tr \rho", ("tr",)),
    ("braket", r"\braket{\phi|\psi} + \ket{0} + \bra{1}", ("⟨", "⟩")),
    ("siunitx-in-math", r"v = \SI{3}{\meter\per\second}", ("m",)),
    ("si-num-in-math", r"x = \num{1.5e3}", ()),
    # -- typical formulas -------------------------------------------------------- #
    ("euler", r"e^{i\pi} + 1 = 0", ()),
    ("gaussian", r"\frac{1}{\sqrt{2\pi\sigma^2}} "
     r"\exp\left(-\frac{(x-\mu)^2}{2\sigma^2}\right)", ()),
    ("variance", r"\frac{1}{n-1}\sum_{i=1}^{n}(x_i-\bar{x})^2", ()),
    ("bayes", r"p(\theta \mid x) = \frac{p(x \mid \theta)\, p(\theta)}{p(x)}", ()),
    ("expectation", r"\mathbb{E}_{x \sim p}\left[ \log \frac{p(x)}{q(x)} \right]", ()),
    ("gradient-step", r"\theta_{t+1} = \theta_t - \eta \nabla_\theta \mathcal{L}(\theta_t)", ()),
    ("big-o", r"O(n \log n) \subseteq \Theta(n^2)", ()),
    ("indicator", r"\mathbb{1}_{\{x > 0\}} + \mathbf{1}[y]", ()),
    ("kronecker", r"\delta_{ij} = \begin{cases} 1 & i = j \\ 0 & i \neq j \end{cases}", ()),
    ("taylor", r"f(x) = \sum_{k=0}^{\infty} \frac{f^{(k)}(a)}{k!}(x-a)^k", ()),
    ("integral-by-parts", r"\int_a^b u\,dv = \left. uv \right|_a^b - \int_a^b v\,du", ()),
    ("maxwell", r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}, \quad "
     r"\nabla \times \mathbf{B} = \mu_0 \mathbf{J}", ()),
    ("schrodinger", r"i\hbar \frac{\partial}{\partial t} \Psi = \hat{H} \Psi", ()),
    ("softmax", r"\sigma(\mathbf{z})_i = \frac{e^{z_i}}{\sum_{j=1}^{K} e^{z_j}}", ()),
    ("attention", r"\operatorname{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right)V", ()),
    ("norm-sub", r"\|x - y\|_2^2 \le \epsilon", ()),
    ("iid", r"X_i \stackrel{\text{iid}}{\sim} \mathcal{N}(0, 1)", ()),
    ("conditional-prob", r"P(A \cap B) = P(A \mid B) P(B)", ()),
    ("piecewise-loss", r"\ell(y, \hat y) = \max(0, 1 - y \hat y)", ()),
    ("matrix-inverse", r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}^{-1}", ()),
    ("long-sum-chain", r"\sum_{i} \sum_{j} \sum_{k} a_{ijk} b_k", ()),
    ("sum-in-frac-in-sqrt", r"\sqrt{\frac{\sum_i x_i^2}{n}}", ()),
    ("int-then-sum", r"\int_0^1 \sum_n f_n(x)\,dx", ()),
    ("ce-like", r"\mathrm{H_2O} + \mathrm{CO_2}", ()),
    ("units-text", r"5\,\mathrm{kg}\cdot\mathrm{m}/\mathrm{s}^2", ()),
    ("negative-exponent", r"10^{-3} - x^{-1}", ("−",)),
    ("minus-unary", r"-x + (-1)^n", ("−",)),
)

DISPLAY_ENVS: tuple[tuple[str, str, str], ...] = (
    ("equation-label", "\\begin{equation}\\label{eq:a} a = b \\end{equation} See (\\ref{eq:a}).",
     ""),
    ("equation-star", "\\begin{equation*} a = b \\end{equation*}", ""),
    ("align-labels", "\\begin{align} a &= b \\label{eq:x}\\\\ c &= d \\label{eq:y}\\end{align}"
     " \\eqref{eq:x} \\eqref{eq:y}", ""),
    ("align-star-spacing", "\\begin{align*} a &= b \\\\[4pt] c &= d \\\\* e &= f\\end{align*}",
     ""),
    ("align-nonumber", "\\begin{align} a &= b \\nonumber\\\\ c &= d \\end{align}", ""),
    ("align-notag-tag", "\\begin{align} a &= b \\tag{A}\\\\ c &= d \\notag\\end{align}", ""),
    ("align-intertext", "\\begin{align} a &= b \\\\ \\intertext{and so} c &= d \\end{align}",
     "and so"),
    ("alignat", "\\begin{alignat}{2} a &= b &\\quad c &= d \\end{alignat}", ""),
    ("gather", "\\begin{gather} a = b \\\\ c = d \\end{gather}", ""),
    ("multline", "\\begin{multline} a + b + c \\\\ + d + e \\end{multline}", ""),
    ("flalign", "\\begin{flalign} a &= b & c &= d \\end{flalign}", ""),
    ("eqnarray", "\\begin{eqnarray} a &=& b \\\\ c &=& d \\end{eqnarray}", ""),
    ("subequations", "\\begin{subequations}\\label{eq:grp}\\begin{align} a &= b\\label{eq:g1}"
     "\\\\ c &= d \\end{align}\\end{subequations} \\eqref{eq:g1} \\eqref{eq:grp}", ""),
    ("split-in-equation", "\\begin{equation}\\begin{split} a &= b \\\\ &= c \\end{split}"
     "\\end{equation}", ""),
    ("cases-in-equation", "\\begin{equation} f = \\begin{cases} 1 & a \\\\ 0 & b \\end{cases}"
     "\\end{equation}", ""),
    ("dollar-dollar", "$$ a + b $$", ""),
    ("bracket-display", "\\[ \\int f \\]", ""),
    ("paren-inline", "\\( x + y \\)", ""),
    ("math-env", "\\begin{math} x^2 \\end{math}", ""),
    ("displaymath-env", "\\begin{displaymath} x^2 \\end{displaymath}", ""),
    ("equation-in-itemize", "\\begin{itemize}\\item \\begin{equation} a=b \\end{equation}"
     "\\end{itemize}", ""),
    ("equation-in-theorem", "\\newtheorem{thm}{Theorem}\\begin{thm} \\begin{equation} a=b "
     "\\end{equation}\\end{thm}", ""),
    ("tag-star", "\\begin{equation} a = b \\tag*{(*)} \\end{equation}", ""),
)


def probes() -> list[Probe]:
    out: list[Probe] = []
    for name, latex, glyphs in EXPRESSIONS:
        for mode, wrap in (("inline", "Text ${}$ text."), ("display", "\\[ {} \\]")):
            src = PREAMBLE + wrap.format(latex) + "\n\\end{document}\n"
            out.append(Probe(
                id=f"math/{name}@{mode}",
                source=src,
                expect=Expect(texts=list(glyphs), min_math=1, roundtrip=True,
                              allow_backslash=False),
                tags={"construct": name, "context": mode},
                fragment=latex,
                note=f"math {name} ({mode})",
                tier="smoke" if name in _SMOKE else "full",
            ))
    for name, body, text in DISPLAY_ENVS:
        out.append(Probe(
            id=f"math/env-{name}",
            source=PREAMBLE + body + "\n\\end{document}\n",
            expect=Expect(texts=[text] if text else [], min_math=1, roundtrip=True),
            tags={"construct": name, "context": "display-env"},
            fragment=body,
            note=f"display environment {name}",
            tier="smoke" if name in _SMOKE else "full",
        ))
    return out


_SMOKE = {"frac", "sum-limits", "cases", "pmatrix", "relations", "equation-label",
          "align-labels", "text-hyphen", "left-right"}
