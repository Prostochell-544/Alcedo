import time

import pytest


@pytest.fixture(autouse=True)
def no_real_semantic_scholar_calls(monkeypatch):
    """Runs through the command line must turn it off or fake it: the tests use no network."""
    from alcedo_lit.sources import semantic_scholar

    monkeypatch.setattr(semantic_scholar, "search_semantic_scholar",
                        lambda *_, **__: pytest.fail("a test reached the real Semantic Scholar"))


@pytest.fixture(autouse=True)
def no_real_pauses(monkeypatch):
    """Keep polite pauses out of the test run. Worker processes are not affected."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def no_keys_from_the_machine(monkeypatch, tmp_path_factory):
    """Keep the developer's own keys and saved settings out of the tests."""
    for name in ("SEARCHAPI_KEY", "SERPER_API_KEY", "SERPAPI_KEY", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALCEDO_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
