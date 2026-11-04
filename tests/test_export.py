import csv

import pytest

from alcedo_lit import cli, export
from alcedo_lit.export import bibtex_entry, bibtex_key, read_records, ris_entry

PAPER = {"title": "Nacre & toughness: 50% better {really}", "year": 2020, "journal": "Journal of Things",
         "issn": ["1111-1111"], "language": "en", "type": "article", "retracted": False,
         "authors": ["Anna Müller", "Bo Li", None], "volume": "5", "issue": "2", "pages": "10-20",
         "abstract": "Line one.\nLine two.", "source": "OpenAlex"}
ITEM = {"doi": "10.1234/a", "title": "Nacre", "queries": ["q one", "q two"]}


def tags(text):
    return [line[:2] for line in text.splitlines()]


def test_ris_entry_has_every_field_on_one_line():
    text = ris_entry(ITEM, PAPER)
    assert tags(text) == ["TY", "TI", "AU", "AU", "PY", "T2", "VL", "IS", "SP", "EP", "SN", "LA", "DO", "UR", "AB",
                          "N1", "ER"]
    assert "TY  - JOUR" in text
    assert "AU  - Müller, Anna\nAU  - Li, Bo\n" in text
    assert "SP  - 10\nEP  - 20" in text
    assert "AB  - Line one. Line two." in text
    assert "N1  - Found by Alcedo queries: q one | q two" in text
    assert text.endswith("ER  -\n")


@pytest.mark.parametrize("kind, ris, bibtex", [
    ("book-chapter", "CHAP", "@incollection"), ("dissertation", "THES", "@phdthesis"), ("preprint", "UNPB", "@misc"),
    ("conference-paper", "CPAPER", "@inproceedings"), ("something-new", "GEN", "@misc"),
])
def test_types(kind, ris, bibtex):
    record = {**PAPER, "type": kind}
    assert f"TY  - {ris}" in ris_entry(ITEM, record)
    assert bibtex_entry(ITEM, record, set()).startswith(bibtex)


def test_a_record_without_data_keeps_its_title():
    text = ris_entry({"doi": None, "title": "Only a title", "queries": []}, None)
    assert text == "TY  - GEN\nTI  - Only a title\nER  -\n"
    bib = bibtex_entry({"doi": None, "title": "Only a title", "queries": []}, None, set())
    assert bib == "@misc{anononly,\n  title = {Only a title}\n}\n"


def test_a_retracted_paper_says_so():
    assert "N1  - Retracted, according to OpenAlex" in ris_entry(ITEM, {**PAPER, "retracted": True})
    assert "Retracted, according to OpenAlex" in bibtex_entry(ITEM, {**PAPER, "retracted": True}, set())


def test_bibtex_entry_escapes_and_joins():
    text = bibtex_entry(ITEM, PAPER, set())
    assert text.startswith("@article{muller2020nacre,\n")
    assert "  title = {Nacre \\& toughness: 50\\% better really},\n" in text
    assert "  author = {Müller, Anna and Li, Bo},\n" in text
    assert "  journal = {Journal of Things},\n" in text
    assert "  pages = {10--20},\n" in text
    assert "  number = {2},\n" in text
    assert "  abstract = {Line one. Line two.},\n" in text
    assert text.count("{") == text.count("}")


@pytest.mark.parametrize("name, expected", [
    ("Jie Li", "Li, Jie"),
    ("S. James Reynolds", "Reynolds, S. James"),
    ("Ludwig van Beethoven", "van Beethoven, Ludwig"),
    ("Maria de la Cruz", "de la Cruz, Maria"),
    ("Martin Luther King Jr.", "King, Martin Luther, Jr."),
    ("Li, Jie", "Li, Jie"),
    ("Aristotle", "Aristotle"),
    ("World Health Organization", "World Health Organization"),
    ("  Jie   Li ", "Li, Jie"),
    ("Tobias Stalder A", "Stalder, Tobias A"),
    ("Lourdes R. Herrera C.", "Herrera, Lourdes R. C."),
    ("Jie A", "A, Jie"),
])
def test_names_are_written_family_name_first(name, expected):
    assert export.last_first(name) == expected


