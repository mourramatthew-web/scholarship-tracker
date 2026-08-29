"""Static site generation: one index page plus one page per country."""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from pathlib import Path

from . import dates

VERDICT_BADGE = {
    "eligible":             ("ok",   "Open to Palestinian students"),
    "eligible-conditional": ("warn", "Open, with a condition"),
    "partial":              ("warn", "Partial funding only"),
    "not-bachelor":         ("hot",  "Not available at bachelor level"),
    "residency-required":   ("hot",  "Requires residence in country"),
}

FUNDING_BADGE = {
    "full":            ("ok",   "Fully funded"),
    "near-full":       ("ok",   "Tuition + housing"),
    "partial-to-full": ("warn", "Partial, can reach full"),
    "partial":         ("warn", "Partial funding"),
    "varies":          ("info", "Varies"),
}

PALESTINE_LABEL = {
    "explicit":                      ("ok",   "Palestine is a named partner country"),
    "explicit-conditional":          ("warn", "Palestine named, extra condition applies"),
    "palestine-only":                ("ok",   "Written specifically for Palestinian students"),
    "palestine-focused":             ("ok",   "Targeted at students affected by the war"),
    "palestine-included":            ("ok",   "Palestine included among eligible nationalities"),
    "nationality-blind":             ("ok",   "No nationality restriction"),
    "conditional":                   ("warn", "Conditional - read carefully"),
    "not-applicable-at-this-level":  ("hot",  "Not applicable at bachelor level"),
}

RATING_BADGE = {
    "strong":   ("ok",   "Realistic route"),
    "moderate": ("warn", "Possible, with effort"),
    "weak":     ("hot",  "No real route right now"),
}

FIELD_LABEL = {
    "computer-engineering": "Computer engineering",
    "mechatronics": "Mechatronics",
    "all": "Any field",
}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _join_names(names: list[str]) -> str:
    """'Spain, Italy and Hungary' - natural-language join, oxford-comma-free."""
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


class Links:
    """How one page refers to another.

    The separate country sites link file-to-file; the single-file bundle links
    to hash fragments in the same document. Everything else about the two
    outputs is identical, so the body builders take one of these rather than
    knowing which they are.
    """

    def __init__(self, page, anchor, nav_attr):
        self.page = page          # (slug) -> href
        self.anchor = anchor      # (slug, entry_id) -> href
        self.nav_attr = nav_attr  # (slug) -> extra attributes for a nav link


PAGE_LINKS = Links(
    page=lambda slug: "index.html" if slug == "index" else f"{slug}.html",
    anchor=lambda slug, eid: f"{slug}.html#{eid}",
    nav_attr=lambda slug: "",
)

BUNDLE_LINKS = Links(
    page=lambda slug: "#overview" if slug == "index" else f"#{slug}",
    anchor=lambda slug, eid: f"#{slug}/{eid}",
    nav_attr=lambda slug: f' data-page="{"overview" if slug == "index" else slug}"',
)


def _code(meta: dict) -> str:
    """Windows ships no flag-emoji font, so country identity is an ISO chip."""
    return f'<span class="cc">{esc(meta["code"])}</span>'


def _nav(countries: dict, active: str, links: "Links") -> str:
    current = ' aria-current="page"' if active == "index" else ""
    items = [
        f'<a class="tab-link" href="{links.page("index")}"{links.nav_attr("index")}{current}>Overview</a>'
    ]
    for slug, meta in countries.items():
        current = ' aria-current="page"' if active == slug else ""
        items.append(
            f'<a class="tab-link" href="{links.page(slug)}"{links.nav_attr(slug)}{current}>'
            f'{_code(meta)} {esc(meta["name"])}</a>'
        )
    return '<nav class="tabs">' + "".join(items) + "</nav>"


def _shell(*, title: str, description: str, body: str, countries: dict,
           active: str, accent: str, accent_soft: str, generated: str, css: str,
           links: "Links" = None, extra_js: str = "") -> str:
    links = links or PAGE_LINKS
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="noindex">
<script>
// Runs before paint: without this the page renders in the system theme and
// then visibly snaps to the saved one.
(function () {{
  try {{
    var saved = localStorage.getItem('tracker-theme');
    if (saved === 'light' || saved === 'dark') {{
      document.documentElement.setAttribute('data-theme', saved);
    }}
  }} catch (err) {{ /* private mode; system theme is a fine fallback */ }}
}})();
</script>
<style>
{css}
:root {{ --accent: {accent}; --accent-soft: {accent_soft}; }}
</style>
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="{links.page("index")}"{links.nav_attr("index")}><span class="dot"></span>Fully-funded BSc tracker</a>
    {_nav(countries, active, links)}
    <button class="theme-btn" type="button" data-theme-toggle
            aria-label="Switch between system, light and dark">
      <span class="theme-ico" aria-hidden="true"></span><span class="theme-txt">Auto</span>
    </button>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site">
  <div class="wrap">
    <p><strong>Read this before you rely on it.</strong> This site is generated from a curated
    dataset that is re-checked automatically every day. The daily job verifies that every official
    link still resolves, re-reads the official pages for contact addresses and changes, and
    recalculates every countdown. It does not discover brand-new scholarships on its own, and a
    deadline marked <em>typical</em> or <em>estimate</em> is a pattern from previous years, not a
    published date. Always confirm on the official page before you plan around a date.</p>
    <p>Generated {esc(generated)}. Data lives in <code>data/scholarships.json</code> - edit it and
    re-run <code>python update.py</code> to change what appears here.</p>
  </div>
