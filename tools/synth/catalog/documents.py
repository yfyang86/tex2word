"""Document-level probes: macros, conditionals, files, structure, lists,
floats, verbatim, bibliographies, cross-references and robustness.

Each probe is a small complete document with explicit expectations. Tokens
like ``KEEP1`` must survive, ``DROP1`` must not (e.g. inside ``\\iffalse``).
"""

from __future__ import annotations

from .. import SENTINEL as S
from ..assets import png
from ..model import Expect, Probe

BASE = r"""\documentclass{%(cls)s}
\usepackage{amsmath,amssymb,amsthm,graphicx,xcolor,hyperref}
%(pre)s
\begin{document}
%(body)s
\end{document}
"""

_ALL: list[Probe] = []


def D(name: str, body: str, *, pre: str = "", cls: str = "article", note: str = "",
      files: dict | None = None, smoke: bool = False, raw_source: str | None = None,
      **expect) -> None:
    src = raw_source if raw_source is not None else BASE % {"cls": cls, "pre": pre, "body": body}
    _ALL.append(Probe(
        id=f"doc/{name}", source=src, expect=Expect(**expect), files=files or {},
        note=note or name, fragment=body if raw_source is None else raw_source[:300],
        tier="smoke" if smoke else "full", tags={"construct": name, "context": "document"},
    ))


# -- macros ------------------------------------------------------------------ #
D("newcommand-args", r"\newcommand{\pair}[2]{(#1, #2)}\pair{KEEP1}{KEEP2}",
  texts=["(KEEP1, KEEP2)"], smoke=True)
D("newcommand-optional", r"\newcommand{\greet}[2][Hello]{#1, #2!}\greet{KEEP1} \greet[Hi]{KEEP2}",
  texts=["Hello, KEEP1!", "Hi, KEEP2!"])
D("renewcommand", r"\newcommand{\x}{DROP1}\renewcommand{\x}{KEEP1}\x", texts=["KEEP1"],
  absent=["DROP1"])
D("providecommand-existing", r"\providecommand{\LaTeX}{DROP1}\LaTeX{} KEEP1",
  texts=["LaTeX", "KEEP1"], absent=["DROP1"])
D("def-params", r"\def\br#1{[#1]}\br{KEEP1}", texts=["[KEEP1]"])
D("def-delimited", r"\def\pt(#1,#2){#1+#2}\pt(KEEP1,KEEP2) done", texts=["KEEP1+KEEP2 done"])
D("let-alias", r"\let\strong\textbf \strong{KEEP1}", texts=["KEEP1"], styles={"KEEP1": "w:b"})
D("newcommand-star", r"\newcommand*{\nm}{KEEP1}\nm", texts=["KEEP1"])
D("nested-macros", r"\newcommand{\inner}[1]{<#1>}\newcommand{\outer}[1]{\inner{\inner{#1}}}"
  r"\outer{KEEP1}", texts=["<<KEEP1>>"])
D("xparse-command", r"\NewDocumentCommand{\nd}{m o}{#1\IfValueT{#2}{/#2}}\nd{KEEP1}[KEEP2]",
  texts=["KEEP1/KEEP2"])
D("declare-robust", r"\DeclareRobustCommand{\rb}[1]{*#1*}\rb{KEEP1}", texts=["*KEEP1*"])
D("macro-in-preamble-uses-textbf", r"\important{KEEP1}",
  pre=r"\newcommand{\important}[1]{\textbf{\textcolor{red}{#1}}}",
  texts=["KEEP1"], styles={"KEEP1": "w:b"})
D("newenvironment", r"\begin{note}KEEP1\end{note}",
  pre=r"\newenvironment{note}{\begin{quote}\textbf{Note:} }{\end{quote}}",
  texts=["Note:", "KEEP1"], smoke=True)
D("newenvironment-args", r"\begin{boxed}{KEEP1}KEEP2\end{boxed}",
  pre=r"\newenvironment{boxed}[1]{\par\textbf{#1}: }{\par}", texts=["KEEP1", "KEEP2"])
D("renewenvironment", r"\begin{quote}KEEP1\end{quote}",
  pre=r"\renewenvironment{quote}{\begin{center}}{\end{center}}", texts=["KEEP1"])
D("xparse-environment", r"\begin{card}{KEEP1}KEEP2\end{card}",
  pre=r"\NewDocumentEnvironment{card}{m}{\textbf{#1} }{}", texts=["KEEP1", "KEEP2"])
