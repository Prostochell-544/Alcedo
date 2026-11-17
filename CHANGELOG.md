# Changelog

## Unreleased

- `alcedo app` opens a desktop window with the same steps as the command line: sources and keys, queries checked as
  you type, the search with its progress, and the filtered lists with export. It needs
  `pip install "alcedo-lit[app]"`, which adds Qt for Python. This first version is for feedback on the layout.
- A Windows program for people without Python: each release gets `Alcedo-<version>-windows.zip`, a folder with
  `Alcedo.exe`, built by GitHub Actions. It does not include direct Google Scholar search, which stays in the Python
  version; search APIs and the free sources work as usual. Settings are shared with the Python version.
- The window shows where the settings file is, with a link that opens its folder.

## 0.3.0 - 2026-11-15

A review you can report in a paper: repeats removed, the selection counted at every step, and the open copies found.

- `alcedo filter` finds the same work under different DOIs: a preprint and the article it became, or two editions
  of one paper. It keeps the published version, adds the queries that found the repeat, and lists the repeats in
  `alcedo_duplicates.csv`. Titles that are close but not the same are only marked, in a `similar_to` column, for you
  to check. In a 1,426-record run this found about ten repeats and eight close titles.
- `alcedo filter --type article,review` keeps only these record types. Others include preprint, book-chapter,
  dissertation and conference-paper. In the same run it cut the records with unknown data by more than half, because
  most of them were dissertations, preprints and book chapters, which have no journal quartile.
- The lists from `alcedo filter` show whether each paper has a legal open copy, and where, from OpenAlex. Kept papers
  with no open copy go to `alcedo_no_access.csv`, for interlibrary loan or to ask the authors. The exports link the
  open copy and say which version it is, because an accepted manuscript can differ from the published paper.
- `alcedo filter` writes a selection log, `alcedo_selection_log.md`: records found by each source, duplicates
  removed, records excluded and why, records to check by hand, and access to the kept papers. Its last section gives
  the numbers for the identification part of a PRISMA 2020 flow diagram.
- For developers: the search reports its progress, problems and final counts as events, which another program, such
  as the interface planned for 0.4, can listen to. The command line prints exactly what it printed before.

Known limits:

- Repeats are found only by exactly the same title. Close titles are marked for you to decide.
- Open access data comes from OpenAlex only. Records that only Crossref knows have none.
- The selection log covers what Alcedo does. Screening titles, abstracts and full texts is yours to record.
- The first `alcedo filter` after updating fetches paper data again, because the records gained open access fields.

## 0.2.0 - 2026-11-04

From a raw list of DOIs to a filtered list that a reference manager can read.

- A local cache of DOI lookups, so a repeated run does not look up the same records again. `--no-cache` turns it off.
- `alcedo filter` narrows results by year, language, quartile and words, using no search quota. It writes the kept,
  excluded and unknown records to separate files, each with the reason, and excludes papers marked as retracted.
- `alcedo export` writes the filtered list, or any results file, as RIS and BibTeX, with authors, journal and
  abstracts, for Zotero, Mendeley, EndNote and ASReview. Authors are written family name first, so Zotero splits and
  sorts them correctly.
- Messages say "1 error" rather than "1 errors".

Known limits:

- The quartile is the journal's best one across its fields. The SJR file is downloaded by the user.
- Records without a DOI cannot be filtered by year, language or quartile, so they go to the unknown list.
- Family names are guessed from the last word of a name, which can be wrong for some double family names.
- The export was tested by importing RIS into Zotero. Mendeley, EndNote and ASReview were not tried.

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
