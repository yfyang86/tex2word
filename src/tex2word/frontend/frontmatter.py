"""Front matter of journal classes and templates.

``FrontMatterMixin`` is mixed into the parser's ``_Builder``. It turns the
title-page commands of the common classes into document metadata (authors,
affiliations, notes) or blocks:

* authors with markers: ``\\author*[1]{...}`` (sn-jnl, authblk), elsarticle
  ``\\author[a]{...\\corref{c}}``, llncs ``\\inst``/``\\orcidID``, NeurIPS
  ``\\And``/``\\AND``, IEEE ``\\IEEEmembership``, ICML ``\\icmlauthor``;
* structured affiliations: acmart ``\\institution``/``\\city``/``\\country``,
  sn-jnl ``\\orgdiv``/``\\orgname``/``\\orgaddress``, elsarticle
  ``organization={...},city={...}`` and ``\\affil[1]{...}`` labels;
* notes: amsart ``\\curraddr``/``\\urladdr``/``\\dedicatory``, elsarticle
  ``\\cortext``/``\\fntext``, KOMA ``\\subtitle``/``\\subject``/``\\publishers``,
  ICML ``\\icmlcorrespondingauthor``;
* class-specific body commands: sn-jnl ``\\abstract{}``/``\\bmhead``, KOMA
  ``\\addsec``/``\\minisec``, IEEE ``\\appendices``, beamer frames, the
  ``letter`` class, moderncv entries.

The preamble is scanned for every front-matter call (``preamble_calls``), so
templates that list several ``\\author``/``\\affil`` lines before
``\\begin{document}`` (authblk) keep all of them.
"""

from __future__ import annotations

import re
from typing import Any

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
)

from .. import ir

#: block-level commands handled by ``FrontMatterMixin.front_matter``
FRONT_MATTER = frozenset({
    "title", "column", "author", "affil", "affiliation", "institute", "address", "email", "ead",
    "orcid", "orcidID", "keywords", "curraddr", "urladdr", "dedicatory", "dedication",
    "subtitle", "subject", "titlehead", "publishers", "uppertitleback", "lowertitleback",
    "extratitle", "cortext", "fntext", "abstract", "icmltitle", "icmlauthor", "icmlaffiliation",
    "icmlcorrespondingauthor", "icmlkeywords", "icmlsetsymbol", "icmltitlerunning",
    "printAffiliationsAndNotice", "authorrunning", "titlerunning", "IEEEpeerreviewmaketitle",
    "appendices", "bmhead", "addsec", "addchap", "addpart", "minisec", "frametitle",
    "framesubtitle", "frame", "titlepage", "opening", "closing", "ps", "cc", "encl",
    "signature", "name", "makecvtitle", "moderncvstyle", "moderncvcolor", "phone", "mobile",
    "homepage", "social", "extrainfo", "photo", "cventry", "cvitem", "cvitemwithcomment",
    "cvlistitem", "cvdoubleitem", "cvlistdoubleitem", "cvline", "acmConference", "acmYear",
    "acmDOI", "acmISBN", "acmBooktitle", "acmPrice", "copyrightyear", "setcopyright", "ccsdesc",
    "settopmatter", "received", "keywordsname",
})

