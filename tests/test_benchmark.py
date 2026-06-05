"""V4-4: the quantitative benchmark harness."""

from __future__ import annotations

import json
import os

from tex2word.benchmark import benchmark_dir, format_report

CORPUS = os.path.join(os.path.dirname(__file__), "corpus")


def test_benchmark_over_corpus():
    result = benchmark_dir(CORPUS)
    agg = result["aggregate"]
    assert agg["documents"] >= 5
    assert agg["aborted"] == 0
    assert agg["valid"] == agg["documents"]          # every doc valid OOXML
    assert agg["math_raw"] == 0                       # nothing fell back to raw
    assert agg["math_omml_pct"] == 100.0
    # per-doc rows carry the metrics
    assert all("math_omml" in d and "valid" in d for d in result["documents"])


def test_benchmark_report_is_json_serialisable_and_formats():
    result = benchmark_dir(CORPUS)
    json.dumps(result)  # must round-trip to JSON for the --output file
    text = format_report(result)
    assert "TOTAL" in text and "math%" in text


def test_benchmark_empty_dir(tmp_path):
    assert benchmark_dir(str(tmp_path))["documents"] == []
