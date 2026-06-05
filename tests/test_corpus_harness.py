"""Corpus harness (PRD: 0 hard aborts; schema-valid output)."""

from __future__ import annotations

import glob
import os

import pytest

from tex2word import convert_source
from tex2word.frontend import parse_document
from tex2word.roundtrip import recover_ir, to_latex
from tex2word.validate import validate_docx

CORPUS = os.path.join(os.path.dirname(__file__), "corpus")
TEX_FILES = sorted(glob.glob(os.path.join(CORPUS, "*.tex")))


@pytest.mark.parametrize("path", TEX_FILES, ids=[os.path.basename(p) for p in TEX_FILES])
def test_corpus_file_converts_cleanly(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    # 1. no hard abort
    result = convert_source(src, base_dir=CORPUS)

    # 2. no errors logged (warnings are acceptable graceful degradation)
    assert result.report.errors == [], result.report.errors

    # 3. output is structurally valid OOXML/OPC
    problems = validate_docx(result.docx)
    assert problems == [], problems

    # 4. round-trip manifest recovers the same IR
    recovered = recover_ir(result.docx)
    assert recovered is not None
    assert recovered.to_dict() == result.document.to_dict()


@pytest.mark.parametrize("path", TEX_FILES, ids=[os.path.basename(p) for p in TEX_FILES])
def test_corpus_latex_roundtrip_preserves_structure(path):
    # latex -> docx -> latex -> IR should keep the same block structure (A2/M1).
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    docx = convert_source(src, base_dir=CORPUS).docx
    latex = to_latex(docx)
    assert latex is not None
    original, _ = parse_document(src, CORPUS)
    recovered, _ = parse_document(latex, CORPUS)
    assert [type(b).__name__ for b in original.blocks] == [
        type(b).__name__ for b in recovered.blocks
    ]


def test_corpus_is_nonempty():
    assert TEX_FILES, "no corpus .tex files found"
