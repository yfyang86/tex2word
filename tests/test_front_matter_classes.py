"""Journal/class front matter (issue #45, found by the synthetic probes)."""

from __future__ import annotations

from tex2word import convert_source, ir


def _meta(src: str):
    r = convert_source(src)
    assert [w.message for w in r.report.warnings] == []
    return r.document.meta, r.document


def _txt(inlines) -> str:
    out = []
    for n in inlines or []:
        if isinstance(n, ir.Text):
            out.append(n.value)
        elif hasattr(n, "inlines"):
            out.append(_txt(n.inlines))
    return "".join(out)


def _doc(cls: str, body: str, pre: str = "") -> str:
    return f"\\documentclass{{{cls}}}\n{pre}\n\\begin{{document}}\n{body}\n\\end{{document}}\n"


def test_acmart_affiliation_parts_are_joined():
    meta, _ = _meta(_doc("acmart", r"\title{T}\author{A}\affiliation{\institution{Uni}"
                                   r"\city{Town}\country{Land}}\maketitle"))
    assert [_txt(a) for a in meta.affiliations] == ["Uni, Town, Land"]


def test_springer_nature_authors_and_affiliations():
    meta, doc = _meta(_doc("sn-jnl", r"\title{T}\author*[1]{\fnm{Ann} \sur{Lee}}"
                                     r"\affil*[1]{\orgdiv{Dept}, \orgname{Uni}, "
                                     r"\orgaddress{\city{Town}, \country{Land}}}"
                                     r"\abstract{Abs.}\maketitle\bmhead{Thanks} Text."))
    assert _txt(meta.authors[0]) == "Ann Lee1*"
    assert _txt(meta.affiliations[0]) == "1Dept, Uni, Town, Land"
    assert meta.abstract and isinstance(meta.abstract[0], ir.Paragraph)
    assert any(isinstance(b, ir.Heading) and _txt(b.inlines) == "Thanks" for b in doc.blocks)


def test_elsarticle_markers_keyvalue_affiliation_and_notes():
    meta, _ = _meta(_doc("elsarticle", r"\begin{frontmatter}\author[a]{Ann\corref{c1}}"
                                       r"\ead{a@b.org}\cortext[c1]{Corresponding.}"
                                       r"\affiliation[a]{organization={Uni},city={Town}}"
                                       r"\end{frontmatter}"))
    assert _txt(meta.authors[0]) == "Ann∗a"
    assert "aUni, Town" in [_txt(a) for a in meta.affiliations]
    assert [_txt(n) for n in meta.front_notes] == ["∗ Corresponding."]


def test_authblk_preamble_lists_every_author_and_affil():
    meta, _ = _meta(_doc("article", r"\maketitle",
                         r"\usepackage{authblk}\title{T}\author[1]{A}\author[2]{B}"
                         r"\affil[1]{U1}\affil[2]{U2}"))
    assert [_txt(a) for a in meta.authors] == ["A1", "B2"]
    assert [_txt(a) for a in meta.affiliations] == ["1U1", "2U2"]


def test_llncs_institutes_orcid_and_keywords():
    meta, _ = _meta(_doc("llncs", r"\title{T}\author{A\inst{1}\orcidID{0000-0001} \and B\inst{2}}"
                                  r"\authorrunning{Short}\institute{U1 \email{a@b} \and U2}"
                                  r"\maketitle\begin{abstract}X \keywords{k1 \and k2}"
                                  r"\end{abstract}"))
    assert [_txt(a) for a in meta.authors] == ["A1", "B2"]
    affils = [_txt(a) for a in meta.affiliations]
    assert "1U1 a@b" in affils and "2U2" in affils and "ORCID: 0000-0001" in affils
    assert _txt(meta.keywords) == "k1 · k2"


