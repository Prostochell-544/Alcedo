import csv

import pytest

from alcedo_lit import cli, filters
from alcedo_lit.filters import load_sjr, normalize_issn, read_entries

RESULTS = """=== Query: q one ===
Source: Semantic Scholar (3)
https://doi.org/10.1234/keep
https://doi.org/10.1234/old
https://doi.org/10.1234/german
DOI not found: A paper without any DOI
DOI not found: A dental paper without a DOI
https://doi.org/10.1234/low
https://doi.org/10.1234/notinsjr
https://doi.org/10.1234/noissn
https://doi.org/10.1234/noquartile
https://doi.org/10.1234/noyear
https://doi.org/10.1234/nolanguage
https://doi.org/10.1234/retracted
https://doi.org/10.1234/dental
https://doi.org/10.1234/missing
https://doi.org/10.1234/failed
DOI not registered: 10.1234/fake

=== Query: q two ===
https://doi.org/10.1234/KEEP
DOI not found: Same Title As The Kept Paper

"""


def paper(title="T", year=2020, language="en", issn=("1111-1111",), retracted=False, abstract=None, journal="J"):
    return {"title": title, "year": year, "language": language, "issn": list(issn), "retracted": retracted,
            "abstract": abstract, "journal": journal, "type": "article", "authors": ["A One", None]}


