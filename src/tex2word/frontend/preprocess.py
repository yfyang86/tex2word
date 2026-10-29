"""Source preprocessing: comment stripping and \\input/\\include flattening."""

from __future__ import annotations

import os
import re

from .conditionals import resolve_conditionals

# A TeX comment runs from an unescaped ``%`` to the end of the line *and*
# consumes the line-ending newline plus the next line's leading whitespace.
# Eating the newline is essential: otherwise a full-line ``% comment`` collapses
# to a blank line and is misread as a paragraph break (LaTeX soft newlines and
# comment lines do NOT start a new paragraph -- only a blank line / \par does).
# \input{f}, \include{f}, and the plain-TeX \input f (ended by a space)
_INPUT_RE = re.compile(
    r"\\(?:input|include)\s*\{([^}]+)\}|\\input[ \t]+(?![\\{])([^\s{}%\\]+)"
)
# subfiles: \subfile{f} / \subfileinclude{f} inline the subfile's document body
_SUBFILE_RE = re.compile(r"\\subfile(?:include)?\s*\{([^}]+)\}")
_ENDINPUT_RE = re.compile(r"\\endinput(?![A-Za-z@])")
# import package: \import{dir/}{file}, \subimport{dir/}{file} (and *from variants)
_IMPORT_RE = re.compile(
    r"\\(?:sub)?(?:import|includefrom|inputfrom)\s*\{([^}]+)\}\s*\{([^}]+)\}"
)
# booktabs \cmidrule(lr){2-3} trim spec -- drop the (lr)/(l)/(r) so the static
# parser sees a clean \cmidrule{2-3} mandatory argument.
_CMIDRULE_TRIM_RE = re.compile(r"(\\cmidrule)\s*\([lr]*\)")


#: environments whose body is verbatim: a ``%`` there is text, not a comment
_VERBATIM_ENVS = (
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "BVerbatim", "LVerbatim",
    "lstlisting", "minted", "alltt", "filecontents", "filecontents*", "comment",
    "spverbatim", "boxedverbatim",
)
_COMMENT_SCAN_RE = re.compile(
    r"\\begin\s*\{(?P<env>" + "|".join(re.escape(e) for e in _VERBATIM_ENVS) + r")\}"
    r"|\\(?P<inline>verb\*?|lstinline|url|path|nolinkurl)(?![A-Za-z])"
    r"|\\[\\%]"  # \\ and \% are not comment starts
    r"|%"
)


def strip_comments(source: str) -> str:
    """Remove LaTeX line comments, preserving escaped ``\\%`` and the bodies of
    verbatim environments, ``\\verb``/``\\lstinline`` and ``\\url``/``\\path``
    arguments, where ``%`` is literal text."""
    if "%" not in source:
        return source
    out: list[str] = []
    pos = 0
    n = len(source)
    while True:
        m = _COMMENT_SCAN_RE.search(source, pos)
        if m is None:
            out.append(source[pos:])
            break
        start = m.start()
        if m.group("env"):
            end_tag = "\\end{" + m.group("env") + "}"
            stop = source.find(end_tag, m.end())
            stop = n if stop < 0 else stop + len(end_tag)
            out.append(source[pos:stop])
            pos = stop
        elif m.group("inline"):
            stop = _inline_verbatim_end(source, m.end(), m.group("inline"))
            out.append(source[pos:stop])
            pos = stop
        elif m.group(0) == "%":
            out.append(source[pos:start])
            line_end = source.find("\n", start)
            if line_end < 0:
                pos = n
                break
            # a comment eats its newline and the next line's indentation
            pos = line_end + 1
            while pos < n and source[pos] in " \t":
                pos += 1
        else:  # \\ or \%
            out.append(source[pos:m.end()])
            pos = m.end()
    return "".join(out)


