# Bibliothek (Koha / LMSCloud) – Home Assistant Integration

Generic Home Assistant connector for libraries running the **Koha** library system – including
every **LMSCloud**-hosted OPAC (`https://<library>.lmscloud.net`, e.g. Stadtbibliothek Neumarkt).
It logs into the library's web OPAC with your card number and password, reads your loans and
renews them on request. Several cards (e.g. the whole family) are shown together.

Koha's REST API does not expose a patron's own loans, so the integration reads the OPAC account
page like a browser would.

> Fork of [makefu/ha_stadtbibliothek](https://github.com/makefu/ha_stadtbibliothek), extended with
> a configurable Koha URL, a due-date calendar and a dashboard card with renew buttons. The
> original library types Remseck (Koha) and Stuttgart (aDIS/BMS) remain available.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/HA-2024.11%2B-blue)](https://www.home-assistant.io)

## Features

- **Any Koha / LMSCloud library** via a configurable OPAC URL
- Multiple library cards, each with an optional account name (e.g. one per family member)
- Loans sensor with full details per item: title, author, media type, due date, days remaining,
  renewable or not, renewals left, earliest renewal date, cover, ISBN
- Warning sensor (days until the earliest due date, overdue count) and fees sensor
- **Renew single loans** (`stadtbibliothek.renew_loan`), or all due loans at once (`renew_all`)
- **Calendar** per account with one all-day event per due date
- **Calendar subscription (iCal/ICS)** for any calendar app: one combined feed for all accounts, plus one per account
- **Dashboard card** with all accounts in one list and a renew button per item – served by the
  integration, no Lovelace resource needed
- German and English UI

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu -> Custom repositories
3. Add `https://github.com/mroesch99/ha_stadtbibliothek` as an Integration
4. Search for "Bibliothek (Koha / LMSCloud)", download, restart Home Assistant

### Manual

Copy `custom_components/stadtbibliothek/` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

1. Go to **Settings -> Integrations -> Add Integration**
2. Search for **Bibliothek (Koha / LMSCloud)**
3. Select library type **Koha / LMSCloud (eigene URL)** (Remseck and Stuttgart are kept as presets)
4. Enter your library's OPAC URL, e.g. `https://sb-neumarkt.lmscloud.net` (the default). A pasted
   address such as `…/cgi-bin/koha/opac-user.pl` is fine. Optionally add an account name such as `Michael`
5. Enter your library card number and password
6. Repeat to add multiple accounts (the same card cannot be added twice)

Entries with an account name get readable entity ids, e.g. `sensor.bibliothek_michael_loans`
and `calendar.bibliothek_michael_ruckgaben`. Without a name the card number is used.

The integration domain stays `stadtbibliothek` (as in the original) so services are called
`stadtbibliothek.*`.

### Which libraries work?

Any Koha OPAC whose login is a plain card number + password form at
`/cgi-bin/koha/opac-user.pl` – this is the default for LMSCloud-hosted libraries in Germany.
Libraries that log in via an external single sign-on (Shibboleth, CAS) are not supported.

## Sensors

Each configured account creates three sensors and a calendar:

### Loans (`sensor.*_loans`)

- **State:** number of active loans
- **Attributes:**
  - `account` -- the account name (entry title)
  - `config_entry_id` -- the entry to address in service calls
  - `loans` -- list of loan objects containing: `title`, `item_id`, `due_date`, `can_be_renewed`, `days_remaining`, `is_overdue`, `library` (e.g. "Koha"), plus optional fields like `author`, `checkout_date`, `media_type`, `library_branch`, `times_renewed`, `max_renewals`, `renewals_left`, `renew_not_before`, `call_number`, `barcode`, `publisher`, `isbn`, `cover_url`, `detail_url`

### Warning (`sensor.*_warning`)

- **State:** days until earliest due date (negative = overdue), `unknown` if no loans
- **Attributes:**
  - `overdue_count` -- number of overdue items
  - `items_due_soon` -- items due within 7 days
  - `earliest_due_date` -- ISO date of earliest due item
  - `refresh_required` -- bool, indicates a manual HA refresh is recommended after renewals

### Fees (`sensor.*_fees`)

- **State:** total outstanding fees in EUR
- **Attributes:**
  - `fee_items` -- list of individual fee entries


### Calendar (`calendar.*_ruckgaben`)

One all-day event per due date (loans due on the same day are grouped), with the titles in the
description and non-renewable ones marked. Overdue loans stay the calendar's current event.

## Calendar subscription (iCal)

Home Assistant cannot publish calendars to other apps, so the integration serves its own iCal feeds:

- **All accounts:** `https://<home-assistant>/api/stadtbibliothek/ics/<secret>/alle.ics`
- **One account:** `https://<home-assistant>/api/stadtbibliothek/ics/<secret>/<config_entry_id>.ics`

Open **Settings → Devices & services → Bibliothek → (account) → Configure** to see both links ready
to copy. Subscribe to them in Apple Calendar, Google Calendar ("From URL"), Outlook or Thunderbird.

- One all-day event per due date; in the combined feed loans of all accounts due the same day are
  one event ("Bibliothek: 3 Medien zurückgeben (Anna, Michael)") with the titles per account in the
  description and non-renewable ones marked
- Reminder at 18:00 the evening before (apps that ignore alarms in subscriptions skip it)
- Stable event ids: renewals move items to another day's event instead of creating duplicates
- Clients are asked to refresh hourly; Google Calendar refreshes subscriptions on its own schedule
  (often every few hours)

**Access:** the feed needs no Home Assistant login – calendar apps cannot log in – so the random
secret in the URL is the only protection. Anyone with the link sees due dates and titles. The
*Configure* dialog can create new links, which invalidates the old ones. Google Calendar fetches
from Google's servers, so Home Assistant must be reachable from the internet; behind a login proxy
(e.g. Authelia) allow `/api/stadtbibliothek/ics/` without login.

## Loans card with renew buttons

The integration serves its own card, so after installing and restarting it is available in the
card picker as **"Bibliothek – Ausleihen"**:

```yaml
type: custom:stadtbibliothek-loans-card
title: Bibliothek            # optional
entities:                    # optional, default: all library accounts
  - sensor.bibliothek_michael_loans
warn_days: 7                 # optional
urgent_days: 3               # optional
show_covers: false           # optional
```

It merges all accounts into one list sorted by due date, colour-coded (overdue / urgent / soon / ok),
with filter chips per account. Each loan Koha would renew gets a **Verlängern** button (with a
confirmation prompt) that calls `stadtbibliothek.renew_loan` for the right account; otherwise the
card says why not (`verlängerbar ab …`, `keine Verlängerung mehr`). The refresh button triggers
`force_update` on all accounts.

## Alternative dashboard example (read-only)

[`examples/books-lent-dashboard/`](examples/books-lent-dashboard/) (from the original project) ships a
ready-made Lovelace setup: a full-width panel dashboard with a small custom
card (`books-lent-card.js`) that turns the `loans` attributes of all accounts
into one color-coded table — cover images, due dates, remaining renewals,
latest-possible return date (`due + 30 days × renewals_left`) — sorted so the
books due soonest are on top, with per-library filter chips for collecting a
batch. See its README for the two-line install.

## Services

### `stadtbibliothek.renew_loan`

Renew a specific item by its `item_id` (Koha itemnumber, from the `loans` attribute).

| Field | Description |
|-------|-------------|
| `entity_id` | Any sensor of the account (e.g. `sensor.bibliothek_michael_loans`) |
| `item_id` | `item_id` of the loan to renew |
| `config_entry_id` | *(alternative to entity_id)* The config entry of the library account |

**Response** (via `response_variable`): `{item_id, title, author, due_date, media_type, times_renewed, max_renewals, renewals_left, success, error}`

### `stadtbibliothek.renew_all`

Renew all renewable items for a library account.

| Field | Description |
|-------|-------------|
| `entity_id` | Any sensor of the account |
| `days_remaining_threshold` | *(optional, default 14)* Only renew items due within this many days (0-90) |
| `config_entry_id` | *(alternative to entity_id)* The config entry of the library account |

**Response** (via `response_variable`): `{renewed, total_attempted, results}` where `results` is a list of `{item_id, title, author, due_date, media_type, times_renewed, max_renewals, renewals_left, success, error}`

### `stadtbibliothek.force_update`

Force an immediate data refresh.

| Field | Description |
|-------|-------------|
| `entity_id` | Any sensor of the account |
| `config_entry_id` | *(alternative to entity_id)* The config entry of the library account |

## CLI

Standalone command-line tools (from the original project) for the Remseck and Stuttgart presets.

### Installation

```sh
nix run .#stadtbibliothek-remseck -- --help
nix run .#stadtbibliothek-stuttgart -- --help
```

### Usage

```sh
# Show loan status (human-readable)
stadtbibliothek-remseck status --username 12345 --password mypin

# Show loan status (JSON)
stadtbibliothek-remseck status --username 12345 --password mypin --json

# Renew specific items
stadtbibliothek-remseck renew --username 12345 --password mypin --item-id ABC123 --item-id DEF456
```

Replace `remseck` with `stuttgart` for Stuttgart accounts.

## Automation Examples

All examples below can be pasted directly into the Home Assistant automation editor (YAML mode). Replace `sensor.bibliothek_michael_*` with your actual sensor entity IDs.

> **Identifying your account:** All service calls accept an `entity_id` field — pass any sensor of the account (loans, warning, or fees) to identify the account. You can also use `config_entry_id` directly if you prefer.

### Notify when items are due within 3 days

```yaml
alias: "Library due date warning"
trigger:
  - platform: numeric_state
    entity_id: sensor.bibliothek_michael_warning
    below: 4
action:
  - service: notify.mobile_app
    data:
      title: "Library books due soon"
      message: >
        {{ state_attr('sensor.bibliothek_michael_warning', 'items_due_soon') }}
        item(s) due within 7 days.
        Earliest due: {{ state_attr('sensor.bibliothek_michael_warning', 'earliest_due_date') }}
```

### Send loan list via notification

```yaml
alias: "Weekly library loan summary"
trigger:
  - platform: time
    at: "09:00:00"
condition:
  - condition: time
    weekday: [mon]
action:
  - service: notify.mobile_app
    data:
      title: "Library loans ({{ states('sensor.bibliothek_michael_loans') }})"
      message: >
        {% for loan in state_attr('sensor.bibliothek_michael_loans', 'loans') %}
        - {{ loan.title }}{% if loan.author %} ({{ loan.author }}){% endif %} — due {{ loan.due_date }}{% if loan.is_overdue %} ⚠ OVERDUE{% endif %}, {{ loan.renewals_left }} renewals left
        {% endfor %}
```

### Auto-renew all items when due within 3 days

```yaml
alias: "Auto-renew library books"
trigger:
  - platform: numeric_state
    entity_id: sensor.bibliothek_michael_warning
    below: 4
action:
  - service: stadtbibliothek.renew_all
    data:
      entity_id: sensor.bibliothek_michael_loans
      days_remaining_threshold: 3
    response_variable: renew_result
  - service: notify.mobile_app
    data:
      title: "{{ renew_result.renewed }}/{{ renew_result.total_attempted }} verlängert"
      message: >
        {% for r in renew_result.results %}
        {% if r.success %}✅{% else %}❌{% endif %} {{ r.title }}{% if r.author %} ({{ r.author }}){% endif %} — fällig {{ r.due_date }}{% if r.renewals_left is not none %}, {{ r.renewals_left }} Verlängerungen übrig{% endif %}{% if r.error %} — {{ r.error }}{% endif %}
        {% endfor %}
```

### Renew individual loans and notify results

instead of using renew_all you can also loop through all available loans manually

```yaml
alias: "Renew individual loans"
trigger:
  - platform: time
    at: "08:00:00"
action:
  - repeat:
      for_each: >
        {{ state_attr('sensor.bibliothek_michael_loans', 'loans')
           | selectattr('days_remaining', 'lt', 3)
           | selectattr('can_be_renewed')
           | list }}
      sequence:
        - service: stadtbibliothek.renew_loan
          data:
            entity_id: sensor.bibliothek_michael_loans
            item_id: "{{ repeat.item.item_id }}"
          response_variable: result
        - service: notify.mobile_app
          data:
            title: >
              {% if result.success %}✅ Verlängert{% else %}❌ Fehlgeschlagen{% endif %}
            message: >
              {{ result.title }}{% if result.author %} ({{ result.author }}){% endif %} — fällig {{ result.due_date }}{% if result.renewals_left is not none %}, {{ result.renewals_left }} Verlängerungen übrig{% endif %}{% if result.error %} — {{ result.error }}{% endif %}
```

### Warn about non-renewable loans due soon

Notify about loans that are due within 7 days but cannot be renewed anymore — these must be returned in person. This example combines the loans of two accounts.

```yaml
alias: "Non-renewable loans due soon"
trigger:
  - platform: time
    at: "09:00:00"
variables:
  all_loans: >
    {{ (state_attr('sensor.bibliothek_michael_loans', 'loans') | default([], true))
       + (state_attr('sensor.bibliothek_anna_loans', 'loans') | default([], true)) }}
  due_soon: >
    {{ all_loans
       | selectattr('days_remaining', 'lt', 7)
       | rejectattr('can_be_renewed')
       | list }}
condition:
  - condition: template
    value_template: "{{ due_soon | count > 0 }}"
action:
  - service: notify.mobile_app
    data:
      title: "Rückgabe nötig! ({{ due_soon | count }})"
      message: >
        Folgende Medien sind bald fällig und können nicht verlängert werden:
        {% for loan in due_soon %}
        - [{{ loan.library }}] {{ loan.title }} — fällig {{ loan.due_date }} ({{ loan.days_remaining }} Tage)
        {% endfor %}
```

## Development

```sh
nix develop                  # dev shell with all dependencies
pytest tests/ --ignore=tests/integration   # unit tests

# live integration tests (require credentials)
nix run .#integration-remseck -- /path/to/.secrets.yml
SECRETS_FILE=/path/to/.secrets.yml nix run .#integration-stuttgart

# NixOS VM test
nix build .#checks.x86_64-linux.vm-test
```

## License

MIT License. See [LICENSE](LICENSE) for details.

Based on [makefu/ha_stadtbibliothek](https://github.com/makefu/ha_stadtbibliothek). Originally inspired by [bibliotheek_be](https://github.com/myTselection/bibliotheek_be) by @myTselection.
