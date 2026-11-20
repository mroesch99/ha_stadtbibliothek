"""Shared test fixtures for HA integration tests."""

from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out homeassistant modules so we can import our integration code
# without a full HA installation.
# ---------------------------------------------------------------------------


def _make_module(name: str, **attrs) -> ModuleType:
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# --- homeassistant.const ---
class Platform:
    SENSOR = "sensor"
    CALENDAR = "calendar"


ha_const = _make_module(
    "homeassistant.const",
    Platform=Platform,
)

# --- homeassistant.core ---
HomeAssistant = MagicMock
ServiceCall = MagicMock
ServiceResponse = dict | None


class SupportsResponse:
    NONE = "none"
    ONLY = "only"
    OPTIONAL = "optional"


ha_core = _make_module(
    "homeassistant.core",
    HomeAssistant=HomeAssistant,
    ServiceCall=ServiceCall,
    ServiceResponse=ServiceResponse,
    SupportsResponse=SupportsResponse,
    callback=lambda func: func,
)

# --- homeassistant.config_entries ---


class ConfigFlowResult(dict):
    pass


class _ConfigFlowMeta(type):
    """Metaclass that accepts domain= keyword."""

    DOMAIN: str | None

    def __new__(mcs, name, bases, namespace, domain=None, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        if domain is not None:
            cls.DOMAIN = domain
        return cls


class AbortFlow(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_make_module("homeassistant.data_entry_flow", AbortFlow=AbortFlow)


class ConfigFlow(metaclass=_ConfigFlowMeta):
    DOMAIN: str | None = None
    hass = MagicMock()
    unique_id: str | None = None
    #: Unique ids of entries that already exist; tests set this to simulate them.
    _configured_unique_ids: set[str] = frozenset()

    async def async_set_unique_id(self, unique_id=None):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if self.unique_id in self._configured_unique_ids:
            raise AbortFlow("already_configured")

    def async_show_form(self, *, step_id, data_schema, errors=None):
        return ConfigFlowResult(type="form", step_id=step_id, data_schema=data_schema, errors=errors or {})

    def async_create_entry(self, *, title, data):
        return ConfigFlowResult(type="create_entry", title=title, data=data)


class OptionsFlow:
    """Home Assistant sets hass and config_entry on the flow before step init."""

    hass = None
    config_entry = None

    def async_show_form(self, *, step_id, data_schema, errors=None, description_placeholders=None):
        return ConfigFlowResult(
            type="form",
            step_id=step_id,
            data_schema=data_schema,
            errors=errors or {},
            description_placeholders=description_placeholders or {},
        )

    def async_create_entry(self, *, title="", data):
        return ConfigFlowResult(type="create_entry", title=title, data=data)


class ConfigEntry:
    def __init__(self, entry_id="test_entry_id", data=None, title="Test account"):
        self.entry_id = entry_id
        self.data = data or {}
        self.title = title


ha_config_entries = _make_module(
    "homeassistant.config_entries",
    ConfigEntry=ConfigEntry,
    ConfigFlow=ConfigFlow,
    ConfigFlowResult=ConfigFlowResult,
    OptionsFlow=OptionsFlow,
)

# --- homeassistant.helpers ---
_make_module("homeassistant.helpers")
_make_module("homeassistant.helpers.typing", ConfigType=dict)


def _get_async_client(hass):
    return MagicMock()


_make_module("homeassistant.helpers.httpx_client", get_async_client=_get_async_client)

_make_module(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=lambda domain: None,
)

# --- homeassistant.helpers.entity ---


class DeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)


_make_module("homeassistant.helpers.entity", DeviceInfo=DeviceInfo)

# --- homeassistant.helpers.device_registry ---


class DeviceEntryType:
    SERVICE = "service"


_make_module("homeassistant.helpers.device_registry", DeviceEntryType=DeviceEntryType)

# --- homeassistant.helpers.entity_registry ---


class _EntityRegistryEntry:
    def __init__(self, config_entry_id=None):
        self.config_entry_id = config_entry_id


class _EntityRegistry:
    def __init__(self):
        self._entries: dict[str, _EntityRegistryEntry] = {}

    def async_get(self, entity_id: str) -> _EntityRegistryEntry | None:
        return self._entries.get(entity_id)

    def add(self, entity_id: str, config_entry_id: str | None = None) -> None:
        self._entries[entity_id] = _EntityRegistryEntry(config_entry_id)


_entity_registry_instance = _EntityRegistry()


def _er_async_get(hass):
    return _entity_registry_instance


_make_module(
    "homeassistant.helpers.entity_registry",
    async_get=_er_async_get,
)

# --- homeassistant.helpers.entity_platform ---
_make_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=list)

# --- homeassistant.helpers.update_coordinator ---


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval, config_entry=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.config_entry = config_entry
        self.data = None

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def async_request_refresh(self):
        self.data = await self._async_update_data()

    async def _async_update_data(self):
        raise NotImplementedError


class CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


_make_module(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=DataUpdateCoordinator,
    UpdateFailed=UpdateFailed,
    CoordinatorEntity=CoordinatorEntity,
)

# --- homeassistant.components.sensor ---


class SensorEntity:
    pass


class SensorDeviceClass:
    MONETARY = "monetary"


_make_module(
    "homeassistant.components.sensor",
    SensorEntity=SensorEntity,
    SensorDeviceClass=SensorDeviceClass,
)

# --- homeassistant.components.calendar ---


class CalendarEntity:
    pass


class CalendarEvent:
    def __init__(self, *, start, end, summary, description=None, location=None, uid=None):
        self.start = start
        self.end = end
        self.summary = summary
        self.description = description
        self.location = location
        self.uid = uid


_make_module("homeassistant.components.calendar", CalendarEntity=CalendarEntity, CalendarEvent=CalendarEvent)

# --- homeassistant.components.http / helpers.storage / helpers.network ---


class HomeAssistantView:
    url: str = ""
    name: str = ""
    requires_auth: bool = True


class StaticPathConfig:
    def __init__(self, url_path, path, cache_headers=True):
        self.url_path, self.path, self.cache_headers = url_path, path, cache_headers


_make_module("homeassistant.components.http", HomeAssistantView=HomeAssistantView, StaticPathConfig=StaticPathConfig)


class Store:
    """In-memory stand-in for homeassistant.helpers.storage.Store, kept on hass."""

    def __init__(self, hass, version, key, **kwargs):
        self._hass, self._key = hass, key
        if not isinstance(getattr(hass, "_stub_store", None), dict):
            hass._stub_store = {}

    async def async_load(self):
        return self._hass._stub_store.get(self._key)

    async def async_save(self, data):
        self._hass._stub_store[self._key] = data


_make_module("homeassistant.helpers.storage", Store=Store)


class NoURLAvailableError(Exception):
    pass


def _get_url(hass, **kwargs):
    url = getattr(hass, "_stub_url", None)
    if not isinstance(url, str):
        raise NoURLAvailableError
    return url


_make_module("homeassistant.helpers.network", get_url=_get_url, NoURLAvailableError=NoURLAvailableError)

# --- homeassistant.exceptions ---
_make_module("homeassistant.exceptions", HomeAssistantError=Exception)

# ---------------------------------------------------------------------------
# Now we can safely import our integration modules.
# ---------------------------------------------------------------------------

from custom_components.stadtbibliothek.backends.base import (  # noqa: E402
    AccountInfo,
    FeeItem,
    LibraryType,
    LoanItem,
)


@pytest.fixture(autouse=True)
def _no_pacing(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests assert on request sequences, not on waiting.

    Each backend overrides REQUEST_MIN_INTERVAL on itself, so every class
    must be patched, not just the base. A test marked keep_pacing opts out to
    assert on the production interval.
    """
    if request.node.get_closest_marker("keep_pacing"):
        return
    from custom_components.stadtbibliothek.backends import BACKENDS

    for backend_cls in BACKENDS.values():
        monkeypatch.setattr(backend_cls, "REQUEST_MIN_INTERVAL", 0.0)


@pytest.fixture
def sample_loans() -> list[LoanItem]:
    return [
        LoanItem(
            title="Python Crash Course",
            item_id="12345",
            due_date=date.today(),
            author="Eric Matthes",
            media_type="Book",
            can_be_renewed=True,
            times_renewed=1,
            max_renewals=3,
        ),
        LoanItem(
            title="Clean Code",
            item_id="67890",
            due_date=date(2020, 1, 1),  # overdue
            author="Robert C. Martin",
            media_type="Book",
            can_be_renewed=False,
            times_renewed=3,
            max_renewals=3,
        ),
    ]


@pytest.fixture
def sample_fees() -> list[FeeItem]:
    return [
        FeeItem(description="Late fee", amount=1.50, date=date(2024, 1, 15)),
        FeeItem(description="Lost item", amount=10.00, date=date(2024, 2, 1)),
    ]


@pytest.fixture
def sample_account(sample_loans, sample_fees) -> AccountInfo:
    return AccountInfo(
        username="testuser",
        library_type=LibraryType.REMSECK,
        loans=sample_loans,
        fees=sample_fees,
        total_fees=11.50,
    )


@pytest.fixture
def mock_backend(sample_loans, sample_fees):
    backend = AsyncMock()
    backend.login = AsyncMock()
    backend.get_loans = AsyncMock(return_value=sample_loans)
    backend.get_fees = AsyncMock(return_value=sample_fees)
    backend.renew_loan = AsyncMock(return_value=True)
    backend.renew_all = AsyncMock(return_value=2)
    backend.close = AsyncMock()
    return backend