def _inline_verbatim_end(s: str, i: int, cmd: str) -> int:
    """End index of the argument of ``\\verb|..|``, ``\\lstinline[..]{..}``,
    ``\\url{..}`` & co. that starts at ``i`` (``i`` itself if there is none)."""
    n = len(s)
    if cmd == "lstinline" and i < n and s[i] == "[":
        close = s.find("]", i)
        i = n if close < 0 else close + 1
    if i >= n:
        return n
    if s[i] == "{" and cmd != "verb" and cmd != "verb*":
        depth = 0
        for j in range(i, n):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
            elif s[j] == "\n" and cmd in ("url", "path", "nolinkurl"):
                return j  # never let a broken \url swallow the document
        return n
    delim = s[i]
    if delim.isspace() or delim.isalpha():
        return i
    close = s.find(delim, i + 1)
    line_end = s.find("\n", i + 1)
    if close < 0 or (0 <= line_end < close):
        return i  # not a well-formed inline verbatim: treat normally
    return close + 1


def flatten_inputs(
    source: str, base_dir: str, _depth: int = 0, _dirs: list[str] | None = None
) -> str:
    """Inline ``\\input``/``\\include`` (and import-package ``\\import``) files.

    As in TeX, a nested ``\\input`` resolves against the main document's
    directory first and only then against the including file's directory
    (``gen/outer.tex`` doing ``\\input{gen/inner}`` means ``gen/inner.tex``).
    Inside an ``\\import``-ed file, the import directory comes first.
    """
    if _depth > 20:
        return source
    dirs = _dirs or [base_dir]

    def _inline(path: str, nested: list[str], *, body_only: bool = False) -> str:
        with open(path, encoding="utf-8") as fh:
            inner = strip_comments(_control_chars(fh.read()))
        if body_only:  # a subfile: only what is between \begin/\end{document}
            b = inner.find("\\begin{document}")
            e = inner.rfind("\\end{document}")
            if b >= 0:
                inner = inner[b + len("\\begin{document}"):e if e > b else len(inner)]
        end = _ENDINPUT_RE.search(inner)
        if end:  # \endinput: TeX stops reading this file after the current line
            line_end = inner.find("\n", end.end())
            inner = inner[:end.start()] + (inner[end.end():line_end] if line_end >= 0 else "")
        return flatten_inputs(inner, base_dir, _depth + 1, _dedupe(nested))

    def _find(name: str, search: list[str]) -> str | None:
        candidates = [name, name + ".tex"] if not name.endswith(".tex") else [name]
        for directory in search:
            for cand in candidates:
                path = os.path.join(directory, cand)
                if os.path.isfile(path):
                    return path
        return None

    def _glue(match: re.Match[str], text: str) -> str:
        # \protect\input{f} must not glue f's first word onto \protect
        before = match.string[max(0, match.start() - 64) : match.start()]
        if re.search(r"\\[A-Za-z@]+$", before):
            return " " + text
        return text

    def repl(match: re.Match[str]) -> str:
        path = _find((match.group(1) or match.group(2)).strip(), dirs)
        if path is None:
            return ""  # missing include -> drop (graceful degradation)
        return _glue(match, _inline(path, [dirs[0], os.path.dirname(path)]))

    def subfile_repl(match: re.Match[str]) -> str:
        # a subfile's own paths are relative to its directory (subfiles package)
        path = _find(match.group(1).strip(), dirs)
        if path is None:
            return ""
        return _glue(match, _inline(path, [os.path.dirname(path), dirs[0]], body_only=True))

    def import_repl(match: re.Match[str]) -> str:
        # \import{dir/}{file}: the file lives under dir, relative to the
        # current file; its own \input{}s look in dir first
        directory, name = match.group(1).strip(), match.group(2).strip()
        path = _find(name, [os.path.join(d, directory) for d in dirs])
        if path is None:
            return ""
        return _glue(match, _inline(path, [os.path.dirname(path), *dirs]))

    source = _IMPORT_RE.sub(import_repl, source)
    source = _SUBFILE_RE.sub(subfile_repl, source)
    return _INPUT_RE.sub(repl, source)


def _dedupe(dirs: list[str]) -> list[str]:
    out: list[str] = []
    for d in dirs:
        norm = os.path.normpath(d or ".")
        if norm not in out:
            out.append(norm)
    return out


#: \verb* (show-spaces form) -> \verb, which pylatexenc parses natively.
_VERBSTAR_RE = re.compile(r"\\verb\*")

