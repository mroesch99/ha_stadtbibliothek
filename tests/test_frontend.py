"""The integration serves its own dashboard card.

HACS installs an integration's files but not a card's resource entry, so a
separately shipped card would need a manual Lovelace resource. Serving it
from the integration and announcing it via add_extra_js_url makes
`type: custom:stadtbibliothek-loans-card` work right after install.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

from custom_components.stadtbibliothek import CARD_URL, async_register_card


def _stub_frontend(monkeypatch):
    http = ModuleType("homeassistant.components.http")

    class StaticPathConfig:
        def __init__(self, url_path, path, cache_headers=True):
            self.url_path, self.path, self.cache_headers = url_path, path, cache_headers

    http.StaticPathConfig = StaticPathConfig
    frontend = ModuleType("homeassistant.components.frontend")
    frontend.add_extra_js_url = MagicMock()
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http)
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend)
    return frontend


async def test_card_is_served_and_announced_once(monkeypatch):
    frontend = _stub_frontend(monkeypatch)
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()

    await async_register_card(hass)
    await async_register_card(hass)  # a second account must not register again

    hass.http.async_register_static_paths.assert_awaited_once()
    (config,) = hass.http.async_register_static_paths.await_args.args[0]
    assert config.url_path == CARD_URL
    assert Path(config.path).is_file()
    frontend.add_extra_js_url.assert_called_once()
    announced = frontend.add_extra_js_url.call_args.args[1]
    assert announced.startswith(f"{CARD_URL}?v=")


async def test_card_is_registered_when_the_integration_loads(monkeypatch):
    """The card must not depend on an account's first poll succeeding.

    Registering it from async_setup_entry *after* the first refresh meant a
    single failed login (ConfigEntryNotReady) left every dashboard with
    "Custom element doesn't exist" -- exactly when the user most needs to
    see what is going on.
    """
    from custom_components.stadtbibliothek import async_setup

    _stub_frontend(monkeypatch)
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()

    assert await async_setup(hass, {}) is True
    hass.http.async_register_static_paths.assert_awaited_once()
