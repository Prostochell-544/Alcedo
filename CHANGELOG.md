# Changelog

## Unreleased

- A local cache of DOI lookups, so a repeated run does not look up the same records again. `--no-cache` turns it off.
- `alcedo filter` narrows results by year, language, quartile and words, using no search quota. It writes the kept,
  excluded and unknown records to separate files, each with the reason, and excludes papers marked as retracted.
- `alcedo export` writes the filtered list, or any results file, as RIS and BibTeX, with authors, journal and
  abstracts, for Zotero, Mendeley, EndNote and ASReview.
- Messages say "1 error" rather than "1 errors".

## 0.1.0 - 2026-11-02

First release.

- Turn a file of queries into DOIs grouped by query, with up to 50 results per query from each source.
- Search Google Scholar through SearchApi, Serper or SerpApi with your own key.
- Without a working API, combine Semantic Scholar and OpenAlex, plus direct Google Scholar search if you agree to it.
  A source that fails is left out, and the block says so.
- `alcedo setup` explains the options and saves your keys and your choice about direct search.
- `alcedo check` finds mistakes in a query file before a run, using no network and no quota.
- Find a DOI through the URL, Europe PMC, publisher meta tags, then by title in Crossref and OpenAlex.
- Save after every query. `--resume` continues a run, and `--redo-free` collects blocks from the free sources again.
- Write a list with each DOI once and the queries that found it.
- `--verify-dois` checks DOIs in the doi.org registry.

Known limits:

- There are no filters by quartile, language or year yet, and no export to BibTeX or RIS.
- Alcedo has not yet been run with a real SerpApi key, so its cost and results are not measured.
- In a small test, Serper matched SearchApi on the first 10 results, and later results differed.
- Direct Google Scholar search can return incomplete lists even when Scholar answers, and it makes a run slow.