PAPERS = {
    "10.1234/keep": paper("Same title as the kept paper"),
    "10.1234/old": paper(year=2001),
    "10.1234/german": paper(language="de"),
    "10.1234/low": paper(issn=("3333-3333",)),
    "10.1234/notinsjr": paper(issn=("9999-9999",)),
    "10.1234/noissn": paper(issn=()),
    "10.1234/noquartile": paper(issn=("4444-4444",)),
    "10.1234/noyear": paper(year=None),
    "10.1234/nolanguage": paper(language=None),
    "10.1234/retracted": paper(retracted=True),
    "10.1234/dental": paper(abstract="A study of DENTAL care."),
    "10.1234/missing": None,
}
SJR = '''Rank;Sourceid;Title;Type;Issn;SJR;SJR Best Quartile;H index
1;100;"Journal; One";journal;"11111111, 22222222";"18,663";Q1;200
2;101;Journal Three;journal;33333333;"0,5";Q3;10
3;102;Journal None;journal;44444444;;-;1
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alcedo_results.txt").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "sjr.csv").write_text(SJR, encoding="utf-8-sig")

    def fake_fetch(dois, args, cache=None):
        assert all(d == d.strip() for d in dois)
        lowered = {d.lower() for d in dois}
        known = {d: r for d, r in PAPERS.items() if d in lowered}
        return known, ["10.1234/failed"] if "10.1234/failed" in lowered else []

    monkeypatch.setattr(filters, "fetch_metadata", fake_fetch)
    return tmp_path


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {r["doi"] or r["title"]: r for r in csv.DictReader(file, delimiter=";")}


def run(*flags):
    return cli.main(["filter", *flags])


ALL_CONDITIONS = ("--year-from", "2015", "--language", "en", "--quartile", "Q1,Q2", "--sjr", "sjr.csv",
                  "--exclude-word", "dental")


def test_every_record_lands_in_one_list_with_its_reason(project, capsys):
    assert run(*ALL_CONDITIONS) == 0
    kept = rows(project / "alcedo_filtered.csv")
    excluded = rows(project / "alcedo_excluded.csv")
    unknown = rows(project / "alcedo_unknown.csv")

    assert set(kept) == {"10.1234/keep"}
    assert excluded["10.1234/old"]["reason"] == "year 2001 is before 2015"
    assert excluded["10.1234/german"]["reason"] == "language de"
    assert excluded["10.1234/low"]["reason"] == "quartile Q3"
    assert excluded["10.1234/retracted"]["reason"] == "retracted"
    assert excluded["10.1234/dental"]["reason"] == 'contains "dental"'
    assert excluded["10.1234/fake"]["reason"] == "DOI not registered in doi.org"
    assert excluded["A dental paper without a DOI"]["reason"] == 'contains "dental"'

    assert unknown["A paper without any DOI"]["reason"] == "no DOI"
    assert unknown["10.1234/notinsjr"]["reason"] == "journal not in the SJR file"
    assert unknown["10.1234/noissn"]["reason"] == "no ISSN (article)"
    assert unknown["10.1234/noquartile"]["reason"] == "no quartile in the SJR file"
    assert unknown["10.1234/noyear"]["reason"] == "no year"
    assert unknown["10.1234/nolanguage"]["reason"] == "no language"
    assert unknown["10.1234/missing"]["reason"] == "no data for this DOI"
    assert unknown["10.1234/failed"]["reason"] == "could not be checked, run again later"

    assert len(kept) + len(excluded) + len(unknown) == 16
    out = capsys.readouterr().out
    summary = f"Kept: {len(kept)}. Excluded: {len(excluded)}. Unknown: {len(unknown)}."
    assert f"Records: 16. Repeats of the same work: 0. {summary}" in out
    assert "Check the unknown list by hand" in out
    assert "Could not check 1 DOI." in out


def test_a_record_found_by_two_queries_counts_once_with_both(project):
    assert run() == 0
    keep = rows(project / "alcedo_filtered.csv")["10.1234/keep"]
    assert keep["found_by_queries"] == "2"
    assert keep["queries"] == "q one | q two"
    assert keep["url"] == "https://doi.org/10.1234/keep"
    assert keep["authors"] == "A One"
    assert keep["issn"] == "1111-1111"


def test_a_record_without_a_doi_joins_the_same_title_that_has_one(project):
    assert run() == 0
    unknown = rows(project / "alcedo_unknown.csv")
    assert "Same Title As The Kept Paper" not in unknown


def test_records_often_found_come_first(project):
    assert run() == 0
    with (project / "alcedo_filtered.csv").open(encoding="utf-8-sig", newline="") as file:
        assert next(csv.DictReader(file, delimiter=";"))["doi"] == "10.1234/keep"


def test_without_conditions_only_retracted_and_unregistered_are_excluded(project):
    assert run() == 0
    assert set(rows(project / "alcedo_excluded.csv")) == {"10.1234/retracted", "10.1234/fake"}
    kept = rows(project / "alcedo_filtered.csv")
    assert "10.1234/old" in kept and "10.1234/noissn" in kept


def test_keep_retracted(project):
    assert run("--keep-retracted") == 0
    assert rows(project / "alcedo_filtered.csv")["10.1234/retracted"]["retracted"] == "True"


def test_a_failed_condition_outweighs_missing_data(project, monkeypatch):
    PAPERS_WITH = {**PAPERS, "10.1234/old": paper(year=2001, issn=())}
    monkeypatch.setattr(filters, "fetch_metadata", lambda dois, args, cache=None: (PAPERS_WITH, []))
    assert run(*ALL_CONDITIONS) == 0
    assert rows(project / "alcedo_excluded.csv")["10.1234/old"]["reason"] == "year 2001 is before 2015"


def test_year_to(project):
    assert run("--year-to", "2010") == 0
    assert "10.1234/old" in rows(project / "alcedo_filtered.csv")
    assert rows(project / "alcedo_excluded.csv")["10.1234/keep"]["reason"] == "year 2020 is after 2010"


def test_several_languages_and_case(project):
    assert run("--language", "EN, de") == 0
    assert "10.1234/german" in rows(project / "alcedo_filtered.csv")


def test_quartile_is_shown_for_kept_records_and_lowercase_is_accepted(project):
    assert run("--quartile", "q1", "--sjr", "sjr.csv") == 0
    assert rows(project / "alcedo_filtered.csv")["10.1234/keep"]["quartile"] == "Q1"


@pytest.mark.parametrize("word, excluded", [("dent", False), ("dental care", True), ("DENTAL", True)])
def test_excluded_words_match_whole_words_and_phrases(project, word, excluded):
    assert run("--exclude-word", word) == 0
    assert ("10.1234/dental" in rows(project / "alcedo_excluded.csv")) is excluded


def test_a_file_name_can_be_chosen(project):
    assert run("-o", "my") == 0
    assert (project / "my_filtered.csv").exists()
    assert not (project / "alcedo_filtered.csv").exists()


def test_names_follow_the_input_file(project):
    (project / "other_results.txt").write_text(RESULTS, encoding="utf-8")
    assert run("-i", "other_results.txt") == 0
    assert (project / "other_unknown.csv").exists()


def test_failed_queries_are_mentioned(project, capsys):
    (project / "alcedo_results.txt").write_text(
        "=== Query: q ===\nhttps://doi.org/10.1234/keep\nQuery error after 1 results: x\n\n", encoding="utf-8")
    assert run() == 0
    assert "1 query failed during collection" in capsys.readouterr().out


def test_read_entries_skips_notes(project):
    note = "=== Query: q ===\nDOI not found (no source returned anything)\n\n"
    (project / "r.txt").write_text(note, encoding="utf-8")
    assert read_entries(project / "r.txt") == ([], 0)


@pytest.mark.parametrize("flags, fragment", [
    (["--quartile", "Q1"], "go together"),
    (["--sjr", "sjr.csv"], "go together"),
    (["--quartile", "Q9", "--sjr", "sjr.csv"], "Q1, Q2, Q3 or Q4"),
    (["--year-from", "2020", "--year-to", "2010"], "later than"),
])
def test_wrong_options_are_explained(project, capsys, flags, fragment):
    with pytest.raises(SystemExit):
        run(*flags)
    assert fragment in capsys.readouterr().err


@pytest.mark.parametrize("name, content, fragment", [
    ("missing.txt", None, "not found"),
    ("other.txt", "just some text\n", "no Alcedo results"),
    ("empty.txt", "=== Query: q ===\n\n", "No records"),
])
def test_a_file_that_cannot_be_used_is_explained(project, capsys, name, content, fragment):
    if content is not None:
        (project / name).write_text(content, encoding="utf-8")
    assert run("-i", name) == 1
    assert fragment in capsys.readouterr().err


def test_a_file_that_is_not_from_scimago_is_explained(project, capsys):
    (project / "wrong.csv").write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    assert run("--quartile", "Q1", "--sjr", "wrong.csv") == 1
    err = capsys.readouterr().err
    assert "SJR Best Quartile" in err
    assert "scimagojr.com" in err


def test_an_output_file_open_elsewhere_is_explained(project, monkeypatch, capsys):
    def locked(path, entries):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(filters, "_write", locked)
    assert run() == 1
    assert "close it" in capsys.readouterr().err


def test_sjr_file_reading(project):
    assert load_sjr(project / "sjr.csv") == {"11111111": "Q1", "22222222": "Q1", "33333333": "Q3", "44444444": "-"}


def test_issn_forms():
    assert normalize_issn("1234-567x") == "1234567X"
    assert normalize_issn(" 12345678 ") == "12345678"


def test_a_journal_listed_under_two_issns_takes_the_best_quartile():
    assert filters._best_quartile(["1111-1111", "2222-2222"], {"11111111": "Q3", "22222222": "Q1"}) == "Q1"
    assert filters._best_quartile(["1111-1111"], {"11111111": "-"}) == ""
    assert filters._best_quartile(["1111-1111"], {}) is None