</footer>
{extra_js}
</body>
</html>
"""


def _badge(kind: str, text: str) -> str:
    return f'<span class="badge {kind}">{esc(text)}</span>'


def _deadline_pill(resolved: dict) -> str:
    return f'<span class="big {esc(resolved["state"])}">{esc(resolved["label"])}</span>'


def _deadline_box(resolved: dict) -> str:
    conf = resolved.get("confidence") or ""
    conf_html = ""
    if conf:
        word = {"confirmed": "confirmed date", "typical": "typical date - confirm",
                "estimate": "estimate - confirm"}.get(conf, conf)
        conf_html = f'<div class="conf">{esc(word)}</div>'
    return (
        '<div class="deadline-box">'
        f'{_deadline_pill(resolved)}'
        f'<div class="detail">{esc(resolved["detail"])}</div>'
        f'{conf_html}'
        "</div>"
    )


def _links_block(entry: dict) -> str:
    checks = entry.get("_links", {})
    rows = []
    for link in entry.get("links", []):
        url = link["url"]
        result = checks.get(url)
        if result is None:
            status, cls = "", ""
        elif result["status"] == "bot-blocked":
            status, cls = "blocks bots - open manually", "soft"
        elif result["status"] == "cert-unverified":
            status, cls = "live (cert chain unverified)", "soft"
        elif result["ok"]:
            status, cls = "live", ""
        else:
            status, cls = f'unreachable: {result["status"]}', "bad"
        status_html = f'<span class="status {cls}">{esc(status)}</span>' if status else ""
        rows.append(
            f'<div class="row"><a href="{esc(url)}" target="_blank" rel="noopener">'
            f'{esc(link["label"])}</a>{status_html}</div>'
        )
    if not rows:
        return ""
    return (
        '<div class="block"><h4>Official links</h4>'
        f'<div class="linklist">{"".join(rows)}</div></div>'
    )


def _contacts_block(entry: dict) -> str:
    cards = []
    for item in entry.get("emails", []):
        addr = item["address"]
        if item.get("verified"):
            flag = '<div class="flagline found">Verified against the official page.</div>'
        else:
            flag = ('<div class="flagline unverified">Not independently verified - '
                    "confirm on the contact page before you rely on it.</div>")
        cards.append(
            f'<div class="contact"><div class="who">{esc(item["label"])}</div>'
            f'<a class="addr" href="mailto:{esc(addr)}">{esc(addr)}</a>{flag}</div>'
        )

    known = {item["address"].lower() for item in entry.get("emails", [])}
    for addr, source in entry.get("_discovered_emails", []):
        if addr.lower() in known:
            continue
        cards.append(
            f'<div class="contact"><div class="who">Found on the official page</div>'
            f'<a class="addr" href="mailto:{esc(addr)}">{esc(addr)}</a>'
            f'<div class="flagline found">Scraped today from '
            f'<a href="{esc(source)}" target="_blank" rel="noopener">this page</a>.</div></div>'
        )

    for phone in entry.get("phones", []):
        cards.append(
            f'<div class="contact"><div class="who">Phone</div>'
            f'<a class="addr" href="tel:{esc(phone.replace(" ", ""))}">{esc(phone)}</a></div>'
        )

    if not cards:
        return ('<div class="block"><h4>Contact</h4><p class="quiet">No published email address '
                "on file. Use the contact form on the official links above.</p></div>")
    return (f'<div class="block"><h4>Contact</h4>'
            f'<div class="contact-grid">{"".join(cards)}</div></div>')


def _programmes_block(entry: dict) -> str:
    rows = []
    for prog in entry.get("programmes", []):
        link = prog.get("url") or prog.get("site") or ""
        degree = esc(prog["degree"])
        if link:
            degree = f'<a href="{esc(link)}" target="_blank" rel="noopener">{degree}</a>'
        rows.append(
            f'<tr data-field="{esc(" ".join(prog.get("field", ["all"])))}">'
            f'<td class="deg">{degree}</td>'
            f'<td>{esc(prog.get("university", ""))}</td>'
            f'<td>{esc(prog.get("city", ""))}</td>'
            f'<td>{esc(prog.get("duration", ""))}</td>'
            f'<td>{esc(prog.get("language", ""))}</td>'
            "</tr>"
        )
    if not rows:
        return ""
    return (
        '<div class="block"><h4>Degrees this funds</h4><div class="table-scroll"><table>'
        "<thead><tr><th>Degree</th><th>University</th><th>City</th>"
        "<th>Length</th><th>Taught in</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def _funding_block(entry: dict) -> str:
    funding = entry.get("funding", {})
    covered = "".join(f"<li>{esc(item)}</li>" for item in funding.get("items", []))
    not_covered = "".join(f"<li>{esc(item)}</li>" for item in funding.get("not_covered", []))
    parts = [f'<div class="block"><h4>What it pays for</h4><ul class="plain">{covered}</ul>']
    if not_covered:
        parts.append(
            '<h4 style="margin-top:16px">What it does not pay for</h4>'
            f'<ul class="plain cross">{not_covered}</ul>'
        )
    parts.append("</div>")
    return "".join(parts)


def _signals_block(entry: dict) -> str:
    signals = entry.get("_signals", [])
    if not signals:
        return ""
    lines = "".join(f"<p>{esc(line)}</p>" for line in signals[:6])
    return (
        '<div class="block"><details class="sig">'
        "<summary>What today's scrape read on the official page</summary>"
        f"{lines}</details></div>"
    )


def _field_badges(fields: list[str]) -> str:
    labelled = [f for f in fields if f in FIELD_LABEL and f != "all"]
    if not labelled:
        # An entry with no specific degree list (the "skip this" entries) -
        # say so explicitly rather than showing nothing where a major would be.
        return _badge("", FIELD_LABEL["all"])
    return "".join(_badge("", FIELD_LABEL[f]) for f in labelled)


def entry_fields(entry: dict) -> list[str]:
    """Which fields a scholarship really covers, taken from its degrees.

    Tagging this on the scholarship by hand made the filter a no-op: nearly
    every entry claimed both fields, so pressing "Mechatronics" hid nothing.
    The degrees are the honest source - Spain's UCM and UAB routes fund a
    computer engineering grado and no mechatronics one, and the filter should
    say so.
    """
    found = {f for prog in entry.get("programmes", []) for f in prog.get("field", [])}
    if found:
        return sorted(found)
    # No degree list (entries kept only to tell you to skip them): always shown.
    return ["all"]


def _card(entry: dict) -> str:
    resolved = entry["_deadline"]
    verdict_kind, verdict_text = VERDICT_BADGE.get(entry.get("verdict", ""), ("info", entry.get("verdict", "")))
    tier = entry.get("funding", {}).get("tier", "")
    funding_kind, funding_text = FUNDING_BADGE.get(tier, ("info", tier))
    pal = entry.get("palestine", {})
    pal_kind, pal_text = PALESTINE_LABEL.get(pal.get("status", ""), ("info", pal.get("status", "")))

    fields = entry_fields(entry)
    badges = [_badge(verdict_kind, verdict_text), _badge(funding_kind, funding_text),
              _field_badges(fields), _badge("", f'Taught in {entry.get("language", "n/a")}')]

    warnings = ""
    if entry.get("warnings"):
        items = "".join(f"<li>{esc(w)}</li>" for w in entry["warnings"])
        warnings = f'<div class="callout warn"><strong>Watch out.</strong><ul class="plain">{items}</ul></div>'

    steps = ""
    if entry.get("how_to_apply"):
        items = "".join(f"<li>{esc(s)}</li>" for s in entry["how_to_apply"])
        steps = f'<div class="block"><h4>How to apply</h4><ol class="steps">{items}</ol></div>'

    note = resolved.get("note", "")
    note_html = f'<div class="block"><h4>Deadline notes</h4><p style="margin:0;color:var(--ink-2)">{esc(note)}</p></div>' if note else ""

    stale = dates.stale_days(entry.get("last_verified", ""))
    stale_txt = f"Curated entry last hand-checked {stale} days ago." if stale is not None else ""
    sources = "".join(
        f'<div class="row"><a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a></div>'
        for u in entry.get("sources", [])
    )
    sources_html = (
        '<div class="block"><h4>Sources for this entry</h4>'
        f'<div class="linklist">{sources}</div>'
        f'<p class="quiet" style="margin:9px 0 0">{esc(stale_txt)}</p></div>'
    ) if sources else ""

    dim = " dim" if entry.get("verdict") in ("not-bachelor", "residency-required") else ""
    field_attr = " ".join(fields)

    # Hidden by default: the country page always opens on the compact list,
    # and JS reveals exactly one of these when its row is clicked. Kept in the
    # DOM (rather than built lazily) so a deep link from the overview timeline
    # can jump straight to it.
    return f"""
