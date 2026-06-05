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
# booktabs \cmidrule(lr){2-3} trim spec -- drop the (lr)/(l)/(r) so the static
# parser sees a clean \cmidrule{2-3} mandatory argument.
_CMIDRULE_TRIM_RE = re.compile(r"(\\cmidrule)\s*\([lr]*\)")


def strip_comments(source: str) -> str:
    """Remove LaTeX line comments, preserving escaped ``\\%``."""
    return _COMMENT_RE.sub("", source)


def flatten_inputs(source: str, base_dir: str, _depth: int = 0) -> str:
    """Inline ``\\input``/``\\include`` files relative to ``base_dir``."""
    if _depth > 20:
        return source

    def repl(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        candidates = [name, name + ".tex"] if not name.endswith(".tex") else [name]
        for cand in candidates:
            path = os.path.join(base_dir, cand)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    inner = strip_comments(fh.read())
                return flatten_inputs(inner, os.path.dirname(path) or base_dir, _depth + 1)
        return ""  # missing include -> drop (graceful degradation)

    return _INPUT_RE.sub(repl, source)


#: \verb* (show-spaces form) -> \verb, which pylatexenc parses natively.
_VERBSTAR_RE = re.compile(r"\\verb\*")


def preprocess(source: str, base_dir: str = ".") -> str:
    source = _VERBSTAR_RE.sub(r"\\verb", source)
    source = _CMIDRULE_TRIM_RE.sub(r"\1", source)
    return flatten_inputs(strip_comments(source), base_dir)


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
