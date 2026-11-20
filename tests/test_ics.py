"""Tests for the iCalendar subscription feed.

Calendar apps (Apple, Google, Thunderbird, Outlook) subscribe to the feed
and are strict about RFC 5545; these tests pin the parts they reject or
mis-read when wrong: CRLF line endings, 75-octet folding, text escaping,
all-day DATE values with an exclusive end, and UIDs that stay stable across
polls so an event is updated instead of duplicated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.stadtbibliothek.backends.base import AccountInfo, LibraryType, LoanItem
from custom_components.stadtbibliothek.const import DOMAIN
from custom_components.stadtbibliothek.ics import (
    IcsView,
    async_get_token,
    async_rotate_token,
    build_ics,
    feed_urls,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _account(*loans: LoanItem) -> AccountInfo:
    return AccountInfo(username="u", library_type=LibraryType.KOHA, loans=list(loans))


def _loan(title: str, due: date, renewable: bool = True, author: str | None = None) -> LoanItem:
    return LoanItem(title=title, item_id=title, due_date=due, can_be_renewed=renewable, author=author)


def _unfold(ics: str) -> list[str]:
    """Undo RFC 5545 line folding: CRLF followed by one space continues a line."""
    return ics.replace("\r\n ", "").split("\r\n")


def _events(ics: str) -> list[dict[str, str]]:
    events, current = [], None
    for line in _unfold(ics):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            events.append(current)
            current = None
        elif current is not None and ":" in line and not line.startswith(("BEGIN:", "END:", "ACTION", "TRIGGER")):
            key, _, value = line.partition(":")
            current.setdefault(key, value)
    return events


def test_combined_feed_has_one_event_per_due_date_across_accounts():
    """One trip to the library per day, whoever's card the media are on."""
    ics = build_ics(
        [
            ("Michael", _account(_loan("Der Hobbit", date(2026, 11, 25)), _loan("Dune", date(2026, 12, 2)))),
            ("Anna", _account(_loan("Gregs Tagebuch", date(2026, 11, 25), renewable=False))),
        ],
        calendar_name="Bibliothek",
        now=NOW,
    )
    events = _events(ics)
    assert [e["DTSTART;VALUE=DATE"] for e in events] == ["20261125", "20261202"]
    assert [e["DTEND;VALUE=DATE"] for e in events] == ["20261126", "20261203"]
    assert events[0]["SUMMARY"] == "Bibliothek: 2 Medien zurückgeben (Anna\\, Michael)"
    assert events[1]["SUMMARY"] == "Bibliothek: Dune zurückgeben (Michael)"
    description = events[0]["DESCRIPTION"]
    assert "Anna:\\n• Gregs Tagebuch (nicht verlängerbar)" in description
    assert "Michael:\\n• Der Hobbit" in description


def test_uids_are_stable_across_polls_and_distinct_per_feed():
    accounts = [("Michael", _account(_loan("A", date(2026, 11, 25))))]
    first = _events(build_ics(accounts, calendar_name="Bibliothek", now=NOW, feed_id="alle"))
    later = _events(
        build_ics(accounts, calendar_name="Bibliothek", now=datetime(2026, 11, 21, tzinfo=UTC), feed_id="alle")
    )
    other = _events(build_ics(accounts, calendar_name="Michael", now=NOW, feed_id="entry1"))
    assert first[0]["UID"] == later[0]["UID"]
    assert first[0]["UID"] != other[0]["UID"]


def test_calendar_envelope():
    ics = build_ics([], calendar_name="Bibliothek", now=NOW)
    lines = _unfold(ics)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert "X-WR-CALNAME:Bibliothek" in lines
    # Ask clients to re-fetch hourly; Apple and Outlook honour these.
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT1H" in lines
    assert "X-PUBLISHED-TTL:PT1H" in lines
    assert lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "BEGIN:VEVENT" not in lines


def test_crlf_and_folding():
    long_title = "Ein sehr langer Titel mit Umlauten äöü " * 6
    ics = build_ics([("Michael", _account(_loan(long_title, date(2026, 11, 25))))], calendar_name="Bibliothek", now=NOW)
    assert "\n" not in ics.replace("\r\n", "")
    for line in ics.split("\r\n"):
        assert len(line.encode()) <= 75
    # Folding never splits a multi-byte UTF-8 character.
    ics.encode("utf-8").decode("utf-8")
    assert long_title.strip().replace(",", "\\,") in "".join(_unfold(ics))


