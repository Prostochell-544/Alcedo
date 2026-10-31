"""A fake scholarly for tests. The real worker runs in a real process with a real pipe."""

import time

# query: (total results, index that raises an error, index that hangs)
SCENARIOS = {
    "few23": (23, None, None),
    "many200": (200, 50, None),  # asking for result 51 would raise, so this also proves page 6 is never fetched
    "exact10": (10, None, None),
    "zero": (0, None, None),
    "ban_on_page3": (200, 25, None),
    "hang_on_page2": (200, None, 15),
}


class FakeScholarly:
    def __init__(self, total, fail_at, hang_at):
        self.total, self.fail_at, self.hang_at = total, fail_at, hang_at

    def search_pubs(self, query):
        for i in range(self.total):
            if i == self.fail_at:
                raise RuntimeError("Cannot Fetch from Google Scholar.")
            if i == self.hang_at:
                time.sleep(3600)
            yield {"bib": {"title": f"{query} {i + 1}"}, "pub_url": f"https://doi.org/10.1234/{query}.{i + 1}"}


def fake_worker(query, max_pages, proxy, conn):
    from alcedo_lit.sources import scholar

    scholar.load_scholarly = lambda _proxy: FakeScholarly(*SCENARIOS[query])
    scholar.PAGE_DELAY = 0.01
    scholar._search_worker(query, max_pages, proxy, conn)