# Delimiter-form inline listings -> \verb<delim>…<delim>, which pylatexenc parses
# natively. \lstinline[opt]|code| and \mintinline[opt]{lang}|code| (any non-brace
# delimiter). The brace forms (\lstinline{code}, \mintinline{lang}{code}) are
# left for the parser to handle as a normal {} argument.
_LSTINLINE_DELIM_RE = re.compile(r"\\lstinline\s*(?:\[[^\]]*\])?\s*([^\s{[*])")
_MINTINLINE_DELIM_RE = re.compile(r"\\mintinline\s*(?:\[[^\]]*\])?\s*\{[^}]*\}\s*([^\s{[*])")


# \lstinputlisting[opts]{file} / \verbatiminput{file}: embed an external source
# file verbatim. Resolved after flattening so the file body is never
# comment-stripped (a literal "%" in code must survive).
_LSTINPUT_RE = re.compile(
    r"\\(?:lstinputlisting|verbatiminput)\s*(?:\[(?P<opts>(?:[^\[\]{}]|\{[^{}]*\})*)\])?"
    r"\s*\{([^}]+)\}"
)


def _split_options(opts: str) -> dict[str, str]:
    """``key=value`` pairs of a listings option list (top-level commas only)."""
    out: dict[str, str] = {}
    depth, buf, parts = 0, "", []
    for c in opts:
        depth += 1 if c in "{[" else -1 if c in "}]" else 0
        if c == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += c
    parts.append(buf)
    for part in parts:
        key, eq, value = part.partition("=")
        if eq:
            value = value.strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1].strip()
            out[key.strip().lower()] = value
    return out


def _listing_marker(opts: str | None) -> str:
    """``\\twlistingcaption{label}{caption}{1|0}`` for a listing's
    ``caption=``/``title=``/``label=`` options (empty if it has none)."""
    if not opts:
        return ""
    kv = _split_options(opts)
    caption, numbered = kv.get("caption"), "1"
    if caption is None and "title" in kv:
        caption, numbered = kv["title"], "0"
    if caption and caption.startswith("["):  # caption={[short]long}
        close = caption.find("]")
        caption = caption[close + 1:].strip() if close >= 0 else caption
    label = kv.get("label", "")
    if not caption and not label:
        return ""
    return f"\\twlistingcaption{{{label}}}{{{caption or ''}}}{{{numbered}}}"


def inline_listing_files(source: str, base_dir: str) -> str:
    def repl(match: re.Match[str]) -> str:
        path = os.path.join(base_dir, match.group(2).strip())
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                body = fh.read().rstrip("\n")
            return (_listing_marker(match.group("opts"))
                    + "\\begin{verbatim}\n" + body + "\n\\end{verbatim}")
        return ""  # missing source file -> drop (graceful degradation)

    return _LSTINPUT_RE.sub(repl, source)


# Code-listing environments pylatexenc has no verbatim spec for. Left alone, it
# parses their bodies as LaTeX -- so a ``$`` in the code (e.g. R's ``df$col``)
# opens math mode and, with an odd count, swallows the rest of the document
# (the listing never closes; everything after renders as code). Normalising them
# to ``verbatim`` (which pylatexenc captures literally) fixes that and drops the
# ``[options]`` / minted ``{lang}`` that would otherwise leak in as a code line.
# Backreference \1 ties \end to the same environment name.
_LISTING_ENV_RE = re.compile(
    r"\\begin\{(lstlisting|minted|Verbatim\*?|verbatim\*)\}"
    # optional [options]; allow two levels of nested {…}/[…] so braced keys like
    # [caption={[x]}] or [caption={\textbf{C}}] don't truncate at an inner ]/}.
    r"[ \t]*(?:\[(?P<opts>(?:[^\[\]{}]|\{(?:[^{}]|\{[^{}]*\})*\}|\[[^\]]*\])*)\])?"
    r"[ \t]*(?:\{[^}]*\})?"    # optional {lang} (minted)
    r"(?P<body>.*?)"
    r"\\end\{\1\}",
    re.DOTALL,
)


