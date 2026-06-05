"""End-to-end orchestration: LaTeX source -> IR -> transforms -> .docx."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import ir
from .backend.document import DocumentWriter
from .backend.numbering import numbering_xml
from .backend.package import DocxPackage
from .frontend import parse_document
from .report import ConversionReport
from .roundtrip import build_manifest
from .templates import load_styles_xml
from .transforms import resolve_crossrefs


@dataclass
class ConversionResult:
    document: ir.Document
    report: ConversionReport
    docx: bytes


def convert_source(
    source: str,
    base_dir: str = ".",
    *,
    embed_manifest: bool = True,
    number_by_section: bool = False,
    citation_mode: str = "static",
    columns: int = 1,
    frontend: str = "pure",
    math_image_fallback: bool = False,
    csl: str | None = None,
    reference_doc: str | None = None,
) -> ConversionResult:
    """Convert a LaTeX string to a ``.docx`` (bytes) + IR + report.

    When ``embed_manifest`` is set (default), the IR is persisted as a custom
    part inside the ``.docx`` to support round-tripping. With
    ``number_by_section`` figures/tables/equations are numbered ``N.M`` per
    section instead of with a flat counter. ``citation_mode`` is ``"static"``
    (formatted text) or ``"zotero"`` (live ``CSL_CITATION`` fields). ``columns``
    sets the page column count. ``frontend`` is ``"pure"`` (default, pylatexenc)
    or ``"latexml"`` (genuine TeX expansion; falls back to pure if unavailable).
    ``reference_doc`` is a path to a Word ``.docx`` whose styles, theme and page
    geometry the output adopts (the journal/corporate "template" pattern).
    """
    if frontend == "latexml":
        from .frontend.latexml import parse_document as _parse
        doc, report = _parse(source, base_dir)
    else:
        doc, report = parse_document(source, base_dir, csl_path=csl)
    resolve_crossrefs(doc, report)

    image_renderer = None
    if math_image_fallback:
        from .mathml.imagemath import default_renderer

        image_renderer = default_renderer()
        if image_renderer is None:
            report.warn("math", "no math-image backend (install latex2word[mathimg] or TeX)")

    reference = _load_reference(reference_doc, report)
    hf_refs, hf_parts, hf_rels, hf_extra = _header_footer_wiring(reference, report)

    writer = DocumentWriter(
        report,
        base_dir=base_dir,
        image_math_renderer=image_renderer,
        number_by_section=number_by_section,
        citation_mode=citation_mode,
        columns=columns,
        page_pgsz=reference.page_pgsz if reference else None,
        page_pgmar=reference.page_pgmar if reference else None,
        header_footer_refs=hf_refs,
    )
    document_xml = writer.build(doc)
    package = DocxPackage(
        document_xml=document_xml,
        styles_xml=reference.styles_xml if reference else load_styles_xml(),
        numbering_xml=numbering_xml(),
        document_rels=writer.document_rels + hf_rels,
        media=writer.media,
        footnotes=writer.footnotes_xml(),
        comments=writer.comments_xml(),
        manifest=build_manifest(doc) if embed_manifest else None,
        theme=reference.theme_xml if reference else None,
        header_footer_parts=hf_parts,
        extra_parts=hf_extra,
    )
    return ConversionResult(document=doc, report=report, docx=package.to_bytes())


_HF_REL_TYPE = {
    "header": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
    "footer": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer",
}


def _header_footer_wiring(reference, report: ConversionReport):
    """Turn carried headers/footers into (sectPr refs, .xml parts, doc rels, extra parts)."""
    refs: list[tuple[str, str, str]] = []
    parts: dict[str, bytes] = {}
    rels: list[str] = []
    extra: dict[str, bytes] = {}
    if reference and reference.headers_footers:
        for i, hf in enumerate(reference.headers_footers, 1):
            rid = f"rIdHF{i}"
            parts[f"word/{hf.part_name}"] = hf.content
            refs.append((f"{hf.kind}Reference", hf.w_type, rid))
            rels.append(
                f'<Relationship Id="{rid}" Type="{_HF_REL_TYPE[hf.kind]}" '
                f'Target="{hf.part_name}"/>'
            )
            if hf.rels:
                extra[f"word/_rels/{hf.part_name}.rels"] = hf.rels
            extra.update(hf.media)
    if reference and reference.skipped_header_footers:
        report.info("reference-doc",
                    f"skipped {reference.skipped_header_footers} header/footer(s) "
                    "with unsupported sub-resources")
    return refs, parts, rels, extra


def _load_reference(reference_doc: str | None, report: ConversionReport):
    """Load a ``--reference-doc`` template, or warn + fall back to the bundled styles."""
    if not reference_doc:
        return None
    from .templates.reference import extract_reference

    try:
        with open(reference_doc, "rb") as fh:
            ref = extract_reference(fh.read())
        report.info("reference-doc", f"using template styles from {reference_doc}")
        return ref
    except (OSError, ValueError) as exc:
        report.warn("reference-doc", f"ignored ({exc}); used the built-in styles")
        return None


def convert_file(
    input_path: str,
    output_path: str | None = None,
    *,
    embed_manifest: bool = True,
    number_by_section: bool = False,
    citation_mode: str = "static",
    columns: int = 1,
    frontend: str = "pure",
    math_image_fallback: bool = False,
    csl: str | None = None,
    reference_doc: str | None = None,
) -> tuple[str, ConversionResult]:
    """Convert a ``.tex`` file to ``.docx`` on disk. Returns the output path."""
    with open(input_path, encoding="utf-8") as fh:
        source = fh.read()
    base_dir = os.path.dirname(os.path.abspath(input_path))
    result = convert_source(
        source, base_dir, embed_manifest=embed_manifest,
        number_by_section=number_by_section, citation_mode=citation_mode,
        columns=columns, frontend=frontend, math_image_fallback=math_image_fallback,
        csl=csl, reference_doc=reference_doc,
    )

    if output_path is None:
        output_path = os.path.splitext(input_path)[0] + ".docx"
    with open(output_path, "wb") as fh:
        fh.write(result.docx)
    return output_path, result
