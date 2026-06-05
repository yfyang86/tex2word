from __future__ import annotations

import io
import zipfile

import pytest
from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}


@pytest.fixture
def ns():
    return NS


def document_root(docx_bytes: bytes) -> etree._Element:
    """Parse ``word/document.xml`` out of a generated .docx."""
    zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    return etree.fromstring(zf.read("word/document.xml"))


def part_names(docx_bytes: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).namelist()


@pytest.fixture
def parse_doc():
    def _parse(docx_bytes: bytes):
        return document_root(docx_bytes)

    return _parse