def normalize_listing_envs(source: str) -> str:
    """Rewrite ``lstlisting``/``minted``/``Verbatim`` blocks to ``verbatim``."""
    # lstlisting's caption=/label= become a marker the parser attaches to the
    # code block (a numbered, referenceable "Listing N")
    return _LISTING_ENV_RE.sub(
        lambda m: (_listing_marker(m.group("opts")) if m.group(1) == "lstlisting" else "")
        + "\\begin{verbatim}" + m.group("body") + "\\end{verbatim}",
        source,
    )


# amsmath \DeclareMathOperator{\name}{body} (and starred, with limits) -> a
# \newcommand that wraps the body in \operatorname, which the math path renders.
# The body may itself contain braced groups (e.g. \DeclareMathOperator*{\Exp}{\mathbb{E}}
# or \mathbb{\mathcal{E}}), so allow two levels of nesting, not just brace-free bodies.
_DECLAREMATHOP_RE = re.compile(
    r"\\DeclareMathOperator\s*(\*?)\s*\{\s*\\([A-Za-z]+)\s*\}\s*"
    r"\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}"
)


def _rewrite_mathoperators(source: str) -> str:
    def repl(m: re.Match[str]) -> str:
        star, name, body = m.group(1), m.group(2), m.group(3)
        return rf"\newcommand{{\{name}}}{{\operatorname{star}{{{body}}}}}"

    return _DECLAREMATHOP_RE.sub(repl, source)


_IFFALSE_RE = re.compile(r"\\iffalse(?![a-zA-Z@])")
# An \if… opener is a control word (letters only, so it stops at a non-letter such
# as the digit in \ifnum1>0); \fi closes; \else splits. The negative lookahead
# keeps \fi from matching \fill/\final and \else from \elsewhere.
_IFFI_RE = re.compile(r"\\(if[a-zA-Z@]*|else(?![a-zA-Z@])|fi(?![a-zA-Z@]))")


