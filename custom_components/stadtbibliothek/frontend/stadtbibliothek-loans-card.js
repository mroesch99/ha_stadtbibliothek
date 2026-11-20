/*
 * Stadtbibliothek – Ausleihen-Karte
 *
 * Lists the loans of every configured library account in one table, sorted
 * by due date, with a renew button per loan. Served by the integration
 * itself (no Lovelace resource needed):
 *
 *   type: custom:stadtbibliothek-loans-card
 *   title: Bibliothek          # optional
 *   entities:                  # optional, default: all accounts
 *     - sensor.bibliothek_michael_loans
 *   warn_days: 7               # optional, yellow from this many days
 *   urgent_days: 3             # optional, orange from this many days
 *   show_covers: false         # optional
 */

const DOMAIN = "stadtbibliothek";
const CARD_VERSION = "1.5.2";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const parseDate = (iso) => {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};

const fmtDate = (iso, withYear = true) => {
  const d = parseDate(iso);
  if (!d) return "–";
  return d.toLocaleDateString("de-DE", withYear ? { day: "2-digit", month: "2-digit", year: "numeric" } : { day: "2-digit", month: "2-digit" });
};

const today = () => {
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate());
};

// days_remaining in the attributes is as of the last poll; recompute so the
// card stays right across midnight.
const daysLeft = (loan) => {
  const due = parseDate(loan.due_date);
  return due ? Math.round((due - today()) / 86400000) : loan.days_remaining;
};

const dueText = (days) => {
  if (days < -1) return `seit ${-days} Tagen überfällig`;
  if (days === -1) return "seit gestern überfällig";
  if (days === 0) return "heute fällig";
  if (days === 1) return "morgen fällig";
  return `in ${days} Tagen`;
};

const MEDIA_ICONS = [
  [/blu-?ray|dvd|film|video/i, "mdi:filmstrip"],
  [/tonie/i, "mdi:account-music"],
  [/cd|hörbuch|audio|musik/i, "mdi:disc"],
  [/spiel|game|konsole/i, "mdi:gamepad-variant"],
  [/zeitschrift|magazin|heft/i, "mdi:newspaper-variant"],
  [/comic|manga/i, "mdi:book-open-page-variant"],
  [/buch|book|roman|sachbuch/i, "mdi:book-open-variant"],
];
const mediaIcon = (type) => (MEDIA_ICONS.find(([re]) => re.test(type || "")) || [null, "mdi:bookshelf"])[1];

class StadtbibliothekLoansCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Bibliothek" };
  }

  static getConfigElement() {
    return undefined;
  }

  setConfig(config) {
    this._config = {
      title: "Bibliothek",
      warn_days: 7,
      urgent_days: 3,
      show_covers: false,
      ...config,
    };
    this._filter = null; // account name, or null for all
    this._pending = {}; // key -> "busy" | {ok, text}
    this._signature = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const signature = JSON.stringify(this._sources().map((s) => [s.entity_id, s.last_updated]));
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return 2 + Math.min(this._loans().length, 10);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _sources() {
    if (!this._hass) return [];
    const wanted = this._config.entities;
    return Object.values(this._hass.states).filter((s) => {
      if (wanted && !wanted.includes(s.entity_id)) return false;
      const a = s.attributes || {};
      if (!Array.isArray(a.loans) || !a.config_entry_id) return false;
      const reg = this._hass.entities && this._hass.entities[s.entity_id];
      return !reg || !reg.platform || reg.platform === DOMAIN;
    });
  }

  _loans() {
    const loans = [];
    for (const s of this._sources()) {
      const a = s.attributes;
      for (const loan of a.loans) {
        loans.push({ ...loan, _account: a.account || s.entity_id, _entry: a.config_entry_id, _days: daysLeft(loan) });
      }
    }
    return loans.sort((x, y) => x._days - y._days || String(x.title).localeCompare(String(y.title), "de"));
  }

  _accounts() {
    return this._sources()
      .map((s) => ({ name: s.attributes.account || s.entity_id, entity: s.entity_id, state: s.state, entry: s.attributes.config_entry_id }))
      .sort((a, b) => a.name.localeCompare(b.name, "de"));
  }

  _severity(days) {
    if (days < 0) return "overdue";
    if (days <= this._config.urgent_days) return "urgent";
    if (days <= this._config.warn_days) return "warn";
    return "ok";
  }

  _renewCell(loan) {
    const key = `${loan._entry}:${loan.item_id}`;
    const pending = this._pending[key];
    if (pending === "busy") return `<span class="muted">wird verlängert …</span>`;
    if (pending && pending.ok) return `<span class="good">✓ ${esc(pending.text)}</span>`;
    const error = pending && !pending.ok ? `<div class="bad">${esc(pending.text)}</div>` : "";

    if (loan.can_be_renewed) {
      const left = loan.renewals_left != null ? `<span class="muted small">noch ${loan.renewals_left}×</span>` : "";
      return `${error}<button class="renew" data-key="${esc(key)}">Verlängern</button>${left}`;
    }
    let reason = "nicht verlängerbar";
    if (loan.renew_not_before && parseDate(loan.renew_not_before) > today()) {
      reason = `verlängerbar ab ${fmtDate(loan.renew_not_before, false)}`;
    } else if (loan.renewals_left === 0) {
      reason = "keine Verlängerung mehr";
    }
    return `${error}<span class="muted">${reason}</span>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const accounts = this._accounts();
    const all = this._loans();
    const loans = this._filter ? all.filter((l) => l._account === this._filter) : all;
    const multi = accounts.length > 1;
    const overdue = all.filter((l) => l._days < 0).length;
    const next = all.find((l) => l._days >= 0);
    const unavailable = accounts.filter((a) => a.state === "unavailable" || a.state === "unknown");

    const summary = [
      `${all.length} ${all.length === 1 ? "Medium" : "Medien"}`,
      overdue ? `<span class="bad">${overdue} überfällig</span>` : null,
      next ? `nächste Rückgabe ${fmtDate(next.due_date, false)}` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const chips = multi
      ? `<div class="chips">
          <button class="chip ${this._filter ? "" : "active"}" data-filter="">Alle</button>
          ${accounts
            .map((a) => {
              const n = all.filter((l) => l._account === a.name).length;
              return `<button class="chip ${this._filter === a.name ? "active" : ""}" data-filter="${esc(a.name)}">${esc(a.name)} <span class="count">${n}</span></button>`;
            })
            .join("")}
        </div>`
      : "";

    const rows = loans
      .map((loan) => {
        const sev = this._severity(loan._days);
        const cover = this._config.show_covers && loan.cover_url ? `<img class="cover" src="${esc(loan.cover_url)}" alt="" loading="lazy">` : `<ha-icon class="type" icon="${mediaIcon(loan.media_type)}"></ha-icon>`;
        const sub = [loan.author, loan.media_type].filter(Boolean).map(esc).join(" · ");
        return `<div class="row ${sev}">
          <div class="bar"></div>
          ${cover}
          <div class="main">
            <div class="title" title="${esc(loan.title)}">${loan.detail_url ? `<a href="${esc(loan.detail_url)}" target="_blank" rel="noopener">${esc(loan.title)}</a>` : esc(loan.title)}</div>
            <div class="sub">${multi ? `<span class="account">${esc(loan._account)}</span>` : ""}${sub}</div>
          </div>
          <div class="due">
            <div class="date">${fmtDate(loan.due_date)}</div>
            <div class="rel">${dueText(loan._days)}</div>
          </div>
          <div class="action">${this._renewCell(loan)}</div>
        </div>`;
      })
      .join("");

    const empty = this._hass && !accounts.length
      ? `<div class="empty">Keine Bibliothekskonten gefunden. Integration „Stadtbibliothek“ einrichten.</div>`
      : !loans.length
        ? `<div class="empty">Keine Ausleihen 🎉</div>`
        : "";

    const warn = unavailable.length
      ? `<div class="banner">Nicht aktuell: ${unavailable.map((a) => esc(a.name)).join(", ")} (Abruf fehlgeschlagen)</div>`
      : "";

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div>
            <div class="name">${esc(this._config.title)}</div>
            <div class="summary">${summary}</div>
          </div>
          <button class="icon refresh" title="Jetzt aktualisieren"><ha-icon icon="mdi:refresh"></ha-icon></button>
        </div>
        ${chips}
        ${warn}
        <div class="list">${rows}${empty}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-filter]").forEach((el) =>
      el.addEventListener("click", () => {
        this._filter = el.dataset.filter || null;
        this._render();
      }),
    );
    this.shadowRoot.querySelectorAll("button.renew").forEach((el) => el.addEventListener("click", () => this._renew(el.dataset.key)));
    const refresh = this.shadowRoot.querySelector(".refresh");
    if (refresh) refresh.addEventListener("click", () => this._refresh(refresh));
  }

  async _renew(key) {
    const loan = this._loans().find((l) => `${l._entry}:${l.item_id}` === key);
    if (!loan || !this._hass) return;
    const who = this._accounts().length > 1 ? ` (${loan._account})` : "";
    if (!window.confirm(`„${loan.title}“${who} verlängern?`)) return;

    this._pending[key] = "busy";
    this._render();
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "call_service",
        domain: DOMAIN,
        service: "renew_loan",
        service_data: { config_entry_id: loan._entry, item_id: String(loan.item_id) },
        return_response: true,
      });
      const response = (result && result.response) || {};
      this._pending[key] = response.success
        ? { ok: true, text: "verlängert" }
        : { ok: false, text: response.error ? "Verlängerung abgelehnt" : "Verlängerung fehlgeschlagen" };
    } catch (err) {
      this._pending[key] = { ok: false, text: (err && err.message) || "Fehler beim Verlängern" };
    }
    this._render();
  }

  async _refresh(button) {
    if (!this._hass) return;
    button.classList.add("spin");
    this._pending = {};
    try {
      await Promise.all(
        this._accounts().map((a) => this._hass.callService(DOMAIN, "force_update", { config_entry_id: a.entry })),
      );
    } finally {
      button.classList.remove("spin");
    }
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  button { font: inherit; cursor: pointer; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; padding: 16px 16px 8px; }
  .name { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color); }
  .summary { font-size: 0.9rem; color: var(--secondary-text-color); margin-top: 2px; }
  button.icon { background: none; border: none; color: var(--secondary-text-color); padding: 6px; border-radius: 50%; line-height: 0; }
  button.icon:hover { background: var(--secondary-background-color); }
  .spin ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 8px; }
  .chip { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); border-radius: 16px; padding: 4px 12px; font-size: 0.85rem; }
  .chip.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .chip .count { opacity: 0.7; margin-left: 2px; }
  .banner { margin: 0 16px 8px; padding: 6px 10px; border-radius: 6px; font-size: 0.85rem; background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.15); color: var(--primary-text-color); }
  .list { padding-bottom: 8px; }
  .row { display: grid; grid-template-columns: 4px 36px minmax(0, 1fr) auto 150px; align-items: center; gap: 12px; padding: 8px 16px 8px 0; border-top: 1px solid var(--divider-color); }
  .bar { align-self: stretch; border-radius: 0 3px 3px 0; }
  .row.ok .bar { background: var(--success-color, #43a047); }
  .row.warn .bar { background: var(--warning-color, #ffa600); opacity: 0.6; }
  .row.urgent .bar { background: var(--warning-color, #ffa600); }
  .row.overdue .bar { background: var(--error-color, #db4437); }
  .type { color: var(--secondary-text-color); justify-self: center; --mdc-icon-size: 22px; }
  .cover { width: 32px; height: 44px; object-fit: cover; border-radius: 3px; justify-self: center; }
  .main { min-width: 0; }
  .title { font-weight: 500; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .title a { color: inherit; text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .sub { font-size: 0.85rem; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .account { display: inline-block; font-size: 0.75rem; padding: 0 6px; margin-right: 6px; border-radius: 8px; background: var(--secondary-background-color); color: var(--primary-text-color); }
  .due { text-align: right; white-space: nowrap; }
  .date { color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .rel { font-size: 0.8rem; color: var(--secondary-text-color); }
  .row.overdue .rel { color: var(--error-color, #db4437); font-weight: 500; }
  .row.urgent .rel { color: var(--warning-color, #ffa600); }
  .action { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 0.85rem; text-align: right; }
  button.renew { border: 1px solid var(--primary-color); color: var(--primary-color); background: none; border-radius: 16px; padding: 4px 14px; font-size: 0.85rem; }
  button.renew:hover { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .muted { color: var(--secondary-text-color); }
  .small { font-size: 0.75rem; }
  .good { color: var(--success-color, #43a047); }
  .bad { color: var(--error-color, #db4437); }
  .empty { padding: 16px; color: var(--secondary-text-color); text-align: center; }
  @media (max-width: 600px) {
    .row { grid-template-columns: 4px 28px minmax(0, 1fr) auto; grid-template-areas: "bar type main due" "bar type action action"; row-gap: 4px; }
    .bar { grid-area: bar; } .type, .cover { grid-area: type; } .main { grid-area: main; } .due { grid-area: due; }
    .action { grid-area: action; flex-direction: row; justify-content: flex-end; align-items: center; gap: 8px; }
  }
`;

if (!customElements.get("stadtbibliothek-loans-card")) {
  customElements.define("stadtbibliothek-loans-card", StadtbibliothekLoansCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "stadtbibliothek-loans-card",
    name: "Bibliothek – Ausleihen",
    description: "Alle Ausleihen aller Bibliothekskonten, sortiert nach Rückgabedatum, mit Verlängern-Button.",
    preview: false,
  });
  console.info(`%c STADTBIBLIOTHEK-LOANS-CARD %c ${CARD_VERSION} `, "background:#03a9f4;color:#fff", "background:#555;color:#fff");
}
