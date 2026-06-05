"""Parsing pseudocode bodies (algorithmic / algpseudocode / algorithm2e).

These packages have no fixed pylatexenc arg signatures, so we walk the raw node
list ourselves. The output is a flat list of :class:`~tex2word.ir.AlgLine`
(indent depth + inline content), which the back-end renders as numbered,
indented lines. This is a best-effort structural rendering -- not a faithful
typeset of every algorithmic macro.
"""

from __future__ import annotations

from collections.abc import Callable

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
)

from .. import ir

InlinesFn = Callable[[list], list]

# command (lowercased) -> ("if {cond} then" template, indent delta after)
_OPEN = {
    "if": ("if", "then"),
    "for": ("for", "do"),
    "forall": ("for all", "do"),
    "while": ("while", "do"),
}
# statement commands taking the rest of the line, mapped to a keyword prefix
_STMT = {
    "state": "", "statex": "", "return": "return ", "print": "print ",
    "require": "Input: ", "ensure": "Output: ", "input": "Input: ",
    "output": "Output: ", "kwin": "Input: ", "kwout": "Output: ",
    "kwresult": "Result: ", "kwdata": "Data: ",
}
_CLOSE = {"endif", "endfor", "endwhile", "endloop", "endfunction", "endprocedure"}
# structural commands that flush the current line and emit their own
_STRUCTURAL = (
    set(_OPEN) | set(_STMT) | _CLOSE
    | {"else", "elsif", "elif", "elseif", "repeat", "until", "loop",
       "function", "procedure", "eif", "uif"}
)
_COMMENT = {"comment", "tcp", "tcc", "tcp*", "algorithmiccomment"}
_SKIP = {"caption", "label"}  # handled at the float level, not in the body


def _kw(text: str) -> ir.Emphasis:
    return ir.Emphasis([ir.Text(text)], "bold")


def _find_algorithmic(nodes: list) -> LatexEnvironmentNode | None:
    for n in nodes:
        if isinstance(n, LatexEnvironmentNode) and n.environmentname.rstrip("*") in (
            "algorithmic", "algorithmicx", "algpseudocode", "algpseudocodex",
        ):
            return n
    return None


def parse_algorithm_body(nodes: list, inlines: InlinesFn) -> list[ir.AlgLine]:
    inner = _find_algorithmic(nodes)
    body = inner.nodelist if inner is not None else nodes
    return _Parser(inlines).run(body)