#: pylatexenc argument specs for the commands above (and inline helpers)
SPECS: tuple[tuple[str, str], ...] = (
    ("author", "*[{"), ("affil", "*[{"), ("affiliation", "*[{"), ("institute", "{"),
    ("address", "[{"), ("email", "[{"), ("ead", "[{"), ("orcid", "{"), ("orcidID", "{"),
    ("curraddr", "{"), ("urladdr", "[{"), ("dedicatory", "{"), ("dedication", "{"),
    ("subtitle", "[{"), ("subject", "{"), ("titlehead", "{"), ("publishers", "{"),
    ("uppertitleback", "{"), ("lowertitleback", "{"), ("extratitle", "{"),
    ("cortext", "[{"), ("fntext", "[{"), ("corref", "{"), ("fnref", "{"),
    ("abstract", "{"), ("icmltitle", "{"), ("icmlauthor", "{{"), ("icmlaffiliation", "{{"),
    ("icmlcorrespondingauthor", "{{"), ("icmlkeywords", "{"), ("icmlsetsymbol", "{{"),
    ("icmltitlerunning", "{"), ("printAffiliationsAndNotice", "{"), ("authorrunning", "{"),
    ("titlerunning", "{"), ("IEEEmembership", "{"), ("bmhead", "{"), ("addsec", "*[{"),
    ("addchap", "*[{"), ("addpart", "*[{"), ("minisec", "{"), ("frametitle", "[{"),
    ("framesubtitle", "{"), ("frame", "[{"), ("opening", "{"), ("closing", "{"), ("ps", "{"),
    ("cc", "{"), ("encl", "{"), ("signature", "{"), ("name", "{{"), ("moderncvstyle", "{"),
    ("moderncvcolor", "{"), ("phone", "[{"), ("mobile", "{"), ("homepage", "{"),
    ("social", "[{"), ("extrainfo", "{"), ("photo", "[[{"),
    ("cventry", "{{{{{{"), ("cvitem", "{{"), ("cvitemwithcomment", "{{{"), ("cvlistitem", "{"),
    ("cvdoubleitem", "{{{{"), ("cvlistdoubleitem", "{{"), ("cvline", "{{"),
    ("acmConference", "[{{{"), ("acmYear", "{"), ("acmDOI", "{"), ("acmISBN", "{"),
    ("acmBooktitle", "{"), ("acmPrice", "{"), ("copyrightyear", "{"), ("setcopyright", "{"),
    ("ccsdesc", "[{"), ("settopmatter", "{"), ("received", "[{"), ("marginnote", "[{["),
    ("newthought", "{"), ("alert", "{"), ("column", "[{"),
    # name / affiliation sub-fields (rendered through their content)
    ("fnm", "{"), ("sur", "{"), ("pfx", "{"), ("sfx", "{"), ("spfx", "{"), ("dgr", "{"),
    ("orgdiv", "{"), ("orgname", "{"), ("orgaddress", "{"), ("street", "{"),
    ("postcode", "{"), ("city", "{"), ("state", "{"), ("country", "{"), ("institution", "{"),
    ("department", "[{"), ("streetaddress", "{"), ("position", "{"),
)

#: affiliation sub-fields: their contents are joined with ", "
AFFIL_PARTS = frozenset({
    "institution", "department", "streetaddress", "city", "state", "postcode", "country",
    "orgdiv", "orgname", "orgaddress", "street", "position",
})
#: name parts and similar wrappers that just contribute their content
TRANSPARENT = frozenset({"fnm", "sur", "pfx", "sfx", "spfx", "dgr"}) | AFFIL_PARTS

#: commands that carry no visible content in Word
_SILENT = frozenset({
    "icmlkeywords", "icmlsetsymbol", "icmltitlerunning", "printAffiliationsAndNotice",
    "authorrunning", "titlerunning", "IEEEpeerreviewmaketitle", "titlepage", "makecvtitle",
    "moderncvstyle", "moderncvcolor", "photo", "acmConference", "acmYear", "acmDOI",
    "acmISBN", "acmBooktitle", "acmPrice", "copyrightyear", "setcopyright", "ccsdesc",
    "settopmatter", "received", "keywordsname", "column",
})

#: commands worth recovering from the preamble, with how many {} groups they take
PREAMBLE_CALLS: dict[str, int] = {
    "title": 1, "subtitle": 1, "author": 1, "date": 1, "keywords": 1, "institute": 1,
    "affiliation": 1, "affil": 1, "address": 1, "email": 1, "orcid": 1, "subject": 1,
    "titlehead": 1, "publishers": 1, "dedication": 1, "name": 2, "phone": 1, "mobile": 1,
    "homepage": 1, "social": 1, "extrainfo": 1, "signature": 1,
}

_KV_RE = re.compile(r"^\s*[A-Za-z]+\s*=")


def preamble_calls(preamble: str) -> list[tuple[str, str]]:
    """``(name, call source)`` for every front-matter command in the preamble, in
    order (several ``\\author``/``\\affil`` lines included). Mentions inside
    definitions (``\\renewcommand{\\title}``) have no argument and are skipped."""
    out: list[tuple[str, str]] = []
    rx = re.compile(r"\\(" + "|".join(sorted(PREAMBLE_CALLS, key=len, reverse=True))
                    + r")(?![A-Za-z@])")
    for m in rx.finditer(preamble):
        name = m.group(1)
        i = m.end()
        if i < len(preamble) and preamble[i] == "*":
            i += 1
        groups = 0
        while groups < PREAMBLE_CALLS[name]:
            j = i
            while j < len(preamble) and preamble[j] in " \t\n":
                j += 1
            if j < len(preamble) and preamble[j] == "[":
                close = _balanced_end(preamble, j, "[", "]")
                if close is None:
                    break
                i = close + 1
                continue
            if j < len(preamble) and preamble[j] == "{":
                close = _balanced_end(preamble, j, "{", "}")
                if close is None:
                    break
                i = close + 1
                groups += 1
                continue
            break
        if groups == PREAMBLE_CALLS[name]:
            out.append((name, preamble[m.start():i]))
    return out


