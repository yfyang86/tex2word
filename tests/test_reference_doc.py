"""V5-1: --reference-doc (journal/corporate Word template) support."""

from __future__ import annotations

import io
import zipfile

from latex2word import convert_source
from latex2word.templates.reference import extract_reference, merge_styles

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# A reference template: Heading1 in red 24pt, A4 page, plus a (tiny) theme part.
_REF_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:rPr><w:color w:val="FF0000"/><w:sz w:val="48"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>
</w:styles>""".encode()

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PR = "http://schemas.openxmlformats.org/package/2006/relationships"

_REF_DOC = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W}" xmlns:r="{_R}"><w:body><w:p/>
  <w:sectPr>
    <w:headerReference w:type="default" r:id="rId10"/>
    <w:footerReference w:type="default" r:id="rId11"/>
    <w:headerReference w:type="first" r:id="rId12"/>
    <w:headerReference w:type="even" r:id="rId13"/>
    <w:pgSz w:w="11906" w:h="16838"/>
    <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"
             w:header="360" w:footer="360"/></w:sectPr>
</w:body></w:document>""".encode()

_REF_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_PR}">
  <Relationship Id="rId10" Type="{_R}/header" Target="header1.xml"/>
  <Relationship Id="rId11" Type="{_R}/footer" Target="footer1.xml"/>
  <Relationship Id="rId12" Type="{_R}/header" Target="header2.xml"/>
  <Relationship Id="rId13" Type="{_R}/header" Target="header3.xml"/>
