"""Render a standalone TikZ/PGF picture to PNG by compiling it with a TeX engine.

tex2word cannot reproduce arbitrary TikZ as OOXML, so when a figure's only
content is a ``tikzpicture`` (or ``pgfpicture``/``circuitikz``/…) we compile it
with whatever TeX engine is on PATH -- pdflatex for pdflatex papers (their text
fonts), xelatex for Unicode ones (CJK node labels) -- into a cropped
``standalone`` PDF, then rasterise to PNG via the ``pdf`` extra (PDFium).
Everything is best-effort: any missing tool, package, or compile error returns
``None`` and the caller falls back to a caption-only figure. The document
preamble is filtered down to the parts a picture needs (TikZ libraries,
colours, styles, user macros) so journal-class preambles with
``hyperref``/``geometry``/… don't break the standalone build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

# Default order; ``engine_order`` moves pdflatex first for documents written for
# it (no fontspec & co., ASCII picture) and keeps xelatex/lualatex first for
# Unicode documents, whose fontspec/xeCJK set up CJK text in nodes.
_ENGINES = ("xelatex", "lualatex", "pdflatex")
_UNICODE_ENGINES = ("xelatex", "lualatex")

#: drawing environments we try to compile (mirror of the front-end's opaque set)
DRAWING_ENVS = (
    "tikzpicture", "pgfpicture", "circuitikz", "tikzcd", "forest", "pspicture",
)

# Preamble commands a picture may rely on; everything else (geometry, hyperref,
# ctex class options, …) is dropped so the standalone build stays minimal.
_KEEP_MACRO = re.compile(
    r"^\s*\\(usetikzlibrary|usepgflibrary|usepgfplotslibrary|tikzset|pgfplotsset|"
    r"pgfdeclare\w*|definecolor|colorlet|newcommand|renewcommand|providecommand|"
    r"def|let|newif|DeclareMathOperator|newcounter|setlength|tikzstyle)\b"
)
# Packages safe to load in the cropped standalone build and whose macros a
# picture's node text may use. Besides the drawing/math/colour core, this keeps
# symbol and citation packages (pifont's \ding, natbib's \citep, …) so a node
# that embeds document text doesn't fail with "Undefined control sequence".
_KEEP_USEPACKAGE = re.compile(
    r"^\s*\\usepackage\b[^\n]*\{[^}]*\b"
    r"(tikz|pgfplots|pgfplotstable|pgf|pgfgantt|circuitikz|tikz-cd|"
    r"amsmath|amssymb|amsfonts|amsthm|mathtools|mathrsfs|dsfont|bbm|stmaryrd|"
    r"xcolor|color|bm|siunitx|graphicx|"
    r"pifont|wasysym|marvosym|textcomp|fontawesome5|fontawesome|"
    r"natbib|cite)\b"
)
# fontspec/xeCJK lines only make sense under a Unicode engine. (The \b belongs
# to the \set...font alternative: after "}" it could never match.)
_KEEP_FONT = re.compile(r"^\s*\\(usepackage\b[^\n]*\{(fontspec|xeCJK)\}|set(main|CJK\w*)font\b)")
# Text-font/encoding packages, kept for pdflatex so node text uses the paper's
# font (label widths then match the original layout).
_KEEP_PDF_FONT = re.compile(
    r"^\s*\\usepackage\b[^\n]*\{[^}]*\b"
    r"(times|mathptmx|newtxtext|newtxmath|txfonts|helvet|courier|palatino|mathpazo|"
    r"lmodern|libertine|libertinus|charter|bookman|avant|fontenc|inputenc)\b"
)
# A preamble that needs a Unicode engine.
_UNICODE_PREAMBLE = re.compile(
    r"\\usepackage\b[^\n]*\{[^}]*\b(fontspec|xeCJK|unicode-math|polyglossia)\b"
)
# Figure-local definitions outside the pictures that they may rely on.
_LOCAL_DEF = re.compile(
    r"^\s*\\(definecolor|colorlet|tikzset|pgfplotsset|tikzstyle|usetikzlibrary)\b"
)

# Header/footer/page-layout (re)definitions that belong to packages we DROP
# (fancyhdr's \headrulewidth/\footrulewidth, its \fancyhead/\fancyhf/\pagestyle,
# titlesec's \titleformat, …). \renewcommand is otherwise kept for user macros,
# so without this a \renewcommand{\headrulewidth}{0.4pt} survives into the
# standalone build and fails with "\headrulewidth undefined" (fancyhdr absent).
_DROP_LAYOUT = re.compile(
    r"^\s*\\(?:re|provide)?newcommand\*?\s*\{?\s*\\"
    r"(?:head|foot|plainhead|plainfoot)rule(?:width)?\b"
    r"|^\s*\\(?:let|def)\s*\\(?:head|foot|plainhead|plainfoot)rule(?:width)?\b"
    r"|^\s*\\(?:pagestyle|thispagestyle|fancypagestyle|fancyhf|fancyhead|fancyfoot|"
    r"lhead|chead|rhead|lfoot|cfoot|rfoot|fancyheadoffset|fancyfootoffset|"
    r"titleformat|titlespacing)\b"
)

_PICTURE_BEGIN_RE = re.compile(r"\\begin\{(" + "|".join(DRAWING_ENVS) + r")\}")


def find_engine() -> str | None:
    """First available TeX engine on PATH (xelatex preferred), or None."""
    for engine in _ENGINES:
        if shutil.which(engine):
            return engine
    return None


def extract_picture(source: str) -> str | None:
    """The first ``tikzpicture`` (etc.) of a figure's LaTeX source."""
    pictures = extract_pictures(source)
    return pictures[0] if pictures else None


