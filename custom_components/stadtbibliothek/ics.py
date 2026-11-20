"""iCalendar (RFC 5545) subscription feed of due dates.

Home Assistant has no way to publish a calendar to other apps, so the
integration serves its own feed: one combined calendar for all accounts
(``alle.ics``) and one per account (``<config_entry_id>.ics``), behind a
secret token in the URL because calendar apps cannot log in to Home
Assistant.
"""

from __future__ import annotations

import hmac
import secrets
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from .backends.base import AccountInfo, LoanItem

FEED_ALL = "alle"
URL_BASE = "/api/stadtbibliothek/ics"
_PRODID = "-//mroesch99//ha_stadtbibliothek//DE"
_STORAGE_KEY = "stadtbibliothek.ics"
_STORAGE_VERSION = 1
_TOKEN_KEY = "stadtbibliothek_ics_token"


# --- RFC 5545 text helpers ---------------------------------------------------


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold to lines of at most 75 octets, never splitting a UTF-8 character."""
    out: list[str] = []
    current, size, limit = "", 0, 75
    for char in line:
        width = len(char.encode())
        if size + width > limit:
            out.append(current)
            # Continuation lines start with one space, which counts.
            current, size, limit = " ", 1, 75
        current += char
        size += width
    out.append(current)
    return "\r\n".join(out)


def _date(value: date) -> str:
    return value.strftime("%Y%m%d")


# --- feed --------------------------------------------------------------------


def _loan_line(loan: LoanItem) -> str:
    return f"• {loan.title}" if loan.can_be_renewed else f"• {loan.title} (nicht verlängerbar)"


def build_ics(
    accounts: Iterable[tuple[str, AccountInfo | None]],
    *,
    calendar_name: str,
    now: datetime,
    feed_id: str = FEED_ALL,
) -> str:
    """Render the due dates of ``accounts`` (name, data) as a VCALENDAR.

    Loans due the same day are one all-day event, across accounts: they go
    back to the library together. The UID depends only on feed and date, so
    a re-fetch updates the event instead of adding a copy, and a renewed
    loan simply moves to another day's event.
    """
    by_day: dict[date, dict[str, list[LoanItem]]] = defaultdict(lambda: defaultdict(list))
    for name, account in accounts:
        if account is None:
            continue
        for loan in account.loans:
            by_day[loan.due_date][name].append(loan)

    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for day in sorted(by_day):
        per_account = by_day[day]
        names = sorted(per_account, key=str.casefold)
        loans = [loan for name in names for loan in per_account[name]]
        what = loans[0].title if len(loans) == 1 else f"{len(loans)} Medien"
        summary = f"Bibliothek: {what} zurückgeben ({', '.join(names)})"
        description = "\n\n".join(
            f"{name}:\n" + "\n".join(_loan_line(loan) for loan in per_account[name]) for name in names
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:{feed_id}-{_date(day)}@stadtbibliothek",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{_date(day)}",
            f"DTEND;VALUE=DATE:{_date(day + timedelta(days=1))}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            # All-day events start at 00:00: this is 18:00 the evening before.
            "TRIGGER:-PT6H",
            f"DESCRIPTION:{_escape(summary)}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


# --- Home Assistant glue -----------------------------------------------------
# Imported lazily so the feed builder above stays usable without Home Assistant.


async def async_get_token(hass) -> str:
    """The secret in the feed URLs; created on first use, kept across restarts."""
    if token := hass.data.get(_TOKEN_KEY):
        return token
    from homeassistant.helpers.storage import Store

    store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
    data = await store.async_load() or {}
    token = data.get("token")
    if not token:
        token = secrets.token_urlsafe(32)
        await store.async_save({"token": token})
    hass.data[_TOKEN_KEY] = token
    return token


async def async_rotate_token(hass) -> str:
    """Replace the secret: every previously shared feed URL stops working."""
    from homeassistant.helpers.storage import Store

    token = secrets.token_urlsafe(32)
    await Store(hass, _STORAGE_VERSION, _STORAGE_KEY).async_save({"token": token})
    hass.data[_TOKEN_KEY] = token
    return token


def feed_urls(hass, token: str, entry_id: str | None = None) -> dict[str, str]:
    """Absolute feed URLs, preferring the address reachable from outside."""
    from homeassistant.helpers.network import NoURLAvailableError, get_url

    try:
        base = get_url(hass, prefer_external=True, allow_internal=True)
    except NoURLAvailableError:
        base = "https://<home-assistant>"
    urls = {"all": f"{base}{URL_BASE}/{token}/{FEED_ALL}.ics"}
    if entry_id:
        urls["account"] = f"{base}{URL_BASE}/{token}/{entry_id}.ics"
    return urls


try:
    from homeassistant.components.http import HomeAssistantView as _ViewBase
except ImportError:  # feed builder used without Home Assistant
    _ViewBase = object


class IcsView(_ViewBase):
    """Serves the feeds without Home Assistant login; the URL token is the key."""

    url = URL_BASE + "/{token}/{feed}.ics"
    name = "api:stadtbibliothek:ics"
    requires_auth = False

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, token: str, feed: str):
        from aiohttp import web

        from .const import DOMAIN

        expected = await async_get_token(self.hass)
        coordinators = self.hass.data.get(DOMAIN, {})
        # 404 rather than 401 for a wrong token: don't confirm the endpoint.
        if not hmac.compare_digest(token.encode(), expected.encode()):
            return web.Response(status=404)

        if feed == FEED_ALL:
            entry_ids = list(coordinators)
            calendar_name = "Bibliothek"
        elif feed in coordinators:
            entry_ids = [feed]
            calendar_name = None
        else:
            return web.Response(status=404)

        accounts = []
        for entry_id in entry_ids:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            name = entry.title if entry else entry_id
            accounts.append((name, coordinators[entry_id].data))
        if calendar_name is None:
            calendar_name = f"Bibliothek {accounts[0][0]}"

        body = build_ics(accounts, calendar_name=calendar_name, now=datetime.now(UTC), feed_id=feed)
        return web.Response(
            body=body.encode(),
            content_type="text/calendar",
            charset="utf-8",
            headers={"Cache-Control": "no-cache", "Content-Disposition": f'inline; filename="bibliothek-{feed}.ics"'},
        )
