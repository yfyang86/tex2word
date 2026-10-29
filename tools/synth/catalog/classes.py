"""Journal/class templates: the front matter real papers use.

Each template marks every piece of visible front-matter text with a ``K...``
token (title, authors, affiliations, abstract, keywords, body); all must reach
the document, and the generic oracles catch leaked class macros. Tokens
starting with ``DROP`` (e.g. running heads, CCS XML) must not show in the body.
"""

from __future__ import annotations

from ..model import Expect, Probe

T: dict[str, tuple[str, list[str], list[str]]] = {}


def C(name: str, source: str, keep: list[str] | None = None, drop: list[str] | None = None):
    import re

    toks = keep if keep is not None else sorted(set(re.findall(r"\bK[A-Z]+\d*\b", source)))
    drops = drop if drop is not None else sorted(set(re.findall(r"\bDROP[A-Z]*\d*\b", source)))
    T[name] = (source, toks, drops)


C("ieeetran-conference", r"""\documentclass[conference]{IEEEtran}
\IEEEoverridecommandlockouts
\usepackage{amsmath,graphicx,cite}
\begin{document}
\title{KTITLE\thanks{KFUND}}
\author{\IEEEauthorblockN{KAUTHA}
\IEEEauthorblockA{\textit{KDEPTA} \\ \textit{KUNIA}\\ a@b.org}
\and
\IEEEauthorblockN{KAUTHB}
\IEEEauthorblockA{KUNIB}}
\maketitle
\begin{abstract}KABSTRACT\end{abstract}
\begin{IEEEkeywords}KKWA, KKWB\end{IEEEkeywords}
\section{Introduction}
\IEEEPARstart{T}{his} KBODY \cite{knuth1984}.
\bibliographystyle{IEEEtran}
\bibliography{refs}
\end{document}
""")
C("ieeetran-journal", r"""\documentclass[journal]{IEEEtran}
\begin{document}
\title{KTITLE}
\author{KAUTHA,~\IEEEmembership{Member,~IEEE,}
        KAUTHB,~\IEEEmembership{Fellow,~IEEE}
\thanks{KTHANKS}}
\markboth{DROPHEAD}{DROPHEAD}
\maketitle
\begin{abstract}KABSTRACT\end{abstract}
\begin{IEEEkeywords}KKW\end{IEEEkeywords}
\IEEEpeerreviewmaketitle
\section{Introduction}
KBODY
\appendices
\section{Proof}KAPPX
\begin{IEEEbiography}{KBIONAME}KBIO\end{IEEEbiography}
\end{document}
""")
C("acmart-sigconf", r"""\documentclass[sigconf]{acmart}
\acmConference[DROPCONF]{Conf}{2024}{City}
\acmYear{2024}
\copyrightyear{2024}
\begin{document}
\title{KTITLE}
\author{KAUTHA}
\affiliation{\institution{KUNIA}\city{KCITY}\country{KCOUNTRY}}
\email{a@b.org}
\author{KAUTHB}
\affiliation{\institution{KUNIB}}
\begin{abstract}KABSTRACT\end{abstract}
\begin{CCSXML}
<ccs2012><concept><concept_id>DROPCCS</concept_id></concept></ccs2012>
\end{CCSXML}
\ccsdesc[500]{Computing methodologies~Machine learning}
\keywords{KKWA, KKWB}
\maketitle
\section{Introduction}
KBODY
\begin{acks}KACK\end{acks}
\end{document}
""")
C("llncs", r"""\documentclass{llncs}
\begin{document}
\title{KTITLE}
\author{KAUTHA\inst{1}\orcidID{0000-0001-2345-6789} \and KAUTHB\inst{2}}
\authorrunning{DROPRUN}
\institute{KUNIA, KCITY \email{a@b.org} \and KUNIB}
\maketitle
\begin{abstract}KABSTRACT
\keywords{KKWA \and KKWB}
\end{abstract}
\section{Introduction}
KBODY
\end{document}
""")
C("elsarticle", r"""\documentclass[preprint,12pt]{elsarticle}
\begin{document}
\begin{frontmatter}
\title{KTITLE}
\author[a]{KAUTHA\corref{cor1}}
\ead{a@b.org}
\author[b]{KAUTHB}
\cortext[cor1]{KCORR}
\affiliation[a]{organization={KUNIA},city={KCITY},country={KCOUNTRY}}
\affiliation[b]{organization={KUNIB}}
\begin{abstract}KABSTRACT\end{abstract}
\begin{highlights}
\item KHIGHLIGHT
\end{highlights}
\begin{keyword}KKWA \sep KKWB\end{keyword}
\end{frontmatter}
\section{Introduction}
KBODY
\end{document}
""")
C("revtex", r"""\documentclass[aps,prl,reprint]{revtex4-2}
\begin{document}
\title{KTITLE}
\author{KAUTHA}
\email{a@b.org}
\affiliation{KUNIA}
\author{KAUTHB}
\affiliation{KUNIB}
\date{\today}
\begin{abstract}KABSTRACT\end{abstract}
\maketitle
\section{Introduction}
KBODY
\begin{acknowledgments}KACK\end{acknowledgments}
\end{document}
""")
C("springer-nature", r"""\documentclass[pdflatex,sn-mathphys-num]{sn-jnl}
\begin{document}
\title[DROPSHORT]{KTITLE}
\author*[1]{\fnm{KFIRSTA} \sur{KSURA}}\email{a@b.org}
\author[2]{\fnm{KFIRSTB} \sur{KSURB}}
\affil*[1]{\orgdiv{KDIV}, \orgname{KUNIA}, \orgaddress{\city{KCITY}, \country{KCOUNTRY}}}
\affil[2]{\orgname{KUNIB}}
\abstract{KABSTRACT}
\keywords{KKWA, KKWB}
\maketitle
\section{Introduction}
KBODY
\bmhead{KBMHEAD} KBMTEXT
\backmatter
\end{document}
""")
C("amsart-address", r"""\documentclass{amsart}
\begin{document}
\title{KTITLE}
\author{KAUTHA}
\address{KADDRA}
\curraddr{KCURR}
\email{a@b.org}
\urladdr{https://example.org}
\author{KAUTHB}
\address{KADDRB}
\dedicatory{KDEDIC}
\date{KDATE}
\subjclass[2020]{Primary 11A05}
\keywords{KKW}
\begin{abstract}KABSTRACT\end{abstract}
\maketitle
\section{Introduction}
KBODY
\end{document}
""")
C("report-thesis", r"""\documentclass{report}
\begin{document}
\begin{titlepage}
\centering
{\Huge KTITLE\par}
\vspace{2cm}
{\Large KAUTHOR\par}
\vfill
KSCHOOL\par
\end{titlepage}
\chapter*{KDEDIC}
\tableofcontents
\listoffigures
\chapter{KCHAPA}
KBODY
\chapter{KCHAPB}
\section{KSECB}
KBODYB
\appendix
\chapter{KAPPX}
\end{document}
""")
C("memoir", r"""\documentclass{memoir}
\begin{document}
\title{KTITLE}\author{KAUTHOR}\date{}
\maketitle
\begin{abstract}KABSTRACT\end{abstract}
\chapter{KCHAP}
\epigraph{KQUOTE}{KWHO}
KBODY
\end{document}
""")
C("koma-scrartcl", r"""\documentclass{scrartcl}
\begin{document}
\titlehead{KTITLEHEAD}
\subject{KSUBJECT}
\title{KTITLE}
\subtitle{KSUBTITLE}
\author{KAUTHOR}
\publishers{KPUBLISHER}
\date{}
\maketitle
\addsec{KADDSEC}
KBODY
\minisec{KMINISEC}
KBODYB
\end{document}
""")
C("beamer", r"""\documentclass{beamer}
\usetheme{Madrid}
\title{KTITLE}
\author{KAUTHOR}
\institute{KINST}
\begin{document}
\frame{\titlepage}
\begin{frame}{KFRAMEA}
\begin{itemize}
\item<1-> KITEMA
\item<2-> KITEMB
\end{itemize}
\end{frame}
\begin{frame}
\frametitle{KFRAMEB}
\begin{columns}
\column{0.5\textwidth} KCOLA
\column{0.5\textwidth} KCOLB
\end{columns}
\end{frame}
\end{document}
""")
C("moderncv", r"""\documentclass[11pt,a4paper]{moderncv}
\moderncvstyle{classic}
\name{KFIRST}{KLAST}
\title{KJOBTITLE}
\email{a@b.org}
\begin{document}
\makecvtitle
\section{KSECTION}
\cventry{2020--2024}{KDEGREE}{KSCHOOL}{KCITY}{}{KDESC}
\cvitem{KLABEL}{KVALUE}
\end{document}
""")
C("exam", r"""\documentclass{exam}
\begin{document}
\begin{questions}
\question[5] KQUESTIONA
\begin{parts}
\part KPARTA
\part KPARTB
\end{parts}
\question KQUESTIONB
\begin{solution}DROPSOLUTION\end{solution}
\end{questions}
\end{document}
""")
C("letter", r"""\documentclass{letter}
\signature{KSIGN}
\address{KFROM}
\begin{document}
\begin{letter}{KTO}
\opening{KOPENING,}
KBODY
\closing{KCLOSING,}
\ps{KPS}
\end{letter}
\end{document}
""")
C("authblk", r"""\documentclass{article}
\usepackage{authblk}
\title{KTITLE}
\author[1]{KAUTHA}
\author[2]{KAUTHB}
\affil[1]{KUNIA}
\affil[2]{KUNIB}
\begin{document}
\maketitle
KBODY
\end{document}
""")
C("neurips-style", r"""\documentclass{article}
\usepackage[final]{neurips_2024}
\title{KTITLE}
\author{KAUTHA \\ KUNIA \\ \texttt{a@b.org} \And KAUTHB \\ KUNIB \AND KAUTHC}
\begin{document}
\maketitle
\begin{abstract}KABSTRACT\end{abstract}
\section{Introduction}
KBODY
\end{document}
""")
C("icml-style", r"""\documentclass{article}
\usepackage{icml2024}
\icmltitlerunning{DROPRUN}
\begin{document}
\twocolumn[
\icmltitle{KTITLE}
\begin{icmlauthorlist}
\icmlauthor{KAUTHA}{x}
\icmlauthor{KAUTHB}{y}
\end{icmlauthorlist}
\icmlaffiliation{x}{KUNIA}
\icmlaffiliation{y}{KUNIB}
\icmlcorrespondingauthor{KAUTHA}{a@b.org}
\icmlkeywords{DROPKW}
\vskip 0.3in
]
\printAffiliationsAndNotice{}
\begin{abstract}KABSTRACT\end{abstract}
\section{Introduction}
KBODY
\end{document}
""")
C("ctexart", r"""\documentclass{ctexart}
\title{KTITLE 中文标题}
\author{KAUTHOR 作者}
\begin{document}
\maketitle
\section{引言 KSECTION}
这是正文 KBODY。
\end{document}
""")
C("tufte-handout", r"""\documentclass{tufte-handout}
\title{KTITLE}
\author{KAUTHOR}
\begin{document}
\maketitle
\begin{abstract}KABSTRACT\end{abstract}
KBODY\sidenote{KSIDENOTE} and\marginnote{KMARGIN}.
\begin{fullwidth}KFULLWIDTH\end{fullwidth}
\end{document}
""")


def probes() -> list[Probe]:
    out = []
    for name, (src, keep, drop) in T.items():
        out.append(Probe(
            id=f"class/{name}", source=src,
            expect=Expect(texts=keep, absent=drop),
            note=f"{name} front matter",
            fragment=src,
            tier="smoke" if name in ("ieeetran-conference", "acmart-sigconf", "elsarticle")
            else "full",
            tags={"construct": name, "context": "class"},
        ))
    return out
