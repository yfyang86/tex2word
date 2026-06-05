"""Conversion report: warnings, coverage telemetry, and fallback accounting.

The PRD makes graceful degradation a hard non-functional requirement: the tool
must *never* abort on an unknown construct, and every fallback must be logged so
we can produce per-construct coverage telemetry. This module is the single sink
for that information.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["info", "warning", "error"]


@dataclass
class ReportEntry:
    severity: Severity
    construct: str
    message: str


@dataclass
class ConversionReport:
    entries: list[ReportEntry] = field(default_factory=list)
    #: math nodes routed to each path of the decision cascade.
    math_omml: int = 0
    math_image: int = 0
    math_raw: int = 0

    def warn(self, construct: str, message: str) -> None:
        self.entries.append(ReportEntry("warning", construct, message))

    def error(self, construct: str, message: str) -> None:
        self.entries.append(ReportEntry("error", construct, message))

    def info(self, construct: str, message: str) -> None:
        self.entries.append(ReportEntry("info", construct, message))

    @property
    def warnings(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.severity == "warning"]

    @property
    def errors(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.severity == "error"]

    def coverage(self) -> dict[str, int]:
        total = self.math_omml + self.math_image + self.math_raw
        return {
            "math_total": total,
            "math_omml": self.math_omml,
            "math_image": self.math_image,
            "math_raw": self.math_raw,
        }

    def construct_counts(self) -> dict[str, int]:
        counter: Counter[str] = Counter(e.construct for e in self.entries)
        return dict(counter)

    def to_json(self) -> str:
        return json.dumps(
            {
                "coverage": self.coverage(),
                "constructs": self.construct_counts(),
                "entries": [
                    {"severity": e.severity, "construct": e.construct, "message": e.message}
                    for e in self.entries
                ],
            },
            indent=2,
        )

    def summary(self) -> str:
        cov = self.coverage()
        return (
            f"math: {cov['math_omml']} OMML / {cov['math_image']} image / "
            f"{cov['math_raw']} raw; "
            f"{len(self.warnings)} warning(s), {len(self.errors)} error(s)"
        )

    def to_html(self) -> str:
        cov = self.coverage()
        total = cov["math_total"] or 1
        pct = 100.0 * cov["math_omml"] / total
        rows = "".join(
            f"<tr class='{e.severity}'><td>{e.severity}</td>"
            f"<td><code>{_esc(e.construct)}</code></td><td>{_esc(e.message)}</td></tr>"
            for e in self.entries
        )
        constructs = "".join(
            f"<tr><td><code>{_esc(k)}</code></td><td>{v}</td></tr>"
            for k, v in sorted(self.construct_counts().items())
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>latex2word conversion report</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left;font-size:.9rem}}
 .warning{{background:#fff7e6}} .error{{background:#fde8e8}}
 .bar{{height:1.4rem;background:#e6f4ea;border:1px solid #b7d7be}}
 .bar>span{{display:block;height:100%;background:#34a853}}
</style></head><body>
<h1>latex2word conversion report</h1>
<h2>Math coverage</h2>
<div class="bar"><span style="width:{pct:.0f}%"></span></div>
<p>{cov['math_omml']} OMML &middot; {cov['math_image']} image &middot;
   {cov['math_raw']} raw (of {cov['math_total']} equations, {pct:.0f}% editable)</p>
<h2>Constructs</h2>
<table><tr><th>construct</th><th>count</th></tr>{constructs or '<tr><td colspan=2>none</td></tr>'}</table>
<h2>Messages</h2>
<table><tr><th>severity</th><th>construct</th><th>message</th></tr>
{rows or '<tr><td colspan=3>no warnings or errors</td></tr>'}</table>
</body></html>
"""


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def aggregate_html(results: list[tuple[str, ConversionReport]]) -> str:
    """A coverage dashboard across a corpus of (name, report) pairs."""
    from collections import Counter

    tot = Counter()  # type: Counter[str]
    rows = []
    construct_totals: Counter[str] = Counter()
    for name, rep in results:
        cov = rep.coverage()
        for k, v in cov.items():
            tot[k] += v
        construct_totals.update(rep.construct_counts())
        omml = cov["math_omml"]
        total = cov["math_total"] or 1
        pct = 100.0 * omml / total
        rows.append(
            f"<tr><td>{_esc(name)}</td><td>{cov['math_total']}</td>"
            f"<td>{omml}</td><td>{cov['math_raw']}</td>"
            f"<td>{pct:.0f}%</td><td>{len(rep.warnings)}</td>"
            f"<td>{len(rep.errors)}</td></tr>"
        )
    grand = tot["math_total"] or 1
    grand_pct = 100.0 * tot["math_omml"] / grand
    constructs = "".join(
        f"<tr><td><code>{_esc(k)}</code></td><td>{v}</td></tr>"
        for k, v in construct_totals.most_common(40)
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>latex2word corpus coverage</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;max-width:64rem}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left;font-size:.9rem}}
 .bar{{height:1.4rem;background:#e6f4ea;border:1px solid #b7d7be;max-width:40rem}}
 .bar>span{{display:block;height:100%;background:#34a853}}
</style></head><body>
<h1>latex2word corpus coverage</h1>
<p>{len(results)} document(s) &middot; {tot['math_total']} equations &middot;
   {tot['math_omml']} editable OMML &middot; {tot['math_raw']} raw fallback</p>
<div class="bar"><span style="width:{grand_pct:.0f}%"></span></div>
<p>{grand_pct:.0f}% of equations are editable OMML across the corpus.</p>
<h2>Per document</h2>
<table><tr><th>file</th><th>eqns</th><th>OMML</th><th>raw</th><th>OMML%</th>
<th>warnings</th><th>errors</th></tr>{''.join(rows)}</table>
<h2>Constructs (warnings/info, all docs)</h2>
<table><tr><th>construct</th><th>count</th></tr>{constructs or '<tr><td colspan=2>none</td></tr>'}</table>
</body></html>
"""
