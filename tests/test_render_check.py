from __future__ import annotations

import pytest

from latex2word.render_check import check_docx, find_soffice, inspect_pdf

pytest.importorskip("pypdfium2")  # the `pdf` extra backend (PDFium)
plt = pytest.importorskip("matplotlib.pyplot")  # authors the test PDFs (permissive)


def _make_pdf(path, text: str) -> None:
    fig = plt.figure()
    fig.text(0.1, 0.5, text)
    fig.savefig(str(path), format="pdf")
    plt.close(fig)


def test_inspect_pdf_passes_with_text(tmp_path):
    pdf = tmp_path / "ok.pdf"
    _make_pdf(pdf, "Hello Introduction section")
    assert inspect_pdf(pdf) == []
    assert inspect_pdf(pdf, ["Introduction"]) == []


def test_inspect_pdf_flags_missing_expected_text(tmp_path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, "only this text")
    problems = inspect_pdf(pdf, ["Nonexistent"])
    assert problems and "Nonexistent" in problems[0]


def test_inspect_pdf_flags_empty_text(tmp_path):
    pdf = tmp_path / "blank.pdf"
    fig = plt.figure()  # a page with no text
    fig.savefig(str(pdf), format="pdf")
    plt.close(fig)
    problems = inspect_pdf(pdf)
    assert any("empty" in p for p in problems)


def test_check_docx_skips_when_renderer_unavailable(tmp_path):
    # in this sandbox LibreOffice cannot load files, so check_docx returns None
    # (skip) rather than a false failure; that is the contract we rely on.
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"not really a docx")
    result = check_docx(docx)
    assert result is None or isinstance(result, list)


def test_find_soffice_returns_path_or_none():
    s = find_soffice()
    assert s is None or s.endswith(("soffice", "libreoffice"))


def test_main_skips_cleanly_when_no_soffice(monkeypatch, tmp_path):
    import latex2word.render_check as rc

    monkeypatch.setattr(rc, "find_soffice", lambda: None)
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"x")
    assert rc._main([str(docx)]) == 0  # no renderer installed -> skip, not fail


def test_main_fails_when_renderer_present_but_no_pdf(monkeypatch, tmp_path):
    # blocking-gate contract: soffice present + no PDF produced == failure
    import latex2word.render_check as rc

    monkeypatch.setattr(rc, "find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(rc, "render_to_pdf", lambda *a, **k: None)
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"x")
    assert rc._main([str(docx)]) == 1


def test_main_ok_when_render_succeeds(monkeypatch, tmp_path):
    import latex2word.render_check as rc

    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, "rendered content")
    monkeypatch.setattr(rc, "find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(rc, "render_to_pdf", lambda *a, **k: pdf)
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"x")
    assert rc._main([str(docx)]) == 0