class _Parser:
    def __init__(self, inlines: InlinesFn) -> None:
        self.inlines = inlines
        self.lines: list[ir.AlgLine] = []
        self.indent = 0
        #: content for the line currently being built (raw nodes + ir inlines)
        self.prefix: list[ir.Inline] = []
        self.pending: list = []

    def run(self, nodes: list) -> list[ir.AlgLine]:
        i, n = 0, len(nodes)
        while i < n:
            node = nodes[i]
            if isinstance(node, LatexMacroNode):
                name = node.macroname.lower()
                if node.macroname in (";", "\\"):  # \; and \\ end a line
                    self._flush()
                    i += 1
                    continue
                if name in _SKIP:  # \caption/\label belong to the float
                    i += 1
                    continue
                if name in _COMMENT:  # attach to the current line, don't flush
                    note, i = self._read_group(nodes, i + 1)
                    self.pending += [ir.Text("  ▷ "), *note]
                    continue
                if name in _STRUCTURAL:
                    self._flush()
                    i = self._command(nodes, i, name)
                    continue
                self.pending.append(node)
                i += 1
            elif _is_semicolon(node):
                self._flush()
                i += 1
            else:
                self.pending.append(node)
                i += 1
        self._flush()
        return self.lines

    # -- line assembly ---------------------------------------------------- #

    def _flush(self) -> None:
        out: list[ir.Inline] = list(self.prefix)
        batch: list = []
        for item in self.pending:
            if isinstance(item, ir.Node):  # already-built inline (e.g. a comment)
                if batch:
                    out += self.inlines(batch)
                    batch = []
                out.append(item)  # type: ignore[arg-type]
            else:
                batch.append(item)
        if batch:
            out += self.inlines(batch)
        if any(not (isinstance(x, ir.Text) and not x.value.strip()) for x in out):
            self.lines.append(ir.AlgLine(max(self.indent, 0), out))
        self.prefix = []
        self.pending = []

    def _emit(self, parts: list[ir.Inline]) -> None:
        self.lines.append(ir.AlgLine(max(self.indent, 0), parts))

    def _read_group(self, nodes: list, i: int) -> tuple[list[ir.Inline], int]:
        nodelist, j = self._peek_group(nodes, i)
        if nodelist is not None:
            return self.inlines(nodelist), j
        return [], i

    def _peek_group(self, nodes: list, i: int) -> tuple[list | None, int]:
        while i < len(nodes) and _is_blank(nodes[i]):
            i += 1
        if i < len(nodes) and isinstance(nodes[i], LatexGroupNode):
            return nodes[i].nodelist, i + 1
        return None, i

    def _run_group(self, nodes: list, i: int) -> int:
        body, j = self._peek_group(nodes, i)
        if body is None:
            return i
        self.indent += 1
        self.run(body)
        self.indent -= 1
        return j

    # -- command dispatch ------------------------------------------------- #

    def _command(self, nodes: list, i: int, name: str) -> int:  # noqa: C901
        if name in ("eif", "uif"):  # algorithm2e \eIf{cond}{then}{else}
            cond, j = self._read_group(nodes, i + 1)
            self._emit([_kw("if"), ir.Text(" "), *cond, ir.Text(" "), _kw("then")])
            j = self._run_group(nodes, j)
            self._emit([_kw("else")])
            j = self._run_group(nodes, j)
            return j
        if name in _OPEN:
            opener, tail = _OPEN[name]
            cond, j = self._read_group(nodes, i + 1)
            self._emit([_kw(opener), ir.Text(" "), *cond, ir.Text(" "), _kw(tail)])
            self.indent += 1
            # algorithm2e puts the body in a following group; algorithmic lets it
            # follow as statements until \End... .
            body, j2 = self._peek_group(nodes, j)
            if body is not None:
                self.run(body)
                self.indent -= 1
                return j2
            return j
        if name in ("elsif", "elif", "elseif"):
            cond, j = self._read_group(nodes, i + 1)
            self.indent -= 1
            self._emit([_kw("else if"), ir.Text(" "), *cond, ir.Text(" "), _kw("then")])
            self.indent += 1
            return j
        if name == "else":
            self.indent = max(self.indent - 1, 0)
            self._emit([_kw("else")])
            self.indent += 1
            return i + 1
        if name in ("repeat", "loop"):
            self._emit([_kw(name)])
            self.indent += 1
            return i + 1
        if name == "until":
            cond, j = self._read_group(nodes, i + 1)
            self.indent = max(self.indent - 1, 0)
            self._emit([_kw("until"), ir.Text(" "), *cond])
            return j
        if name in ("function", "procedure"):
            head, j = self._read_group(nodes, i + 1)
            args, j = self._read_group(nodes, j)
            parts = [_kw(name), ir.Text(" "), *head]
            if args:
                parts += [ir.Text("("), *args, ir.Text(")")]
            self._emit(parts)
            self.indent += 1
            return j
        if name in _CLOSE:
            self.indent = max(self.indent - 1, 0)
            return i + 1
        if name in _STMT:
            prefix = _STMT[name]
            if prefix.strip():
                self.prefix = [_kw(prefix.strip()), ir.Text(" ")]
            return i + 1
        return i + 1


def _is_blank(node) -> bool:
    return isinstance(node, LatexCharsNode) and not node.chars.strip()


def _is_semicolon(node) -> bool:
    return getattr(node, "specials_chars", None) == ";"