def strip_iffalse(source: str) -> str:
    """Resolve ``\\iffalse … \\fi`` blocks (a common way to comment out sections).

    The false branch is dropped; an ``\\else`` branch (``\\iffalse A \\else B \\fi``
    -> ``B``) is kept, per TeX semantics. Nested ``\\if…``/``\\fi`` are tracked so
    the matching ``\\fi`` closes the block and a nested ``\\else`` isn't mistaken
    for this block's.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        m = _IFFALSE_RE.search(source, i)
        if not m:
            out.append(source[i:])
            break
        out.append(source[i : m.start()])
        depth = 1
        else_at: int | None = None  # end offset of a top-level \else, if any
        j = n  # unbalanced -> drop to end of source
        for cm in _IFFI_RE.finditer(source, m.end()):
            tok = cm.group(1)
            if tok == "else":
                if depth == 1 and else_at is None:
                    else_at = cm.end()  # this block's else branch starts here
                continue
            depth += -1 if tok == "fi" else 1
            if depth == 0:
                # keep the else branch (between \else and \fi), drop the rest
                if else_at is not None:
                    out.append(source[else_at : cm.start()])
                j = cm.end()
                break
        i = j
    return "".join(out)


# Common typo: the star of a starred environment belongs on the *name*
# (\begin{figure*}), but authors sometimes write \begin*{figure}/\end*{figure}.
# Normalise it so figure*/table* spanning (etc.) still works.
_BEGINEND_STAR_RE = re.compile(r"\\(begin|end)\*\s*\{([^}]*)\}")


def _normalize_begin_star(source: str) -> str:
    return _BEGINEND_STAR_RE.sub(
        lambda m: f"\\{m.group(1)}{{{m.group(2).strip().rstrip('*')}*}}", source
    )


# exam document class: question/part markers (with an optional [points] arg) and
# the questions/parts/subparts environments. \miquestion is a common alias
# (oxmathproblems.cls: \newcommand{\miquestion}[1][]{\question}).
_EXAM_ITEM_RE = re.compile(r"\\(?:miquestion|question|subpart|part)\b\s*(?:\[[^\]]*\])?")
_EXAM_ENVS = ("questions", "parts", "subparts")
# exam's answer environments — shown only under \printanswers, hidden otherwise.
_EXAM_SOLUTION_ENVS = ("solution", "solutionorbox", "solutionorlines", "solutionordottedlines")


def _uses_exam_class(source: str, base_dir: str) -> bool:
    """True if the document is (directly or via a local ``.cls``) the exam class."""
    if re.search(r"\\documentclass(?:\[[^\]]*\])?\{exam\}", source):
        return True
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", source)
    if not m:
        return False
    path = os.path.join(base_dir, m.group(1).strip() + ".cls")
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return False
    return bool(re.search(r"\\LoadClass(?:WithOptions)?(?:\[[^\]]*\])?\{exam\}", content))


def _rewrite_exam_class(source: str, base_dir: str) -> str:
    """Rewrite the ``exam`` class's structure into nested ``enumerate``/``\\item``.

    ``questions``/``parts``/``subparts`` → ``enumerate``; ``\\question``/
    ``\\miquestion``/``\\part``/``\\subpart`` (dropping any ``[points]``) →
    ``\\item``. This renders the sheet as nested numbered lists and, crucially,
    stops exam's ``\\part`` (a subpart) from being mistaken for standard LaTeX
    ``\\part`` sectioning (which produced garbage like "Part I D").
    """
    if not _uses_exam_class(source, base_dir):
        return source
    # solutions are printed only under \printanswers; otherwise drop them so the
    # output matches the compiled sheet (and their text doesn't leak into the
    # preceding question item).
    if not re.search(r"\\printanswers\b", source):
        for env in _EXAM_SOLUTION_ENVS:
            source = re.sub(
                r"\\begin\{" + env + r"\}.*?\\end\{" + env + r"\}",
                "",
                source,
                flags=re.DOTALL,
            )
    for env in _EXAM_ENVS:
        source = re.sub(r"\\begin\{" + env + r"\}", r"\\begin{enumerate}", source)
        source = re.sub(r"\\end\{" + env + r"\}", r"\\end{enumerate}", source)
    return _EXAM_ITEM_RE.sub(r"\\item ", source)


# TikZ drawing primitives — if any of these appear, the picture is a real
# diagram (leave it for the image/compile path, not text recovery).
_TIKZ_DRAW_RE = re.compile(
    r"\\(draw|fill|filldraw|path|clip|shade|shadedraw|pgf|coordinate|foreach|pic)\b"
)
# a \tikzstyle{name} = [ ... ] declaration (produces no content)
_TIKZSTYLE_RE = re.compile(r"\\tikzstyle\s*\{[^}]*\}\s*=\s*\[[^\]]*\]", re.DOTALL)


def _extract_tikz_nodes(body: str) -> list[tuple[str, str]]:
    """Return each ``\\node[style] … {content}``'s (style, content)."""
    nodes: list[tuple[str, str]] = []
    for m in re.finditer(r"\\node\b", body):
        i = m.end()
        while i < len(body) and body[i] in " \t\n\r":
            i += 1
        style = ""
        if i < len(body) and body[i] == "[":
            style, i = _read_balanced(body, i, "[", "]")
        brace = body.find("{", i)
        if brace == -1:
            continue
        content, _ = _read_balanced(body, brace, "{", "}")
        nodes.append((style, content))
    return nodes


def _recover_tikz_boxes(source: str) -> str:
    """Recover content from the "cheatsheet" TikZ idiom — a ``tikzpicture`` that
    is just ``\\node{…minipage…}`` content boxes plus a ``\\node[fancytitle]{Title}``,
    with no drawing. Without a TeX engine these otherwise become empty graphics
    placeholders, losing all the content. A `title`-styled node becomes a
    ``\\subsection*``; the rest is emitted inline. Pictures with real drawing
    primitives are left untouched (the image/compile path handles them).
    """

    def repl(match: re.Match[str]) -> str:
        body = match.group(1)
        if _TIKZ_DRAW_RE.search(body):
            return match.group(0)
        # only the content-box idiom (a minipage or a title node)
        if "\\begin{minipage}" not in body and not re.search(r"title", body, re.I):
            return match.group(0)
        nodes = _extract_tikz_nodes(body)
        if not nodes:
            return match.group(0)
        out: list[str] = []
        for style, content in nodes:
            if re.search(r"title", style, re.I):
                title = content.strip()
                if title:
                    out.append("\n\n\\subsection*{" + title + "}\n")
            else:
                out.append(content)
        return "\n".join(out) + "\n"

    return re.sub(
        r"\\begin\{tikzpicture\}(.*?)\\end\{tikzpicture\}", repl, source, flags=re.DOTALL
    )