<article class="card{dim}" id="{esc(entry['id'])}" data-entry="{esc(entry['id'])}"
         data-fields="{esc(field_attr)}"
         data-state="{esc(resolved['state'])}" data-verdict="{esc(entry.get('verdict',''))}" hidden>
  <div class="back-bar">
    <button type="button" class="back-btn" data-back><span class="arrow">&larr;</span>All scholarships</button>
  </div>
  <header>
    <div class="title">
      <h3>{esc(entry['name'])}</h3>
      <p class="provider">{esc(entry.get('provider',''))}</p>
      <div class="badge-row">{''.join(badges)}</div>
    </div>
    {_deadline_box(resolved)}
  </header>
  <div class="body">
    {warnings}
    <div class="block">
      <h4>Can a Palestinian student get this?</h4>
      <div class="eligibility">
        <span class="tag">{_badge(pal_kind, pal_text)}</span>
        {esc(pal.get('note',''))}
      </div>
    </div>
    {_funding_block(entry)}
    {note_html}
    {_programmes_block(entry)}
    {steps}
    {_links_block(entry)}
    {_contacts_block(entry)}
    {_signals_block(entry)}
    {sources_html}
  </div>
</article>"""


def _compact_row(entry: dict) -> str:
    """One line per scholarship: name, deadline, major - nothing else.

    This is what a country page opens on. Clicking a row is the only way to
    reach the full detail card, so it doubles as that scholarship's tab.
    """
    resolved = entry["_deadline"]
    fields = entry_fields(entry)
    dim = " dim" if entry.get("verdict") in ("not-bachelor", "residency-required") else ""
    days = resolved.get("days")
    return (
        f'<button type="button" class="srow{dim}" data-entry="{esc(entry["id"])}" '
        f'data-fields="{esc(" ".join(fields))}" '
        f'data-open="{"true" if resolved.get("is_open", True) else "false"}" '
        f'data-days="{days if days is not None else ""}">'
        f'<span class="sname">{esc(entry["name"])}</span>'
        f'{_deadline_pill(resolved)}'
        f'<span class="sfields">{_field_badges(fields)}</span>'
        "</button>"
    )


FILTER_JS = """
<script>
(function () {
  // One controller per country block. In the single-file app all four live in
  // the same document, so Italy's filters must never touch Hungary's rows.
  document.querySelectorAll('[data-scope]').forEach(function (scope) {
    var fieldChips = [].slice.call(scope.querySelectorAll('[data-filter]'));
    var openToggle = scope.querySelector('[data-toggle-open]');
    var sortToggle = scope.querySelector('[data-sort-toggle]');
    var rows = [].slice.call(scope.querySelectorAll('.srow'));
    var cards = [].slice.call(scope.querySelectorAll('.card[data-entry]'));
    var list = scope.querySelector('[data-slist]');
    var empty = scope.querySelector('.empty-note');

    var state = { field: 'all', openOnly: false, sort: 'asc', entry: 'all' };

    function fieldOk(el) {
      if (state.field === 'all') { return true; }
      var f = (el.dataset.fields || '').split(' ');
      return f.indexOf(state.field) > -1 || f.indexOf('all') > -1;
    }
    function openOk(el) {
      return !state.openOnly || el.dataset.open === 'true';
    }

    function filterDegreeRows(card) {
      card.querySelectorAll('tbody tr[data-field]').forEach(function (row) {
        if (state.field === 'all') { row.hidden = false; return; }
        var f = (row.dataset.field || '').split(' ');
        row.hidden = f.indexOf(state.field) === -1 && f.indexOf('all') === -1;
      });
    }

    // Rows with no known date always sort to the end, in either direction -
    // they are not really part of the ordering, just along for the ride.
    function sortRows() {
      if (!list) { return; }
      var dated = [], undated = [];
      rows.forEach(function (r) {
        (r.dataset.days === '' ? undated : dated).push(r);
      });
      dated.sort(function (a, b) {
        var da = parseFloat(a.dataset.days), db = parseFloat(b.dataset.days);
        return state.sort === 'asc' ? da - db : db - da;
      });
      dated.concat(undated).forEach(function (r) { list.appendChild(r); });
    }

    function apply() {
      fieldChips.forEach(function (c) {
        c.setAttribute('aria-pressed', String(c.dataset.filter === state.field));
      });
      if (openToggle) { openToggle.setAttribute('aria-pressed', String(state.openOnly)); }
      if (sortToggle) {
        sortToggle.textContent = state.sort === 'asc' ? 'Soonest first' : 'Latest first';
        sortToggle.setAttribute('aria-pressed', String(state.sort === 'desc'));
      }

      if (state.entry !== 'all') {
        // One scholarship open: hide the list, show just that card, and keep
        // the major filter live inside it so the degree table still reflects
        // whichever major you were browsing when you opened it.
        if (list) { list.hidden = true; }
        if (empty) { empty.hidden = true; }
        cards.forEach(function (card) {
          var visible = card.dataset.entry === state.entry;
          card.hidden = !visible;
          if (visible) { filterDegreeRows(card); }
        });
        return;
      }

      if (list) { list.hidden = false; }
      cards.forEach(function (card) { card.hidden = true; });

      var shown = 0;
      rows.forEach(function (row) {
        var visible = fieldOk(row) && openOk(row);
        row.hidden = !visible;
        if (visible) { shown++; }
      });
      if (empty) { empty.hidden = shown > 0; }
      sortRows();
    }

    fieldChips.forEach(function (chip) {
      chip.addEventListener('click', function () { state.field = chip.dataset.filter; apply(); });
    });
    if (openToggle) {
      openToggle.addEventListener('click', function () {
        state.openOnly = !state.openOnly;
        apply();
      });
    }
    if (sortToggle) {
      sortToggle.addEventListener('click', function () {
        state.sort = state.sort === 'asc' ? 'desc' : 'asc';
        apply();
      });
    }
    rows.forEach(function (row) {
      row.addEventListener('click', function () { state.entry = row.dataset.entry; apply(); });
    });
    scope.querySelectorAll('[data-back]').forEach(function (btn) {
      btn.addEventListener('click', function () { state.entry = 'all'; apply(); });
    });

    // Let the router open one scholarship directly: #italy/it-edisu-...
    scope.selectEntry = function (id) {
      state.entry = id || 'all';
      state.field = 'all';     // a deep link should never land on a filtered-out card
      state.openOnly = false;
      apply();
    };
    scope.resetEntry = function () {
      state.entry = 'all';
      apply();
    };

    apply();
  });
})();
</script>
"""


THEME_JS = """
<script>
(function () {
  var btn = document.querySelector('[data-theme-toggle]');
  if (!btn) { return; }
  var txt = btn.querySelector('.theme-txt');

  // Three states, not two: "Auto" follows the operating system, and the two
  // explicit choices override it. Auto is the default because most people
  // already told their OS which they want.
  var ORDER = ['auto', 'light', 'dark'];
  var LABEL = { auto: 'Auto', light: 'Light', dark: 'Dark' };

  // Held in memory, with storage as persistence only. Reading the mode back
  // out of localStorage meant the button froze on the first step wherever
  // storage is unavailable - private windows, sandboxed viewers.
  var mode = 'auto';
  try {
    var saved = localStorage.getItem('tracker-theme');
    if (saved === 'light' || saved === 'dark') { mode = saved; }
  } catch (err) { /* private mode; Auto is a fine starting point */ }

  function paint(mode) {
    if (mode === 'auto') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', mode);
    }
    btn.dataset.mode = mode;
    if (txt) { txt.textContent = LABEL[mode]; }
    btn.setAttribute('title', 'Theme: ' + LABEL[mode] + ' (click to change)');
  }

  paint(mode);

  btn.addEventListener('click', function () {
    mode = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    try {
      if (mode === 'auto') { localStorage.removeItem('tracker-theme'); }
      else { localStorage.setItem('tracker-theme', mode); }
    } catch (err) { /* choice will not survive a reload, but it applies now */ }
    paint(mode);
  });
})();
</script>
"""


def country_body(slug: str, meta: dict, entries: list[dict], generated: str) -> str:
    rating_kind, rating_text = RATING_BADGE.get(meta.get("rating", ""), ("info", ""))
    live = [e for e in entries if e.get("verdict") in ("eligible", "eligible-conditional", "partial")]

    cards = "".join(_card(e) for e in entries)
    rows = "".join(_compact_row(e) for e in entries)

    body = f"""
