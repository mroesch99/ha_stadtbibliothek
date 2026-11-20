"""Tests for Stadtbibliothek config flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import AbortFlow

from custom_components.stadtbibliothek.backends.base import AuthenticationError
from custom_components.stadtbibliothek.config_flow import (
    StadtbibliothekConfigFlow,
    StadtbibliothekOptionsFlow,
)
from custom_components.stadtbibliothek.const import (
    CONF_ACCOUNT_NAME,
    CONF_BASE_URL,
    CONF_LIBRARY_TYPE,
    CONF_PASSWORD,
    CONF_USERNAME,
)


def _user_input(library_type="remseck", username="testuser", password="testpass"):
    return {
        CONF_LIBRARY_TYPE: library_type,
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
    }


def _mock_create_backend(login_side_effect=None):
    """Return a create_backend replacement plus the backend it hands out."""
    backend = AsyncMock()
    if login_side_effect:
        backend.login = AsyncMock(side_effect=login_side_effect)
    else:
        backend.login = AsyncMock()
    return AsyncMock(return_value=backend), backend


@pytest.fixture
def flow():
    return StadtbibliothekConfigFlow()


async def test_show_form_on_first_step(flow):
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"


async def test_successful_login_remseck(flow):
    factory, inst = _mock_create_backend()
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(_user_input())
    assert result["type"] == "create_entry"
    assert result["title"] == "Remseck (Koha) - testuser"
    assert result["data"][CONF_LIBRARY_TYPE] == "remseck"
    inst.login.assert_awaited_once_with("testuser", "testpass")


async def test_successful_login_stuttgart(flow):
    factory, inst = _mock_create_backend()
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(_user_input(library_type="stuttgart"))
    assert result["type"] == "create_entry"
    assert result["title"] == "Stuttgart (aDIS) - testuser"


async def test_invalid_auth_shows_error(flow):
    factory, _ = _mock_create_backend(login_side_effect=AuthenticationError("bad creds"))
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(_user_input())
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


async def test_connection_error_shows_error(flow):
    factory, _ = _mock_create_backend(login_side_effect=ConnectionError("timeout"))
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(_user_input())
    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


async def test_backend_is_closed_after_validation(flow):
    factory, inst = _mock_create_backend()
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        await flow.async_step_user(_user_input())
    inst.close.assert_awaited_once()


async def test_backend_is_closed_after_failed_login(flow):
    factory, inst = _mock_create_backend(login_side_effect=AuthenticationError("bad"))
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        await flow.async_step_user(_user_input())
    inst.close.assert_awaited_once()


async def test_koha_with_url_and_account_name(flow):
    factory, inst = _mock_create_backend()
    data = {
        **_user_input(library_type="koha", username="A123"),
        CONF_BASE_URL: "sb-neumarkt.lmscloud.net/cgi-bin/koha/opac-user.pl",
        CONF_ACCOUNT_NAME: "Michael",
    }
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(data)
    assert result["type"] == "create_entry"
    assert result["title"] == "Michael"
    assert result["data"][CONF_BASE_URL] == "https://sb-neumarkt.lmscloud.net"
    factory.assert_awaited_once_with("koha", base_url="https://sb-neumarkt.lmscloud.net")
    assert flow.unique_id == "koha:sb-neumarkt.lmscloud.net:a123"


async def test_koha_without_url_uses_neumarkt(flow):
    factory, _ = _mock_create_backend()
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(_user_input(library_type="koha", username="A123"))
    assert result["data"][CONF_BASE_URL] == "https://sb-neumarkt.lmscloud.net"
    assert result["title"] == "sb-neumarkt.lmscloud.net - A123"


async def test_fixed_libraries_ignore_a_base_url(flow):
    factory, _ = _mock_create_backend()
    data = {**_user_input(), CONF_BASE_URL: "https://elsewhere.example"}
    with patch("custom_components.stadtbibliothek.config_flow.create_backend", factory):
        result = await flow.async_step_user(data)
    assert CONF_BASE_URL not in result["data"]
    factory.assert_awaited_once_with("remseck", base_url=None)


async def test_same_account_twice_aborts(flow):
    flow._configured_unique_ids = {"koha:sb-neumarkt.lmscloud.net:a123"}
    factory, inst = _mock_create_backend()
    with (
        patch("custom_components.stadtbibliothek.config_flow.create_backend", factory),
        pytest.raises(AbortFlow, match="already_configured"),
    ):
        await flow.async_step_user(_user_input(library_type="koha", username="A123"))
    inst.login.assert_not_awaited()


# --- options: calendar subscription links ------------------------------------


def _options_flow():
    hass = MagicMock()
    hass.data = {}
    hass._stub_url = "https://ha.example.net"
    flow = StadtbibliothekOptionsFlow()
    flow.hass = hass
    flow.config_entry = SimpleNamespace(entry_id="e1", title="Michael")
    return flow


def test_config_flow_offers_options():
    assert isinstance(StadtbibliothekConfigFlow.async_get_options_flow(MagicMock()), StadtbibliothekOptionsFlow)


async def test_options_show_the_combined_and_the_account_feed():
    flow = _options_flow()
    result = await flow.async_step_init()
    assert result["type"] == "form"
    links = result["description_placeholders"]
    token = flow.hass.data["stadtbibliothek_ics_token"]
    assert links["all_url"] == f"https://ha.example.net/api/stadtbibliothek/ics/{token}/alle.ics"
    assert links["account_url"] == f"https://ha.example.net/api/stadtbibliothek/ics/{token}/e1.ics"
    assert links["account"] == "Michael"


async def test_regenerating_shows_the_new_links_instead_of_closing():
    """After a new secret the old links are dead -- the user needs the new
    ones right away, so the form comes back instead of finishing."""
    flow = _options_flow()
    old = (await flow.async_step_init())["description_placeholders"]["all_url"]
    result = await flow.async_step_init({"regenerate_token": True})
    assert result["type"] == "form"
    assert result["description_placeholders"]["all_url"] != old


async def test_closing_without_regenerating_keeps_the_links():
    flow = _options_flow()
    old = (await flow.async_step_init())["description_placeholders"]["all_url"]
    result = await flow.async_step_init({"regenerate_token": False})
    assert result["type"] == "create_entry"
    assert (await flow.async_step_init())["description_placeholders"]["all_url"] == old