def _rewrite_halign(source: str) -> str:
    """Convert a plain-TeX ``\\halign`` alignment (a system of equations) inside
    ``\\[ … \\]`` into an ``array`` the math engine handles. The whole display
    (including the ``\\centerline{\\hbox{\\vbox{\\openup…\\jot …}}}`` wrappers) is
    replaced, so those plain-TeX box/glue primitives never reach the parser.
    """

    def to_array(inner: str) -> str:
        h = inner.find(r"\halign")
        brace = inner.find("{", h)
        if h == -1 or brace == -1:
            return inner
        body, _ = _read_balanced(inner, brace, "{", "}")
        # the template precedes the first \cr; the rest are the data rows
        cr = body.find(r"\cr")
        data = body[cr + 3 :] if cr != -1 else body
        rows = [r.strip() for r in data.split(r"\cr") if r.strip()]
        if not rows:
            return inner
        ncols = max(r.count("&") for r in rows) + 1
        return r"\begin{array}{" + "c" * ncols + "}" + r" \\ ".join(rows) + r"\end{array}"

    out: list[str] = []
    i = 0
    while i < len(source):
        if source.startswith(r"\[", i):
            end = source.find(r"\]", i + 2)
            if end != -1 and r"\halign" in source[i + 2 : end]:
                out.append(r"\[" + to_array(source[i + 2 : end]) + r"\]")
                i = end + 2
                continue
        out.append(source[i])
        i += 1
    return "".join(out)


def _inject_exam_title(source: str) -> str:
    """Oxford-style problem-sheet header: the class puts the title in a fancyhdr
    ``\\chead`` (a page header we don't render), so recover it from the
    ``\\course``/``\\sheetnumber``/``\\oxfordterm``/``\\sheettitle`` values into a
    centred title block at the top of the body."""

    def val(cmd: str) -> str:
        m = re.search(r"\\" + cmd + r"\s*\{([^}]*)\}", source)
        return m.group(1).strip() if m else ""

    course, num, term, title = (
        val("course"),
        val("sheetnumber"),
        val("oxfordterm"),
        val("sheettitle"),
    )
    if not (course or title):
        return source
    lines: list[str] = []
    if course:
        lines.append(r"{\Large\bfseries " + course + "}")
    sheet = f"Sheet {num}" if num else ""
    if term:
        sheet = f"{sheet} --- {term}" if sheet else term
    if sheet:
        lines.append(sheet)
    if title:
        lines.append(title)
    block = "\n\\begin{center}\n" + r"\\".join(lines) + "\n\\end{center}\n"
    return re.sub(r"\\begin\{document\}", lambda m: m.group(0) + block, source, count=1)


# beamer overlay specifications: \item<2->, \alert<1>{..}, \only<2-3>{..}, ...
_OVERLAY_RE = re.compile(
    r"(\\(?:item|only|uncover|visible|invisible|onslide|alt|temporal|alert|textbf|"
    r"textit|emph|color|textcolor|includegraphics|pause|structure|frame|column|"
    r"hyperlink|action)\*?)\s*<[^<>\n]*>"
)
# overlay-only commands: \pause, \onslide<2-> (no argument) carry no content
_OVERLAY_ONLY_RE = re.compile(r"\\(?:pause|onslide)(?![A-Za-z])(?:\s*\[[^\]]*\])?")


def _strip_overlays(source: str) -> str:
    """Remove beamer overlay specifications (the slides are flattened)."""
    return _OVERLAY_ONLY_RE.sub("", _OVERLAY_RE.sub(r"\1", source))