<section class="hero">
  <div class="country-mark">{_code(meta)}</div>
  <div class="eyebrow" style="margin-top:10px">Fully funded bachelor scholarships</div>
  <h1>{esc(meta['name'])}</h1>
  <div class="badge-row" style="margin-bottom:16px">
    {_badge(rating_kind, rating_text)}
    {_badge('', f'{len(live)} route' + ('' if len(live) == 1 else 's') + ' worth your time')}
    {_badge('', f'{len(entries)} entries tracked')}
  </div>
  <p class="lede">{esc(meta['headline'])}</p>
  <span class="stamp"><span class="pulse"></span>Checked {esc(generated)}</span>
</section>

<section>
  <h2 class="section">The honest version</h2>
  <div class="panel">
    <p style="margin-top:0;color:var(--ink-2)">{esc(meta['reality_check'])}</p>
    <p style="margin-bottom:0;color:var(--ink-2)"><strong style="color:var(--ink)">Language.</strong>
      {esc(meta['language_note'])}</p>
  </div>
</section>

<section data-scope="{slug}">
  <h2 class="section">Scholarships</h2>
  <div class="filters">
    <span class="lbl">Major</span>
    <button class="chip" data-filter="all" aria-pressed="true">All</button>
    <button class="chip" data-filter="computer-engineering" aria-pressed="false">Computer engineering</button>
    <button class="chip" data-filter="mechatronics" aria-pressed="false">Mechatronics</button>
    <span class="sep"></span>
    <span class="lbl">Status</span>
    <button class="chip" data-toggle-open aria-pressed="false">Open now only</button>
    <span class="sep"></span>
    <span class="lbl">Sort</span>
    <button class="chip" data-sort-toggle aria-pressed="false">Soonest first</button>
  </div>
  <p class="empty-note" hidden>Nothing matches these filters. Loosen the major
    or status filter to see more.</p>
  <div class="slist" data-slist>{rows}</div>
  {cards}
