# Roadmap

Alcedo's aim is reproducible batch literature search: from a list of queries to a filtered,
explained list of DOIs. It is built on open APIs first, with Google Scholar as an option.

## Done: project setup

- Package, command line entry point and optional extras.
- Sources: OpenAlex, SerpApi, experimental direct Scholar access.
- DOI resolution, fallback between sources, resume.
- Offline test suite and CI configuration.

## 0.1: first release

- Subcommands (`search`, `check`, `filter`, `export`) and a config file.
- `alcedo check`: find mistakes before a run, such as lowercase `or`, `*`, guillemets, unbalanced brackets.
- A query parser that translates one syntax for each source (idea: findpapers).
- `--scope`: search titles and abstracts only, to reduce topic drift (idea: findpapers).
- Two-pass deduplication: by DOI, then by title and year (idea: findpapers).
- Retries with backoff and per-source rate limits (idea: findpapers, pyalex).
- Retraction flag (idea: paper-qa; OpenAlex `is_retracted`).
- Filters: years, excluded words, journal lists (idea: PyPaperBot, findpapers).
- Language filter. Quartile filter using an SJR file the user downloads from Scimago;
  the file is not redistributed, because its terms could not be confirmed.
- An `excluded.csv` report that gives the reason for each excluded record.
- Cache. Export to CSV, BibTeX and RIS, with abstracts so that ASReview can read it.
- Russian interface. First release on PyPI as `alcedo-lit`.

## 0.2

- More search sources: Crossref, PubMed, Semantic Scholar, arXiv.
- Citation snowballing (idea: findpapers).
- Links to legal open-access PDFs through Unpaywall and OpenAlex (idea: paper-qa).
- `--library-proxy` for links through a university's proxy.
- `no_access.csv`: papers with no open copy, for interlibrary loan or asking the authors.
- A run log with counts at every stage, in the style of PRISMA.
- SearchApi as an alternative to SerpApi (idea: paperscraper).
- A compare mode for choosing the default source: SerpApi against OpenAlex.

## 0.3 and later

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
