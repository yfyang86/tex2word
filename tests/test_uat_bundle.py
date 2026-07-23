"""UAT bundle harness — the ProblemSet / bundle / oxmathproblems / resume UATs.

Each is a real-world document with a custom document class (and, for
ProblemSet, `\\input`ed fragments + an image). The bar (per the PRD) is: no hard
abort, no *errors* logged (warnings are acceptable graceful degradation, e.g.
`tikzpicture kept as a graphics placeholder` when no TeX engine is present), and
structurally valid OOXML. Content quality beyond that is not asserted here.
"""

from __future__ import annotations

import os

import pytest

from tex2word import convert_source
from tex2word.validate import validate_docx

UAT = os.path.join(os.path.dirname(__file__), "uat")

# Entry-point documents (not the `\input`ed fragments or the .cls files).
ENTRIES = [
    "ProblemSet/main.tex",
    "bundle/ams-article.tex",
    "bundle/cheetsheet.tex",
    "bundle/cheetsheet-colored.tex",
    "bundle/exam.tex",
    "bundle/homework.tex",
    "bundle/scribe1.tex",
    "bundle/sribe2.tex",
    "oxmathproblems/oxmathproblems.tex",
    "resume/resume.tex",
]


def _convert(rel):
    path = os.path.join(UAT, rel)
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    return convert_source(src, base_dir=os.path.dirname(path))


@pytest.mark.parametrize("rel", ENTRIES, ids=[r.replace("/", ":") for r in ENTRIES])
def test_uat_bundle_converts_cleanly(rel):
    result = _convert(rel)
    # 1. no hard errors (warnings — unknown envs, un-compilable TikZ — are OK)
    assert result.report.errors == [], result.report.errors
    # 2. structurally valid OOXML/OPC
    problems = validate_docx(result.docx)
    assert problems == [], problems


def test_uat_bundle_present():
    missing = [e for e in ENTRIES if not os.path.exists(os.path.join(UAT, e))]
    assert not missing, f"missing UAT entry files: {missing}"


def test_cheatsheet_tikz_boxes_recover_content():
    """The TikZ "cheatsheet" idiom (\\node{minipage …} content boxes + a
    \\node[fancytitle]{Title}) must have its content recovered, not dropped as
    an empty graphics placeholder — even without a TeX engine to compile TikZ."""
    result = _convert("bundle/cheetsheet.tex")
    d = _document_xml(result)
    # math formulas from inside the boxes are now native OMML (was 0)
    assert d.count("<m:oMath>") > 50
    # the picture titles became headings, not lost
    assert "Heating Problem" in d and "Mixing Problem" in d
    # no tikzpicture placeholders left
    assert not any(m.construct == "tikzpicture" for m in result.report.warnings)


def _document_xml(result):
    import zipfile
    from io import BytesIO

    return zipfile.ZipFile(BytesIO(result.docx)).read("word/document.xml").decode()


def test_oxmathproblems_exam_class_renders_as_lists():
    """The exam-class problem sheet renders as nested numbered lists — not the
    old garbage where exam's \\part collided with \\part sectioning ("Part I D")
    and \\subpart/\\begin leaked as literal text."""
    import re
    import zipfile
    from io import BytesIO

    result = _convert("oxmathproblems/oxmathproblems.tex")
    d = zipfile.ZipFile(BytesIO(result.docx)).read("word/document.xml").decode()
    # no "Part N" sectioning garbage, no leaked exam markers
    assert ">Part " not in d
    assert "subpart" not in d and ">\\begin" not in d
    # questions/parts/subparts became real list items
    assert d.count("<w:numPr>") >= 15
    # actual question content survived
    text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", d))
    assert "linearly independent" in text
    # the pmatrix (\cr rows) has its cells
    assert re.search(r"<m:t[^>]*>a</m:t>", d) and re.search(r"<m:t[^>]*>b</m:t>", d)
    # a question that leads straight into \parts still gets its own number (an
    # ilvl-0 numbered paragraph) BEFORE the (a)/(b)/(c) sub-items -- regression
    # for "(a) misses 1".
    ilvls = re.findall(r'<w:ilvl w:val="(\d+)"', d)
    assert ilvls[:2] == ["0", "1"], ilvls[:6]
    # solutions are hidden without \printanswers (matches the compiled sheet)
    assert "solution would go here" not in text
    # the Oxford sheet title (from \course/\sheettitle) is recovered
    assert "Impossible Maths" in text
    # \halign system of equations became an array (its variables survive as math)
    assert re.search(r"<m:t[^>]*>x</m:t>", d)