</section>
"""
    return body


def _timeline(entries: list[dict], countries: dict, links: "Links",
              limit: int = 8) -> str:
    live = [e for e in entries
            if e["_deadline"]["days"] is not None
            and e.get("verdict") in ("eligible", "eligible-conditional", "partial")]
    live.sort(key=lambda e: (e["_deadline"]["days"], e.get("priority", 5)))
    rows = []
    for entry in live[:limit]:
        resolved = entry["_deadline"]
        country = countries[entry["country"]]
        state = resolved["state"]
        rows.append(
            '<div class="tl-row">'
            f'<div class="when">{esc(resolved["target"] or "-")}</div>'
            '<div class="what">'
            f'<a href="{links.anchor(country["slug"], entry["id"])}">{esc(entry["name"])}</a>'
            f'<div class="meta">{_code(country)} {esc(country["name"])} &middot; {esc(resolved["detail"])}</div>'
            "</div>"
            f'<div>{_badge({"urgent": "hot", "open": "ok", "soon": "warn"}.get(state, "info"), resolved["label"])}</div>'
            "</div>"
        )
    if not rows:
        return '<p class="quiet">Nothing with a dated deadline right now.</p>'
    return f'<div class="timeline">{"".join(rows)}</div>'


def _changes_feed(changes: list[dict]) -> str:
    if not changes:
        return ('<p class="quiet">No link failures and no content changes detected on the '
                "official pages since the last run.</p>")
    rows = []
    for change in changes[:40]:
        kind = change["kind"]
        cls = {"new": "new", "recovered": "new", "changed": "changed", "dates": "broken",
               "broken": "broken", "still down": "broken"}.get(kind, "changed")
        link = (f' <a href="{esc(change["url"])}" target="_blank" rel="noopener">open</a>'
                if change.get("url") else "")
        rows.append(
            f'<div class="change {cls}"><span class="kind">{esc(kind)}</span>'
            f'<span>{esc(change["text"])}{link}</span></div>'
        )
    return f'<div class="changes">{"".join(rows)}</div>'


def index_body(countries: dict, entries: list[dict], changes: list[dict],
               generated: str, run_stats: dict, links: "Links") -> str:
    cards = []
    for slug, meta in countries.items():
        own = [e for e in entries if e["country"] == slug]
        live = [e for e in own if e.get("verdict") in ("eligible", "eligible-conditional", "partial")]
        dated = [e for e in live if e["_deadline"]["days"] is not None]
        dated.sort(key=lambda e: e["_deadline"]["days"])
        nearest = dated[0]["_deadline"]["label"] if dated else "no dated deadline"
        rating_kind, rating_text = RATING_BADGE.get(meta.get("rating", ""), ("info", ""))
        cards.append(f"""
