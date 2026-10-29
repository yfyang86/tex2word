"""The construct x context matrix.

Every inline *construct* (``\\textbf``, ``\\cite``, ``\\ref``, an accent, a
siunitx quantity, ...) is placed in every *context* it is legal LaTeX in (a
paragraph, a table cell, a caption, a theorem title, a footnote, a tcolorbox,
...). The sentinel token inside the construct must survive exactly once, and the
generic oracles catch leaks, unresolved references and raw citation keys.

This is the shape of issue #44: constructs that work in a paragraph but not
inside some container. The triage report reads the matrix by row (a broken
construct), by column (a broken context) and by cell (an interaction).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import SENTINEL as S
from ..model import Expect, Probe

PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsthm}
\usepackage{graphicx,xcolor}
\usepackage{booktabs,tabularx,longtable,multirow,makecell,array,adjustbox}
\usepackage{caption,subcaption,threeparttable,rotating,pdflscape,wrapfig}
\usepackage{tcolorbox,mdframed,framed,multicol,enumitem}
\usepackage{algorithm,algpseudocode}
\usepackage[normalem]{ulem}
\usepackage{soul,siunitx,pifont,csquotes,listings,textcomp}
\usepackage[authoryear]{natbib}
\usepackage{hyperref}
\usepackage{cleveref}
\newtheorem{theorem}{Theorem}
\theoremstyle{definition}
\newtheorem{definition}{Definition}
"""

#: before the context: targets for \ref/\eqref/\cref and a cited bibliography
TARGETS = r"""\section{Target}\label{sec:target}
Anchor text.
\begin{equation}a=b\label{eq:target}\end{equation}
"""

TAIL = r"""
\bibliographystyle{plainnat}
\bibliography{refs}
\end{document}
"""


@dataclass(frozen=True)
class Construct:
    name: str
    latex: str  # uses the sentinel S
    texts: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    styles: tuple[tuple[str, str], ...] = ()  # (token, rPr tag)
    counts: tuple[tuple[str, int], ...] = ()
    verbatim: bool = False  # \verb & co.: never inside a macro argument
    fragile: bool = False  # breaks in moving arguments (captions, headings)
    cell_only: bool = False  # only meaningful inside a tabular row
    no_cell: bool = False  # contains \\ or & that would end a cell/row
    allow_dims: bool = False
    allow_braces: bool = False
    allow_backslash: bool = False
    smoke: bool = False


@dataclass(frozen=True)
class Context:
    name: str
    body: str = "%X"  # goes after the targets
    head: str = ""  # goes right after \begin{document} (title, abstract)
    slot: str = "body"  # body | arg | moving
    cell: bool = False  # the slot is a tabular cell
    allow: tuple[str, ...] = ()  # acceptable warnings
    smoke: bool = False
    extra: dict[str, str] = field(default_factory=dict)