def extract_pictures(source: str) -> list[str]:
    """Every top-level drawing environment in a figure's source, in order.

    A figure may stack several pictures (two ``\\input`` TikZ files in one
    ``figure*``); each is compiled on its own. Nesting of the same environment
    (a ``tikzpicture`` inside a node) is balanced, so the outer picture stays
    whole.
    """
    out: list[str] = []
    pos = 0
    while True:
        m = _PICTURE_BEGIN_RE.search(source, pos)
        if m is None:
            break
        env = m.group(1)
        token = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
        depth = 0
        stop = None
        for t in token.finditer(source, m.start()):
            depth += 1 if t.group(1) == "begin" else -1
            if depth == 0:
                stop = t.end()
                break
        if stop is None:
            break  # unbalanced: nothing compilable from here on
        out.append(source[m.start() : stop])
        pos = stop
    return out


def _figure_definitions(source: str) -> str:
    """Figure-local style/colour definitions outside the pictures (e.g. a
    ``\\definecolor`` just before an ``\\input`` TikZ file) that they need."""
    rest = source
    for pic in extract_pictures(source):
        rest = rest.replace(pic, "\n", 1)
    lines = rest.splitlines()
    keep: list[str] = []
    i = 0
    while i < len(lines):
        if not _LOCAL_DEF.search(lines[i]):
            i += 1
            continue
        block = [lines[i]]
        depth = _brace_delta(lines[i])
        i += 1
        while depth > 0 and i < len(lines):
            block.append(lines[i])
            depth += _brace_delta(lines[i])
            i += 1
        keep.extend(block)
    return "\n".join(keep)


def engine_order(picture: str, preamble: str) -> list[str]:
    """Engines to try, best first.

    A document written for pdflatex (no fontspec/unicode-math/polyglossia/xeCJK
    and an ASCII picture) compiles with pdflatex, so its text fonts and metrics
    match the paper; Unicode documents prefer xelatex/lualatex. The later
    engines are fallbacks when a compile fails.
    """
    engines = available_engines()
    unicode = bool(_UNICODE_PREAMBLE.search(preamble)) or not picture.isascii()
    if not unicode and "pdflatex" in engines:
        engines.remove("pdflatex")
        engines.insert(0, "pdflatex")
    return engines


def _brace_delta(line: str) -> int:
    """Net ``{`` minus ``}`` on a line, ignoring escaped ``\\{``/``\\}``."""
    depth = 0
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            i += 2  # skip the escaped char (\{ \} \% …)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return depth