<a class="country-card" href="{links.page(slug)}"{links.nav_attr(slug)} style="--c:{meta['accent']};--c2:{meta['accent_soft']}">
  <div class="flag">{_code(meta)}</div>
  <h3>{esc(meta['name'])}</h3>
  <div class="sub">{_badge(rating_kind, rating_text)}</div>
  <div class="metric"><span>Routes worth your time</span><b>{len(live)}</b></div>
  <div class="metric"><span>Entries tracked</span><b>{len(own)}</b></div>
  <div class="metric"><span>Next date</span><b>{esc(nearest)}</b></div>
</a>""")

    body = f"""
<section class="hero">
  <div class="eyebrow">Computer engineering &amp; mechatronics &middot; bachelor level &middot; Palestinian applicants</div>
  <h1>Where a fully funded BSc is actually possible</h1>
  <p class="lede">{len(countries)} countries, {len(entries)} funding routes, re-checked every day.
  Deadlines roll forward automatically, dead links are flagged, and contact addresses are
  re-read from the official pages on each run.</p>
  <span class="stamp"><span class="pulse"></span>Last run {esc(generated)} &middot;
    {run_stats['links_checked']} links checked &middot; {run_stats['pages_read']} pages read</span>
</section>

<section>
  <h2 class="section">Countries</h2>
  <div class="country-grid">{''.join(cards)}</div>
