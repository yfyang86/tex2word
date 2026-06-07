"""OPC (Open Packaging Conventions) package assembly.

A ``.docx`` is a ZIP of XML parts joined by relationship files. This module
builds that ZIP deterministically (fixed timestamps + sorted members) so output
is reproducible -- a PRD non-functional requirement.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

# Fixed timestamp for deterministic archives (1980-01-01, the zip epoch).
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

#: archive path of the embedded round-trip IR manifest.
MANIFEST_PART = "word/tex2word/manifest.json"
MANIFEST_REL_TYPE = "http://tex2word.org/2026/relationships/manifest"

_CONTENT_TYPES_HEAD = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="emf" ContentType="image/x-emf"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
"""
_MANIFEST_OVERRIDE = (
    f'  <Override PartName="/{MANIFEST_PART}" ContentType="application/json"/>\n'
)
_FOOTNOTES_OVERRIDE = (
    '  <Override PartName="/word/footnotes.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>\n'
)
_ENDNOTES_OVERRIDE = (
    '  <Override PartName="/word/endnotes.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/>\n'
)
_THEME_OVERRIDE = (
    '  <Override PartName="/word/theme/theme1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>\n'
)
_COMMENTS_OVERRIDE = (
    '  <Override PartName="/word/comments.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>\n'
)
_CONTENT_TYPES_TAIL = "</Types>\n"

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>
"""

_SETTINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:updateFields w:val="true"/>
</w:settings>
"""

_CORE_PROPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>tex2word</dc:creator>
</cp:coreProperties>
"""


@dataclass
class DocxPackage:
    """Accumulates parts and writes a deterministic OPC zip.

    ``settings.xml`` enables ``w:updateFields`` so Word recalculates ``SEQ``/
    ``REF`` fields on first open -- essential for the live-numbering feature.
    """

    document_xml: bytes
    styles_xml: bytes
    numbering_xml: bytes
    #: extra word/_rels/document.xml.rels relationship lines (raw XML strings).
    document_rels: list[str] = field(default_factory=list)
    #: media parts: archive path -> bytes (e.g. "word/media/image1.png").
    media: dict[str, bytes] = field(default_factory=dict)
    #: round-trip IR manifest (JSON bytes) embedded as a custom part, or None.
    manifest: bytes | None = None
    #: word/footnotes.xml part (bytes), or None when the document has no notes.
    footnotes: bytes | None = None
    #: word/endnotes.xml part (bytes), or None when the document has no endnotes.
    endnotes: bytes | None = None
    #: word/comments.xml part (bytes), or None when there are no review comments.
    comments: bytes | None = None
    #: word/theme/theme1.xml (bytes) from a --reference-doc, or None.
    theme: bytes | None = None
    #: carried header/footer parts (archive path -> bytes) from a --reference-doc.
    header_footer_parts: dict[str, bytes] = field(default_factory=dict)
    #: carried header/footer sub-resources (their _rels + media), archive path ->
    #: bytes; these need no content-type Override (rels/png/jpeg/emf are Defaults).
    extra_parts: dict[str, bytes] = field(default_factory=dict)

    def _content_types(self) -> str:
        body = _CONTENT_TYPES_HEAD
        if self.theme is not None:
            body += _THEME_OVERRIDE
        for arc in sorted(self.header_footer_parts):
            base = arc.rsplit("/", 1)[-1]
            kind = "header" if base.startswith("header") else "footer"
            body += (
                f'  <Override PartName="/{arc}" ContentType="application/'
                f'vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>\n'
            )
        if self.footnotes is not None:
            body += _FOOTNOTES_OVERRIDE
        if self.endnotes is not None:
            body += _ENDNOTES_OVERRIDE
        if self.comments is not None:
            body += _COMMENTS_OVERRIDE
        if self.manifest is not None:
            body += _MANIFEST_OVERRIDE
        return body + _CONTENT_TYPES_TAIL

    def _document_rels_xml(self) -> str:
        rels = list(self.document_rels)
        if self.theme is not None:
            rels.append(
                '<Relationship Id="rIdTheme" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
                'Target="theme/theme1.xml"/>'
            )
        if self.footnotes is not None:
            rels.append(
                '<Relationship Id="rIdFootnotes" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
                'Target="footnotes.xml"/>'
            )
        if self.endnotes is not None:
            rels.append(
                '<Relationship Id="rIdEndnotes" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" '
                'Target="endnotes.xml"/>'
            )
        if self.comments is not None:
            rels.append(
                '<Relationship Id="rIdComments" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
                'Target="comments.xml"/>'
            )
        if self.manifest is not None:
            rels.append(
                f'<Relationship Id="rIdManifest" Type="{MANIFEST_REL_TYPE}" '
                f'Target="tex2word/manifest.json"/>'
            )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
            '<Relationship Id="rIdNumbering" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
            'Target="numbering.xml"/>'
            '<Relationship Id="rIdSettings" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" '
            'Target="settings.xml"/>'
            f"{''.join(rels)}</Relationships>"
        )

    def parts(self) -> dict[str, bytes]:
        parts: dict[str, bytes] = {
            "[Content_Types].xml": self._content_types().encode("utf-8"),
            "_rels/.rels": _ROOT_RELS.encode("utf-8"),
            "docProps/core.xml": _CORE_PROPS.encode("utf-8"),
            "word/document.xml": self.document_xml,
            "word/styles.xml": self.styles_xml,
            "word/numbering.xml": self.numbering_xml,
            "word/settings.xml": _SETTINGS.encode("utf-8"),
            "word/_rels/document.xml.rels": self._document_rels_xml().encode("utf-8"),
        }
        parts.update(self.media)
        parts.update(self.header_footer_parts)
        parts.update(self.extra_parts)
        if self.theme is not None:
            parts["word/theme/theme1.xml"] = self.theme
        if self.footnotes is not None:
            parts["word/footnotes.xml"] = self.footnotes
        if self.endnotes is not None:
            parts["word/endnotes.xml"] = self.endnotes
        if self.comments is not None:
            parts["word/comments.xml"] = self.comments
        if self.manifest is not None:
            parts[MANIFEST_PART] = self.manifest
        return parts

    def _zip_into(self, target) -> None:
        parts = self.parts()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(parts):
                info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, parts[name])

    def write(self, path: str) -> None:
        self._zip_into(path)

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        self._zip_into(buf)
        return buf.getvalue()