D("recursive-macro-no-hang", r"\newcommand{\loopy}{\loopy}KEEP1 \loopy",
  texts=["KEEP1"], allow_warnings=[".*"], allow_raw=True, allow_backslash=True,
  note="self-recursive macro must not hang")
D("csname", r"\expandafter\def\csname kp\endcsname{KEEP1}\kp", texts=["KEEP1"])
D("makeatletter-macro", r"\makeatletter\newcommand{\my@x}{KEEP1}\my@x\makeatother",
  texts=["KEEP1"])
D("counter-value", r"\newcounter{cnt}\setcounter{cnt}{5}\stepcounter{cnt}N\arabic{cnt} "
  r"R\roman{cnt} A\Alph{cnt}", texts=["N6", "Rvi", "AF"])
D("the-counter", r"\newcounter{cnt}\setcounter{cnt}{3}V\thecnt", texts=["V3"])
D("setlength-silent", r"\newlength{\gap}\setlength{\gap}{3pt}\addtolength{\gap}{1pt}KEEP1",
  texts=["KEEP1"])
# -- conditionals -------------------------------------------------------------- #
D("newif-true", r"\newif\ifdraft\drafttrue \ifdraft KEEP1\else DROP1\fi",
  texts=["KEEP1"], absent=["DROP1"], smoke=True)
D("newif-false", r"\newif\ifdraft\draftfalse \ifdraft DROP1\else KEEP1\fi",
  texts=["KEEP1"], absent=["DROP1"])
D("iffalse-block", "KEEP1\n\\iffalse\nDROP1 \\section{DROP2}\n\\fi\nKEEP2",
  texts=["KEEP1", "KEEP2"], absent=["DROP1", "DROP2"], smoke=True,
  note="\\iffalse ... \\fi is a common way to comment out text")
D("iftrue-block", r"\iftrue KEEP1\else DROP1\fi", texts=["KEEP1"], absent=["DROP1"])
D("ifdefined", r"\ifdefined\undefinedthing DROP1\else KEEP1\fi", texts=["KEEP1"],
  absent=["DROP1"])
D("ifthenelse", r"\newboolean{long}\setboolean{long}{true}"
  r"\ifthenelse{\boolean{long}}{KEEP1}{DROP1}", pre=r"\usepackage{ifthen}",
  texts=["KEEP1"], absent=["DROP1"])
D("iffileexists", r"\IfFileExists{refs.bib}{KEEP1}{DROP1}", texts=["KEEP1"], absent=["DROP1"])
D("ifpackageloaded", r"\makeatletter\@ifpackageloaded{hyperref}{KEEP1}{DROP1}\makeatother",
  texts=["KEEP1"], absent=["DROP1"])
D("comment-env", "KEEP1\n\\begin{comment}\nDROP1\n\\end{comment}\nKEEP2",
  pre=r"\usepackage{comment}", texts=["KEEP1", "KEEP2"], absent=["DROP1"])
D("percent-comments", "KEEP1 % DROP1\nKEEP2 50\\% off", texts=["KEEP1", "KEEP2 50% off"],
  absent=["DROP1"])
D("atbegindocument", r"KEEP2", pre=r"\AtBeginDocument{KEEP1}", texts=["KEEP2"])
# -- files ------------------------------------------------------------------------ #
D("input-file", r"\input{part}", files={"part.tex": "KEEP1 from part"}, texts=["KEEP1"],
  smoke=True)
D("input-no-braces", "\\input part\n", files={"part.tex": "KEEP1 from part"}, texts=["KEEP1"],
  note="plain-TeX \\input part (no braces)")
D("include-file", r"\include{chap}", files={"chap.tex": r"\section{KEEP1}KEEP2"},
  texts=["KEEP1", "KEEP2"])
D("input-subdir-nested", r"\input{sec/a}",
  files={"sec/a.tex": r"A1 \input{sec/b}", "sec/b.tex": "KEEP1"}, texts=["A1", "KEEP1"])
D("subfile", r"\subfile{sub}", pre=r"\usepackage{subfiles}",
  files={"sub.tex": "\\documentclass[main]{subfiles}\n\\begin{document}\nKEEP1\n"
         "\\end{document}\n"}, texts=["KEEP1"],
  note="subfiles: only the subfile's body is inlined")
