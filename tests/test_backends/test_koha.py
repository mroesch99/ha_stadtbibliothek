"""Tests for the generic Koha/LMSCloud backend.

The Remseck parser already reads a stock Koha OPAC; the generic type only has
to point it at another host. These tests pin that the configured host -- not
Remseck's -- is what every request goes to.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from custom_components.stadtbibliothek.backends import create_backend, get_backend_class
from custom_components.stadtbibliothek.backends.base import LibraryType
from custom_components.stadtbibliothek.backends.remseck import KohaBackend, RemseckBackend

FIXTURES = Path(__file__).parent / "fixtures"
NEUMARKT = "https://sb-neumarkt.lmscloud.net"


def test_koha_type_is_registered():
    assert get_backend_class(LibraryType.KOHA.value) is KohaBackend
    assert issubclass(KohaBackend, RemseckBackend)


async def test_koha_defaults_to_neumarkt():
    backend = await create_backend(LibraryType.KOHA.value)
    try:
        assert backend.base_url == NEUMARKT
    finally:
        await backend.close()


@respx.mock
async def test_koha_requests_go_to_the_configured_host():
    other = "https://example.lmscloud.net"
    html = (FIXTURES / "remseck_checkouts.html").read_text()
    login = respx.post(f"{other}/cgi-bin/koha/opac-user.pl").mock(return_value=httpx.Response(200, html=html))
    page = respx.get(f"{other}/cgi-bin/koha/opac-user.pl").mock(return_value=httpx.Response(200, html=html))

    backend = await create_backend(LibraryType.KOHA.value, base_url=other)
    try:
        await backend.login("card", "pin")
        loans = await backend.get_loans()
    finally:
        await backend.close()

    assert login.called and page.called
    assert loans


@respx.mock
async def test_rows_carry_the_earliest_renewal_date():
    """Koha prints 'Keine Verlängerung vor DD.MM.YYYY' on loans renewed too
    recently; the dashboard shows that date instead of a dead button."""
    from datetime import date

    html = (FIXTURES / "recorded" / "remseck_checkouts.html").read_text()
    respx.get(f"{NEUMARKT}/cgi-bin/koha/opac-user.pl").mock(return_value=httpx.Response(200, html=html))
    backend = await create_backend(LibraryType.KOHA.value)
    try:
        loans = await backend.get_loans()
    finally:
        await backend.close()
    assert {loan.renew_not_before for loan in loans} == {date(2026, 10, 19), None}
