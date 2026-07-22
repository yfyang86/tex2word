//! Round-trip idempotence: `parse → to_latex → parse` must reach an equal IR.
//! This differential test catches lossy parsing or writing (see PHASE5_PLAN.md).
//! The cross-reference pass is *not* run, so `Document.labels` stays empty on
//! both sides and the comparison is purely structural.

use std::path::Path;

fn roundtrip(src: &str) {
    let ir1 = tex2word_frontend::parse_document(src);
    let tex = tex2word_latex::to_latex(&ir1);
    let ir2 = tex2word_frontend::parse_document_in(&tex, Path::new("."));
    assert_eq!(
        ir1.blocks, ir2.blocks,
        "\n--- IR mismatch ---\nregenerated LaTeX:\n{tex}\n"
    );
    assert_eq!(ir1.title, ir2.title);
    assert_eq!(ir1.authors, ir2.authors);
    assert_eq!(ir1.columns.max(1), ir2.columns.max(1));
}

#[test]
fn roundtrip_text_and_math() {
    roundtrip(
        r"\documentclass{article}\title{Paper}\author{A \and B}\begin{document}\maketitle
\section{Intro}\label{sec:a}
Some \textbf{bold} and \emph{italic} and \texttt{code} with $x^2$ and a break\\here.
See \ref{sec:a}, \eqref{eq:e}, \autoref{sec:a}, \cite{k}, \href{https://x.io}{link}.
\[ a^2 + b^2 = c^2 \]
\begin{equation}\label{eq:e} E = mc^2 \end{equation}
\end{document}",
    );
}

#[test]
fn roundtrip_lists_tables_floats() {
    roundtrip(
        r"\documentclass{article}\begin{document}
\begin{itemize}\item one \item two\end{itemize}
\begin{enumerate}\item a \item b\end{enumerate}
\begin{table}\centering\caption{R}\label{t}
\begin{tabular}{l c r}\toprule H1 & H2 & H3 \\\midrule
\multicolumn{2}{c}{Span} & z \\ x & y & w \\\bottomrule\end{tabular}
\end{table}
\begin{quote}A quoted line.\end{quote}
\end{document}",
    );
}

#[test]
fn roundtrip_citations_footnotes_theorems() {
    roundtrip(
        r"\documentclass{article}\begin{document}
Text \citep{a,b} and \citet{c}, note\footnote{A note.}.
\begin{theorem}[Main]\label{thm:m}
The statement holds.
\end{theorem}
\begin{proof}It follows.\end{proof}
\begin{thebibliography}{9}
\bibitem{a} Author A. Title. 2020.
\bibitem[XY]{b} Author B. Title. 2021.
\bibitem{c} Author C. Title. 2022.
\end{thebibliography}
\end{document}",
    );
}

#[test]
fn roundtrip_twocolumn() {
    roundtrip(
        r"\documentclass[twocolumn]{article}\title{T}\begin{document}\maketitle
\section{S}Body.
\begin{figure*}\centering\caption{Wide}\label{f}\end{figure*}
More.\end{document}",
    );
}