D("input-missing", r"KEEP1 \input{nothere} KEEP2", texts=["KEEP1", "KEEP2"],
  allow_warnings=[".*"])
D("endinput", r"\input{part}KEEP2", files={"part.tex": "KEEP1\n\\endinput\nDROP1"},
  texts=["KEEP1", "KEEP2"], absent=["DROP1"])
D("crlf-bom", "", raw_source="\ufeff\\documentclass{article}\r\n\\begin{document}\r\n"
  "\\section{KEEP1}\r\nKEEP2 line\r\n\r\nKEEP3\r\n\\end{document}\r\n",
  texts=["KEEP1", "KEEP2", "KEEP3"], note="Windows line endings and a UTF-8 BOM")
D("tabs-and-spaces", "KEEP1\t\tKEEP2   \t KEEP3", texts=["KEEP1 KEEP2 KEEP3"])
D("graphicspath", r"\graphicspath{{figs/}}\begin{figure}\includegraphics{pic}\caption{C}"
  r"\end{figure}", files={"figs/pic.png": png()}, xml=[r"<a:blip "])
D("includegraphics-no-ext", r"\begin{figure}\includegraphics[width=3cm]{img}\caption{C}"
  r"\end{figure}", xml=[r"<a:blip "])
D("includegraphics-missing", r"\begin{figure}\includegraphics{nope}\caption{KEEP1}"
  r"\end{figure}", texts=["KEEP1"], allow_warnings=[".*"])
# -- structure --------------------------------------------------------------------- #
D("setcounter-section", r"\setcounter{section}{4}\section{KEEP1}\label{s}See \ref{s}.",
  texts=["KEEP1"], note="the section is numbered 5")
D("section-short-title", r"\section[DROP1]{KEEP1}", texts=["KEEP1"], absent=["DROP1"])
D("section-footnote", r"\section{KEEP1\protect\footnote{KEEP2}}", texts=["KEEP1", "KEEP2"])
D("chapter-report", r"\chapter{KEEP1}\section{KEEP2}", cls="report", texts=["KEEP1", "KEEP2"])
D("book-matter", r"\frontmatter\chapter{KEEP1}\mainmatter\chapter{KEEP2}\backmatter"
  r"\chapter{KEEP3}", cls="book", texts=["KEEP1", "KEEP2", "KEEP3"])
D("part", r"\part{KEEP1}\section{KEEP2}", texts=["KEEP1", "KEEP2"])
D("appendix-numbering", r"\section{A}\appendix\section{KEEP1}\label{app}See \ref{app}.",
  texts=["KEEP1"])
D("toc-lists", r"\tableofcontents\listoffigures\listoftables\section{KEEP1}", texts=["KEEP1"])
D("maketitle-and", r"\title{KEEP1}\author{KEEP2 \and KEEP3}\date{KEEP4}\maketitle",
  texts=["KEEP1", "KEEP2", "KEEP3", "KEEP4"], smoke=True)
D("maketitle-thanks", r"\title{T}\author{A\thanks{KEEP1}}\maketitle KEEP2",
  texts=["KEEP1", "KEEP2"])
D("abstract-keywords", r"\title{T}\maketitle\begin{abstract}KEEP1\end{abstract}",
  texts=["KEEP1"])
D("titlepage-env", r"\begin{titlepage}\centering{\Large KEEP1\par}\vspace{1cm}KEEP2"
  r"\end{titlepage}", texts=["KEEP1", "KEEP2"])
D("paragraph-subparagraph", r"\paragraph{KEEP1} text \subparagraph{KEEP2} more",
  texts=["KEEP1", "KEEP2"])
D("section-star-addcontents", r"\section*{KEEP1}\addcontentsline{toc}{section}{DROP1}",
  texts=["KEEP1"], absent=["DROP1"])
D("acknowledgments-env", r"\begin{acknowledgments}KEEP1\end{acknowledgments}"
  r"\begin{acknowledgements}KEEP2\end{acknowledgements}",
  pre=r"\newenvironment{acknowledgments}{\section*{Acknowledgments}}{}"
  r"\newenvironment{acknowledgements}{\section*{Acknowledgements}}{}", texts=["KEEP1", "KEEP2"])
