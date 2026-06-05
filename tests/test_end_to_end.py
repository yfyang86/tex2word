from __future__ import annotations

import io
import os
import zipfile

from conftest import NS, document_root

from tex2word import convert_file, convert_source

CORPUS = os.path.join(os.path.dirname(__file__), "corpus")


def test_corpus_article_converts_without_aborting():
    path = os.path.join(CORPUS, "article.tex")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    result = convert_source(src, base_dir=CORPUS)

    # 0 hard aborts (we got here), and a valid zip with the body part.
    zf = zipfile.ZipFile(io.BytesIO(result.docx))
    assert "word/document.xml" in zf.namelist()

    root = document_root(result.docx)

    # Math went to OMML, not raw fallback.
    assert result.report.coverage()["math_raw"] == 0
    assert result.report.coverage()["math_omml"] >= 5

    # Live numbering + cross-reference fields exist.
    instrs = "".join(t.text or "" for t in root.xpath("//w:instrText", namespaces=NS))
    assert "SEQ Equation" in instrs
    assert "SEQ Table" in instrs
    assert "REF " in instrs

    # Heading styles present.
    styles = {e.get(f"{{{NS['w']}}}val") for e in root.xpath("//w:pStyle", namespaces=NS)}
    assert {"Title", "Heading1", "Heading2"} <= styles


def test_convert_file_writes_docx(tmp_path):
    tex = tmp_path / "a.tex"
    tex.write_text(r"\begin{document}\section{Hi}$x^2$\end{document}", encoding="utf-8")
    out, result = convert_file(str(tex))
    assert os.path.exists(out)
    assert out.endswith(".docx")
    assert result.report.coverage()["math_omml"] == 1


def test_input_flattening(tmp_path):
    (tmp_path / "child.tex").write_text(r"Included \textbf{content}.", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(r"\begin{document}\input{child}\end{document}", encoding="utf-8")
    _, result = convert_file(str(main))
    root = document_root(result.docx)
    assert root.xpath("//w:r/w:rPr/w:b", namespaces=NS)
