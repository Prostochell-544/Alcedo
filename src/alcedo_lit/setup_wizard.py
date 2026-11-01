"""`alcedo setup`: explain the search options honestly and save the user's keys and choice."""

from __future__ import annotations

import getpass
import importlib.util
import sys

from .config import config_path, load_config, save_config
from .sources.scholar import INSTALL_HINT, WARNING

OVERVIEW = """\
Alcedo searches in this order:

1. Google Scholar through a search API, with your own key. This gave the best results in our small tests.
   You create the key, and you accept the provider's terms. Your queries are visible to the provider.
     SearchApi  https://www.searchapi.io   100 free requests to try it, then from $40 a month
     Serper     https://serper.dev         2500 free queries, then one-off packs from $50 (not tested yet)
     SerpApi    https://serpapi.com        250 free searches a month, asks for a phone number
   With SearchApi, a query with 50 results uses 3 requests. Prices and limits may have changed; check the site.

2. Without a working API, the free sources together. A source that fails is left out.
   Semantic Scholar. Matches strictly, so it finds less but is often precise. No key is needed, but then all
   users share one limit. A free key gives you your own: https://www.semanticscholar.org/product/api
   OpenAlex. Finds more, with its own ranking, and its first results were less on topic than through an API.
   A free key raises the daily budget: https://openalex.org/settings/api
   Direct Google Scholar search, if you turn it on. Free, no key, but unreliable: see the warning below.
"""

KEY_FIELDS = (("searchapi_key", "SearchApi key"), ("serper_key", "Serper key"), ("serpapi_key", "SerpApi key"),
              ("openalex_key", "OpenAlex key"), ("semantic_scholar_key", "Semantic Scholar key"))
MIN_KEY_LENGTH = 12
DIRECT_QUESTION = "Add direct Google Scholar search to the free sources when no API answers?"


def looks_like_key(value: str) -> bool:
    """Catch slips such as a stray word or a Ctrl+V that a console passed on as a control character."""
    return len(value) >= MIN_KEY_LENGTH and all(c.isprintable() and not c.isspace() for c in value)


def is_terminal() -> bool:
    """Tell whether a person can answer. On Windows the null device also counts as a tty, and getpass would hang."""
    if not sys.stdin.isatty():
        return False
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt

    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_ulong())))


def ask_yes_no(question: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{question} [{hint}] ").strip().lower()
    except EOFError:
        return default
    return answer.startswith("y") if answer else default


def ask_direct_choice(config: dict) -> bool:
    """Explain direct search, ask, and save the answer so the question is asked only once."""
    print(WARNING)
    choice = ask_yes_no(DIRECT_QUESTION)
    config["direct_scholar"] = choice
    save_config(config)
    print("Saved. Change this any time with: alcedo setup")
    return choice


def run_setup() -> int:
    if not is_terminal():
        print("alcedo setup needs an interactive terminal. You can also set the SEARCHAPI_KEY, SERPER_API_KEY, "
              "SERPAPI_KEY, OPENALEX_API_KEY and SEMANTIC_SCHOLAR_API_KEY environment variables.", file=sys.stderr)
        return 1

    print(OVERVIEW)
    config = load_config()
    print("Paste a key and press Enter. Press Enter alone to keep what is saved, or type - to remove it. "
          "What you type is not shown.")
    for field, label in KEY_FIELDS:
        state = "saved" if config.get(field) else "not set"
        value = getpass.getpass(f"{label} ({state}): ").strip()
        if not value:
            continue
        if not value.strip("-"):
            config.pop(field, None)
        elif looks_like_key(value):
            config[field] = value
        else:
            print(f"That does not look like a {label}, so it was not saved.")

    print()
    print(WARNING)
    config["direct_scholar"] = ask_yes_no(DIRECT_QUESTION, default=bool(config.get("direct_scholar")))
    save_config(config)

    print("\nSaved:")
    for field, label in KEY_FIELDS:
        key = config.get(field)
        print(f"  {label}: {f'set, ends in {key[-4:]}' if key else 'not set'}")
    print(f"  Direct Google Scholar: {'on' if config['direct_scholar'] else 'off'}")
    print(f"Keys are stored as plain text in {config_path()}. Do not share this file.")
    if config["direct_scholar"] and importlib.util.find_spec("scholarly") is None:
        print(f"Direct search needs one more package: {INSTALL_HINT}")
    return 0
