"""Source preprocessing: comment stripping and \\input/\\include flattening."""

from __future__ import annotations

import os
import re

# A TeX comment runs from an unescaped ``%`` to the end of the line *and*
# consumes the line-ending newline plus the next line's leading whitespace.
# Eating the newline is essential: otherwise a full-line ``% comment`` collapses
# to a blank line and is misread as a paragraph break (LaTeX soft newlines and
# comment lines do NOT start a new paragraph -- only a blank line / \par does).
_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*(?:\n[ \t]*)?")
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
# import package: \import{dir/}{file}, \subimport{dir/}{file} (and *from variants)
_IMPORT_RE = re.compile(
    r"\\(?:sub)?(?:import|includefrom|inputfrom)\s*\{([^}]+)\}\s*\{([^}]+)\}"
)
# booktabs \cmidrule(lr){2-3} trim spec -- drop the (lr)/(l)/(r) so the static
# parser sees a clean \cmidrule{2-3} mandatory argument.
_CMIDRULE_TRIM_RE = re.compile(r"(\\cmidrule)\s*\([lr]*\)")


def strip_comments(source: str) -> str:
    """Remove LaTeX line comments, preserving escaped ``\\%``."""
    return _COMMENT_RE.sub("", source)


def flatten_inputs(source: str, base_dir: str, _depth: int = 0) -> str:
    """Inline ``\\input``/``\\include`` (and import-package ``\\import``) files."""
    if _depth > 20:
        return source

    def _inline(path: str) -> str | None:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                inner = strip_comments(fh.read())
            return flatten_inputs(inner, os.path.dirname(path) or base_dir, _depth + 1)
        return None

    def repl(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        candidates = [name, name + ".tex"] if not name.endswith(".tex") else [name]
        for cand in candidates:
            inlined = _inline(os.path.join(base_dir, cand))
            if inlined is not None:
                return inlined
        return ""  # missing include -> drop (graceful degradation)

    def import_repl(match: re.Match[str]) -> str:
        # \import{dir/}{file}: the file lives under dir, relative to base_dir
        directory, name = match.group(1).strip(), match.group(2).strip()
        candidates = [name, name + ".tex"] if not name.endswith(".tex") else [name]
        for cand in candidates:
            inlined = _inline(os.path.join(base_dir, directory, cand))
            if inlined is not None:
                return inlined
        return ""

    source = _IMPORT_RE.sub(import_repl, source)
    return _INPUT_RE.sub(repl, source)


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
    r"\\(?:lstinputlisting|verbatiminput)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)


def inline_listing_files(source: str, base_dir: str) -> str:
    def repl(match: re.Match[str]) -> str:
        path = os.path.join(base_dir, match.group(1).strip())
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                body = fh.read().rstrip("\n")
            return "\\begin{verbatim}\n" + body + "\n\\end{verbatim}"
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
    # optional [options]; allow one level of nested {…}/[…] so keys whose value
    # is braced (e.g. [caption={[x]}]) don't truncate at the inner ``]``.
    r"[ \t]*(?:\[(?:[^\[\]{}]|\{[^{}]*\}|\[[^\]]*\])*\])?"
    r"[ \t]*(?:\{[^}]*\})?"    # optional {lang} (minted)
    r"(?P<body>.*?)"
    r"\\end\{\1\}",
    re.DOTALL,
)


def normalize_listing_envs(source: str) -> str:
    """Rewrite ``lstlisting``/``minted``/``Verbatim`` blocks to ``verbatim``."""
    return _LISTING_ENV_RE.sub(
        lambda m: "\\begin{verbatim}" + m.group("body") + "\\end{verbatim}",
        source,
    )


# amsmath \DeclareMathOperator{\name}{body} (and starred, with limits) -> a
# \newcommand that wraps the body in \operatorname, which the math path renders.
# The body may itself contain a braced group (e.g. \DeclareMathOperator*{\Exp}{\mathbb{E}}),
# so allow one level of nesting rather than only brace-free bodies.
_DECLAREMATHOP_RE = re.compile(
    r"\\DeclareMathOperator\s*(\*?)\s*\{\s*\\([A-Za-z]+)\s*\}\s*"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)


def _rewrite_mathoperators(source: str) -> str:
    def repl(m: re.Match[str]) -> str:
        star, name, body = m.group(1), m.group(2), m.group(3)
        return rf"\newcommand{{\{name}}}{{\operatorname{star}{{{body}}}}}"

    return _DECLAREMATHOP_RE.sub(repl, source)


_IFFALSE_RE = re.compile(r"\\iffalse(?![a-zA-Z@])")
# An \if… opener is a control word (letters only, so it stops at a non-letter such
# as the digit in \ifnum1>0); \fi closes. The negative lookahead keeps \fi from
# matching \fill/\final.
_IFFI_RE = re.compile(r"\\(if[a-zA-Z@]*|fi(?![a-zA-Z@]))")


def strip_iffalse(source: str) -> str:
    """Drop ``\\iffalse … \\fi`` blocks (a common way to comment out whole sections).

    Left in, the disabled content is wrongly included in the output. Nested
    ``\\if…``/``\\fi`` are tracked so the matching ``\\fi`` closes the block.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        m = _IFFALSE_RE.search(source, i)
        if not m:
            out.append(source[i:])
            break
        out.append(source[i : m.start()])
        depth, j = 1, m.end()
        for cm in _IFFI_RE.finditer(source, m.end()):
            depth += -1 if cm.group(1) == "fi" else 1
            if depth == 0:
                j = cm.end()
                break
        else:
            j = n  # unbalanced -> drop to end of source
        i = j
    return "".join(out)


def preprocess(source: str, base_dir: str = ".") -> str:
    # Flatten \input/\include FIRST so every later rewrite (listing normalisation,
    # \verb/\lstinline, math operators, …) sees the included content too.
    # Otherwise a code listing pulled in via \input keeps its raw lstlisting form
    # and a ``$`` in the code (R's df$col) breaks parsing -- the very bug that
    # copy-pasting the same text avoided.
    source = flatten_inputs(strip_comments(source), base_dir)
    source = strip_iffalse(source)  # drop \iffalse…\fi disabled blocks
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