def _balanced_end(s: str, i: int, op: str, cl: str) -> int | None:
    depth = 0
    k = i
    while k < len(s):
        c = s[k]
        if c == "\\":
            k += 2
            continue
        if c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return None


def _sup(text: str) -> ir.Inline:
    return ir.Emphasis([ir.Text(text)], "superscript")


class FrontMatterMixin:
    """Front-matter handling for ``_Builder`` (see the module docstring)."""

    # provided by _Builder
    meta: ir.DocumentMeta
    report: Any
    in_appendix: bool
    doc_class: str = "article"

    def _fm_init(self) -> None:
        self._fn_marks: dict[str, str] = {}  # elsarticle \fnref labels -> marks
        self._icml_keys: list[str] = []  # ICML affiliation keys, in author order
        self.letter_from: list[ir.Inline] | None = None
        self.letter_signature: list[ir.Inline] | None = None

    # -- helpers ------------------------------------------------------------ #

    def _h(self) -> Any:
        from . import parser

        return parser

    def _groups(self, node: LatexMacroNode) -> list[list]:
        return self._h()._brace_groups(node)

    def _opt(self, node: LatexMacroNode) -> str | None:
        """The first ``[...]`` argument as plain text (None if absent)."""
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if isinstance(a, LatexGroupNode) and a.delimiters and a.delimiters[0] == "[":
                return self._h()._chars_of(a.nodelist).strip()
        return None

    def _starred(self, node: LatexMacroNode) -> bool:
        for a in node.nodeargd.argnlist if node.nodeargd else []:
            if isinstance(a, LatexCharsNode) and a.chars == "*":
                return True
        return False

    def _inl(self, nodes: list) -> list[ir.Inline]:
        return self._h()._clean_inlines(self.inlines(nodes), trim=True)  # type: ignore[attr-defined]

    def _segments(self, nodes: list) -> list[list]:
        """Split at ``\\and``, ``\\And`` and ``\\AND`` (several authors)."""
        out: list[list] = [[]]
        for n in nodes:
            if isinstance(n, LatexMacroNode) and n.macroname in ("and", "And", "AND"):
                out.append([])
            else:
                out[-1].append(n)
        return [s for s in out if any(not _blank(x) for x in s)]

    def _affil_inlines(self, nodes: list) -> list[ir.Inline]:
        """An affiliation: sub-fields (``\\institution{..}\\city{..}``) are joined
        with ", " unless the source already separates them."""
        raw = "".join(n.latex_verbatim() for n in nodes).strip()
        if _KV_RE.match(raw):  # elsarticle organization={..},city={..}
            parts = [_kv_value(p) for p in _top_level_split(raw)]
            return self._fragment_inlines(", ".join(p for p in parts if p))  # type: ignore[attr-defined]
        out: list[ir.Inline] = []
        last_part = False
        for n in nodes:
            if isinstance(n, LatexMacroNode) and n.macroname in AFFIL_PARTS:
                groups = self._groups(n)
                inner = self._affil_inlines(groups[-1]) if groups else []
                if inner:
                    if last_part:
                        out.append(ir.Text(", "))
                    out.extend(inner)
                    last_part = True
                continue
            if _blank(n):
                if not last_part:
                    out.extend(self.inlines([n]))  # type: ignore[attr-defined]
                continue
            out.extend(self.inlines([n]))  # type: ignore[attr-defined]
            last_part = False
        return self._h()._clean_inlines(out, trim=True)

    def _front_note(self, inl: list[ir.Inline]) -> None:
        if inl:
            self.meta.front_notes.append(inl)

    # -- block-level commands ----------------------------------------------- #

    def front_matter(self, node: LatexMacroNode) -> list[ir.Block] | None:  # noqa: C901
        """Handle a front-matter command: update the metadata and return the
        blocks to emit (often none), or ``None`` if the command is not ours."""
        name = node.macroname
        if name not in FRONT_MATTER:
            return None
        if name in _SILENT:
            return []
        groups = self._groups(node)
        last = groups[-1] if groups else []
        moderncv = self.doc_class == "moderncv"
        letter = self.doc_class == "letter"

        if name == "author":
            opt, star = self._opt(node), self._starred(node)
            segs = self._segments(last)
            for seg in segs:
                inl = self._inl(seg)
                if not inl:
                    continue
                marks = (opt or "") + ("*" if star else "")
                if marks and len(segs) == 1:
                    inl.append(_sup(marks))
                self.meta.authors.append(inl)
            return []
        if name in ("affil", "affiliation", "institute") or (name == "address" and not (
                letter or moderncv)):
            opt = self._opt(node)
            segs = self._segments(last)
            for i, seg in enumerate(segs, 1):
                inl = self._affil_inlines(seg)
                if not inl:
                    continue
                mark = opt if opt else (str(i) if len(segs) > 1 else "")
                self.meta.affiliations.append([_sup(mark), *inl] if mark else inl)
            return []
        if name == "address" and letter:
            self.letter_from = self._inl(last)
            return []
        if name in ("email", "ead"):
            inl = self._inl(last)
            if inl:
                label = "URL: " if (self._opt(node) or "").lower() == "url" else "Email: "
                (self.meta.front_notes if moderncv else self.meta.affiliations).append(
                    [ir.Text(label), *inl])
            return []
        if name in ("orcid", "orcidID"):
            oid = self._h()._chars_of(last).strip()
            if oid:
                url = oid if oid.startswith("http") else f"https://orcid.org/{oid}"
                self.meta.affiliations.append([ir.Link([ir.Text(f"ORCID: {oid}")], url)])
            return []
        if name == "keywords":
            parts = [self._inl(seg) for seg in self._segments(last)]
            kws: list[ir.Inline] = []
            for i, p in enumerate(x for x in parts if x):
                if i:
                    kws.append(ir.Text(" · "))
                kws.extend(p)
            self.meta.keywords = kws
            return []
        if name == "curraddr":
            self.meta.affiliations.append([ir.Text("Current address: "), *self._inl(last)])
            return []
        if name == "urladdr":
            url = self._h()._url_text(last)
            self.meta.affiliations.append([ir.Text("URL: "), ir.Link([ir.Text(url)], url)])
            return []
        if name in ("dedicatory", "dedication"):
            self._front_note([ir.Emphasis(self._inl(last), "italic")])
            return []
        if name == "subtitle" or (name == "title" and moderncv):
            self.meta.subtitle = self._inl(last)
            return []
        if name in ("subject", "titlehead", "publishers", "uppertitleback", "lowertitleback",
                    "extratitle"):
            self._front_note(self._inl(last))
            return []
        if name in ("cortext", "fntext"):
            mark = "∗" if name == "cortext" else self._fn_mark(self._opt(node) or "")
            self._front_note([_sup(mark), ir.Text(" "), *self._inl(last)])
            return []
        if name == "abstract":  # sn-jnl \abstract{...}
            self.meta.abstract = self.blocks(last)  # type: ignore[attr-defined]
            return []
        if name == "icmltitle":
            self.meta.title = self._inl(last)
            return []
        if name == "icmlauthor" and len(groups) >= 2:
            inl = self._inl(groups[0])
            keys = [k.strip() for k in self._h()._chars_of(groups[1]).split(",") if k.strip()]
            nums = []
            for k in keys:
                if k not in self._icml_keys:
                    self._icml_keys.append(k)
                nums.append(str(self._icml_keys.index(k) + 1))
            if nums:
                inl.append(_sup(",".join(nums)))
            self.meta.authors.append(inl)
            return []
        if name == "icmlaffiliation" and len(groups) >= 2:
            key = self._h()._chars_of(groups[0]).strip()
            if key not in self._icml_keys:
                self._icml_keys.append(key)
            mark = str(self._icml_keys.index(key) + 1)
            self.meta.affiliations.append([_sup(mark), *self._affil_inlines(groups[1])])
            return []
        if name == "icmlcorrespondingauthor" and len(groups) >= 2:
            self._front_note([ir.Text("Correspondence to: "), *self._inl(groups[0]),
                        ir.Text(" <"), *self._inl(groups[1]), ir.Text(">")])
            return []
        if name == "appendices":  # IEEEtran
            self.in_appendix = True
            return []
        if name == "bmhead":  # sn-jnl back-matter heading
            return [ir.Heading(2, self._inl(last), numbered=False)]
        if name in ("addsec", "addchap", "addpart"):  # KOMA unnumbered divisions
            return [ir.Heading(1, self._inl(last), numbered=False, part=name == "addpart")]
        if name == "minisec":
            return [ir.Paragraph([ir.Emphasis(self._inl(last), "bold")])]
        if name == "frametitle":
            return [ir.Heading(2, self._inl(last), numbered=False)]
        if name == "framesubtitle":
            return [ir.Paragraph([ir.Emphasis(self._inl(last), "italic")])]
        if name == "frame":  # beamer \frame{...}
            return self.blocks(last)  # type: ignore[attr-defined, no-any-return]
        if name == "opening":
            return [ir.Paragraph(self._inl(last))]
        if name == "closing":
            out: list[ir.Block] = [ir.Paragraph(self._inl(last))]
            if self.letter_signature:
                out.append(ir.Paragraph(list(self.letter_signature)))
            return out
        if name in ("ps", "cc", "encl"):
            lead = {"ps": [], "cc": [ir.Text("cc: ")], "encl": [ir.Text("encl: ")]}[name]
            return [ir.Paragraph([*lead, *self._inl(last)])]
        if name == "signature":
            self.letter_signature = self._inl(last)
            return []
        if name == "name" and moderncv and len(groups) >= 2:
            self.meta.title = [*self._inl(groups[0]), ir.Text(" "), *self._inl(groups[1])]
            return []
        if name in ("phone", "mobile", "homepage", "social", "extrainfo") or (
                name == "address" and moderncv):
            labels: dict[str, str] = {
                "phone": "Phone", "mobile": "Mobile", "homepage": "Homepage",
                "social": (self._opt(node) or "Social").capitalize(), "address": "Address"}
            field = labels.get(name)
            parts = [self._inl(g) for g in groups]
            line: list[ir.Inline] = [ir.Text(f"{field}: ")] if field else []
            for i, p in enumerate(x for x in parts if x):
                if i:
                    line.append(ir.Text(", "))
                line.extend(p)
            self._front_note(line)
            return []
        if name in ("cventry", "cvitem", "cvitemwithcomment", "cvlistitem", "cvdoubleitem",
                    "cvlistdoubleitem", "cvline"):
            return self._cv(name, groups)
        return None

    def _fn_mark(self, label: str) -> str:
        if label not in self._fn_marks:
            self._fn_marks[label] = str(len(self._fn_marks) + 1)
        return self._fn_marks[label]

    def _cv(self, name: str, groups: list[list]) -> list[ir.Block]:
        """moderncv entries as plain paragraphs."""
        g = [self._inl(x) for x in groups]

        def join(parts: list[list[ir.Inline]], sep: str = ", ") -> list[ir.Inline]:
            out: list[ir.Inline] = []
            for i, p in enumerate(x for x in parts if x):
                if i:
                    out.append(ir.Text(sep))
                out.extend(p)
            return out

        def item(label: list[ir.Inline], text: list[ir.Inline]) -> ir.Paragraph:
            lead: list[ir.Inline] = [ir.Emphasis(label, "bold"), ir.Text(": ")] if label else []
            return ir.Paragraph([*lead, *text])

        if name == "cventry" and len(g) >= 6:
            line: list[ir.Inline] = []
            if g[0]:
                line += [*g[0], ir.Text("  ")]
            line += [ir.Emphasis(g[1], "bold")] if g[1] else []
            rest = join(g[2:5])
            if rest:
                line += [ir.Text(", ") if g[1] else ir.Text(""), *rest]
            if g[5]:
                line += [ir.LineBreak(), *g[5]]
            return [ir.Paragraph(line)]
        if name in ("cvitem", "cvline") and len(g) >= 2:
            return [item(g[0], g[1])]
        if name == "cvitemwithcomment" and len(g) >= 3:
            return [item(g[0], join([g[1], g[2]], " — "))]
        if name == "cvlistitem" and g:
            return [ir.Paragraph([ir.Text("• "), *g[0]])]
        if name == "cvdoubleitem" and len(g) >= 4:
            return [item(g[0], g[1]), item(g[2], g[3])]
        if name == "cvlistdoubleitem" and len(g) >= 2:
            return [ir.Paragraph([ir.Text("• "), *g[0]]), ir.Paragraph([ir.Text("• "), *g[1]])]
        return []

    # -- inline commands ------------------------------------------------------ #

    def front_inline(self, node: LatexMacroNode, out: list[ir.Inline]) -> bool:
        name = node.macroname
        if name == "corref":
            out.append(_sup("∗"))
            return True
        if name == "fnref":
            label = self._h()._chars_of(self._h()._group_nodes(node)).strip()
            out.append(_sup(",".join(self._fn_mark(x.strip()) for x in label.split(","))))
            return True
        if name == "IEEEmembership":
            out.append(ir.Emphasis(self._inl(self._h()._group_nodes(node)), "italic"))
            return True
        if name == "orcidID":
            oid = self._h()._chars_of(self._h()._group_nodes(node)).strip()
            if oid:
                url = f"https://orcid.org/{oid}"
                self.meta.affiliations.append([ir.Link([ir.Text(f"ORCID: {oid}")], url)])
            return True
        if name in ("email", "ead"):  # inside \institute / an author block
            out.append(ir.Emphasis(self._inl(self._h()._group_nodes(node)), "typewriter"))
            return True
        if name in ("and", "And", "AND"):
            out.append(ir.Text(" · "))
            return True
        if name in ("alert",):
            out.append(ir.Emphasis(self._inl(self._h()._group_nodes(node)), "bold"))
            return True
        if name == "newthought":
            out.append(ir.Emphasis(self._inl(self._h()._group_nodes(node)), "smallcaps"))
            return True
        if name in ("pause", "titlepage", "IEEEpeerreviewmaketitle", "makecvtitle", "column"):
            return True
        if name in TRANSPARENT:
            groups = self._groups(node)
            out.extend(self.inlines(groups[-1]) if groups else [])  # type: ignore[attr-defined]
            return True
        return False

    # -- environments ----------------------------------------------------------- #

    def front_env(self, node: LatexEnvironmentNode, out: list[ir.Block]) -> bool:
        base = node.environmentname.rstrip("*")
        if base == "letter":
            groups = [a for a in (node.nodeargd.argnlist if node.nodeargd else [])
                      if isinstance(a, LatexGroupNode) and a.delimiters
                      and a.delimiters[0] == "{"]
            if self.letter_from:
                out.append(ir.Paragraph(list(self.letter_from), align="right"))
            if groups:
                out.append(ir.Paragraph(self._inl(groups[0].nodelist)))
            out.extend(self.blocks(node.nodelist))  # type: ignore[attr-defined]
            return True
        if base == "frame":  # beamer: \begin{frame}[opts]{Title}{Subtitle}
            nodes = list(node.nodelist)
            while nodes and _blank(nodes[0]):
                nodes.pop(0)
            if nodes and isinstance(nodes[0], LatexCharsNode) and nodes[0].chars.startswith("["):
                close = nodes[0].chars.find("]")
                rest = nodes[0].chars[close + 1:] if close >= 0 else ""
                nodes.pop(0)
                if rest.strip():
                    nodes.insert(0, _chars_like(node, rest))
            while nodes and _blank(nodes[0]):
                nodes.pop(0)
            if nodes and isinstance(nodes[0], LatexGroupNode):
                title = self._inl(nodes.pop(0).nodelist)
                if title:
                    out.append(ir.Heading(2, title, numbered=False))
            out.extend(self.blocks(nodes))  # type: ignore[attr-defined]
            return True
        if base == "icmlauthorlist":
            out.extend(self.blocks(node.nodelist))  # type: ignore[attr-defined]
            return True
        return False


def _blank(n: Any) -> bool:
    if isinstance(n, LatexCharsNode):
        return not n.chars.strip()
    return type(n).__name__ == "LatexCommentNode"


def _chars_like(env: LatexEnvironmentNode, text: str) -> LatexCharsNode:
    return LatexCharsNode(text, parsing_state=env.parsing_state, pos=env.pos, len=len(text))


def _top_level_split(s: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for c in s:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    parts.append("".join(buf))
    return parts


def _kv_value(part: str) -> str:
    _, _, value = part.partition("=")
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    return value.strip()
