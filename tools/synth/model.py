"""Probe, expectation and result records."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Expect:
    """What a probe's conversion must (not) produce, beyond the generic oracles.

    Text checks run on the visible text (body, footnotes, endnotes, comments,
    math text); ``xml``/``no_xml`` are regular expressions on ``document.xml``.
    """

    #: strings that must appear in the visible text
    texts: list[str] = field(default_factory=list)
    #: exact occurrence counts (the sentinel defaults to 1: dropped/duplicated)
    counts: dict[str, int] = field(default_factory=dict)
    #: strings that must not appear in the visible text
    absent: list[str] = field(default_factory=list)
    #: regexes that must / must not match document.xml
    xml: list[str] = field(default_factory=list)
    no_xml: list[str] = field(default_factory=list)
    #: label keys that must resolve (present in ``doc.labels``)
    labels: list[str] = field(default_factory=list)
    #: substrings that must / must not appear in the IR JSON
    ir: list[str] = field(default_factory=list)
    no_ir: list[str] = field(default_factory=list)
    #: sentinel -> run property tag its run must carry (e.g. "w:b", "w:i")
    styles: dict[str, str] = field(default_factory=dict)
    #: minimum number of OMML equations
    min_math: int = 0
    #: regexes over "construct: message" of warnings that are acceptable
    allow_warnings: list[str] = field(default_factory=list)
    #: generic-oracle opt-outs
    allow_raw: bool = False  # RawInline/RawPassthrough in the IR is fine
    allow_braces: bool = False  # literal { } in the text is expected
    allow_backslash: bool = False  # a literal \word in the text is expected
    allow_dims: bool = False  # a "2pt"/"3 mm" in the text is expected
    #: run the math round-trip oracle (OMML -> LaTeX -> OMML is stable)
    roundtrip: bool = False


@dataclass
class Probe:
    """One synthetic document and what its conversion must satisfy."""

    id: str  # "<area>/<name>", stable: the baseline is keyed on it
    source: str  # the complete LaTeX document (main.tex)
    expect: Expect = field(default_factory=Expect)
    #: extra files next to main.tex: relative path -> text or bytes
    files: dict[str, str | bytes] = field(default_factory=dict)
    note: str = ""  # what the probe exercises (shown in reports)
    #: "smoke" probes run in the pytest gate; "full" ones only from the CLI
    tier: str = "full"
    #: free-form facets for triage, e.g. {"construct": "cite", "context": "caption"}
    tags: dict[str, str] = field(default_factory=dict)
    #: the LaTeX fragment under test, for reports and repro stubs
    fragment: str = ""

    @property
    def area(self) -> str:
        return self.id.split("/", 1)[0]


@dataclass
class Finding:
    """One oracle failure. ``signature`` is stable (baseline key); ``detail``
    is for humans."""

    signature: str
    detail: str = ""


@dataclass
class Result:
    probe_id: str
    findings: list[Finding] = field(default_factory=list)
    seconds: float = 0.0
    text: str = ""  # visible text (for reports and repro)
    warnings: list[str] = field(default_factory=list)

    @property
    def signatures(self) -> list[str]:
        return sorted({f.signature for f in self.findings})

    @property
    def ok(self) -> bool:
        return not self.findings
