import requests


class FakeResponse:
    def __init__(self, status_code=200, data=None, url="", headers=None, body=b"", encoding="utf-8"):
        self.status_code = status_code
        self._data = data
        self.url = url
        self.headers = headers or {}
        self.encoding = encoding
        self._body = body

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, _size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def pubs(tag, numbers):
    """Records whose DOI is in the URL, so resolving them needs no network."""
    return [{"title": f"{tag} {i}", "pub_url": f"https://doi.org/10.1234/{tag}.{i}", "eprint_url": None}
            for i in numbers]


def blocks_of(path):
    """Parse a results file into {query: lines}."""
    blocks = {}
    for chunk in path.read_text(encoding="utf-8").strip().split("\n\n"):
        head, *body = chunk.splitlines()
        blocks[head.removeprefix("=== Query: ").removesuffix(" ===")] = body
    return blocks


def dois_in(lines):
    return [line for line in lines if line.startswith("https://doi.org/")]
