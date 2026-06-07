"""The math decision-cascade (PRD §C).

Per math node, try in order:
  1. direct LaTeX -> OMML  (texmath-style, the primary path)
  2. LaTeX -> presentation-MathML -> OMML  (secondary; post-V1 -- stub here)
  3. image fallback (dvisvgm -> EMF/PNG)   (pluggable hook; default off)
  4. raw LaTeX text                         (last resort, like texmath)

Every node records which path it took on the :class:`ConversionReport`, giving
the per-construct coverage telemetry the PRD asks for. The cascade lives in one
place so new paths slot in without touching the document writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from lxml import etree

from ..report import ConversionReport
from . import omml
from .latex_math import MathUnsupported

_Element = etree._Element

Path = Literal["omml", "pmml", "image", "raw"]


@runtime_checkable
class ImageMathRenderer(Protocol):
    """Pluggable renderer that rasterises/vectorises a math snippet.

    Implementations (e.g. a dvisvgm+Inkscape pipeline) return image bytes and
    a format, or ``None`` if they cannot render. None ship in V1 -- the hook
    exists so the image path can be enabled without changing the cascade.
    """

    def render(self, latex: str, display: bool) -> tuple[bytes, str] | None: ...


@dataclass
class MathResult:
    path: Path
    #: for "omml": one or more m:oMath elements (block) or one (inline)
    omath: list[_Element] | None = None
    #: for "image": (bytes, format) to embed
    image: tuple[bytes, str] | None = None
    #: for "raw": the source LaTeX to render as text
    raw: str | None = None


class MathCascade:
    """Drives the per-node math decision-cascade and updates the report."""

    def __init__(
        self,
        report: ConversionReport,
        image_renderer: ImageMathRenderer | None = None,
        enable_pmml: bool | None = None,
    ) -> None:
        self.report = report
        self.image_renderer = image_renderer
        # auto-enable the LaTeX->MathML->OMML stage when latex2mathml is present
        self.enable_pmml = _pmml_available() if enable_pmml is None else enable_pmml
        #: (latex, display) -> rendered image, memoising repeated equations
        self._image_cache: dict[tuple[str, bool], tuple[bytes, str] | None] = {}
        #: East-Asian font for CJK glyphs inside math (set per-document by the
        #: writer from the xeCJK preamble); None leaves math runs untagged.
        self.cjk_font: str | None = None

    def inline(self, latex: str) -> MathResult:
        return self._run(latex, display=False)

    def block(self, latex: str, collapse_align: bool = True) -> MathResult:
        return self._run(latex, display=True, collapse_align=collapse_align)

    # ------------------------------------------------------------------ #

    def _omml_result(self, omath: list[_Element]) -> MathResult:
        """Tag CJK math runs with the document font, count, and wrap as a result."""
        if self.cjk_font:
            for element in omath:
                omml.tag_cjk_runs(element, self.cjk_font)
        self.report.math_omml += len(omath)
        return MathResult("omml", omath=omath)

    def _run(self, latex: str, display: bool, collapse_align: bool = True) -> MathResult:
        # 1. direct OMML
        try:
            omath = (
                omml.render_block_lines(latex, collapse_align) if display
                else [omml.render_inline(latex)]
            )
            return self._omml_result(omath)
        except MathUnsupported as exc:
            construct = exc.construct
        except Exception as exc:  # never let a parser bug abort the conversion
            construct = f"{type(exc).__name__}"
            self.report.warn("math", f"direct math parse failed ({exc}); falling back")

        # 2. presentation-MathML -> OMML (secondary path; needs latex2mathml)
        if self.enable_pmml:
            pmml = self._try_pmml(latex, display)
            if pmml is not None:
                self.report.info("math", f"converted '{construct}' via LaTeX->MathML->OMML")
                return self._omml_result(pmml)

        # 3. image fallback (pluggable). Memoise by (latex, display): the same
        # equation often recurs, and image rendering is the slowest path.
        if self.image_renderer is not None:
            cache_key = (latex, display)
            if cache_key in self._image_cache:
                rendered = self._image_cache[cache_key]
            else:
                rendered = self.image_renderer.render(latex, display)
                self._image_cache[cache_key] = rendered
            if rendered is not None:
                self.report.math_image += 1
                self.report.info("math", f"rendered '{construct}' via image fallback")
                return MathResult("image", image=rendered)

        # 4. raw
        self.report.math_raw += 1
        self.report.warn("math", f"fell back to raw LaTeX for construct {construct}")
        return MathResult("raw", raw=latex)

    def _try_pmml(self, latex: str, display: bool) -> list[_Element] | None:
        from .mathml_to_omml import latex_via_mathml

        omath = latex_via_mathml(latex)
        return [omath] if omath is not None else None


def _pmml_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("latex2mathml") is not None
