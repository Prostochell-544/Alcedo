import time

import pytest


@pytest.fixture(autouse=True)
def no_real_pauses(monkeypatch):
    """Keep polite pauses out of the test run. Worker processes are not affected."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def no_keys_from_environment(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