# -- lists ------------------------------------------------------------------------- #
D("itemize-4-deep", r"\begin{itemize}\item a\begin{itemize}\item b\begin{itemize}\item c"
  r"\begin{itemize}\item KEEP1\end{itemize}\end{itemize}\end{itemize}\end{itemize}",
  texts=["KEEP1"])
D("enumerate-custom-item", r"\begin{enumerate}\item[(x)] KEEP1\item KEEP2\end{enumerate}",
  texts=["(x)", "KEEP1", "KEEP2"])
D("enumitem-start", r"\begin{enumerate}[start=5,label=\Roman*.]\item KEEP1\end{enumerate}",
  pre=r"\usepackage{enumitem}", texts=["KEEP1"])
D("item-label-ref", r"\begin{enumerate}\item\label{it:a} KEEP1\end{enumerate}See \ref{it:a}.",
  texts=["KEEP1"], labels=["it:a"])
D("description-long", r"\begin{description}\item[KEEP1] KEEP2\item[KEEP3] KEEP4"
  r"\end{description}", texts=["KEEP1", "KEEP2", "KEEP3", "KEEP4"])
D("compactitem", r"\begin{compactitem}\item KEEP1\end{compactitem}"
  r"\begin{inparaenum}\item KEEP2 \item KEEP3\end{inparaenum}", pre=r"\usepackage{paralist}",
  texts=["KEEP1", "KEEP2", "KEEP3"])
D("list-env", r"\begin{list}{$\bullet$}{\setlength{\leftmargin}{1em}}\item KEEP1\end{list}",
  texts=["KEEP1"])
D("empty-item", r"\begin{itemize}\item\item KEEP1\end{itemize}", texts=["KEEP1"])
D("item-paragraphs", "\\begin{itemize}\\item KEEP1\n\nKEEP2\\end{itemize}",
  texts=["KEEP1", "KEEP2"])
# -- tables -------------------------------------------------------------------------- #
D("tabular-rules-spans", r"\begin{tabular}{|l|c|r|}\hline \multicolumn{2}{|c|}{KEEP1} & x\\"
  r"\cline{1-2} a & b & c\\\hline\end{tabular}", texts=["KEEP1"], smoke=True,
  xml=[r'<w:gridSpan w:val="2"/>'])
D("multirow-span", r"\begin{tabular}{ll}\multirow{2}{*}{KEEP1} & a\\ & b\\\end{tabular}",
  pre=r"\usepackage{multirow}", texts=["KEEP1"], xml=[r"<w:vMerge"])
D("rowcolor", r"\begin{tabular}{l}\rowcolor{gray!20} KEEP1\\ KEEP2\\\end{tabular}",
  pre=r"\usepackage[table]{xcolor}", texts=["KEEP1", "KEEP2"], xml=[r"<w:shd "])
D("rowcolors", r"\rowcolors{1}{white}{gray!10}\begin{tabular}{l} KEEP1\\ KEEP2\\\end{tabular}",
  pre=r"\usepackage[table]{xcolor}", texts=["KEEP1", "KEEP2"])
D("cmidrule", r"\begin{tabular}{lll}\toprule & \multicolumn{2}{c}{KEEP1}\\"
  r"\cmidrule(lr){2-3} a & b & c\\\bottomrule\end{tabular}", pre=r"\usepackage{booktabs}",
  texts=["KEEP1"], absent=["(lr)", "2-3"])
D("siunitx-S-column", r"\begin{tabular}{lS}x & 1.25\\ y & 10.5\\\end{tabular}",
  pre=r"\usepackage{siunitx}", texts=["1.25", "10.5"])
D("colspec-at-and-bold", r"\begin{tabular}{@{}>{\bfseries}l@{\hspace{4pt}}r@{}}KEEP1 & 2\\"
  r"\end{tabular}", pre=r"\usepackage{array}", texts=["KEEP1"], styles={"KEEP1": "w:b"})
D("tablefootnote", r"\begin{table}\caption{T}\begin{tabular}{l}x\tablefootnote{KEEP1}\\"
  r"\end{tabular}\end{table}", pre=r"\usepackage{tablefootnote}", texts=["KEEP1"])
D("longtable-heads", r"\begin{longtable}{ll}\caption{KEEP1}\\ A & B\\\endfirsthead "
  r"A & B (cont.)\\\endhead FOOTROW & x\\\endfoot x & KEEP2\\\end{longtable}",
  pre=r"\usepackage{longtable}", texts=["KEEP1", "KEEP2"], absent=["(cont.)"],
  note="page 1 shows the \\endfirsthead header, not the (cont.) one; the body is kept")
