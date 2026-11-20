"""Tests for the due-date calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from freezegun import freeze_time

from custom_components.stadtbibliothek.backends.base import AccountInfo, LibraryType, LoanItem
from custom_components.stadtbibliothek.calendar import DueDateCalendar


def _calendar(loans: list[LoanItem] | None, title: str = "Michael") -> DueDateCalendar:
    coordinator = MagicMock()
    coordinator.data = None if loans is None else AccountInfo(username="u", library_type=LibraryType.KOHA, loans=loans)
    entry = MagicMock()
    entry.entry_id = "e"
    entry.title = title
    return DueDateCalendar(coordinator, entry, "koha", "u")


def _loan(title: str, due: date, renewable: bool = True) -> LoanItem:
    return LoanItem(title=title, item_id=title, due_date=due, can_be_renewed=renewable)


@freeze_time("2026-11-20")
async def test_one_all_day_event_per_due_date():
    """Four accounts with a dozen loans each would bury the calendar in one
    event per medium; a stack returned together is one trip."""
    cal = _calendar(
        [
            _loan("A", date(2026, 11, 25)),
            _loan("B", date(2026, 11, 25), renewable=False),
            _loan("C", date(2026, 12, 2)),
        ]
    )
    events = await cal.async_get_events(MagicMock(), datetime(2026, 11, 1), datetime(2026, 12, 31))
    assert [(e.start, e.end) for e in events] == [
        (date(2026, 11, 25), date(2026, 11, 26)),
        (date(2026, 12, 2), date(2026, 12, 3)),
    ]
    assert events[0].summary == "Bibliothek Michael: 2 Medien fällig"
    assert "A" in events[0].description
    assert "B (nicht verlängerbar)" in events[0].description
    assert events[1].summary == "Bibliothek Michael: C fällig"


@freeze_time("2026-11-20")
async def test_events_outside_the_window_are_left_out():
    cal = _calendar([_loan("A", date(2026, 11, 25)), _loan("C", date(2027, 3, 1))])
    events = await cal.async_get_events(MagicMock(), datetime(2026, 11, 1), datetime(2026, 12, 31))
    assert [e.start for e in events] == [date(2026, 11, 25)]


@freeze_time("2026-11-20")
def test_next_event_is_the_earliest_upcoming_due_date():
    cal = _calendar([_loan("C", date(2026, 12, 2)), _loan("A", date(2026, 11, 25))])
    assert cal.event.start == date(2026, 11, 25)


@freeze_time("2026-11-20")
def test_overdue_loans_remain_the_next_event():
    """An overdue medium is the most urgent thing there is; it must not
    vanish from the calendar's 'next event' just because its day has passed."""
    cal = _calendar([_loan("Late", date(2026, 11, 10)), _loan("A", date(2026, 11, 25))])
    assert cal.event.start == date(2026, 11, 10)


def test_no_data_means_no_event():
    assert _calendar(None).event is None
    assert _calendar([]).event is None


async def test_window_end_is_exclusive():
    due = date(2026, 11, 25)
    cal = _calendar([_loan("A", due)])
    start = datetime.combine(due + timedelta(days=1), datetime.min.time())
    assert await cal.async_get_events(MagicMock(), start, start + timedelta(days=5)) == []