def test_an_organization_with_and_in_its_name_stays_one_author():
    authors = ["Food and Agriculture Organization", "Jie Li"]
    assert "  author = {{Food and Agriculture Organization} and Li, Jie},\n" in bibtex_entry(
        ITEM, {**PAPER, "authors": authors}, set())
    assert "AU  - Food and Agriculture Organization\nAU  - Li, Jie\n" in ris_entry(ITEM, {**PAPER, "authors": authors})


def test_bibtex_keys_stay_unique():
    used = set()
    assert [bibtex_key(ITEM, PAPER, used) for _ in range(3)] == ["muller2020nacre", "muller2020nacrea",
                                                                  "muller2020nacreb"]


def test_a_book_chapter_names_its_book():
    text = bibtex_entry(ITEM, {**PAPER, "type": "book-chapter"}, set())
    assert "booktitle = {Journal of Things}" in text


def test_single_page():
    assert "SP  - 7\n" in ris_entry(ITEM, {**PAPER, "pages": "7"})
    assert "EP  -" not in ris_entry(ITEM, {**PAPER, "pages": "7"})


# ------------------------------- The command -------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, "fetch_metadata",
                        lambda dois, args, cache=None: ({"10.1234/a": PAPER}, [d for d in dois if "fail" in d]))
    return tmp_path


def write_filtered(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["doi", "url", "title", "queries"])
        writer.writerows(rows)


def test_exports_the_filtered_list_by_default(project, capsys):
    write_filtered(project / "alcedo_filtered.csv", [["10.1234/a", "", "Nacre", "q one | q two"],
                                                     ["", "", "No DOI here", "q one"],
                                                     ["10.1234/fail", "", "Failed", "q two"]])
    (project / "alcedo_results.txt").write_text("=== Query: x ===\nhttps://doi.org/10.1234/other\n\n",
                                                encoding="utf-8")
    assert cli.main(["export"]) == 0
    ris = (project / "alcedo_filtered.ris").read_text(encoding="utf-8")
    bib = (project / "alcedo_filtered.bib").read_text(encoding="utf-8")
    assert ris.count("TY  - ") == 3 and bib.count("@") == 3
    assert "10.1234/other" not in ris
    assert "TI  - No DOI here" in ris
    out = capsys.readouterr().out
    assert "Exported 3 records" in out
    assert "With an abstract: 1." in out
    assert "Records without a DOI, which keep only their title: 1." in out
    assert "Could not fetch the data of 1 DOI" in out


def test_without_a_filtered_list_the_results_file_is_used(project):
    (project / "alcedo_results.txt").write_text(
        "=== Query: q ===\nhttps://doi.org/10.1234/a\nDOI not registered: 10.1234/fake\n"
        "DOI not found: A paper without a DOI\n\n=== Query: r ===\nhttps://doi.org/10.1234/A\n\n", encoding="utf-8")
    assert cli.main(["export", "--format", "ris"]) == 0
    ris = (project / "alcedo_results.ris").read_text(encoding="utf-8")
    assert ris.count("TY  - ") == 2  # the unregistered DOI is left out, the repeat counted once
    assert "Found by Alcedo queries: q | r" in ris
    assert not (project / "alcedo_results.bib").exists()


def test_output_name_and_bibtex_only(project):
    write_filtered(project / "list.csv", [["10.1234/a", "", "Nacre", ""]])
    assert cli.main(["export", "-i", "list.csv", "-o", "mine", "--format", "bibtex"]) == 0
    assert (project / "mine.bib").exists()
    assert not (project / "mine.ris").exists()


@pytest.mark.parametrize("name, content, fragment", [
    ("missing.csv", None, "not found"),
    ("other.csv", "a;b\n1;2\n", "no 'doi' column"),
    ("other.txt", "just text\n", "no Alcedo results"),
    ("empty.csv", "doi;title\n", "No records"),
])
def test_files_that_cannot_be_used_are_explained(project, capsys, name, content, fragment):
    if content is not None:
        (project / name).write_text(content, encoding="utf-8")
    assert cli.main(["export", "-i", name]) == 1
    assert fragment in capsys.readouterr().err


def test_read_records_keeps_the_order(project):
    write_filtered(project / "f.csv", [["10.1234/b", "", "B", "q"], ["10.1234/a", "", "A", "q | r"]])
    assert [r["doi"] for r in read_records(project / "f.csv")] == ["10.1234/b", "10.1234/a"]
