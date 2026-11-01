# How to write queries

The same query can go to Google Scholar or to OpenAlex, so write it to work in both.
OpenAlex behaviour and work counts below were measured on the live API in October 2026.
Limits marked as rules of thumb are advice, not measurements.

## The query file

- Separate queries with `;`. One query per line, ending in `;`, is easiest to read.
- A line break inside a query becomes a space.
- `;` cannot appear inside a query, even in quotes: it splits the query in two.
- There are no comments: a line with `#` becomes part of a query.
- Repeated queries are dropped.
- Save the file as UTF-8.

## Syntax

| You want | Write | Example |
|---|---|---|
| All terms (AND) | a space | `nacre toughness` |
| An exact phrase | straight double quotes | `"brick-and-mortar"` |
| Any of several terms (OR) | `(A OR B)`, with OR in capitals, always in parentheses | `(micropillar OR "hierarchical microstructure")` |
| Exclude a term | a minus attached to the term, with a space before it | `-dental` |

Things that are easy to get wrong:

- Lowercase `or` is not an operator. `nacre or toughness` silently means AND:
  it found 4,696 works, while `nacre OR toughness` found 780,771.
- OR needs parentheses. `nacre toughness OR fracture` found 17,274 works, the same as `nacre` alone.
  `nacre (toughness OR fracture)` found 6,157.
- OpenAlex ignores a raw `-word`, so Alcedo turns it into `NOT word`. A hyphen inside a word is
  safe: `mussel-inspired`, `Ti-6Al-4V`.
- Use straight quotes. Guillemets such as `«…»` do not mark a phrase.
- Special characters in terms are fine: `Ti-6Al-4V`, `β-cyclodextrin`, `Ti/TiN`, `Li+`.

## What to avoid

| Avoid | Why |
|---|---|
| `*`, as in `nacre*` | OpenAlex answers with an error and the query gets no results. |
| `intitle:`, `author:`, `source:` | Only Scholar understands them. For OpenAlex the prefix is dropped and the word is searched everywhere. |
| `site:`, `filetype:`, years such as `2020-2024` | These are not filters here. Years just become extra search terms. |
| The word `review` to find reviews | It finds works that contain the word. |
| One or two general words, such as `biomaterials` | The 50 results would be close to random. |
| Two topics in one query | Make two queries. |
| Long OR lists | They blur the results. Rule of thumb: up to 4-5 terms. |
| Very long queries | Rule of thumb: up to 10-12 meaningful words. |
| Queries in languages other than English | The indexes are mostly English: "перламутр" found 175 works in OpenAlex, `nacre` found 17,274. |

## Building a good query

**Subject + key structure or mechanism in quotes + material class or method + property or task.**

```text
biomimetic nacre   ("brick-and-mortar" OR "layered structure")   composite   fracture toughness
```

- Rule of thumb: 2-4 blocks of meaning. Each block is a word, a phrase or an OR group.
- Put the most specific term in quotes: a phrase rules out papers where its words appear separately.
- Exclude known noise. OpenAlex also searches full texts, so general words match papers that mention them
  in passing. In one test, 46% of a polydopamine query was on target because dental papers crept in.
  `mussel-inspired polydopamine "wet adhesion" -dental -periodontal` helps.
- A narrow query is fine: Alcedo takes up to 50 works, and all of them if there are fewer.

## Examples

```text
biomimetic nacre ("brick-and-mortar" OR "layered structure") composite fracture toughness;
gecko-inspired dry adhesive (micropillar OR "hierarchical microstructure") adhesion;
bioinspired superhydrophobic surface "lotus effect" self-cleaning;
"selective laser melting" ("Ti-6Al-4V" OR "titanium alloy") porosity "process parameters";
"higher heating value" biomass correlation "ultimate analysis";
"genetic algorithm" ("inverse design" OR "molecular design") polymer;
```

## Order and limits

- Put the most important queries first, so they get through before a quota runs out.
- SearchApi: 100 free requests to try it at the time of writing. A query with 50 results uses 3, so that is about
  33 queries.
- Serper: 2,500 free queries at the time of writing. Alcedo has not yet been run with a real Serper key.
- Semantic Scholar: free, but without a key all users share one limit, so refusals (`429`) are possible.
- SerpApi free tier: 250 searches a month and 50 an hour at the time of writing. A query with 50 results
  uses 3 searches, so that is about 16 queries an hour and 80 a month. A query with up to 20 results uses 1.
- OpenAlex: at the time of writing, about $0.10 of API budget a day without a key and $1 with a free key,
  which covers about 1,000 searches. Over budget it answers `429`; Alcedo retries and then reports it.

## Testing a query

```bash
alcedo --source openalex --pages 1 -i test.txt -o test_results.txt --overwrite
```

If the results drift off topic, add a phrase in quotes or an exclusion, and try again.
