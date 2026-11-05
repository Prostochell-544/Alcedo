import csv

from alcedo_lit import cli, filters
from alcedo_lit.filters import Entry, mark_similar, remove_duplicates

TITLE = "Kingfisher diet along a stream habitat"


def entry(doi, title=TITLE, year=2020, kind="article", queries=("q",)):
    record = {"title": title, "year": year, "type": kind} if year or kind else None
    return Entry(doi, title, list(queries), record=record)


def test_the_article_is_kept_and_its_preprint_is_a_repeat():
    preprint = entry("10.1101/2019.01.01.123", year=2019, kind="preprint", queries=("q1",))
    article = entry("10.1234/article", year=2020, queries=("q2",))
    kept, repeats = remove_duplicates([preprint, article])
    assert kept == [article]
    assert repeats == [preprint]
    assert article.queries == ["q2", "q1"]
    assert preprint.reasons == ["same work as 10.1234/article (this one is a preprint)"]


def test_a_preprint_server_doi_counts_as_a_preprint_even_without_its_type():
    preprint = entry("10.2139/ssrn.1234567", year=2018, kind="article")
    article = entry("10.1234/article", year=2020)
    kept, _ = remove_duplicates([preprint, article])
    assert kept == [article]


def test_the_same_title_in_the_same_year_is_one_work():
    first = entry("10.1234/a", queries=("q1",))
    second = entry("10.5678/b", queries=("q1", "q2"))
    kept, repeats = remove_duplicates([first, second])
    assert kept == [second]  # found by more queries
    assert repeats[0].reasons == ["same work as 10.5678/b"]


def test_the_same_title_in_different_years_stays_apart_but_is_marked():
    first = entry("10.1234/a", year=2015)
    second = entry("10.5678/b", year=2016)
    kept, repeats = remove_duplicates([first, second])
    assert (len(kept), repeats) == (2, [])
    assert mark_similar(kept) == 2
    assert first.similar == ["10.5678/b"] and second.similar == ["10.1234/a"]


def test_short_titles_are_never_joined():
    kept, repeats = remove_duplicates([entry("10.1234/a", title="Editorial"), entry("10.5678/b", title="Editorial")])
    assert (len(kept), repeats) == (2, [])


def test_titles_are_compared_without_case_and_punctuation():
    first = entry("10.1234/a", title="Kingfisher diet: along a stream habitat.")
    second = entry("10.5678/b", title="KINGFISHER DIET ALONG A STREAM HABITAT")
    assert len(remove_duplicates([first, second])[1]) == 1


def test_similar_titles_are_marked_not_joined():
    first = entry("10.1234/a", title="Variation in the diet of the common kingfisher along a stream habitat")
    second = entry("10.5678/b", title="Variation in the diets of the common kingfisher along a stream habitat")
    third = entry("10.9999/c", title="Something entirely different about trains and beaks")
    kept, repeats = remove_duplicates([first, second, third])
    assert (len(kept), repeats) == (3, [])
    assert mark_similar(kept) == 2
    assert third.similar == []


def test_similar_titles_years_apart_are_not_marked():
    first = entry("10.1234/a", title="Variation in the diet of the common kingfisher", year=2010)
    second = entry("10.5678/b", title="Variation in the diets of the common kingfisher", year=2015)
    assert mark_similar([first, second]) == 0


def test_the_filter_writes_repeats_to_their_own_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alcedo_results.txt").write_text(
        "=== Query: q1 ===\nhttps://doi.org/10.1101/2019.01.01.123\n\n"
        "=== Query: q2 ===\nhttps://doi.org/10.1234/article\n\n", encoding="utf-8")
    papers = {"10.1101/2019.01.01.123": {"title": TITLE, "year": 2019, "type": "preprint"},
              "10.1234/article": {"title": TITLE, "year": 2020, "type": "article"}}
    monkeypatch.setattr(filters, "fetch_metadata", lambda dois, args, cache=None: (papers, []))
    assert cli.main(["filter"]) == 0
    with (tmp_path / "alcedo_duplicates.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    assert [r["doi"] for r in rows] == ["10.1101/2019.01.01.123"]
    with (tmp_path / "alcedo_filtered.csv").open(encoding="utf-8-sig", newline="") as file:
        kept = list(csv.DictReader(file, delimiter=";"))
    assert kept[0]["queries"] == "q2 | q1"
    assert "Records: 2. Repeats of the same work: 1. Kept: 1." in capsys.readouterr().out
