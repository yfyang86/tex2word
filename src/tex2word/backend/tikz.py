"""Render a standalone TikZ/PGF picture to PNG by compiling it with a TeX engine.

tex2word cannot reproduce arbitrary TikZ as OOXML, so when a figure's only
content is a ``tikzpicture`` (or ``pgfpicture``/``circuitikz``/…) we compile it
with whatever TeX engine is on PATH -- ``xelatex`` preferred so CJK node labels
work -- into a cropped ``standalone`` PDF, then rasterise to PNG via the ``pdf``
extra (PDFium). Everything is best-effort: any missing tool, package, or
compile error returns ``None`` and the caller falls back to a caption-only
figure. The document preamble is filtered down to the parts a picture needs
(TikZ libraries, colours, styles, user macros) so journal-class preambles with
``hyperref``/``geometry``/… don't break the standalone build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

# xelatex/lualatex first: they honour fontspec/xeCJK for CJK text in nodes.
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
_KEEP_USEPACKAGE = re.compile(
    r"^\s*\\usepackage\b[^\n]*\{[^}]*\b"
    r"(tikz|pgfplots|pgf|pgfgantt|circuitikz|amsmath|amssymb|amsfonts|mathtools|"
    r"xcolor|color|bm|siunitx)\b"
)
# fontspec/xeCJK lines only make sense under a Unicode engine.
_KEEP_FONT = re.compile(r"^\s*\\(usepackage\b[^\n]*\{(fontspec|xeCJK)\}|set(main|CJK\w*)font)\b")

_PICTURE_RE = re.compile(
    r"\\begin\{(" + "|".join(DRAWING_ENVS) + r")\}.*?\\end\{\1\}", re.DOTALL
)


def find_engine() -> str | None:
    """First available TeX engine on PATH (xelatex preferred), or None."""
    for engine in _ENGINES:
        if shutil.which(engine):
            return engine
    return None


def extract_picture(source: str) -> str | None:
    """Pull the ``tikzpicture`` (etc.) out of a figure's LaTeX source."""
    m = _PICTURE_RE.search(source)
    return m.group(0) if m else None


def _filtered_preamble(preamble: str, *, unicode_engine: bool) -> str:
    keep: list[str] = []
    for line in preamble.splitlines():
        if _KEEP_USEPACKAGE.search(line) or _KEEP_MACRO.search(line):
            keep.append(line)
        elif unicode_engine and _KEEP_FONT.search(line):
            keep.append(line)
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
    """Compile the picture in ``source`` to a cropped PNG; ``None`` on any failure.

    Tries each available engine in turn (a partial TeX install may have, say, a
    ``lualatex`` binary without its support files) until one produces a PDF that
    rasterises. Returns ``(png_bytes, width_px, height_px)``.
    """
    picture = extract_picture(source)
    if picture is None:
        return None
    engines = available_engines()
    if not engines:
        return None
    from .raster import has_pdf_support, rasterize_pdf

    if not has_pdf_support():
        return None
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
                    [engine, "-interaction=nonstopmode", "-halt-on-error", "pic.tex"],
                    cwd=tmp,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
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
