"""Issue #44: nested \\input paths and \\protect\\input spacing."""

from __future__ import annotations

from tex2word.frontend.preprocess import flatten_inputs


def test_nested_input_resolves_against_main_directory(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "outer.tex").write_text("A \\input{gen/inner}", encoding="utf-8")
    (gen / "inner.tex").write_text("B", encoding="utf-8")
    out = flatten_inputs("\\input{gen/outer}", str(tmp_path))
    assert out.split() == ["A", "B"]


def test_nested_input_falls_back_to_including_directory(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "outer.tex").write_text("A \\input{inner}", encoding="utf-8")
    (gen / "inner.tex").write_text("B", encoding="utf-8")
    out = flatten_inputs("\\input{gen/outer}", str(tmp_path))
    assert out.split() == ["A", "B"]


def test_main_directory_wins_over_including_directory(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "outer.tex").write_text("\\input{part}", encoding="utf-8")
    (gen / "part.tex").write_text("WRONG", encoding="utf-8")
    (tmp_path / "part.tex").write_text("RIGHT", encoding="utf-8")
    assert flatten_inputs("\\input{gen/outer}", str(tmp_path)).strip() == "RIGHT"


def test_import_prefers_its_own_directory(tmp_path):
    sub = tmp_path / "chap"
    sub.mkdir()
    (sub / "main.tex").write_text("\\input{part}", encoding="utf-8")
    (sub / "part.tex").write_text("CHAP", encoding="utf-8")
    (tmp_path / "part.tex").write_text("TOP", encoding="utf-8")
    assert flatten_inputs("\\import{chap/}{main}", str(tmp_path)).strip() == "CHAP"


def test_protect_input_does_not_glue_onto_control_word(tmp_path):
    (tmp_path / "cap.tex").write_text("Quality text", encoding="utf-8")
    out = flatten_inputs("\\caption{X \\protect\\input{cap}}", str(tmp_path))
    assert "\\protectQuality" not in out
    assert "\\protect Quality text" in out
    # plain text before \input is left alone
    assert flatten_inputs("a\\input{cap}", str(tmp_path)) == "aQuality text"