D("tabular-star", r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}ll}KEEP1 & KEEP2\\"
  r"\end{tabular*}", texts=["KEEP1", "KEEP2"])
D("tabularx-centering", r"\begin{tabularx}{\linewidth}{>{\centering\arraybackslash}X X}"
  r"KEEP1 & KEEP2\\\end{tabularx}", pre=r"\usepackage{tabularx}", texts=["KEEP1", "KEEP2"])
D("graphic-in-cell", r"\begin{tabular}{ll}\includegraphics[width=1cm]{img.png} & KEEP1\\"
  r"\end{tabular}", texts=["KEEP1"], xml=[r"<a:blip "])
D("table-H-placement", r"\begin{table}[H]\centering\caption{KEEP1}\begin{tabular}{l}x\\"
  r"\end{tabular}\end{table}", pre=r"\usepackage{float}", texts=["KEEP1"])
D("tabular-empty-cells", r"\begin{tabular}{lll} & & KEEP1\\ KEEP2 & & \\\end{tabular}",
  texts=["KEEP1", "KEEP2"])
D("tabular-newline-in-cell", r"\begin{tabular}{p{3cm}}KEEP1\newline KEEP2\\\end{tabular}",
  texts=["KEEP1", "KEEP2"])
# -- figures -------------------------------------------------------------------------- #
D("subfigures-refs", r"\begin{figure}\centering"
  r"\begin{subfigure}{.4\textwidth}\includegraphics[width=2cm]{img.png}\caption{KEEP1}"
  r"\label{fig:a}\end{subfigure}"
  r"\begin{subfigure}{.4\textwidth}\includegraphics[width=2cm]{img.png}\caption{KEEP2}"
  r"\label{fig:b}\end{subfigure}\caption{KEEP3}\label{fig:ab}\end{figure}"
  r"See \ref{fig:a}, \subref{fig:b} and \ref{fig:ab}.", pre=r"\usepackage{subcaption}",
  texts=["KEEP1", "KEEP2", "KEEP3"], labels=["fig:a", "fig:b", "fig:ab"], smoke=True)
D("subfig-package", r"\begin{figure}\centering\subfloat[KEEP1\label{fig:s1}]{"
  r"\includegraphics[width=2cm]{img.png}}\subfloat[KEEP2]{\includegraphics[width=2cm]{img.png}}"
  r"\caption{KEEP3}\end{figure}See \ref{fig:s1}.", pre=r"\usepackage{subfig}",
  texts=["KEEP1", "KEEP2", "KEEP3"])
D("figure-caption-above", r"\begin{figure}\caption{KEEP1}\label{f}\includegraphics[width=2cm]"
  r"{img.png}\end{figure}See \ref{f}.", texts=["KEEP1"], labels=["f"])
D("figure-keepaspect", r"\begin{figure}\includegraphics[width=\linewidth,height=3cm,"
  r"keepaspectratio]{img.png}\caption{C}\end{figure}", xml=[r"<a:blip "])
D("figure-angle-trim", r"\begin{figure}\includegraphics[angle=90,trim=1 1 1 1,clip,width=2cm]"
  r"{img.png}\caption{C}\end{figure}", xml=[r"<a:blip "])
D("minipage-captionof-pair", r"\begin{figure}\begin{minipage}{.45\textwidth}\centering"
  r"\includegraphics[width=2cm]{img.png}\captionof{figure}{KEEP1}\label{fa}\end{minipage}"
  r"\hfill\begin{minipage}{.45\textwidth}\centering\includegraphics[width=2cm]{img.png}"
  r"\captionof{figure}{KEEP2}\label{fb}\end{minipage}\end{figure}See \ref{fa} \ref{fb}.",
  pre=r"\usepackage{caption}", texts=["KEEP1", "KEEP2"], labels=["fa", "fb"])
D("figure-two-images-two-captions", r"\begin{figure}\centering\includegraphics[width=2cm]"
  r"{img.png}\caption{KEEP1}\label{f1}\includegraphics[width=2cm]{img.png}\caption{KEEP2}"
  r"\label{f2}\end{figure}\ref{f1} \ref{f2}", texts=["KEEP1", "KEEP2"], labels=["f1", "f2"])