CONSTRUCTS: tuple[Construct, ...] = (
    Construct("plain", S, smoke=True),
    Construct("textbf", rf"\textbf{{{S}}}", styles=((S, "w:b"),), smoke=True),
    Construct("emph", rf"\emph{{{S}}}", styles=((S, "w:i"),)),
    Construct("textit", rf"\textit{{{S}}}", styles=((S, "w:i"),)),
    Construct("texttt", rf"\texttt{{{S}}}"),
    Construct("underline", rf"\underline{{{S}}}", styles=((S, "w:u"),)),
    Construct("textsc", rf"\textsc{{{S}}}", styles=((S, "w:smallCaps"),)),
    Construct("textsf", rf"\textsf{{{S}}}"),
    Construct("textsl", rf"\textsl{{{S}}}"),
    Construct("textup", rf"\textup{{{S}}}"),
    Construct("bf-decl", rf"{{\bfseries {S}}}", styles=((S, "w:b"),)),
    Construct("it-decl", rf"{{\itshape {S}}}", styles=((S, "w:i"),)),
    Construct("small-decl", rf"{{\small {S}}}"),
    Construct("bold-italic", rf"\textbf{{\textit{{{S}}}}}", styles=((S, "w:b"), (S, "w:i"))),
    Construct("textcolor", rf"\textcolor{{red}}{{{S}}}", styles=((S, "w:color"),), smoke=True),
    Construct("textcolor-rgb", rf"\textcolor[rgb]{{0,0.5,0}}{{{S}}}", styles=((S, "w:color"),)),
    Construct("textcolor-mix", rf"\textcolor{{blue!60!black}}{{{S}}}", styles=((S, "w:color"),)),
    Construct("color-decl", rf"{{\color{{red}}{S}}}", styles=((S, "w:color"),)),
    Construct("colorbox", rf"\colorbox{{yellow}}{{{S}}}"),
    Construct("hl", rf"\hl{{{S}}}", styles=((S, "w:highlight"),)),
    Construct("sout", rf"\sout{{{S}}}", styles=((S, "w:strike"),)),
    Construct("st", rf"\st{{{S}}}", styles=((S, "w:strike"),)),
    Construct("uline", rf"\uline{{{S}}}", styles=((S, "w:u"),)),
    Construct("superscript", rf"x\textsuperscript{{{S}}}", styles=((S, "w:vertAlign"),)),
    Construct("subscript", rf"x\textsubscript{{{S}}}", styles=((S, "w:vertAlign"),)),
    Construct("footnote", rf"word\footnote{{{S}}}", fragile=True, smoke=True),
    Construct("footnote-protect", rf"word\protect\footnote{{{S}}}"),
    Construct("citet", rf"\citet{{tk1991}} {S}", texts=("Tversky",), smoke=True),
    Construct("citep", rf"\citep{{tk1991}} {S}", texts=("Tversky",)),
    Construct("citep-notes", rf"\citep[see][p.~3]{{tk1991}} {S}", texts=("see", "p. 3", "Tversky")),
    Construct("cite-multi", rf"\citep{{tk1991,laibson1997}} {S}", texts=("Tversky", "Laibson")),
    Construct("citeauthor", rf"\citeauthor{{laibson1997}} {S}", texts=("Laibson",)),
    Construct("citeyear", rf"\citeyear{{laibson1997}} {S}", texts=("1997",)),
    Construct("citealp", rf"\citealp{{tk1991}} {S}", texts=("Tversky",),
              absent=("(Tversky",)),
    Construct("ref", rf"Section~\ref{{sec:target}} {S}", smoke=True),
    Construct("eqref", rf"\eqref{{eq:target}} {S}"),
    Construct("cref", rf"\cref{{sec:target}} {S}"),
    Construct("autoref", rf"\autoref{{sec:target}} {S}"),
    Construct("nameref", rf"\nameref{{sec:target}} {S}", texts=("Target",),
              counts=(("Target", 2),)),
    Construct("pageref", rf"page~\pageref{{sec:target}} {S}"),
    Construct("hyperref-text", rf"\hyperref[sec:target]{{{S}}}"),
    Construct("url", rf"\url{{https://example.org/a_b/{S}}}", fragile=True),
    Construct("href", rf"\href{{https://example.org/x_y}}{{{S}}}"),
    Construct("href-mail", rf"\href{{mailto:a@b.org}}{{{S}}}"),
    Construct("nolinkurl", rf"\nolinkurl{{a/b_{S}}}"),
    Construct("verb", rf"\verb|{S}_x|", verbatim=True, texts=(f"{S}_x",)),
    Construct("verb-backslash", rf"\verb|\{S}|", verbatim=True, texts=(f"\\{S}",),
              allow_backslash=True),
    Construct("lstinline", rf"\lstinline|{S}|", verbatim=True),
    Construct("math-inline", rf"$x^2 + \mathrm{{{S}}}$"),
    Construct("math-paren", rf"\(y_1\) {S}"),
    Construct("math-text", rf"$a \text{{ if {S}}}$"),
    Construct("ensuremath", rf"\ensuremath{{\alpha}} {S}", texts=("α",)),
    Construct("accent-acute", rf"caf\'e {S}", texts=("café",)),
    Construct("accent-braced", rf"na\"{{\i}}ve {S}", texts=("naïve",)),
    Construct("accent-cedilla", rf"\c{{c}}a {S}", texts=("ça",)),
    Construct("accent-caron", rf"\v{{s}}i {S}", texts=("ši",)),
    Construct("accent-tilde", rf"ma\~nana {S}", texts=("mañana",)),
    Construct("special-letters", rf"\ss\ \o\ \aa\ \l\ \AE {S}", texts=("ß", "ø", "å", "ł", "Æ")),
    Construct("unicode-direct", f"Ærøskøbing über {S}", texts=("Ærøskøbing über",)),
    Construct("quotes", f"``{S}''", absent=("``", "''")),
    Construct("enquote", rf"\enquote{{{S}}}"),
    Construct("dashes", f"1--2 a---b {S}", texts=("1–2", "a—b")),
    Construct("specials", rf"\& \% \$ \# \_ {S}", texts=("& % $ # _",)),
    Construct("braces", rf"\{{x\}} {S}", texts=("{x}",), allow_braces=True),
    Construct("textbackslash", rf"a\textbackslash{{}}b {S}", texts=("a\\b",),
              allow_backslash=True),
    Construct("tilde-space", rf"Dr.~Smith {S}", texts=("Dr. Smith",)),
    Construct("logos", rf"\LaTeX{{}} and \TeX{{}} {S}", texts=("LaTeX", "TeX")),
    Construct("symbols", rf"\S 3 \P\ \dag\ \ddag\ \copyright\ \textregistered {S}",
              texts=("§", "¶", "†", "‡", "©", "®")),
    Construct("text-symbols", rf"\textdegree\ \texttimes\ \textpm\ \textmu {S}",
              texts=("°", "×", "±", "µ")),
    Construct("pounds-euro", rf"\pounds 3 \texteuro 4 {S}", texts=("£", "€")),
    Construct("dots", rf"a\ldots b\dots {S}", texts=("a…b…",)),
    Construct("checkmark", rf"\checkmark\ \ding{{51}} {S}", texts=("✓",)),
    Construct("siunitx-SI", rf"\SI{{3.5}}{{\meter}} {S}", texts=("3.5", "m")),
    Construct("siunitx-qty", rf"\qty{{2}}{{\kilo\gram}} {S}", texts=("2", "kg")),
    Construct("siunitx-num", rf"\num{{12345}} {S}", texts=("12",)),
    Construct("siunitx-si", rf"\si{{\percent}} {S}", texts=("%",)),
    Construct("siunitx-range", rf"\SIrange{{1}}{{5}}{{\second}} {S}", texts=("1", "5", "s")),
    Construct("mbox", rf"\mbox{{{S}}}"),
    Construct("fbox", rf"\fbox{{{S}}}"),
    Construct("makebox", rf"\makebox[3cm][l]{{{S}}}"),
    Construct("raisebox", rf"\raisebox{{2pt}}{{{S}}}"),
    Construct("parbox", rf"\parbox{{3cm}}{{{S}}}"),
    Construct("scalebox", rf"\scalebox{{0.8}}{{{S}}}"),
    Construct("rotatebox", rf"\rotatebox{{90}}{{{S}}}"),
    Construct("resizebox", rf"\resizebox{{2cm}}{{!}}{{{S}}}"),
    Construct("phantom", rf"\phantom{{zz}}{S}", absent=("zz",)),
    Construct("hspace", rf"a\hspace{{1em}}b {S}"),
    Construct("hfill", rf"a\hfill {S}"),
    Construct("quad", rf"a\quad b\qquad {S}"),
    Construct("vspace-inline", rf"a\vspace{{2pt}} {S}"),
    Construct("newline", rf"a\newline {S}"),
    Construct("linebreak-spacing", rf"a\\[2pt] {S}", no_cell=True),
    Construct("linebreak-star", rf"a\\* {S}", no_cell=True),
    Construct("today", rf"\today{{}} {S}"),
    Construct("texorpdfstring", rf"\texorpdfstring{{{S}}}{{PDFONLY}}", absent=("PDFONLY",)),
    Construct("MakeUppercase", r"\MakeUppercase{qx7k}", counts=((S.upper(), 1),),
              texts=(S.upper(),)),
    Construct("protect", rf"\protect\textbf{{{S}}}"),
    Construct("label-inline", rf"{S}\label{{lbl:inline}}"),
    Construct("index", rf"{S}\index{{IDXTERM}}", absent=("IDXTERM",)),
    Construct("multicolumn", rf"\multicolumn{{1}}{{c}}{{{S}}}", cell_only=True),
    Construct("cellcolor", rf"\cellcolor{{yellow}}{S}", cell_only=True),
    Construct("makecell", rf"\makecell{{{S}\\b}}", texts=("b",)),
    Construct("shortstack", rf"\shortstack{{{S}\\b}}", texts=("b",)),
    Construct("inline-tabular", rf"\begin{{tabular}}{{l}}{S}\end{{tabular}}"),
    Construct("foreignlanguage", rf"\foreignlanguage{{french}}{{{S}}}"),
    Construct("emph-nested", rf"\emph{{a \emph{{{S}}}}}"),
)

