% Modification of a cls file that was used by:

% Ryan Adams
% Department of Computer Science
% Princeton University
% v0.02, 9 Sept 2018 -- For Princeton COS 324
% v0.01, 31 August 2013
% Based on HMC Math Dept. template by Eric J. Malm.
\NeedsTeXFormat{LaTeX2e}[1995/01/01]
\ProvidesClass{cos324}
[2018/09/09 v0.02 Princeton COS324 Assignment Class]

\RequirePackage{ifpdf}

\newif\ifhmlset@submit
\DeclareOption{submit}{%
  \hmlset@submittrue%
}
\DeclareOption{nosubmit}{%
  \hmlset@submitfalse%
}

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ExecuteOptions{nosubmit}
\ProcessOptions\relax

\LoadClass[10pt,letterpaper]{article}

\newif\ifhmlset@header

\hmlset@headertrue

\RequirePackage{mathpazo}
\RequirePackage{palatino}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{amsthm}
\RequirePackage{fullpage}
\RequirePackage{mdframed}
\RequirePackage{hyperref}

\newtheoremstyle{hmlplain}
                {3pt}% Space above
                {3pt}% Space below
                {}% Body font
                {}% Indent amount
                {\bfseries}% Theorem head font
                {\\*[3pt]}% Punctuation after theorem head
                {.5em}% Space after theorem head
                {}% Theorem head spec (can be left empty, meaning `normal')

\def\titlebar{\hrule height2pt\vskip .25in\vskip-\parskip}

\newcommand{\headerblock}{%
  \noindent\begin{minipage}{0.33\textwidth}
  \begin{flushleft}
    \mbox{\hmlset@name}\\
    \mbox{\tt \hmlset@email}\\
    \mbox{\hmlset@course}
  \end{flushleft}
  \end{minipage}
  \noindent\begin{minipage}{0.33\textwidth}
  \begin{center}
    \mbox{\Large\hmlset@assignment}\protect\\
    Due: \hmlset@duedate
  \end{center}
  \end{minipage}
  \vspace{0.1cm}
  \titlebar
}

\ifhmlset@header\AtBeginDocument{\headerblock}\fi

\def\hmlset@name{}
\def\hmlset@email{}
\def\hmlset@course{}
\def\hmlset@assignment{}
\def\hmlset@duedate{}
\def\hmlset@discussants{}
\def\hmlset@extraline{}

%commands to set header block info
\newcommand{\name}[1]{\def\hmlset@name{#1}}
\newcommand{\email}[1]{\def\hmlset@email{#1}}
\newcommand{\course}[1]{\def\hmlset@course{#1}}
\newcommand{\assignment}[1]{\def\hmlset@assignment{#1}}
\newcommand{\duedate}[1]{\def\hmlset@duedate{#1}}
\newcommand{\discussants}[1]{\def\hmlset@discussants{#1}}
\newcommand{\extraline}[1]{\def\hmlset@extraline{#1}}

\theoremstyle{hmlplain}
\newmdtheoremenv[skipabove=\topsep,skipbelow=\topsep,nobreak=false]{problem}{Problem}
\newmdtheoremenv[skipabove=\topsep,skipbelow=\topsep,nobreak=false]{solution}{Solution}