# -- verbatim and code ----------------------------------------------------------------- #
D("verbatim-specials", "\\begin{verbatim}\nKEEP1 % not a comment {}\\foo $x$ & #\n"
  "\\end{verbatim}", texts=["KEEP1 % not a comment {}\\foo $x$ & #"], allow_braces=True,
  allow_backslash=True, smoke=True)
D("lstlisting-caption-label", "\\begin{lstlisting}[language=Python,caption={KEEP1},"
  "label={lst:a}]\nprint('KEEP2')\n\\end{lstlisting}\nSee Listing~\\ref{lst:a}.",
  pre=r"\usepackage{listings}", texts=["KEEP1", "print('KEEP2')"], labels=["lst:a"])
D("minted", "\\begin{minted}{python}\nx = 'KEEP1'\n\\end{minted}", pre=r"\usepackage{minted}",
  texts=["x = 'KEEP1'"])
D("lstinputlisting", r"\lstinputlisting[language=Python]{code.py}", pre=r"\usepackage{listings}",
  files={"code.py": "def f():\n    return 'KEEP1'  # 100%\n"}, texts=["return 'KEEP1'"])
D("verbatiminput", r"\verbatiminput{code.txt}", pre=r"\usepackage{verbatim}",
  files={"code.txt": "KEEP1 \\raw {x}\n"}, texts=["KEEP1 \\raw {x}"], allow_backslash=True,
  allow_braces=True)
D("fancyvrb-Verbatim", "\\begin{Verbatim}[frame=single]\nKEEP1 \\x\n\\end{Verbatim}",
  pre=r"\usepackage{fancyvrb}", texts=["KEEP1 \\x"], absent=["frame=single"],
  allow_backslash=True)
D("alltt", "\\begin{alltt}\nKEEP1 \\textbf{KEEP2}\n\\end{alltt}", pre=r"\usepackage{alltt}",
  texts=["KEEP1", "KEEP2"])
D("verb-percent", r"\verb+50% {x}+ KEEP1", texts=["50% {x}", "KEEP1"], allow_braces=True)
# -- bibliography ------------------------------------------------------------------------ #
D("thebibliography", r"See \cite{kb}.\begin{thebibliography}{9}\bibitem{kb} KEEP1, "
  r"\emph{Title}, 2020.\end{thebibliography}", texts=["KEEP1", "[1]"], smoke=True)
D("biblatex", r"\parencite{knuth1984} and \textcite{tk1991}.\printbibliography",
  pre="\\usepackage[style=authoryear]{biblatex}\n\\addbibresource{refs.bib}",
  texts=["Knuth", "Tversky"])
D("biblatex-numeric", r"\autocite{knuth1984}\printbibliography",
  pre="\\usepackage[style=numeric]{biblatex}\n\\addbibresource{refs.bib}", texts=["[1]"])
D("nocite-star", r"KEEP1\nocite{*}\bibliographystyle{plain}\bibliography{refs}",
  texts=["KEEP1", "Knuth", "Laibson", "Tversky"])
D("cite-missing-key", r"\cite{nokey} KEEP1\bibliographystyle{plain}\bibliography{refs}",
  texts=["KEEP1"], allow_warnings=["nokey"])
D("natbib-numbers", r"\citep{tk1991}\bibliographystyle{plainnat}\bibliography{refs}",
  pre=r"\usepackage[numbers]{natbib}", texts=["[1]"])
D("cite-in-footnote", r"Text\footnote{See \citet{laibson1997}.}"
  r"\bibliographystyle{plainnat}\bibliography{refs}", pre=r"\usepackage{natbib}",
  texts=["Laibson"])
D("bbl-file", r"\cite{zz}\bibliographystyle{plain}\bibliography{nofile}",
  files={"main.bbl": "\\begin{thebibliography}{1}\n\\bibitem{zz}\nKEEP1 Author.\n\\newblock "
         "Title.\n\\end{thebibliography}\n"}, texts=["KEEP1"])
# -- cross-references ------------------------------------------------------------------- #
D("forward-ref", r"See \ref{late}.\section{KEEP1}\label{late}", texts=["KEEP1"],
  labels=["late"], smoke=True)
D("cref-multi", r"\section{A}\label{a}\section{B}\label{b}\cref{a,b} \Cref{a} "
  r"\crefrange{a}{b}", pre=r"\usepackage{cleveref}", labels=["a", "b"])