_HEAD = r"\title{T}\author{A}\date{}\maketitle"

CONTEXTS: tuple[Context, ...] = (
    Context("para", "Lead %X tail.", smoke=True),
    Context("section", r"\section{%X}", slot="moving", smoke=True),
    Context("subsection", r"\subsection{%X}", slot="moving"),
    Context("section-star", r"\section*{%X}", slot="moving"),
    Context("paragraph-head", r"\paragraph{%X} Body.", slot="moving"),
    Context("appendix-section", r"\appendix\section{%X}", slot="moving"),
    Context("caption-figure",
            r"\begin{figure}[h]\centering\includegraphics[width=2cm]{img.png}"
            r"\caption{%X}\label{fig:probe}\end{figure}", slot="moving", smoke=True),
    Context("caption-table",
            r"\begin{table}[h]\centering\caption{%X}\label{tab:probe}"
            r"\begin{tabular}{ll}\toprule a & b\\\bottomrule\end{tabular}\end{table}",
            slot="moving", smoke=True),
    Context("caption-short",
            r"\begin{figure}[h]\centering\includegraphics[width=2cm]{img.png}"
            r"\caption[ShortCap]{%X}\end{figure}", slot="moving"),
    Context("caption-below-table",
            r"\begin{table}[h]\centering\begin{tabular}{ll}a & b\\\end{tabular}"
            r"\caption{%X}\end{table}", slot="moving"),
    Context("subcaption",
            r"\begin{figure}[h]\centering"
            r"\begin{subfigure}{0.45\textwidth}\centering\includegraphics[width=2cm]{img.png}"
            r"\caption{%X}\end{subfigure}\hfill"
            r"\begin{subfigure}{0.45\textwidth}\centering\includegraphics[width=2cm]{img.png}"
            r"\caption{Other}\end{subfigure}\caption{Main}\end{figure}", slot="moving"),
    Context("captionof",
            r"\begin{center}\includegraphics[width=2cm]{img.png}"
            r"\captionof{figure}{%X}\end{center}", slot="moving"),
    Context("caption-algorithm",
            r"\begin{algorithm}\caption{%X}\begin{algorithmic}\State $x \gets 1$"
            r"\end{algorithmic}\end{algorithm}", slot="moving"),
    Context("algorithmic-state",
            r"\begin{algorithm}\caption{Alg}\begin{algorithmic}\State %X"
            r"\end{algorithmic}\end{algorithm}", slot="arg"),
    Context("caption-figure-star",
            r"\begin{figure*}[t]\centering\includegraphics[width=2cm]{img.png}"
            r"\caption{%X}\end{figure*}", slot="moving"),
    Context("caption-wrapfigure",
            r"\begin{wrapfigure}{r}{0.3\textwidth}\centering"
            r"\includegraphics[width=2cm]{img.png}\caption{%X}\end{wrapfigure}Text around.",
            slot="moving"),
    Context("table-cell",
            r"\begin{tabular}{ll}\toprule A & B\\\midrule x & %X\\\bottomrule\end{tabular}",
            cell=True, smoke=True),
    Context("table-header",
            r"\begin{tabular}{ll}\toprule %X & B\\\midrule x & y\\\bottomrule\end{tabular}",
            cell=True),
    Context("pcol-cell", r"\begin{tabular}{p{4cm}l} %X & y\\\end{tabular}", cell=True),
    Context("tabularx-cell",
            r"\begin{tabularx}{\textwidth}{lX} x & %X\\\end{tabularx}", cell=True),
    Context("longtable-cell",
            r"\begin{longtable}{ll}\caption{LT}\\\toprule A & B\\\midrule\endhead"
            r" x & %X\\\bottomrule\end{longtable}", cell=True),
    Context("table-float-cell",
            r"\begin{table}[h]\centering\caption{T}\begin{tabular}{ll} x & %X\\"
            r"\end{tabular}\end{table}", cell=True, smoke=True),
    Context("table-star-cell",
            r"\begin{table*}[t]\centering\caption{T}\begin{tabular}{ll} x & %X\\"
            r"\end{tabular}\end{table*}", cell=True),
    Context("multicolumn-cell",
            r"\begin{tabular}{lll} a & \multicolumn{2}{c}{%X}\\ b & c & d\\\end{tabular}",
            slot="arg", cell=True),
    Context("multirow-cell",
            r"\begin{tabular}{ll} \multirow{2}{*}{%X} & a\\ & b\\\end{tabular}",
            slot="arg", cell=True),
    Context("makecell-cell", r"\begin{tabular}{l} \makecell{%X\\ second}\\\end{tabular}",
            slot="arg", cell=True),
    Context("resizebox-table",
            r"\begin{table}[h]\centering\caption{T}\resizebox{\textwidth}{!}{"
            r"\begin{tabular}{ll} x & %X\\\end{tabular}}\end{table}", slot="arg", cell=True),
    Context("adjustbox-table",
            r"\begin{adjustbox}{width=\textwidth}\begin{tabular}{ll} x & %X\\"
            r"\end{tabular}\end{adjustbox}", slot="arg", cell=True),
    Context("sidewaystable-cell",
            r"\begin{sidewaystable}\centering\caption{T}\begin{tabular}{ll} x & %X\\"
            r"\end{tabular}\end{sidewaystable}", cell=True),
    Context("threeparttable-note",
            r"\begin{table}[h]\centering\begin{threeparttable}\caption{T}"
            r"\begin{tabular}{l} a\tnote{a}\\\end{tabular}"
            r"\begin{tablenotes}\item[a] %X\end{tablenotes}\end{threeparttable}\end{table}"),
    Context("side-by-side-tables",
            r"\begin{table}[h]\begin{minipage}{.45\linewidth}\centering\caption{Left}"
            r"\begin{tabular}{l} %X\\\end{tabular}\end{minipage}\hfill"
            r"\begin{minipage}{.45\linewidth}\centering\caption{Right}"
            r"\begin{tabular}{l} y\\\end{tabular}\end{minipage}\end{table}", cell=True),
    Context("list-in-cell",
            r"\begin{tabular}{p{5cm}}\begin{itemize}\item %X\end{itemize}\\\end{tabular}"),
    Context("theorem", r"\begin{theorem}%X\end{theorem}", smoke=True),
    Context("theorem-title", r"\begin{theorem}[%X] Body.\end{theorem}", slot="moving"),
    Context("definition", r"\begin{definition}%X\end{definition}"),
    Context("proof", r"\begin{proof}%X\end{proof}"),
    Context("itemize-in-theorem",
            r"\begin{theorem}\begin{itemize}\item %X\end{itemize}\end{theorem}"),
    Context("itemize", r"\begin{itemize}\item %X\end{itemize}", smoke=True),
    Context("enumerate-deep",
            r"\begin{enumerate}\item a\begin{enumerate}\item b\begin{enumerate}\item %X"
            r"\end{enumerate}\end{enumerate}\end{enumerate}"),
    Context("description-label",
            r"\begin{description}\item[%X] Body.\end{description}", slot="arg"),
    Context("description-body", r"\begin{description}\item[Term] %X\end{description}"),
    Context("enumitem-label", r"\begin{enumerate}[label=(\alph*)]\item %X\end{enumerate}"),
    Context("table-in-itemize",
            r"\begin{itemize}\item\begin{tabular}{l} %X\\\end{tabular}\end{itemize}",
            cell=True),
    Context("footnote", r"Text\footnote{%X} more.", slot="arg", smoke=True),
    Context("marginpar", r"Text\marginpar{%X} more.", slot="arg"),
    Context("minipage", r"\begin{minipage}{0.5\textwidth}%X\end{minipage}"),
    Context("minipage-row",
            r"\noindent\begin{minipage}{.48\textwidth}%X\end{minipage}\hfill"
            r"\begin{minipage}{.48\textwidth}Right\end{minipage}"),
    Context("center", r"\begin{center}%X\end{center}"),
    Context("flushright", r"\begin{flushright}%X\end{flushright}"),
    Context("quote", r"\begin{quote}%X\end{quote}"),
    Context("quotation", r"\begin{quotation}%X\end{quotation}"),
    Context("multicols", r"\begin{multicols}{2}%X\end{multicols}"),
    Context("landscape", r"\begin{landscape}%X\end{landscape}"),
    Context("tcolorbox", r"\begin{tcolorbox}%X\end{tcolorbox}", smoke=True),
    Context("tcolorbox-title", r"\begin{tcolorbox}[title={%X}]Body\end{tcolorbox}",
            slot="arg"),
    Context("mdframed", r"\begin{mdframed}%X\end{mdframed}"),
    Context("framed", r"\begin{framed}%X\end{framed}"),
    Context("figure-text-body",
            r"\begin{figure}[h]\centering\begin{minipage}{0.8\textwidth}%X\end{minipage}"
            r"\caption{Box}\end{figure}"),
    Context("fbox-parbox", r"\fbox{\parbox{5cm}{%X}}", slot="arg"),
    Context("fbox", r"\fbox{%X}", slot="arg"),
    Context("parbox", r"\parbox{4cm}{%X}", slot="arg"),
    Context("mbox", r"\mbox{%X}", slot="arg"),
    Context("textcolor-span", r"\textcolor{blue}{A %X}", slot="arg"),
    Context("emph-span", r"\emph{A %X}", slot="arg"),
    Context("textbf-span", r"\textbf{A %X}", slot="arg"),
    Context("size-group", r"{\small A %X}"),
    Context("color-decl-group", r"{\color{red} A %X}"),
    Context("href-text", r"\href{https://example.org}{A %X}", slot="arg"),
    Context("title", head=r"\title{%X}\author{A}\date{}\maketitle", body="", slot="moving",
            smoke=True),
    Context("author", head=r"\title{T}\author{%X}\date{}\maketitle", body="", slot="moving"),
    Context("thanks", head=r"\title{T\thanks{%X}}\author{A}\date{}\maketitle", body="",
            slot="moving"),
    Context("date", head=r"\title{T}\author{A}\date{%X}\maketitle", body="", slot="moving"),
    Context("abstract", head=_HEAD + r"\begin{abstract}%X\end{abstract}", body="",
            smoke=True),
)


