# Alcedo

*Alcedo* is the Latin name of the kingfisher, which dives and picks out exactly what it wants.

Alcedo turns a list of literature search queries into DOIs grouped by query. Put your
boolean queries in a file and run one command. The results are a text file with one
block per query. There is no export to reference managers yet.

**Status: pre-alpha.** It is not on PyPI yet, and options may change. See the
[roadmap](docs/ROADMAP.md). Documentation in Russian: [docs/ru](docs/ru/query-rules.md).

## What it does

- Takes up to 5 result pages (50 results) per query, or all of them if there are fewer.
- Searches OpenAlex by default, or Google Scholar through SerpApi with your own key.
- If Scholar results fail or the SerpApi quota runs out, OpenAlex tops up the query.
- Scholar gives links rather than DOIs, so Alcedo looks for the DOI in the URL, Europe PMC and
  publisher meta tags, then by title in Crossref and OpenAlex.
- Saves after every query. `--resume` continues after an interruption and collects failed queries again.

## Install

Requires Python 3.10 or newer. From a clone of this repository:

```bash
pip install .
```

## Quick start

Create `queries.txt`, with `;` after each query. A sample is in [examples/queries.txt](examples/queries.txt).

```text
biomimetic nacre ("brick-and-mortar" OR "layered structure") composite fracture toughness;
gecko-inspired dry adhesive (micropillar OR "hierarchical microstructure") adhesion;
```

Run it:

```bash
alcedo
```

The results go to `alcedo_results.txt`:

```text
=== Query: gecko-inspired dry adhesive (micropillar OR "hierarchical microstructure") adhesion ===
Source: OpenAlex
https://doi.org/10.1039/c3sm52921e
https://doi.org/10.1098/rsif.2018.0681
```

The `Source:` line appears when OpenAlex supplied any of the results. Records with no DOI are
listed as `DOI not found: <title>`, and a query that failed has a `Query error` line. If DOI
lookups failed along the way, the final message says how many, because those records may still have a DOI.

Alcedo will not replace an existing results file: use `--resume` to continue it or `--overwrite` to start again.

To check the wording of a query quickly, look at its first 10 results:

```bash
alcedo --pages 1 -i test.txt -o test_results.txt --overwrite
```

Read [how to write queries](docs/query-syntax.md) before a large run. Some mistakes fail silently:
a lowercase `or`, for example, is treated as AND.

## Sources

| Source | What you need | Notes |
|---|---|---|
| OpenAlex (default) | Nothing, but a [free API key](https://openalex.org/settings/api) is recommended | The keyless daily budget is small and shared per IP |
| Google Scholar via [SerpApi](https://serpapi.com) | Your SerpApi key | Paid service with a free tier; each result page of 20 uses one search |
| Google Scholar directly | `pip install ".[scholar]"` and `--direct-scholar` | Experimental, see below |

Keep keys out of your shell history by setting them as environment variables:
`SERPAPI_KEY` and `OPENALEX_API_KEY`.

```bash
alcedo --resume          # continue after an interruption
alcedo --redo-openalex   # collect OpenAlex blocks again, for example after the SerpApi quota renews
alcedo --source openalex # OpenAlex only
alcedo --help            # all options
```

## Responsible use

- Direct Google Scholar access is off by default. Scholar's `robots.txt` disallows automated search, so
  `--direct-scholar` is experimental and you are responsible for following Google's terms. Alcedo waits
  between queries and stops asking when Scholar refuses. The `scholarly` library it relies on sends a
  random browser User-Agent and may try to open a browser for a captcha, and it has no setting to turn
  that off. Prefer SerpApi or OpenAlex.
- Apart from that route, requests identify themselves as `alcedo/<version>`. With `--mailto`, your
  address goes to Crossref, OpenAlex and Europe PMC, never to publisher sites.
- Alcedo collects metadata. It does not download papers and will not integrate shadow libraries.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
ruff check .
```

The tests use no network. Your own `queries*.txt` and results in the project root are ignored by Git.

## License

[MIT](LICENSE). See also the [third-party notices](THIRD_PARTY_NOTICES.md).