D("autoref-kinds", r"\begin{figure}\includegraphics[width=1cm]{img.png}\caption{C}\label{fig:x}"
  r"\end{figure}\begin{table}\caption{T}\label{tab:x}\begin{tabular}{l}x\\\end{tabular}"
  r"\end{table}\autoref{fig:x} \autoref{tab:x}", texts=["Figure", "Table"])
D("theorem-ref-numbering", r"\begin{theorem}\label{t1}A\end{theorem}\begin{lemma}\label{l1}B"
  r"\end{lemma}\ref{t1} \ref{l1}",
  pre=r"\newtheorem{theorem}{Theorem}\newtheorem{lemma}[theorem]{Lemma}",
  texts=["Theorem 1", "Lemma 2"], note="a lemma sharing the theorem counter is number 2")
D("theorem-per-section", r"\section{S}\begin{theorem}A\end{theorem}",
  pre=r"\newtheorem{theorem}{Theorem}[section]", texts=["Theorem 1.1"])
D("theorem-unnumbered", r"\begin{remark}KEEP1\end{remark}",
  pre=r"\theoremstyle{remark}\newtheorem*{remark}{Remark}", texts=["Remark", "KEEP1"],
  absent=["Remark 1"])
D("proof-named", r"\begin{proof}[Proof of KEEP1]KEEP2\qedhere\end{proof}",
  texts=["Proof of KEEP1", "KEEP2"])
D("label-special-chars", r"\section{S}\label{sec:a_b-c.d}See \ref{sec:a_b-c.d}.",
  labels=["sec:a_b-c.d"])
D("duplicate-label", r"\section{A}\label{x}\section{B}\label{x}\ref{x}", allow_warnings=[".*"])
D("footnotemark-text", r"A\footnotemark[2] B\footnotetext[2]{KEEP1}", texts=["KEEP1"])
D("ref-in-caption-to-later", r"\begin{figure}\includegraphics[width=1cm]{img.png}"
  r"\caption{See \ref{sec:later}.}\end{figure}\section{L}\label{sec:later}")
# -- misc text ------------------------------------------------------------------------- #
D("glossaries", r"\gls{api} KEEP1 \printglossary",
  pre="\\usepackage{glossaries}\n\\newglossaryentry{api}{name={API},description={KEEP2}}",
  texts=["API", "KEEP1"])
D("acronym-pkg", r"\begin{acronym}\acro{KP}{Keep Phrase}\end{acronym}\ac{KP} then \ac{KP}",
  pre=r"\usepackage{acronym}", texts=["Keep Phrase", "KP"])
D("todonotes", r"KEEP1\todo{KEEP2}", pre=r"\usepackage{todonotes}", texts=["KEEP1"])
D("epigraph", r"\epigraph{KEEP1}{KEEP2}", pre=r"\usepackage{epigraph}",
  texts=["KEEP1", "KEEP2"])
D("verse", r"\begin{verse}KEEP1\\KEEP2\end{verse}", texts=["KEEP1", "KEEP2"])
D("blockquote-csquotes", r"\blockquote{KEEP1}", pre=r"\usepackage{csquotes}", texts=["KEEP1"])
D("newtcolorbox", r"\begin{mybox}{KEEP1}KEEP2\end{mybox}",
  pre="\\usepackage{tcolorbox}\n\\newtcolorbox{mybox}[1]{colback=red!5,title=#1}",
  texts=["KEEP1", "KEEP2"])
D("fcolorbox", r"\fcolorbox{red}{yellow}{KEEP1}", texts=["KEEP1"])
D("minipage-footnote", r"\begin{minipage}{5cm}KEEP1\footnote{KEEP2}\end{minipage}",
  texts=["KEEP1", "KEEP2"])
D("multicols-columnbreak", r"\begin{multicols}{2}KEEP1\columnbreak KEEP2\end{multicols}",
  pre=r"\usepackage{multicol}", texts=["KEEP1", "KEEP2"])
D("rule-hrule", r"KEEP1\par\noindent\rule{\linewidth}{0.4pt}\par KEEP2",
  texts=["KEEP1", "KEEP2"])
D("centerline", r"\centerline{KEEP1}", texts=["KEEP1"])
D("babel-german-quotes", r"\glqq KEEP1\grqq{} und \enquote{KEEP2}",
  pre=r"\usepackage[ngerman]{babel}\usepackage{csquotes}", texts=["KEEP1", "KEEP2"])
