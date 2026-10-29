"""TeX primitives and file commands found broken by the probes (issue #45)."""

from __future__ import annotations

from tex2word import convert_source, ir
from tex2word.frontend.counters import resolve_counters
from tex2word.frontend.macros import expand_macros


def _text(body: str, pre: str = "", base_dir: str = ".") -> str:
    r = convert_source("\\documentclass{article}\n" + pre + "\n\\begin{document}\n" + body
                       + "\n\\end{document}\n", base_dir=base_dir)
    assert [w.message for w in r.report.warnings] == []
    out = []
    for b in r.document.blocks:
        if isinstance(b, ir.Paragraph | ir.Heading):
            out.append(_flat(b.inlines))
    return " | ".join(out)


def _flat(inl) -> str:
    return "".join(n.value if isinstance(n, ir.Text) else _flat(getattr(n, "inlines", []))
                   for n in inl or [])


def test_let_copies_and_protects():
    assert "BOLD" in _text(r"\let\strong\textbf \strong{BOLD}")
    # \let\old\section then a redefinition that uses \old: no recursion
    out = expand_macros(r"\let\oldsection\section"
                        r"\renewcommand{\section}[1]{\oldsection{#1!}}\section{T}")
    assert out.strip() == r"\section{T!}"
    # a snapshot: redefining the original later does not change the copy
    out = expand_macros(r"\newcommand{\a}{one}\let\b\a\renewcommand{\a}{two}\b \a")
    assert out.split() == ["one", "two"]


def test_csname_namedef_and_delimited_def():
    assert "KEEP" in _text(r"\expandafter\def\csname kp\endcsname{KEEP}\kp")
    assert expand_macros(r"\makeatletter\@namedef{x}{X}\@nameuse{x}\makeatother").endswith(
        r"\makeatletter X\makeatother")
    assert "A+B done" in _text(r"\def\pt(#1,#2){#1+#2}\pt(A,B) done")
    # a mismatched delimiter leaves the call alone instead of eating text
    assert expand_macros(r"\def\pt(#1,#2){#1+#2}\pt[A]").endswith(r"\pt[A]")


def test_at_macros_and_providecommand():
    assert "KEEP" in _text(r"\makeatletter\newcommand{\my@x}{KEEP}\my@x\makeatother")
    out = _text(r"\providecommand{\LaTeX}{DROP}\providecommand{\fresh}{NEW}\LaTeX{} \fresh")
    assert "LaTeX" in out and "NEW" in out and "DROP" not in out


def test_counters():
    src = (r"\newcounter{q}\newcounter{p}[q]\stepcounter{q}Q\theq."
           r"\stepcounter{p}\stepcounter{p}\thep{} \stepcounter{q}\theq.\thep{} "
           r"\setcounter{q}{4}\addtocounter{q}{1}\roman{q} \Alph{q} \value{q}")
    out = resolve_counters(src).replace("{}", "")
    assert out.split() == ["Q1.2", "2.0", "v", "E", "5"]
    # LaTeX's own counters and verbatim are left alone
    assert resolve_counters(r"\newcounter{c}\thesection \verb|\thec|") == \
        r"\thesection \verb|\thec|"


def test_counter_in_a_user_macro():
    out = _text(r"\newcounter{ex}\newcommand{\ex}{\stepcounter{ex}Ex.~\theex}"
                r"\ex{} one. \ex{} two.")
    assert "Ex. 1 one. Ex. 2 two." in out.replace("\u00a0", " ")


def test_lengths_are_silent():
    out = _text(r"\newlength{\gap}\setlength{\gap}{3pt}\addtolength{\gap}{1pt}"
                r"A\hspace{\gap}B")
    assert out.startswith("A") and "B" in out


def test_endinput_input_without_braces_and_subfile(tmp_path):
    (tmp_path / "part.tex").write_text("KEEP1 \\endinput KEEP2\nDROP\n", encoding="utf-8")
    (tmp_path / "plain.tex").write_text("PLAIN\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "s.tex").write_text(
        "\\documentclass[../main]{subfiles}\n\\begin{document}\nSUB\n\\end{document}\n",
        encoding="utf-8")
    out = _text("\\input{part}\n\n\\input plain\n\n\\subfile{sub/s}",
                r"\usepackage{subfiles}", base_dir=str(tmp_path))
    assert "KEEP1" in out and "KEEP2" in out and "DROP" not in out
    assert "PLAIN" in out and "SUB" in out and "documentclass" not in out
