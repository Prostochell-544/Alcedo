# Roadmap

Alcedo's aim is reproducible batch literature search: from a list of queries to a filtered,
explained list of DOIs. Google Scholar through the user's own API key comes first, because it gave the most
relevant results in our test, and free sources stay available for people who cannot pay for one.

## Done: project setup

- Package, command line entry point and optional extras.
- Sources: SearchApi, Serper or SerpApi with the user's key; without a working API, Semantic Scholar and OpenAlex,
  plus direct Scholar search if the user agrees. A source that fails is left out.
- `alcedo setup` for keys and the choice about direct search. Results from direct search come last and are marked.
- DOI resolution, fallback between sources, resume.
- Offline test suite and CI configuration.

## 0.1: first release

- A combined list without repeats that shows which queries found each paper. In a 40-query test,
  476 of 1,902 result lines repeated a paper found by another query.
- `--verify-dois` checks each DOI in the doi.org registry and marks the ones that do not exist. In the
  same test, 1 of 1,426 unique DOIs from OpenAlex did not exist.
- `alcedo check`: find mistakes before a run, such as lowercase `or`, `*`, guillemets, unbalanced brackets.
- Documentation in English, Russian and Ukrainian. First release on PyPI as `alcedo-lit`.

## 0.2: from a raw list to a filtered one (released)

- Metadata for each DOI from OpenAlex, with Crossref for what it lacks: title, year, journal, ISSN, language, type,
  retraction. Tested on 1,621 DOIs from real runs: year and language filled for 99-100%, ISSN for 85-91%.
- A cache, so a repeated run does not look up the same DOIs and records again.
- `alcedo filter`: years, language, quartile, excluded words, retracted papers. It works on collected results, so
  changing a condition uses no search quota. The quartile comes from an SJR file the user downloads from Scimago,
  because its terms for redistribution could not be confirmed.
- Records with unknown data are kept apart as `unknown`, never dropped silently. In our runs about a quarter of the
  results from Google Scholar had no DOI.
- An `excluded.csv` report that gives the reason for each excluded record.
- Export to BibTeX and RIS, so that Zotero and ASReview can read the results. Authors are written family name
  first, so Zotero splits them.

## 0.3 and later

- A filter by record type, such as `--type article,review`: in a real run, a fifth of the records
  without a quartile were dissertations and preprints.
- Batch import of a filtered list straight into a Zotero library.
- Russian and Ukrainian interface.
- A query parser that translates one syntax for each source (idea: findpapers).
- `--scope`: search titles and abstracts only, to reduce topic drift (idea: findpapers).
- Two-pass deduplication: by DOI, then by title and year (idea: findpapers).
- Retries with backoff and per-source rate limits (idea: findpapers, pyalex).
- Tests of Serper and Semantic Scholar on more queries, to settle the default order.
- An application icon made from the logo.
- More search sources: PubMed, arXiv, OpenAIRE.
- Citation snowballing (idea: findpapers).
- Links to legal open-access PDFs through Unpaywall and OpenAlex (idea: paper-qa).
- `--library-proxy` for links through a university's proxy.
- `no_access.csv`: papers with no open copy, for interlibrary loan or asking the authors.
- A run log with counts at every stage, in the style of PRISMA.
- A compare mode that shows how much the sources differ on the user's own queries.
- Import and filter existing RIS and BibTeX lists (idea: litstudy).
- OpenAlex semantic search (idea: pyalex).
- JUFO levels as a built-in quality signal, once its terms are confirmed (idea: paper-qa).
- Russian sources such as eLIBRARY and CyberLeninka, if a legitimate access route exists.
- Local web interface. MCP server for AI assistants.

## 1.0

- Stable interface, documentation site and a paper in JOSS.

## Out of scope

- Shadow libraries such as Sci-Hub and Anna's Archive.
- Anti-detection measures for Google Scholar.
- Writing reviews with AI, and active-learning screening. Alcedo exports to ASReview instead.