</section>

<section>
  <h2 class="section">What to do next, in order</h2>
  <div class="panel">
    <ol class="steps" style="margin:0">
      <li><strong>Hungary and Germany first, in parallel.</strong> Stipendium Hungaricum is the
        cleanest single package - tuition, stipend, housing and insurance, taught in English -
        if the Palestinian Ministry of Education and Higher Education nominates you; that
        nomination is the bottleneck, not the Hungarian form. Germany's public universities charge
        zero tuition at bachelor level regardless of nationality, which is arguably the single
        strongest financial fact on this whole site - but you carry living costs yourself (a
        roughly EUR 12,000/year blocked account for the visa) and most bachelor's are German-taught.</li>
      <li><strong>Italy, twice over.</strong> Apply for IUPALS (Palestine-specific) and, separately,
        to Politecnico di Torino or Milano plus that region's DSU grant. Different applications,
        different deadlines, and they stack.</li>
      <li><strong>France and Greece, if the timing lines up.</strong> France's Gaza-specific
        scholarship funds licence (bachelor) years directly when it is running - confirm the
        current cycle is actually open before you count on it. Greece's Ministry of Foreign
        Affairs funds three Palestinian students a year, plus a free Greek course to get you ready.</li>
      <li><strong>Spain and the UAE as secondary tracks.</strong> Spain's university refuge
        programmes are real money but Spanish-taught, gated behind a slow UNEDasiss credential.
        Khalifa University in the UAE covers full tuition on merit, but living costs are on you.</li>
      <li><strong>Switzerland, Cyprus and Poland: do not build a plan on them.</strong> None
        currently has a fully funded bachelor route reachable by an applicant abroad. They stay on
        this site so you can see the day that changes.</li>
      <li><strong>Start document legalisation now, wherever you land.</strong> Every route above
        needs attested transcripts, and several need a legalised household income certificate.
        That paperwork, not the applications, is what makes people miss deadlines.</li>
    </ol>
  </div>
</section>

<section>
  <h2 class="section">Next deadlines</h2>
  {_timeline(entries, countries, links)}
</section>

<section>
  <h2 class="section">Changes picked up on this run</h2>
  {_changes_feed(changes)}
