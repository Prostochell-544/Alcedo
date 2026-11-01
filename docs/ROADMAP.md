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

## 0.2

- Language filter. Quartile filter using an SJR file the user downloads from Scimago;
  the file is not redistributed, because its terms could not be confirmed.
- An `excluded.csv` report that gives the reason for each excluded record.
- Filters: years, excluded words, journal lists (idea: PyPaperBot, findpapers).
- Export to BibTeX and RIS, with abstracts so that ASReview can read it.
- Subcommands (`search`, `filter`, `export`).
- A query parser that translates one syntax for each source (idea: findpapers).
- `--scope`: search titles and abstracts only, to reduce topic drift (idea: findpapers).
- Two-pass deduplication: by DOI, then by title and year (idea: findpapers).
- Retries with backoff and per-source rate limits (idea: findpapers, pyalex).
- Retraction flag (idea: paper-qa; OpenAlex `is_retracted`).
- Cache.
- Russian and Ukrainian interface.
- Tests of Serper and Semantic Scholar on real queries, to settle the default order and cost figures.
- An application icon made from the logo.
- More search sources: PubMed, arXiv, OpenAIRE.
- Citation snowballing (idea: findpapers).
- Links to legal open-access PDFs through Unpaywall and OpenAlex (idea: paper-qa).
- `--library-proxy` for links through a university's proxy.
- `no_access.csv`: papers with no open copy, for interlibrary loan or asking the authors.
- A run log with counts at every stage, in the style of PRISMA.
- A compare mode that shows how much the sources differ on the user's own queries.

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