def _filtered_preamble(preamble: str, *, unicode_engine: bool) -> str:
    lines = preamble.splitlines()
    keep: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        # header/footer/layout redefinitions reference dropped packages -> skip
        # (they'd otherwise break the standalone build, e.g. \headrulewidth).
        if _DROP_LAYOUT.search(line):
            i += 1
            continue
        matched = _KEEP_USEPACKAGE.search(line) or _KEEP_MACRO.search(line) or (
            _KEEP_FONT.search(line) if unicode_engine else _KEEP_PDF_FONT.search(line)
        )
        if not matched:
            i += 1
            continue
        # Capture the whole (possibly multi-line) definition: a macro body like a
        # multi-line \newcommand{\box}[3]{ … } would otherwise be truncated to its
        # opening line, leaving an unbalanced "{" that breaks the standalone build.
        block = [line]
        depth = _brace_delta(line)
        i += 1
        while depth > 0 and i < n:
            block.append(lines[i])
            depth += _brace_delta(lines[i])
            i += 1
        keep.extend(block)
    return "\n".join(keep)


def build_standalone(picture: str, preamble: str = "", *, unicode_engine: bool = True) -> str:
    """Wrap a picture in a minimal ``standalone`` document for compilation."""
    return "\n".join(
        [
            r"\documentclass[border=2pt]{standalone}",
            r"\usepackage{tikz}",
            r"\usetikzlibrary{calc,positioning,arrows,arrows.meta,shapes,"
            r"shapes.geometric,decorations.pathmorphing,patterns,shadows,fit,backgrounds}",
            _filtered_preamble(preamble, unicode_engine=unicode_engine),
            r"\begin{document}",
            picture,
            r"\end{document}",
            "",
        ]
    )


def available_engines() -> list[str]:
    """TeX engines on PATH, in preference order (Unicode engines first)."""
    return [e for e in _ENGINES if shutil.which(e)]


def render(
    source: str, preamble: str = "", *, dpi: int = 220, timeout: int = 60
) -> tuple[bytes, int, int] | None:
    """Compile the first picture in ``source`` to a cropped PNG (or ``None``)."""
    picture = extract_picture(source)
    if picture is None:
        return None
    return render_picture(picture, source, preamble, dpi=dpi, timeout=timeout)


def render_picture(
    picture: str, source: str = "", preamble: str = "", *, dpi: int = 220,
    timeout: int = 60,
) -> tuple[bytes, int, int] | None:
    """Compile one ``picture`` (taken from the figure ``source``) to a cropped
    PNG; ``None`` on any failure.

    Tries the engines of ``engine_order`` in turn (a partial TeX install may
    have, say, a ``lualatex`` binary without its support files) until one
    produces a PDF that rasterises. Returns ``(png_bytes, width_px, height_px)``.
    """
    engines = engine_order(picture, preamble)
    if not engines:
        return None
    from .raster import has_pdf_support, rasterize_pdf

    if not has_pdf_support():
        return None
    local = _figure_definitions(source) if source else ""
    if local:
        preamble = f"{preamble}\n{local}"
    with tempfile.TemporaryDirectory() as tmp:
        pdf = os.path.join(tmp, "pic.pdf")
        for engine in engines:
            tex = build_standalone(picture, preamble, unicode_engine=engine in _UNICODE_ENGINES)
            with open(os.path.join(tmp, "pic.tex"), "w", encoding="utf-8") as fh:
                fh.write(tex)
            if os.path.exists(pdf):
                os.remove(pdf)
            try:
                proc = subprocess.run(
                    [engine, "-no-shell-escape", "-interaction=nonstopmode",
                     "-halt-on-error", "pic.tex"],
                    cwd=tmp,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                    env={**os.environ, "openout_any": "p", "shell_escape": "f"},
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                _debug(f"{engine} invocation failed: {exc}")
                continue
            if os.path.exists(pdf):
                result = rasterize_pdf(pdf, dpi=dpi)
                if result is not None:
                    return result
                _debug(f"{engine}: produced a PDF but rasterisation failed")
            else:
                _debug_compile_failure(tmp, proc, engine)
        return None


def _debug(msg: str) -> None:
    if os.environ.get("TEX2WORD_TIKZ_DEBUG"):
        import sys

        print(f"[tikz] {msg}", file=sys.stderr)


def _debug_compile_failure(tmp: str, proc: subprocess.CompletedProcess, engine: str) -> None:
    if not os.environ.get("TEX2WORD_TIKZ_DEBUG"):
        return
    import sys

    out = (proc.stdout or b"").decode("utf-8", "replace")
    log_path = os.path.join(tmp, "pic.log")
    log = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            log = fh.read()
    tail = (log or out)[-3000:]
    print(f"[tikz] {engine}: compile produced no PDF; log tail:\n{tail}", file=sys.stderr)