_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0e-\x1f\x7f]")


def _control_chars(source: str) -> str:
    """LaTeX reads a form feed (^^L) as ``\\par``; other C0 control characters
    have no output (and cannot be written to XML)."""
    return _CONTROL_RE.sub("", source.replace("\x0c", "\n\n"))


def preprocess(source: str, base_dir: str = ".") -> str:
    # Flatten \input/\include FIRST so every later rewrite (listing normalisation,
    # \verb/\lstinline, math operators, …) sees the included content too.
    # Otherwise a code listing pulled in via \input keeps its raw lstlisting form
    # and a ``$`` in the code (R's df$col) breaks parsing -- the very bug that
    # copy-pasting the same text avoided.
    source = flatten_inputs(strip_comments(_control_chars(source)), base_dir)
    if re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{beamer\}", source):
        source = _strip_overlays(source)  # \item<2-> \only<1>{..} -> no overlay spec
    if _uses_exam_class(source, base_dir):
        source = _rewrite_exam_class(source, base_dir)  # exam sheets -> nested lists
        source = _inject_exam_title(source)  # recover the fancyhdr title block
    source = _rewrite_halign(source)  # plain-TeX \halign systems -> array
    source = _TIKZSTYLE_RE.sub("", source)  # drop \tikzstyle{…}=[…] declarations
    source = _recover_tikz_boxes(source)  # cheatsheet content-box tikz -> text
    source = _normalize_begin_star(source)  # \begin*{figure} -> \begin{figure*}
    # \iffalse blocks, \newif switches, \ifdefined, \ifthenelse, etoolbox
    # toggles, \IfFileExists, \@ifpackageloaded: keep the branch TeX would take
    source = resolve_conditionals(source, base_dir)
    source = inline_listing_files(source, base_dir)
    source = _rewrite_mathoperators(source)
    source = _VERBSTAR_RE.sub(r"\\verb", source)
    source = _MINTINLINE_DELIM_RE.sub(lambda m: r"\verb" + m.group(1), source)
    source = _LSTINLINE_DELIM_RE.sub(lambda m: r"\verb" + m.group(1), source)
    source = _CMIDRULE_TRIM_RE.sub(r"\1", source)
    return normalize_listing_envs(source)


def _read_balanced(s: str, i: int, open_ch: str, close_ch: str) -> tuple[str, int]:
    """Read a balanced ``open_ch..close_ch`` group; return (inner, end_index)."""
    assert s[i] == open_ch
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_ch:
            depth += 1
        elif s[j] == close_ch:
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
    return s[i + 1 :], len(s)


def _circled(number: int) -> str | None:
    if number == 0:
        return "⓪"  # ⓪
    if 1 <= number <= 20:
        return chr(0x2460 + number - 1)  # ①..⑳
    return None


def _tikz_replacement(content: str) -> str:
    """Render an inline TikZ snippet's fallback: a circled number, else nothing."""
    m = re.findall(r"\{\s*(\d+)\s*\}", content)
    if m:
        circled = _circled(int(m[-1]))
        if circled is not None:
            return circled
        return f"({m[-1]})"
    return ""


