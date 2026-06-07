"""V4-4: a quantitative conversion-fidelity baseline.

Runs every ``.tex`` under a directory through the converter and records the
metrics the PRD asks us to "establish a baseline" for: native-OMML math share,
schema validity, warning/error counts, block count, and hard aborts. The result
is a machine-readable summary so regressions are measurable (not just "looks
fine"). Wired into the CLI as ``tex2word benchmark <dir>``.
"""

from __future__ import annotations

import glob
import os
import time
from dataclasses import asdict, dataclass

from .pipeline import convert_file
from .validate import validate_docx


@dataclass
class DocMetrics:
    name: str
    math_total: int = 0
    math_omml: int = 0
    math_image: int = 0
    math_raw: int = 0
    blocks: int = 0
    warnings: int = 0
    errors: int = 0
    valid: bool = False
    aborted: bool = False
    seconds: float = 0.0

    @property
    def math_omml_pct(self) -> float:
        return 100.0 * self.math_omml / self.math_total if self.math_total else 100.0


def benchmark_dir(directory: str) -> dict:
    """Convert every ``.tex`` under ``directory``; return per-doc + aggregate metrics."""
    paths = sorted(glob.glob(os.path.join(directory, "**", "*.tex"), recursive=True))
    docs: list[DocMetrics] = [_one(p, directory) for p in paths]
    return {"documents": [asdict(d) for d in docs], "aggregate": _aggregate(docs)}


def _one(path: str, base: str) -> DocMetrics:
    name = os.path.relpath(path, base)
    t0 = time.perf_counter()
    try:
        _, result = convert_file(path, os.devnull, embed_manifest=False)
    except Exception:
        return DocMetrics(name=name, aborted=True, seconds=round(time.perf_counter() - t0, 3))
    elapsed = round(time.perf_counter() - t0, 3)
    cov = result.report.coverage()
    return DocMetrics(
        name=name,
        math_total=cov["math_total"],
        math_omml=cov["math_omml"],
        math_image=cov["math_image"],
        math_raw=cov["math_raw"],
        blocks=len(result.document.blocks),
        warnings=len(result.report.warnings),
        errors=len(result.report.errors),
        valid=validate_docx(result.docx) == [],
        seconds=elapsed,
    )


def _aggregate(docs: list[DocMetrics]) -> dict:
    n = len(docs)
    math_total = sum(d.math_total for d in docs)
    math_omml = sum(d.math_omml for d in docs)
    return {
        "documents": n,
        "aborted": sum(d.aborted for d in docs),
        "valid": sum(d.valid for d in docs),
        "math_total": math_total,
        "math_omml": math_omml,
        "math_raw": sum(d.math_raw for d in docs),
        "math_image": sum(d.math_image for d in docs),
        "math_omml_pct": round(100.0 * math_omml / math_total, 1) if math_total else 100.0,
        "warnings": sum(d.warnings for d in docs),
        "errors": sum(d.errors for d in docs),
        "seconds": round(sum(d.seconds for d in docs), 3),
    }


def format_report(result: dict) -> str:
    """A compact text table of the benchmark result."""
    lines = [f"{'document':<34} {'math%':>6} {'omml':>5} {'raw':>4} {'warn':>5} {'sec':>6} valid"]
    lines.append("-" * 72)
    for d in result["documents"]:
        pct = 100.0 * d["math_omml"] / d["math_total"] if d["math_total"] else 100.0
        flag = "ABORT" if d["aborted"] else ("ok" if d["valid"] else "INVALID")
        lines.append(
            f"{d['name']:<34} {pct:6.1f} {d['math_omml']:5} {d['math_raw']:4} "
            f"{d['warnings']:5} {d.get('seconds', 0.0):6.2f} {flag}"
        )
    a = result["aggregate"]
    lines.append("-" * 72)
    lines.append(
        f"{'TOTAL (' + str(a['documents']) + ' docs)':<34} {a['math_omml_pct']:6.1f} "
        f"{a['math_omml']:5} {a['math_raw']:4} {a['warnings']:5} {a.get('seconds', 0.0):6.2f} "
        f"{a['valid']}/{a['documents']} valid, {a['aborted']} aborted"
    )
    return "\n".join(lines)
