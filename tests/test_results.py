from alcedo_lit.results import load_results, read_queries, save_results


def test_read_queries_normalizes_and_deduplicates(tmp_path):
    path = tmp_path / "q.txt"
    path.write_text('nacre  ("a b" OR\n "c d");\n\n second ; nacre ("a b" OR "c d");', encoding="utf-8")
    assert read_queries(path) == ['nacre ("a b" OR "c d")', "second"]


def test_read_queries_accepts_a_byte_order_mark(tmp_path):
    path = tmp_path / "q.txt"
    path.write_bytes("﻿nacre;".encode())
    assert read_queries(path) == ["nacre"]


def test_save_keeps_query_order_and_load_round_trips(tmp_path):
    path = tmp_path / "r.txt"
    results = {"b": ["https://doi.org/10.1/b"], "a": ["https://doi.org/10.1/a"]}
    save_results(path, ["a", "b"], results)
    assert path.read_text(encoding="utf-8").startswith("=== Query: a ===")
    assert load_results(path) == results


def test_load_drops_error_blocks(tmp_path):
    path = tmp_path / "r.txt"
    save_results(path, ["ok", "bad"], {"ok": ["https://doi.org/10.1/a"], "bad": ["Query error (SerpApi): x"]})
    assert list(load_results(path)) == ["ok"]


def test_redo_openalex_drops_openalex_blocks_only_when_asked(tmp_path):
    path = tmp_path / "r.txt"
    blocks = {"scholar": ["https://doi.org/10.1/a"], "oa": ["Source: OpenAlex", "https://doi.org/10.1/b"]}
    save_results(path, list(blocks), blocks)
    assert list(load_results(path)) == ["scholar", "oa"]
    assert list(load_results(path, redo_openalex=True)) == ["scholar"]


def test_load_missing_file_is_empty(tmp_path):
    assert load_results(tmp_path / "none.txt") == {}