def replace_inline_tikz(source: str) -> str:
    """Replace inline ``\\tikz ...;`` / ``\\tikz{...}`` constructs.

    pylatexenc cannot scope inline TikZ (it ends at a ``;`` or a brace group),
    so the raw ``\\node[...]`` markup leaks into the text. We drop the snippet,
    rendering a Unicode circled number when the TikZ is the common
    circled-number idiom (``\\tikz ... \\node ... {3};`` -> ③).
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith("\\tikz", i) and (i + 5 >= n or not source[i + 5].isalpha()):
            j = i + 5
            while j < n and source[j] in " \t\n":
                j += 1
            if j < n and source[j] == "[":  # optional [options]
                _, j = _read_balanced(source, j, "[", "]")
            while j < n and source[j] in " \t\n":
                j += 1
            if j < n and source[j] == "{":  # \tikz{ ... }
                content, j = _read_balanced(source, j, "{", "}")
            else:  # \tikz <path> ;
                end = source.find(";", j)
                if end == -1:
                    end = n
                content, j = source[j:end], min(end + 1, n)
            out.append(_tikz_replacement(content))
            i = j
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


# -- TeX spacing primitives and icon fonts (applied after macro expansion) ---- #

# A TeX dimension: a signed number with a unit, a coefficient times a register
# (0.5\baselineskip), or a bare register (\baselineskip).
_GLUE_UNIT = r"(?:pt|mm|cm|in|em|ex|bp|pc|sp|dd|cc|mu|fil{1,3}|true\s*(?:pt|mm|cm|in))"
_DIMEN = (
    r"(?:[-+]\s*)?(?:(?:\d+(?:\.\d*)?|\.\d+)\s*(?:" + _GLUE_UNIT + r"|\\[A-Za-z@]+)"
    r"|\\[A-Za-z@]+)"
)
_GLUE = _DIMEN + r"(?:\s*plus\s*" + _DIMEN + r")?(?:\s*minus\s*" + _DIMEN + r")?"
#: \vskip/\hskip/\mskip/\kern take a glue/dimen *without braces*, so the parser
#: would otherwise print it ("\vskip -1mm" -> the text "-1mm").
_SPACING_PRIM_RE = re.compile(r"\\(?:vskip|hskip|mskip|kern|mkern)(?![A-Za-z@])\s*" + _GLUE)

#: fontawesome icons with a sensible Unicode stand-in; the rest are dropped
#: (decorative), never printed as their control sequence.
_FA_GLYPHS = {
    "Envelope": "✉", "EnvelopeOpen": "✉", "Phone": "☎", "PhoneAlt": "☎",
    "Check": "✓", "CheckCircle": "✔", "CheckSquare": "☑", "Times": "✗",
    "TimesCircle": "✗", "Close": "✗", "Star": "★", "StarHalf": "★", "Heart": "♥",
    "ArrowRight": "→", "ArrowLeft": "←", "ArrowUp": "↑", "ArrowDown": "↓",
    "LongArrowAltRight": "⟶", "InfoCircle": "ℹ", "Info": "ℹ",
    "ExclamationTriangle": "⚠", "Exclamation": "!", "Question": "?",
    "Copyright": "©", "Music": "♪", "Sun": "☀", "Cloud": "☁", "Plus": "+",
    "Minus": "−", "Bars": "≡", "Square": "□", "Circle": "●", "Flag": "⚑",
}
# \faGithub, \faEnvelope[regular], \faStar* ; \faIcon[regular]{envelope}
_FA_RE = re.compile(r"\\fa([A-Z][A-Za-z]*)\*?(?:\s*\[[^\]]*\])?(?![A-Za-z@])")
_FAICON_RE = re.compile(r"\\faIcon\*?(?:\s*\[[^\]]*\])?\s*\{([^}]*)\}")
_VERBATIM_BLOCK_RE = re.compile(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", re.DOTALL)


def _fa_name_glyph(name: str) -> str:
    # \faIcon{arrow-right} -> ArrowRight
    camel = "".join(p[:1].upper() + p[1:] for p in re.split(r"[-_\s]+", name.strip()) if p)
    return _FA_GLYPHS.get(camel, "")


def _clean_spacing_and_icons(text: str) -> str:
    text = _SPACING_PRIM_RE.sub("", text)
    text = _FAICON_RE.sub(lambda m: _fa_name_glyph(m.group(1)), text)
    return _FA_RE.sub(lambda m: _FA_GLYPHS.get(m.group(1), ""), text)


def normalize_spacing_and_icons(source: str) -> str:
    """Drop TeX spacing primitives together with their glue (``\\vskip -1mm``,
    ``\\kern2pt``) and replace fontawesome icons by a Unicode stand-in (or
    nothing). Verbatim bodies are left untouched."""
    out: list[str] = []
    pos = 0
    for m in _VERBATIM_BLOCK_RE.finditer(source):
        out.append(_clean_spacing_and_icons(source[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_clean_spacing_and_icons(source[pos:]))
    return "".join(out)