</section>
"""
    return body


BUNDLE_JS = """
<script>
(function () {
  var pages = Array.prototype.slice.call(document.querySelectorAll('.page'));
  var navLinks = Array.prototype.slice.call(document.querySelectorAll('[data-page]'));
  var accents = __ACCENTS__;
  var INITIAL = __INITIAL__;

  function show(slug, deep) {
    if (!accents[slug]) { slug = 'overview'; }
    pages.forEach(function (page) { page.hidden = page.dataset.page !== slug; });
    navLinks.forEach(function (link) {
      if (link.dataset.page === slug && link.classList.contains('tab-link')) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
    var pair = accents[slug];
    document.documentElement.style.setProperty('--accent', pair[0]);
    document.documentElement.style.setProperty('--accent-soft', pair[1]);
    var scope = document.querySelector('[data-scope="' + slug + '"]');
    if (scope) {
      if (deep && scope.selectEntry) { scope.selectEntry(deep); }
      else if (scope.resetEntry) { scope.resetEntry(); }
    }
    if (deep) {
      var target = document.getElementById(deep);
      if (target) { target.scrollIntoView({ block: 'start' }); return; }
    }
    window.scrollTo(0, 0);
  }

  function route() {
    var raw = (location.hash || '#' + INITIAL).slice(1);
    var parts = raw.split('/');
    show(parts[0], parts[1]);
  }

  // Click handling is deliberately not left to the hash alone. Some viewers
  // (preview panes, sandboxed frames, data: URLs) swallow hash navigation, and
  // then every tab looks dead. Handling the click directly means the tabs work
  // even where location.hash never fires.
  document.addEventListener('click', function (event) {
    if (!event.target.closest) { return; }
    // Only anchors. Matching [data-page] as well used to catch the .page
    // wrapper that every control sits inside, so clicking a scholarship tab
    // was read as "navigate to this country" and reset the selection.
    var link = event.target.closest('a[href^="#"]');
    if (!link) { return; }

    var href = link.getAttribute('href') || '';
    var slug, deep;
    if (link.dataset && link.dataset.page) {
      slug = link.dataset.page;
      deep = href.split('/')[1] || '';
    } else {
      var parts = href.slice(1).split('/');
      slug = parts[0];
      deep = parts[1] || '';
    }
    if (!accents[slug]) { return; }  // some other in-page anchor; leave it alone

    event.preventDefault();
    show(slug, deep);
    try {
      location.hash = deep ? slug + '/' + deep : slug;
    } catch (err) {
      /* hash is a convenience for bookmarking; the view already switched. */
    }
  });

  window.addEventListener('hashchange', route);
  route();
})();
</script>
"""


def render_bundle(countries: dict, entries: list[dict], changes: list[dict],
                  generated: str, run_stats: dict, css: str,
                  sorter, initial: str = "overview") -> str:
    """Everything in one file: every country, tabs switching in place.

    Every page the tracker writes is one of these. Nothing ever links to another
    file, because file-to-file links are exactly what breaks the moment a page
    is opened on its own - from a preview pane, an email, a download folder.
    The only difference between the files is which tab opens first.
    """
    overview_accent = ["#6C5CE7", "#A29BFE"]
    accents = {"overview": overview_accent}
    for slug, meta in countries.items():
        accents[slug] = [meta["accent"], meta["accent_soft"]]

    start = initial if initial in accents else "overview"
    start_accent = accents[start]

    def wrap(slug: str, inner: str) -> str:
        # Hidden in the markup itself, so the correct tab is showing before the
        # script runs and there is no flash of all five sections at once.
        hidden = "" if slug == start else " hidden"
        return f'<div class="page" data-page="{slug}"{hidden}>{inner}</div>'

    sections = [wrap("overview", index_body(
        countries, entries, changes, generated, run_stats, BUNDLE_LINKS))]
    for slug, meta in countries.items():
        own = sorter([e for e in entries if e["country"] == slug])
        sections.append(wrap(slug, country_body(slug, meta, own, generated)))

    # A short, specific name - not a summary with a dash-appended explainer.
    # The one-sentence explanation belongs in the meta description below instead.
    if start == "overview":
        title = "Scholarship Tracker"
    else:
        title = f"{countries[start]['name']} Scholarships"

    country_list = _join_names([meta["name"] for meta in countries.values()])
    return _shell(
        title=title,
        description="Fully funded bachelor scholarships in computer engineering and "
                    f"mechatronics for Palestinian students in {country_list}. "
                    f"All {len(countries)} countries in one file.",
        body="".join(sections),
        countries=countries,
        active="index" if start == "overview" else start,
        accent=start_accent[0],
        accent_soft=start_accent[1],
        generated=generated,
        css=css,
        links=BUNDLE_LINKS,
        extra_js=THEME_JS + FILTER_JS + BUNDLE_JS
            .replace("__ACCENTS__", json.dumps(accents))
            .replace("__INITIAL__", json.dumps(start)),
    )


def write_site(out_dir: Path, countries: dict, entries: list[dict], changes: list[dict],
               generated: str, run_stats: dict, asset_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # The stylesheet is inlined into every page so each file stands on its own:
    # you can email one, drop it on a USB stick or open it from anywhere and it
    # still looks right. tracker/assets/style.css stays the single place to edit.
    css = (asset_dir / "style.css").read_text(encoding="utf-8")

    def sorter(items: list[dict]) -> list[dict]:
        return sorted(items, key=lambda e: (
            e.get("priority", 5),
            dates.upcoming_sort_key(dates.Resolved(**e["_deadline"])),
        ))

    def build(initial: str) -> str:
        return render_bundle(countries, entries, changes, generated,
                             run_stats, css, sorter, initial)

    # Every file is the complete app. index.html opens on the overview and each
    # country file opens on that country, but all of them contain all five tabs
    # and switch between them in JavaScript. No page ever links to another file,
    # so there is nothing left to break when a page is opened on its own.
    written = []
    for name, initial in [("index", "overview")] + [(slug, slug) for slug in countries]:
        path = out_dir / f"{name}.html"
        path.write_text(build(initial), encoding="utf-8")
        written.append(path)

    # Older builds wrote a separate single-file edition. index.html is that now.
    stale = out_dir / "all-countries.html"
    if stale.exists():
        stale.unlink()

    payload = {
        "generated": generated,
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "run": run_stats,
        "changes": changes,
        "scholarships": entries,
    }
    data_path = out_dir / "data.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(data_path)
    return written