def test_neurips_and_icml_authors():
    meta, _ = _meta(_doc("article", r"\title{T}\author{A \And B \AND C}\maketitle"))
    assert [_txt(a) for a in meta.authors] == ["A", "B", "C"]
    meta, _ = _meta(_doc("article", r"\twocolumn[\icmltitle{T}\begin{icmlauthorlist}"
                                    r"\icmlauthor{A}{x}\icmlauthor{B}{y,x}\end{icmlauthorlist}"
                                    r"\icmlaffiliation{x}{UX}\icmlaffiliation{y}{UY}"
                                    r"\icmlcorrespondingauthor{A}{a@b}\icmlkeywords{k}]"))
    assert _txt(meta.title) == "T"
    assert [_txt(a) for a in meta.authors] == ["A1", "B2,1"]
    assert [_txt(a) for a in meta.affiliations] == ["1UX", "2UY"]
    assert [_txt(n) for n in meta.front_notes] == ["Correspondence to: A <a@b>"]


def test_ieee_journal_and_amsart_extras():
    meta, doc = _meta(_doc("IEEEtran", r"\title{T}\author{A,~\IEEEmembership{Member,~IEEE}}"
                                       r"\maketitle\IEEEpeerreviewmaketitle\section{S}x"
                                       r"\appendices\section{P}y"))
    assert _txt(meta.authors[0]).replace("\u00a0", " ") == "A, Member, IEEE"  # ~ ties
    heads = [b for b in doc.blocks if isinstance(b, ir.Heading)]
    assert heads[-1].appendix
    meta, _ = _meta(_doc("amsart", r"\title{T}\author{A}\address{Here}\curraddr{There}"
                                   r"\urladdr{https://x.org}\dedicatory{To B.}\maketitle"))
    affils = [_txt(a) for a in meta.affiliations]
    assert "Current address: There" in affils and "URL: https://x.org" in affils
    assert [_txt(n) for n in meta.front_notes] == ["To B."]


def test_koma_title_page_and_divisions():
    meta, doc = _meta(_doc("scrartcl", r"\subject{Sub}\title{T}\subtitle{ST}\author{A}"
                                       r"\publishers{Pub}\date{}\maketitle\addsec{Pre}"
                                       r"x\minisec{Mini}y"))
    assert _txt(meta.subtitle) == "ST"
    assert [_txt(n) for n in meta.front_notes] == ["Sub", "Pub"]
    heads = [b for b in doc.blocks if isinstance(b, ir.Heading)]
    assert _txt(heads[0].inlines) == "Pre" and not heads[0].numbered


def test_beamer_frames_and_overlays():
    meta, doc = _meta(_doc("beamer", r"\frame{\titlepage}\begin{frame}[fragile]{Slide A}"
                                     r"\begin{itemize}\item<1-> one\item<2-> two\end{itemize}"
                                     r"\end{frame}\begin{frame}\frametitle{Slide B}"
                                     r"\begin{columns}\column{0.5\textwidth} L\column{.5\textwidth}"
                                     r" R\end{columns}\pause\alert<2>{hot}\end{frame}",
                           r"\title{T}\author{A}"))
    heads = [_txt(b.inlines) for b in doc.blocks if isinstance(b, ir.Heading)]
    assert heads == ["Slide A", "Slide B"]


def test_letter_class():
    _, doc = _meta(_doc("letter", r"\begin{letter}{To Person\\Street}\opening{Dear X,}Body."
                                  r"\closing{Regards,}\ps{PS.}\end{letter}",
                        r"\address{From Me}\signature{Me}"))
    paras = [_txt(b.inlines) for b in doc.blocks if isinstance(b, ir.Paragraph)]
    assert paras[0] == "From Me" and doc.blocks[0].align == "right"
    assert paras[1:] == ["To PersonStreet", "Dear X,", "Body.", "Regards,", "Me", "PS."]


def test_moderncv():
    meta, doc = _meta(_doc("moderncv", r"\makecvtitle\section{Edu}"
                                       r"\cventry{2020}{MSc}{Uni}{Town}{}{Thesis.}"
                                       r"\cvitem{Lang}{English}",
                           r"\moderncvstyle{classic}\name{Ann}{Lee}\title{Engineer}"
                           r"\email{a@b.org}"))
    assert _txt(meta.title) == "Ann Lee" and _txt(meta.subtitle) == "Engineer"
    assert meta.date is None
    paras = [_txt(b.inlines) for b in doc.blocks if isinstance(b, ir.Paragraph)]
    assert paras == ["2020  MSc, Uni, TownThesis.", "Lang: English"]
