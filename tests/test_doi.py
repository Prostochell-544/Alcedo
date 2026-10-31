import pytest

from alcedo_lit.doi import (
    best_title_match,
    doi_from_meta,
    doi_from_url_pattern,
    doi_url,
    europepmc_query,
    exact_doi,
    extract_doi,
    normalize_title,
)

SICI = "10.1002/(SICI)1097-4636(199709)36:3<321::AID-JBM6>3.0.CO;2-O"


@pytest.mark.parametrize("url, expected", [
    ("https://pubs.acs.org/doi/abs/10.1021/acs.jcim.0c00123", "10.1021/acs.jcim.0c00123"),
    ("https://onlinelibrary.wiley.com/doi/pdf/10.1002/jcc.26000", "10.1002/jcc.26000"),
    ("https://onlinelibrary.wiley.com/doi/10.1002/jcc.26000/full", "10.1002/jcc.26000"),
    ("https://link.springer.com/content/pdf/10.1007/s10847-020-01001-1.pdf", "10.1007/s10847-020-01001-1"),
    ("https://www.frontiersin.org/articles/10.3389/fchem.2020.00123/full", "10.3389/fchem.2020.00123"),
    ("https://iopscience.iop.org/article/10.1088/1742-6596/1234/1/012001/meta", "10.1088/1742-6596/1234/1/012001"),
    ("https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0123456&type=printable",
     "10.1371/journal.pone.0123456"),
    ("https://www.biorxiv.org/content/10.1101/2020.03.22.002386v1.full.pdf", "10.1101/2020.03.22.002386"),
    ("https://doi.org/10.1016/S0006-3495(20)30001-1", "10.1016/S0006-3495(20)30001-1"),
    ("https://www.tandfonline.com/doi/full/10.1080%2F07391102.2020.1234567", "10.1080/07391102.2020.1234567"),
    ("https://arxiv.org/abs/2101.01234v2", "10.48550/arXiv.2101.01234"),
    ("https://arxiv.org/pdf/cond-mat/0501234", "10.48550/arXiv.cond-mat/0501234"),
    ("https://www.nature.com/articles/s41586-020-2649-2.pdf", "10.1038/s41586-020-2649-2"),
    ("https://www.nature.com/articles/nature12345", "10.1038/nature12345"),
    ("https://pubs.rsc.org/en/content/articlehtml/2020/cp/d0cp01234a", "10.1039/D0CP01234A"),
    ("https://www.sciencedirect.com/science/article/pii/S0021967320301234", None),
    ("https://www.mdpi.com/1422-0067/21/3/1234", None),
])
def test_doi_from_url(url, expected):
    assert (extract_doi(url) or doi_from_url_pattern(url)) == expected


@pytest.mark.parametrize("doi", ["10.5555/meta", "10.1234/report.full", "10.1000/abc&def", "10.1101/gr.123456v2", SICI])
def test_a_whole_doi_is_never_trimmed(doi):
    assert exact_doi(doi) == doi
    assert exact_doi(f"https://doi.org/{doi}") == doi
    assert extract_doi(f"https://doi.org/{doi}") == doi
    assert extract_doi(f"doi:{doi}") == doi


def test_exact_doi_rejects_anything_else():
    assert exact_doi("https://publisher.org/10.1234/abc") is None
    assert exact_doi("see 10.1234/abc") is None
    assert exact_doi(None) is None


def test_sici_doi_survives_a_publisher_url():
    url = "https://onlinelibrary.wiley.com/doi/10.1002/(SICI)1097-4636(199709)36:3%3C321::AID-JBM6%3E3.0.CO;2-O/abstract"
    assert extract_doi(url) == SICI


def test_angle_brackets_still_end_an_ordinary_doi():
    assert extract_doi("see <a>10.1234/abc</a> here") == "10.1234/abc"


def test_doi_url_encodes_only_what_it_must():
    assert doi_url("10.1234/abc.1_2-3") == "https://doi.org/10.1234/abc.1_2-3"
    assert doi_url(SICI).endswith("36:3%3C321::AID-JBM6%3E3.0.CO;2-O")


def test_meta_tags_in_any_attribute_order():
    page = '<meta content="10.3390/ijms21031234" name="citation_doi"><meta name="dc.identifier" content="x">'
    assert doi_from_meta(page) == "10.3390/ijms21031234"


def test_meta_value_is_taken_whole():
    assert doi_from_meta('<meta name="citation_doi" content="10.5555/meta">') == "10.5555/meta"


def test_meta_without_doi():
    assert doi_from_meta('<meta name="dc.identifier" content="ISBN 123">') is None


def test_europepmc_query():
    assert europepmc_query("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7175671/") == "PMCID:PMC7175671"
    assert europepmc_query("https://pubmed.ncbi.nlm.nih.gov/32015507/") == "EXT_ID:32015507 AND SRC:MED"
    assert europepmc_query("https://example.org/") is None


def test_normalize_title_strips_markup_and_entities():
    assert normalize_title("Electrochemical CO<sub>2</sub> &amp; more") == "electrochemical co2 more"


def test_title_match_prefers_exact_title_over_review_of_it():
    title = "A pneumonia outbreak associated with a new coronavirus of probable bat origin"
    candidates = [("10.1/review", f'Review of "{title}"'), ("10.1038/real", title)]
    assert best_title_match(title, candidates) == "10.1038/real"


def test_title_match_keeps_the_registry_doi_whole():
    assert best_title_match("A report", [("10.1234/report.full", "A report")]) == "10.1234/report.full"


def test_title_match_rejects_different_title():
    assert best_title_match("Array programming with NumPy", [("10.1/x", "Numpy")]) is None