D("babel-shorthand", r"Gr\"o\ss e \"a KEEP1", pre=r"\usepackage[ngerman]{babel}",
  texts=["Größe", "ä", "KEEP1"])
D("otherlanguage", r"\begin{otherlanguage}{french}KEEP1\end{otherlanguage}",
  pre=r"\usepackage[french,english]{babel}", texts=["KEEP1"])
D("selectlanguage", r"\selectlanguage{english}KEEP1", pre=r"\usepackage[german,english]{babel}",
  texts=["KEEP1"])
D("algorithmic", r"\begin{algorithm}\caption{KEEP1}\begin{algorithmic}[1]\Require $n$"
  r"\For{$i=1$ to $n$}\If{$i>2$}\State KEEP2\EndIf\EndFor\State \Return $x$\end{algorithmic}"
  r"\end{algorithm}", pre=r"\usepackage{algorithm,algpseudocode}",
  texts=["KEEP1", "KEEP2"])
D("algorithm2e", r"\begin{algorithm}\caption{KEEP1}\KwIn{$x$}\While{$x>0$}{KEEP2\;}"
  r"\end{algorithm}", pre=r"\usepackage[ruled]{algorithm2e}", texts=["KEEP1", "KEEP2"])
D("tikz-inline-graceful", r"KEEP1 \begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture} KEEP2",
  pre=r"\usepackage{tikz}", texts=["KEEP1", "KEEP2"], allow_warnings=[".*"])
D("hyperref-href-specials", r"\href{https://example.org/a\#b?c=1\%20d}{KEEP1}",
  texts=["KEEP1"], xml=[r"example\.org"])
D("url-specials", r"\url{https://example.org/~user/a_b#frag}", texts=["~user/a_b#frag"])
D("many-footnotes", " ".join(f"w{i}\\footnote{{N{i}}}" for i in range(1, 13)),
  texts=[f"N{i}" for i in range(1, 13)])
# -- robustness ----------------------------------------------------------------------- #
D("empty-document", "", note="an empty body converts")
D("no-document-env", "", raw_source="Just KEEP1 text with $x$.\n", texts=["KEEP1"],
  allow_warnings=[".*"], note="a fragment without \\begin{document}")
D("unbalanced-brace", r"KEEP1 {unclosed KEEP2", texts=["KEEP1"], allow_warnings=[".*"],
  allow_raw=True, allow_braces=True, allow_backslash=True, note="never crash on bad input")
D("missing-end-env", r"\begin{itemize}\item KEEP1", texts=["KEEP1"], allow_warnings=[".*"],
  allow_raw=True, allow_backslash=True, allow_braces=True)
D("unknown-env", r"\begin{weirdenv}KEEP1\end{weirdenv}", texts=["KEEP1"],
  allow_warnings=["weirdenv"])
D("text-after-end-document", "", raw_source="\\documentclass{article}\n\\begin{document}\n"
  "KEEP1\n\\end{document}\nDROP1 junk\n", texts=["KEEP1"], absent=["DROP1"])
D("deep-nesting", "{" * 200 + "KEEP1" + "}" * 200, texts=["KEEP1"],
  note="200 nested groups must not hit a recursion limit")
D("many-sections", "\n".join(f"\\section{{S{i}}}\\label{{s{i}}}T\\ref{{s{i}}}"
                             for i in range(300)),
  texts=["S299"], note="300 sections with labels and refs")
D("long-paragraph", " ".join(["word"] * 20000) + " KEEP1", texts=["KEEP1"])
D("big-table", r"\begin{tabular}{" + "l" * 12 + "}"
  + "\\\\\n".join(" & ".join(f"c{r}x{c}" for c in range(12)) for r in range(200))
  + r"\\\end{tabular}", texts=["c199x11"])
D("nul-and-control-chars", "KEEP1 \x0c KEEP2 \x07", texts=["KEEP1", "KEEP2"],
  note="form feed / bell characters must not produce invalid XML")
D("emoji-astral", "KEEP1 \U0001F600 \U0001D400", texts=["KEEP1", "\U0001F600"])


def probes() -> list[Probe]:
    return list(_ALL)


_ = S  # the sentinel is used by the matrix; documents use KEEPn/DROPn tokens