def compatible(c: Construct, x: Context) -> bool:
    """True if the construct is legal LaTeX in the context's slot."""
    if c.verbatim and x.slot != "body":
        return False
    if c.fragile and x.slot == "moving":
        return False
    # \multicolumn/\cellcolor act on the cell itself: not inside a cell's argument
    if c.cell_only and (not x.cell or x.slot != "body"):
        return False
    if c.no_cell and x.cell:
        return False
    # a footnote inside a footnote/marginpar is not meaningful LaTeX
    if c.name.startswith("footnote") and x.name in ("footnote", "marginpar", "thanks"):
        return False
    return True


def build(c: Construct, x: Context) -> Probe:
    frag = x.body.replace("%X", c.latex) if x.body else x.head.replace("%X", c.latex)
    head = x.head.replace("%X", c.latex) if x.head else ""
    body = x.body.replace("%X", c.latex) if x.body else ""
    source = PREAMBLE + "\\begin{document}\n" + head + "\n" + TARGETS + body + TAIL
    exp = Expect(
        texts=list(c.texts),
        absent=list(c.absent),
        counts=dict(c.counts),
        styles=dict(c.styles),
        allow_warnings=list(x.allow),
        allow_dims=c.allow_dims,
        allow_braces=c.allow_braces,
        allow_backslash=c.allow_backslash,
    )
    if x.name == "caption-short":
        exp.absent.append("ShortCap")
    return Probe(
        id=f"matrix/{c.name}@{x.name}",
        source=source,
        expect=exp,
        tier="smoke" if (c.smoke and x.smoke) else "full",
        tags={"construct": c.name, "context": x.name},
        fragment=frag,
        note=f"{c.name} inside {x.name}",
    )


def probes() -> list[Probe]:
    return [build(c, x) for c in CONSTRUCTS for x in CONTEXTS if compatible(c, x)]
