"""Pure helpers that find and clean DOIs in strings. Nothing here touches the network."""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from urllib.parse import quote, unquote

TITLE_MATCH_THRESHOLD = 0.9

# A string that is a DOI as a whole: what registries return, or a doi.org link.
EXACT_DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", re.IGNORECASE)
# A DOI inside other text. Angle brackets normally end it, but old SICI-style DOIs contain them.
DOI_RE = re.compile(r"10\.\d{4,9}/(?:\(sici\)[^\s\"']+|[^\s\"'<>]+)", re.IGNORECASE)
# Suffixes publishers append to a DOI in URLs: .../10.1002/xxx/full, ...pdf and so on.
DOI_TAIL_RE = re.compile(
    r"(?:/(?:full|abstract|abs|pdf|epdf|pdfdirect|pdfft|meta|html|fulltext|summary|"
    r"references|figures|tables|suppl|download|view|citedby))+$"
    r"|(?:\.(?:pdf|html?|full|short|long|extract|abstract))+$",
    re.IGNORECASE,
)
_BRACKETS = {")": "(", "]": "[", "}": "{"}

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+(?:\.[a-z]{2})?/\d{7}|\d{4}\.\d{4,5})", re.I)
NATURE_RE = re.compile(r"nature\.com/articles/([a-z0-9.\-]+?)(?:\.pdf)?(?:[/?#]|$)", re.I)
RSC_RE = re.compile(r"pubs\.rsc\.org/[a-z]+/content/article(?:html|landing|pdf)/\d{4}/[a-z]+/([a-z0-9]+)", re.I)
PMC_RE = re.compile(r"(?:/pmc/articles/|pmc\.ncbi\.nlm\.nih\.gov/articles/|europepmc\.org/articles?/)(PMC\d+)", re.I)
PUBMED_RE = re.compile(
    r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/|europepmc\.org/(?:abstract|article)/med/)(\d+)",
    re.I,
)

META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
META_ATTR_RE = re.compile(r"""([\w:.\-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
DOI_META_NAMES = {"citation_doi", "dc.identifier", "dc.identifier.doi", "dcterms.identifier",
                  "prism.doi", "bepress_citation_doi", "doi", "eprints.doi"}


def exact_doi(text: str | None) -> str | None:
    """Return the DOI if the whole string is one. Nothing is trimmed: a DOI may end in `.full` or `/meta`."""
    match = EXACT_DOI_RE.fullmatch((text or "").strip())
    return match.group(1) if match else None


def doi_url(doi: str) -> str:
    """Return a valid link for a DOI, encoding characters such as the angle brackets of SICI DOIs."""
    return "https://doi.org/" + encode_doi(doi)


def encode_doi(doi: str) -> str:
    return quote(doi, safe="/:;(),")


def clean_doi(raw: str) -> str | None:
    """Trim what publishers add around a DOI in a URL. Use it only for DOIs found inside URLs."""
    doi = re.split(r"[?#&]", raw.strip(), maxsplit=1)[0]
    while True:
        prev = doi
        doi = DOI_TAIL_RE.sub("", doi).rstrip(".,;:/")
        # An unmatched closing bracket is punctuation around the DOI, not part of it.
        while doi and doi[-1] in _BRACKETS and doi.count(doi[-1]) > doi.count(_BRACKETS[doi[-1]]):
            doi = doi[:-1]
        if doi == prev:
            break
    if doi.lower().startswith("10.1101/"):  # bioRxiv/medRxiv: drop the preprint version (v1, v2...)
        doi = re.sub(r"v\d+$", "", doi)
    return doi if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else None


def extract_doi(text: str | None) -> str | None:
    """Return the first DOI in a string such as a URL or a meta tag value."""
    if not text:
        return None
    text = html.unescape(unquote(unquote(text)))
    if doi := exact_doi(text):
        return doi
    for match in DOI_RE.finditer(text):
        if doi := clean_doi(match.group(0)):
            return doi
    return None


def doi_from_url_pattern(url: str) -> str | None:
    """Return a DOI that follows directly from an identifier in the URL."""
    if m := ARXIV_RE.search(url):
        return f"10.48550/arXiv.{m.group(1)}"
    if m := NATURE_RE.search(url):
        return f"10.1038/{m.group(1)}"
    if m := RSC_RE.search(url):
        return f"10.1039/{m.group(1).upper()}"
    return None


def doi_from_meta(page_html: str) -> str | None:
    for tag in META_TAG_RE.findall(page_html):
        attrs = {key.lower(): dq or sq for key, dq, sq in META_ATTR_RE.findall(tag)}
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        if name in DOI_META_NAMES and (doi := extract_doi(attrs.get("content"))):
            return doi
    return None


def europepmc_query(url: str) -> str | None:
    if m := PMC_RE.search(url):
        return f"PMCID:{m.group(1).upper()}"
    if m := PUBMED_RE.search(url):
        return f"EXT_ID:{m.group(1)} AND SRC:MED"
    return None


def normalize_title(title: str) -> str:
    title = re.sub(r"<[^>]+>", "", html.unescape(title))  # Crossref titles may contain <i>, <sub>
    return " ".join(re.sub(r"[^\w]+", " ", title.lower()).split())


def best_title_match(title: str, candidates) -> str | None:
    """Pick the DOI whose title is closest to `title`, if it clears the threshold.

    `candidates` is an iterable of (doi, title) pairs.
    """
    target = normalize_title(title)
    # A title cut off with an ellipsis can only be compared by its beginning.
    truncated = title.rstrip().endswith(("…", "..."))
    best_doi, best_score = None, 0.0
    for doi, candidate in candidates:
        candidate = normalize_title(candidate or "")
        if truncated:
            candidate = candidate[:len(target)]
        score = SequenceMatcher(None, target, candidate).ratio()
        if doi and score > best_score:
            best_doi, best_score = doi, score
    if best_doi and best_score >= TITLE_MATCH_THRESHOLD:
        return exact_doi(best_doi)
    return None
