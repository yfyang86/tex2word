%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%
%    University of Oxford, Mathematical Institute LaTeX Problem Sheet class
%    Created by K A Gillow, 12 September 2018
%    Last updated 12 May 2020
%
% this latex package is designed for use with the standard exam.cls
% exam.cls is standard in texlive and miktex
% exam.cls also available at 
%         http://www.ctan.org/tex-archive/macros/latex/contrib/exam/
%         http://math.mit.edu/~psh/#LaTeX
% exam.cls has numerous options, see the 130+ page doc examdoc.pdf
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{oxmathproblems}[2020/05/12 v1.3 Oxford Maths problem sheet class]

% load in the main exam class with appropriate options
\LoadClass[12pt,a4paper]{exam} 

%space out the lines by 25% more than the default (basically 1.5 line spacing)
\linespread{1.25}

% General thinking is that 12pt font, with 1.25 spread, black on white text,
% gives a good readable document for most people. For those that benefit
% from larger fonts many will be best zooming / expanding the document on
% screen or simply printing enlarged on A3 as that will best preserve the
% formatting rather than enlarging the font whilst still fitting into an A4
% sized space.  For those that benefit from a different background colour
% this is likely easiest achieved if the document is on white and then
% software or a film is used to change the white to cream, blue etc

%load in some commonly needed packages 
\RequirePackage{ifthen,amsmath,amssymb,amsthm,bm,graphicx,color}

%increase the printed page area width
\extrawidth{0.5cm}

%increase header space on title page only
\extraheadheight[1.5cm]{0cm}

%setup page headers/footers for first and subsequent pages
\pagestyle{headandfoot}
\lhead{}
\chead[\bfseries \Large \thecourse\\
\large Sheet \thesheetnumber \ifprintanswers \ Solutions \fi \quad---\quad\theoxfordterm\\%
\ifprintanswers \textit{\textcolor{red}{For Tutors Only --- Not For Distribution}}\\ \fi
\thesheettitle]{}
\rhead[]{\bfseries \thecourse: Sheet \thesheetnumber \ifprintanswers \ Solutions \fi --- \theoxfordterm}
\lfoot{\footnotesize Mathematical Institute, University of Oxford\\ \thecontact}
\cfoot{}
\rfoot{Page \thepage{} of \numpages}
\footrule

% define newcommands for user set page header details
\newcommand*{\oxfordterm}[1]{\def\theoxfordterm{#1}}
\newcommand*{\course}[1]{\def\thecourse{#1}}
\newcommand*{\sheetnumber}[1]{\def\thesheetnumber{#1}}
\newcommand*{\sheettitle}[1]{\def\thesheettitle{#1}}
\oxfordterm{}\course{}\sheetnumber{}\sheettitle{}

% define a command for user to set some contact info in the footer
\newcommand*{\contact}[1]{\def\thecontact{#1}}
\contact{}

% revised question command that tries to encourage page breaks
% to lie between questions rather than within questions
\newcommand{\miquestion}[1][]{\filbreak
  \ifthenelse{\equal{#1}{}}{\question}{\question[#1]}
}

% do not put a box/frame around printed solutions
\unframedsolutions

\renewcommand{\subpartlabel}{(\thesubpart)}

%if you produce a problem sheet with solutions but want to strip the
%solutions from the tex file (e.g. to give to a student who needs to use a
%screen reader) you could run one of
%sed '/\\begin{solution}/,/\\end{solution}/d' file.tex > file-nosoln.tex
%perl -ne 'print unless /^\\begin\{solution\}/ .. /^\\end\{solution\}/' file.tex > file-nosoln.tex
