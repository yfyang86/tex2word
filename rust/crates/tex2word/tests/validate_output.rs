//! Integration test: every conversion must produce a structurally valid `.docx`
//! (the in-house OOXML validator returns zero violations). This gates the whole
//! feature surface — a schema-order or field/bookmark regression fails CI.

/// A document exercising Phase 1–5 features: metadata, sections, math, lists,
/// a booktabs table (centered → tblPr order), a captioned figure, cross-refs,
/// hyperlinks, citations, footnotes, and a bibliography.
const SAMPLE: &str = r"\documentclass{article}
\title{Validator Corpus}
\author{A \and B}
\begin{document}
\maketitle
\tableofcontents
\section{Intro}\label{sec:intro}
\subsection{Sub}\label{sec:sub}
Text \textbf{bold} \emph{it}, math $x^2$, \cref{tab:r}, \autoref{sec:sub},
\pageref{eq:e}, \eqref{eq:e}, \href{https://x.io}{link}, \nameref{sec:intro},
\citep{a,b}, note\footnote{A \textbf{note}.}.
\begin{equation}\label{eq:e} E = mc^2 \end{equation}
\begin{itemize}\item one \item two\end{itemize}
\begin{table}[h]\centering\caption{R}\label{tab:r}
\begin{tabular}{l r}\toprule A & B \\\midrule x & 1 \\\bottomrule\end{tabular}
\end{table}
\begin{thebibliography}{9}
\bibitem{a} Author A. Title. 2020.
\bibitem[XY]{b} Author B. Title. 2021.
\end{thebibliography}
\end{document}";

#[test]
fn conversion_output_is_structurally_valid() {
    let docx = tex2word::convert_source(SAMPLE).docx;
    let violations = tex2word_validate::validate_docx(&docx);
    assert!(
        violations.is_empty(),
        "generated .docx failed validation:\n{}",
        violations.join("\n")
    );
}

#[test]
fn twocolumn_output_is_structurally_valid() {
    let src = r"\documentclass[twocolumn]{article}\title{T}\begin{document}\maketitle
\section{S}Body.
\begin{figure*}\centering\caption{Wide}\end{figure*}
More body.\end{document}";
    let docx = tex2word::convert_source(src).docx;
    let violations = tex2word_validate::validate_docx(&docx);
    assert!(
        violations.is_empty(),
        "two-column .docx failed validation:\n{}",
        violations.join("\n")
    );
}
