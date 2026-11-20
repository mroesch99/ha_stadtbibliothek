"""Calendar platform: one all-day event per due date."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backends.base import LoanItem
from .const import CONF_LIBRARY_TYPE, CONF_USERNAME, DOMAIN
from .coordinator import StadtbibliothekCoordinator
from .sensor import device_info, slug


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: StadtbibliothekCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            DueDateCalendar(
                coordinator, config_entry, config_entry.data[CONF_LIBRARY_TYPE], config_entry.data[CONF_USERNAME]
            )
        ]
    )


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


class DueDateCalendar(CoordinatorEntity[StadtbibliothekCoordinator], CalendarEntity):
    """Due dates of one account.

    Loans due the same day are one event: they go back to the library
    together, and four accounts' worth of per-medium events would bury the
    calendar.
    """

    _attr_has_entity_name = True
    _attr_name = "Rückgaben"
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: StadtbibliothekCoordinator,
        config_entry: ConfigEntry,
        lib_type: str,
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self._account_name = config_entry.title
        self._attr_unique_id = f"{DOMAIN}_{slug(lib_type, username)}_calendar"
        self._attr_device_info = device_info(config_entry, lib_type, username)

    def _events(self) -> list[CalendarEvent]:
        account = self.coordinator.data
        if account is None:
            return []
        by_day: dict[date, list[LoanItem]] = defaultdict(list)
        for loan in account.loans:
            by_day[loan.due_date].append(loan)
        return [self._event(day, loans) for day, loans in sorted(by_day.items())]

    def _event(self, day: date, loans: list[LoanItem]) -> CalendarEvent:
        prefix = f"Bibliothek {self._account_name}"
        summary = f"{prefix}: {loans[0].title} fällig" if len(loans) == 1 else f"{prefix}: {len(loans)} Medien fällig"
        lines = [loan.title if loan.can_be_renewed else f"{loan.title} (nicht verlängerbar)" for loan in loans]
        return CalendarEvent(
            start=day,
            end=day + timedelta(days=1),
            summary=summary,
            description="\n".join(f"• {line}" for line in lines),
            uid=f"{self._attr_unique_id}_{day.isoformat()}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The earliest due date -- overdue ones included, they are the most urgent."""
        events = self._events()
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start, end = _as_date(start_date), _as_date(end_date)
        # All-day events: end is exclusive, so an event overlaps the window
        # when it starts before the window ends and ends after it starts.
        return [e for e in self._events() if e.start < end and e.end > start]