def test_text_is_escaped():
    ics = build_ics(
        [("Michael", _account(_loan("Krieg; und, Frieden\\Teil 1", date(2026, 11, 25))))],
        calendar_name="Bibliothek",
        now=NOW,
    )
    (event,) = _events(ics)
    assert event["SUMMARY"] == "Bibliothek: Krieg\\; und\\, Frieden\\\\Teil 1 zurückgeben (Michael)"


def test_reminder_the_evening_before():
    ics = build_ics([("Michael", _account(_loan("A", date(2026, 11, 25))))], calendar_name="Bibliothek", now=NOW)
    lines = _unfold(ics)
    assert "BEGIN:VALARM" in lines
    # All-day events start at 00:00; -PT6H is 18:00 the day before.
    assert "TRIGGER:-PT6H" in lines


def test_accounts_without_data_are_skipped():
    ics = build_ics([("Michael", None), ("Anna", _account())], calendar_name="Bibliothek", now=NOW)
    assert _events(ics) == []


# --- token and HTTP endpoint -------------------------------------------------


def _hass(entries: dict[str, tuple[str, AccountInfo | None]] | None = None):
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    titles = {}
    for entry_id, (title, account) in (entries or {}).items():
        hass.data[DOMAIN][entry_id] = SimpleNamespace(data=account)
        titles[entry_id] = SimpleNamespace(entry_id=entry_id, title=title)
    hass.config_entries.async_get_entry = titles.get
    return hass


async def test_token_is_created_once_and_persisted():
    hass = _hass()
    token = await async_get_token(hass)
    assert len(token) >= 32
    assert await async_get_token(hass) == token
    hass.data.pop("stadtbibliothek_ics_token")  # simulate a restart: only the store survives
    assert await async_get_token(hass) == token


async def test_rotating_the_token_invalidates_the_old_one():
    hass = _hass()
    old = await async_get_token(hass)
    new = await async_rotate_token(hass)
    assert new != old
    hass.data.pop("stadtbibliothek_ics_token")
    assert await async_get_token(hass) == new


async def test_view_serves_the_combined_feed():
    hass = _hass(
        {
            "e1": ("Michael", _account(_loan("A", date(2026, 11, 25)))),
            "e2": ("Anna", _account(_loan("B", date(2026, 11, 25)))),
        }
    )
    token = await async_get_token(hass)
    view = IcsView(hass)
    assert view.requires_auth is False
    response = await view.get(MagicMock(), token, "alle")
    assert response.status == 200
    assert response.content_type == "text/calendar"
    body = response.body.decode()
    assert "SUMMARY:Bibliothek: 2 Medien zurückgeben (Anna\\, Michael)" in "".join(_unfold(body))


async def test_view_serves_a_single_account():
    hass = _hass(
        {
            "e1": ("Michael", _account(_loan("A", date(2026, 11, 25)))),
            "e2": ("Anna", _account(_loan("B", date(2026, 11, 26)))),
        }
    )
    token = await async_get_token(hass)
    response = await IcsView(hass).get(MagicMock(), token, "e2")
    events = _events(response.body.decode())
    assert [e["DTSTART;VALUE=DATE"] for e in events] == ["20261126"]
    assert "X-WR-CALNAME:Bibliothek Anna" in _unfold(response.body.decode())


@pytest.mark.parametrize("feed", ["alle", "e1", "nope"])
async def test_wrong_token_is_a_plain_404(feed):
    """404, not 401: an unauthenticated endpoint should not confirm it exists."""
    hass = _hass({"e1": ("Michael", _account())})
    await async_get_token(hass)
    response = await IcsView(hass).get(MagicMock(), "wrong", feed)
    assert response.status == 404


async def test_unknown_account_is_a_404():
    hass = _hass({"e1": ("Michael", _account())})
    token = await async_get_token(hass)
    response = await IcsView(hass).get(MagicMock(), token, "nope")
    assert response.status == 404


async def test_feed_urls_prefer_the_external_address():
    hass = _hass({"e1": ("Michael", _account())})
    hass._stub_url = "https://ha.example.net"
    token = await async_get_token(hass)
    urls = feed_urls(hass, token, "e1")
    assert urls == {
        "all": f"https://ha.example.net/api/stadtbibliothek/ics/{token}/alle.ics",
        "account": f"https://ha.example.net/api/stadtbibliothek/ics/{token}/e1.ics",
    }


async def test_feed_urls_without_a_known_address_use_a_placeholder():
    hass = _hass()
    token = await async_get_token(hass)
    assert feed_urls(hass, token)["all"].startswith("https://<home-assistant>/api/stadtbibliothek/ics/")