</Relationships>""".encode()

_HDR = (
    f'<?xml version="1.0"?><w:hdr xmlns:w="{_W}">'
    "<w:p><w:r><w:t>Running Title</w:t></w:r></w:p></w:hdr>"
).encode()
_FTR = (
    f'<?xml version="1.0"?><w:ftr xmlns:w="{_W}">'
    "<w:p><w:r><w:t>x</w:t></w:r></w:p></w:ftr>"
).encode()
# header2 references a logo that IS present -> carried with its media.
_HDR2_RELS = (
    f'<?xml version="1.0"?><Relationships xmlns="{_PR}">'
    f'<Relationship Id="rIdI" Type="{_R}/image" Target="media/logo.png"/></Relationships>'
).encode()
# header3 references a MISSING image -> the whole part is skipped (no dangling rel).
_HDR3_RELS = (
    f'<?xml version="1.0"?><Relationships xmlns="{_PR}">'
    f'<Relationship Id="rIdI" Type="{_R}/image" Target="media/missing.png"/></Relationships>'
).encode()

# a minimal 1x1 PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f0005000100ff5ccae20000000049454e44ae426082"
)

_REF_THEME = (
    b'<?xml version="1.0"?><a:theme '
    b'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="t"/>'
)


def _reference_docx(with_theme: bool = True, with_headers: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/styles.xml", _REF_STYLES)
        z.writestr("word/document.xml", _REF_DOC)
        if with_theme:
            z.writestr("word/theme/theme1.xml", _REF_THEME)
        if with_headers:
            z.writestr("word/_rels/document.xml.rels", _REF_RELS)
            z.writestr("word/header1.xml", _HDR)
            z.writestr("word/footer1.xml", _FTR)
            z.writestr("word/header2.xml", _HDR)  # carries a logo (present)
            z.writestr("word/_rels/header2.xml.rels", _HDR2_RELS)
            z.writestr("word/media/logo.png", _PNG)
            z.writestr("word/header3.xml", _HDR)  # references a missing image
            z.writestr("word/_rels/header3.xml.rels", _HDR3_RELS)
    return buf.getvalue()


def _convert_with_reference(tmp_path, **kw) -> bytes:
    ref = tmp_path / "template.docx"
    ref.write_bytes(_reference_docx(**kw))
    src = r"\begin{document}\section{Intro}Body.\end{document}"
    return convert_source(src, reference_doc=str(ref)).docx


def _part(docx: bytes, name: str) -> bytes:
    return zipfile.ZipFile(io.BytesIO(docx)).read(name)


# -- merge_styles ------------------------------------------------------------ #


def test_merge_keeps_reference_styles_and_adds_ours():
    from latex2word.templates import load_styles_xml

    merged = merge_styles(_REF_STYLES, load_styles_xml()).decode()
    # the reference's Heading1 (red) wins, not our bundled one
    assert 'w:styleId="Heading1"' in merged and 'w:val="FF0000"' in merged
    # our custom styles the template lacks are appended so nothing is unstyled
    assert 'w:styleId="SourceCode"' in merged
    assert 'w:styleId="Caption"' in merged


# -- end-to-end through the pipeline ----------------------------------------- #


def test_reference_styles_are_applied(tmp_path):
    styles = _part(_convert_with_reference(tmp_path), "word/styles.xml").decode()
    assert 'w:val="FF0000"' in styles  # template's red Heading1 carried through
    assert 'w:styleId="SourceCode"' in styles  # merged in from our bundled set


def test_reference_theme_is_carried(tmp_path):
    docx = _convert_with_reference(tmp_path)
    names = zipfile.ZipFile(io.BytesIO(docx)).namelist()
    assert "word/theme/theme1.xml" in names
    ctypes = _part(docx, "[Content_Types].xml").decode()
    assert "theme+xml" in ctypes
    rels = _part(docx, "word/_rels/document.xml.rels").decode()
    assert "theme/theme1.xml" in rels


def test_reference_page_geometry_is_applied(tmp_path):
    doc = _part(_convert_with_reference(tmp_path), "word/document.xml").decode()
    assert 'w:w="11906"' in doc and 'w:h="16838"' in doc  # A4 from the template


def test_no_reference_uses_builtin_letter(tmp_path):
    src = r"\begin{document}\section{S}x\end{document}"
    doc = _part(convert_source(src).docx, "word/document.xml").decode()
    assert 'w:w="12240"' in doc  # the built-in Letter default, unchanged


def test_output_with_reference_is_valid(tmp_path):
    from latex2word.validate import validate_docx

    assert validate_docx(_convert_with_reference(tmp_path)) == []


def test_invalid_reference_warns_and_falls_back(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a docx at all")
    src = r"\begin{document}\section{S}x\end{document}"
    result = convert_source(src, reference_doc=str(bad))
    styles = _part(result.docx, "word/styles.xml").decode()
    assert 'w:styleId="Heading1"' in styles  # bundled styles still present
    assert any(w.construct == "reference-doc" for w in result.report.warnings)


def test_extract_reference_reads_parts():
    ref = extract_reference(_reference_docx())
    assert ref.theme_xml is not None
    assert ref.page_pgsz == {"w:w": "11906", "w:h": "16838"}
    assert ref.page_pgmar and ref.page_pgmar["w:top"] == "720"


# -- headers / footers ------------------------------------------------------- #


def test_reference_headers_footers_are_carried(tmp_path):
    docx = _convert_with_reference(tmp_path)
    names = zipfile.ZipFile(io.BytesIO(docx)).namelist()
    assert "word/header1.xml" in names and "word/footer1.xml" in names
    assert "word/header2.xml" in names  # carries its logo
    assert "word/header3.xml" not in names  # missing image -> skipped
    ctypes = _part(docx, "[Content_Types].xml").decode()
    assert "wordprocessingml.header+xml" in ctypes and "wordprocessingml.footer+xml" in ctypes


def test_header_logo_subresource_is_carried_and_namespaced(tmp_path):
    docx = _convert_with_reference(tmp_path)
    names = zipfile.ZipFile(io.BytesIO(docx)).namelist()
    # the logo media is carried under the tmpl/ namespace (no collision with ours)
    assert "word/media/tmpl/header2_logo.png" in names
    # header2's rels were carried and rewritten to point at the namespaced media
    rels = _part(docx, "word/_rels/header2.xml.rels").decode()
    assert "media/tmpl/header2_logo.png" in rels and "media/logo.png" not in rels


def test_sectpr_references_headers_and_footers(tmp_path):
    doc = _part(_convert_with_reference(tmp_path), "word/document.xml").decode()
    assert "headerReference" in doc and "footerReference" in doc
    rels = _part(_convert_with_reference(tmp_path), "word/_rels/document.xml.rels").decode()
    # every header/footer reference in the body must resolve to a relationship
    import re
    rids = set(re.findall(r'r:id="(rIdHF\d+)"', doc))
    assert rids, "no header/footer references emitted"
    for rid in rids:
        assert f'Id="{rid}"' in rels


def test_header_with_unresolvable_subresource_is_skipped(tmp_path):
    ref = extract_reference(_reference_docx())
    carried = {hf.part_name for hf in ref.headers_footers}
    assert {"header1.xml", "footer1.xml", "header2.xml"} <= carried
    # header3 points at a missing image -> skipped, never carried (no dangling rel)
    assert "header3.xml" not in carried
    assert ref.skipped_header_footers == 1
    # header2 carried its media + rewritten rels
    h2 = next(hf for hf in ref.headers_footers if hf.part_name == "header2.xml")
    assert h2.rels is not None and h2.media


def test_output_with_headers_is_valid(tmp_path):
    from latex2word.validate import validate_docx

    assert validate_docx(_convert_with_reference(tmp_path)) == []
