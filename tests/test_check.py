import pytest

from alcedo_lit import cli, pipeline
from alcedo_lit.check import ERROR, WARNING, check_text, find_problems
from alcedo_lit.sources import openalex
from helpers import pubs


def levels(query):
    return [level for level, _ in find_problems(query)]


@pytest.mark.parametrize("query", [
    'biomimetic nacre ("brick-and-mortar" OR "layered structure") composite fracture toughness',
    'gecko-inspired dry adhesive (micropillar OR "hierarchical microstructure") adhesion',
    '"Alcedo atthis" kingfisher (foraging OR diet)',
    "mussel-inspired polydopamine \"wet adhesion\" -dental -periodontal",
    "Ti-6Al-4V β-cyclodextrin Ti/TiN Li+",
    '"what or which" word',  # inside a phrase, these are only text
    '"star * rating" "a ( b" word',
])
def test_good_queries_pass(query):
    assert find_problems(query) == []


@pytest.mark.parametrize("query, fragment", [
    ('"unclosed phrase nacre', "no pair"),
    ("nacre (toughness OR fracture", "Parentheses"),
    ("nacre toughness OR fracture)", "Parentheses"),
    (")nacre toughness(", "Parentheses"),
    ("nacre* toughness", "`*`"),
    ("«brick and mortar» nacre", "Curly quotes"),
    ("“brick and mortar” nacre", "Curly quotes"),
    ("nacre toughness OR fracture", "OR needs parentheses"),
])
def test_errors(query, fragment):
    problems = find_problems(query)
    assert any(level == ERROR and fragment in message for level, message in problems)


@pytest.mark.parametrize("query, fragment", [
    ("nacre or toughness", 'lowercase "or"'),
    ("nacre (toughness or fracture)", 'lowercase "or"'),
    ("nacre - dental", "minus"),
    ("intitle:nacre toughness", "only in Google Scholar"),
    ("nacre site:nature.com", "not filters"),
    ("nacre toughness 2020-2024", "Years"),
    ("перламутр прочность", "mostly English"),
    ("nacre # my note", "no comments"),
    ("biomaterials", "One word"),
    ("a b c d e f g h i j k l m", "long query"),
    ("x (a OR b OR c OR d OR e OR f)", "long OR list"),
])
def test_warnings(query, fragment):
    problems = find_problems(query)
    assert any(level == WARNING and fragment in message for level, message in problems)


def test_a_hyphen_inside_a_word_is_not_a_loose_minus():
    assert levels("mussel-inspired x-ray") == []


def test_five_or_terms_are_still_fine():
    assert levels("x (a OR b OR c OR d OR e)") == []


def test_a_forgotten_semicolon_shows_as_several_lines():
    (query, problems), = check_text("nacre toughness\ngecko adhesive;")
    assert query == "nacre toughness gecko adhesive"
    assert any("several lines" in message for _, message in problems)


def test_repeated_query_is_reported():
    checked = check_text("nacre toughness; gecko adhesive; nacre   toughness;")
    assert [bool(problems) for _, problems in checked] == [False, False, True]


def test_command_reports_problems_and_fails_on_errors(tmp_path, capsys):
    path = tmp_path / "q.txt"
    path.write_text("nacre toughness; nacre*; gecko or adhesive;", encoding="utf-8")
    assert cli.main(["check", "-i", str(path)]) == 1
    out = capsys.readouterr().out
    assert "nacre toughness" not in out
    assert "Query 2: nacre*" in out
    assert "error: `*`" in out
    assert "Query 3: gecko or adhesive" in out
    assert "Checked 3 queries: 1 error, 2 warnings." in out  # one word, and the lowercase or


def test_command_passes_on_warnings_only(tmp_path, capsys):
    path = tmp_path / "q.txt"
    path.write_text("gecko or adhesive;", encoding="utf-8")
    assert cli.main(["check", "-i", str(path)]) == 0
    assert "1 warning." in capsys.readouterr().out


def test_command_uses_queries_txt_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queries.txt").write_text("nacre toughness;", encoding="utf-8")
    assert cli.main(["check"]) == 0
    assert "Checked 1 query: 0 errors, 0 warnings." in capsys.readouterr().out


@pytest.mark.parametrize("content, fragment", [(None, "Cannot read"), (b"", "No queries"), (b"caf\xe9 test;", "UTF-8")])
def test_command_explains_a_file_it_cannot_use(tmp_path, capsys, content, fragment):
    path = tmp_path / "q.txt"
    if content is not None:
        path.write_bytes(content)
    assert cli.main(["check", "-i", str(path)]) == 1
    assert fragment in capsys.readouterr().err


def run_with(tmp_path, monkeypatch, content):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queries.txt").write_bytes(content)
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: (pubs("oa", [1, 2]), None))
    monkeypatch.setattr(pipeline, "pause_before_scholar", lambda args, bar: None)
    return cli.main(["--no-semantic-scholar", "--no-direct-scholar", "--no-page-meta", "--no-title-search"])


def test_a_run_mentions_doubtful_queries_but_goes_ahead(tmp_path, monkeypatch, capsys):
    assert run_with(tmp_path, monkeypatch, b"nacre toughness; gecko or adhesive;") == 0
    assert "1 of 2 queries may have mistakes" in capsys.readouterr().err
    assert (tmp_path / "alcedo_results.txt").exists()


def test_a_run_says_nothing_when_queries_look_fine(tmp_path, monkeypatch, capsys):
    assert run_with(tmp_path, monkeypatch, b"nacre toughness; gecko adhesive;") == 0
    assert "may have mistakes" not in capsys.readouterr().err


def test_a_run_explains_a_file_not_saved_as_utf8(tmp_path, monkeypatch, capsys):
    assert run_with(tmp_path, monkeypatch, "перламутр;".encode("cp1251")) == 1
    assert "UTF-8" in capsys.readouterr().err
