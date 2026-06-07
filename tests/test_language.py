"""V5-10: document language (babel/polyglossia -> Word w:lang) + --lang."""

from __future__ import annotations

import io
import zipfile

from tex2word import convert_source
from tex2word.frontend import parse_document
from tex2word.roundtrip import to_latex


def _styles(docx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read("word/styles.xml").decode()


def test_babel_language_detected():
    src = r"\documentclass{article}\usepackage[ngerman]{babel}\begin{document}Hallo\end{document}"
    doc, _ = parse_document(src)
    assert doc.meta.language == "de-DE"


def test_babel_main_option_and_last_wins():
    src = (
        r"\documentclass{article}\usepackage[german,english]{babel}"
        r"\begin{document}Hi\end{document}"
    )
    doc, _ = parse_document(src)
    assert doc.meta.language == "en-US"  # babel's main is the last option


def test_polyglossia_setmainlanguage():
    src = r"\documentclass{article}\setmainlanguage{french}\begin{document}Bonjour\end{document}"
    doc, _ = parse_document(src)
    assert doc.meta.language == "fr-FR"


def test_language_applied_to_styles_docdefaults():
    src = r"\documentclass{article}\usepackage[french]{babel}\begin{document}x\end{document}"
    styles = _styles(convert_source(src).docx)
    assert 'w:lang' in styles and 'w:val="fr-FR"' in styles


def test_lang_override():
    src = r"\documentclass{article}\usepackage[english]{babel}\begin{document}x\end{document}"
    styles = _styles(convert_source(src, language="de-DE").docx)
    assert 'w:val="de-DE"' in styles  # override beats the detected en-US


def test_no_language_leaves_styles_lang_free():
    styles = _styles(convert_source(r"\begin{document}x\end{document}").docx)
    assert "w:lang" not in styles


def test_language_round_trips_as_babel():
    src = r"\documentclass{article}\usepackage[ngerman]{babel}\begin{document}x\end{document}"
    latex = to_latex(convert_source(src).docx)
    assert r"\usepackage[ngerman]{babel}" in latex


def test_output_with_language_is_valid():
    from tex2word.validate import validate_docx

    res = convert_source(r"\documentclass{article}\usepackage[french]{babel}"
                         r"\begin{document}x\end{document}")
    assert validate_docx(res.docx) == []
