"""Config flow for Stadtbibliothek integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .backends import create_backend, get_backend_class
from .backends.base import AuthenticationError, LibraryType
from .const import CONF_ACCOUNT_NAME, CONF_BASE_URL, CONF_LIBRARY_TYPE, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

LIBRARY_TYPE_OPTIONS = {
    LibraryType.KOHA.value: "Koha / LMSCloud (eigene URL)",
    LibraryType.REMSECK.value: "Remseck (Koha)",
    LibraryType.STUTTGART.value: "Stuttgart (aDIS)",
}

#: Library types whose host comes from the config entry instead of the backend.
CONFIGURABLE_URL_TYPES = frozenset({LibraryType.KOHA.value})

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIBRARY_TYPE, default=LibraryType.KOHA.value): vol.In(LIBRARY_TYPE_OPTIONS),
        vol.Optional(CONF_BASE_URL): str,
        vol.Optional(CONF_ACCOUNT_NAME): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def normalize_base_url(raw: str) -> str:
    """Reduce whatever the user pasted to ``scheme://host``.

    People copy the address bar, which on a Koha OPAC usually ends in
    /cgi-bin/koha/opac-user.pl; the backends append that path themselves.
    """
    raw = raw.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if not parts.netloc:
        raise ValueError(f"Not a URL: {raw!r}")
    return f"{parts.scheme}://{parts.netloc}"


class StadtbibliothekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stadtbibliothek."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = dict(user_input)
            library_type = data[CONF_LIBRARY_TYPE]
            username = data[CONF_USERNAME].strip()
            password = data[CONF_PASSWORD]
            data[CONF_USERNAME] = username
            account_name = (data.pop(CONF_ACCOUNT_NAME, None) or "").strip()

            base_url: str | None = None
            raw_url = (data.pop(CONF_BASE_URL, None) or "").strip()
            if library_type in CONFIGURABLE_URL_TYPES:
                try:
                    base_url = normalize_base_url(raw_url or get_backend_class(library_type).BASE_URL)
                except ValueError:
                    errors[CONF_BASE_URL] = "invalid_url"
                else:
                    data[CONF_BASE_URL] = base_url

            if not errors:
                host = urlsplit(base_url or get_backend_class(library_type).BASE_URL).netloc
                await self.async_set_unique_id(f"{library_type}:{host}:{username.lower()}")
                self._abort_if_unique_id_configured()

                backend = await create_backend(library_type, base_url=base_url)
                try:
                    await backend.login(username, password)
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    _LOGGER.exception("Unexpected error during login")
                    errors["base"] = "cannot_connect"
                else:
                    label = host if library_type in CONFIGURABLE_URL_TYPES else LIBRARY_TYPE_OPTIONS[library_type]
                    title = account_name or f"{label} - {username}"
                    return self.async_create_entry(title=title, data=data)
                finally:
                    await backend.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
