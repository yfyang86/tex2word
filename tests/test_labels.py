"""V5-5 (label tail): restore original label names on read-back."""

from __future__ import annotations

from latex2word import convert_source, ir
from latex2word.frontend.docx_reader import read_docx
from latex2word.roundtrip import recover_ir


def _label_map(docx: bytes) -> dict[str, str]:
    man = recover_ir(docx)
    return {info.bookmark: key for key, info in man.labels.items()}


def test_foreign_prefix_label_is_unsanitised():
    # no manifest: a common cross-ref prefix gets its colon back (sec_intro -> sec:intro)
    src = r"\begin{document}\section{S}\label{sec:intro}See \ref{sec:intro}.\end{document}"
    doc = read_docx(convert_source(src, embed_manifest=False).docx)
    head = next(b for b in doc.blocks if isinstance(b, ir.Heading))
    assert head.label == "sec:intro"
    para = next(b for b in doc.blocks if isinstance(b, ir.Paragraph))
    ref = next(i for i in para.inlines if isinstance(i, ir.Ref))
    assert ref.key == "sec:intro"


def test_manifest_map_restores_arbitrary_label():
    # a non-standard prefix only the manifest map can reverse (myweird_lbl -> myweird:lbl)
    src = r"\begin{document}\section{S}\label{myweird:lbl}See \ref{myweird:lbl}.\end{document}"
    docx = convert_source(src).docx
    doc = read_docx(docx, label_map=_label_map(docx))
    ref = next(
        i for b in doc.blocks if isinstance(b, ir.Paragraph)
        for i in b.inlines if isinstance(i, ir.Ref)
    )
    assert ref.key == "myweird:lbl"


def test_without_map_unknown_prefix_is_left_alone():
    # no manifest + unknown prefix: don't guess (leave the sanitised name)
    src = r"\begin{document}\section{S}\label{myweird:lbl}See \ref{myweird:lbl}.\end{document}"
    doc = read_docx(convert_source(src, embed_manifest=False).docx)
    ref = next(
        i for b in doc.blocks if isinstance(b, ir.Paragraph)
        for i in b.inlines if isinstance(i, ir.Ref)
    )
    assert ref.key == "myweird_lbl"  # unchanged, not mis-restored
