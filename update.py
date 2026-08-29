#!/usr/bin/env python
"""Daily updater for the fully-funded BSc scholarship tracker.

    python update.py              # full run: check links, read pages, rebuild the site
    python update.py --offline    # rebuild the site from cached state, no network
    python update.py --open       # rebuild, then open the overview page in your browser

Designed to be run once a day by Windows Task Scheduler. It never raises on a
network problem - a university web server being down becomes a red badge on the
page, not a failed run.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
import webbrowser
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from tracker import dates, net, render

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site"
STATE = ROOT / "state" / "watch.json"
LOGS = ROOT / "logs"
ASSETS = ROOT / "tracker" / "assets"

ACTIVE_VERDICTS = ("eligible", "eligible-conditional", "partial")


def log(handle, message: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    print(line)
    handle.write(line + "\n")
    handle.flush()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE.exists():
        try:
            return load_json(STATE)
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _registrable(host: str) -> str:
    """Crude but sufficient: the last two labels of a hostname."""
    parts = [p for p in host.lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _entry_domains(entry: dict) -> set[str]:
    """Every domain this scholarship legitimately belongs to."""
    urls = [link["url"] for link in entry.get("links", [])]
    urls += [p.get("url", "") for p in entry.get("programmes", [])]
    urls += [p.get("site", "") for p in entry.get("programmes", [])]
    urls += entry.get("watch", []) + entry.get("sources", [])
    domains = set()
    for url in urls:
        if not url:
            continue
        domains.add(_registrable(urlparse(url).hostname or ""))
    domains.discard("")
    return domains


def _relevant_email(address: str, domains: set[str]) -> bool:
    """Keep only addresses that plausibly belong to this scholarship.

    Some official pages - the Stipendium Hungaricum partners table above all -
    list the contact desk for every sending country on earth. Showing a
    Palestinian applicant the Albanian ministry's inbox is worse than showing
    nothing, so an address has to sit on one of the entry's own domains, or be
    Palestinian, to make it onto the page.
    """
    domain = address.rsplit("@", 1)[-1].lower()
    if domain.endswith(".ps"):
        return True
    return _registrable(domain) in domains


def build(offline: bool, handle) -> tuple[list[dict], dict, list[dict], dict]:
    countries = load_json(DATA / "countries.json")
    entries = load_json(DATA / "scholarships.json")["scholarships"]
    today = date.today()
    stamp = today.isoformat()

    log(handle, f"Loaded {len(entries)} entries across {len(countries)} countries.")

    for entry in entries:
        entry["_deadline"] = dates.resolve(entry.get("deadline"), today).as_dict()

    previous = load_state()
    state: dict = {"last_run": stamp, "links": {}, "pages": {}}
    changes: list[dict] = []

    link_urls, watch_urls = [], []
    for entry in entries:
        link_urls += [link["url"] for link in entry.get("links", [])]
        link_urls += [p["url"] for p in entry.get("programmes", []) if p.get("url")]
        watch_urls += entry.get("watch", [])

    if offline:
        log(handle, "Offline mode - skipping all network checks.")
        link_results, page_results = {}, {}
        state["links"] = previous.get("links", {})
        state["pages"] = previous.get("pages", {})
    else:
        log(handle, f"Checking {len(set(link_urls))} links...")
        link_results = net.check_links(link_urls, stamp)
        broken = [r for r in link_results.values() if not r.ok]
        log(handle, f"  {len(link_results) - len(broken)} live, {len(broken)} unreachable.")

        log(handle, f"Reading {len(set(watch_urls))} watched pages...")
        page_results = net.fetch_pages(watch_urls)
        readable = sum(1 for r in page_results.values() if r.ok)
        log(handle, f"  {readable} read, {len(page_results) - readable} failed.")

        state["links"] = {url: r.as_dict() for url, r in link_results.items()}
        state["pages"] = {url: r.as_dict() for url, r in page_results.items()}

        for url, result in link_results.items():
            if result.ok:
                continue
            was_ok = previous.get("links", {}).get(url, {}).get("ok", True)
            changes.append({
                "kind": "broken" if was_ok else "still down",
                "text": f"Link is unreachable ({result.status}): {url} - ",
                "url": url,
            })

        for url, result in page_results.items():
            if not result.ok or not result.digest:
                continue
            before = previous.get("pages", {}).get(url, {})
            old_digest = before.get("digest")
            if old_digest is None:
                changes.append({
                    "kind": "new",
                    "text": f"Started watching {url} - ",
                    "url": url,
                })
            elif not old_digest:
                # We had this URL on file but could not read it last time, so
                # there is no baseline to diff against - not a content change.
                changes.append({
                    "kind": "recovered",
                    "text": f"Page is readable again after failing on the previous run: {url} - ",
                    "url": url,
                })
            elif old_digest != result.digest:
                # Almost every university page shuffles a news carousel or a
                # cookie token daily. Only speak up when the dates on the page
                # moved, or when a substantial amount of text appeared.
                old_dates = set(before.get("date_tokens", []))
                new_dates = set(result.date_tokens)
                delta = result.text_length - before.get("text_length", 0)
                added = sorted(new_dates - old_dates)[:4]
                removed = sorted(old_dates - new_dates)[:4]

                if added or removed:
                    bits = []
                    if added:
                        bits.append("new date(s): " + ", ".join(added))
                    if removed:
                        bits.append("gone: " + ", ".join(removed))
                    changes.append({
                        "kind": "dates",
                        "text": (f"Dates on the official page moved - {'; '.join(bits)}. "
                                 f"Check it before trusting the countdown: {url} - "),
                        "url": url,
                    })
                elif abs(delta) > 200:
                    direction = f"{abs(delta)} characters {'longer' if delta > 0 else 'shorter'}"
                    changes.append({
                        "kind": "changed",
                        "text": (f"Official page gained or lost content ({direction}) - "
                                 f"worth a look: {url} - "),
                        "url": url,
                    })

    # Attach per-entry network findings.
    by_url_links = {url: r.as_dict() for url, r in link_results.items()} if not offline \
        else previous.get("links", {})
    by_url_pages = {url: r.as_dict() for url, r in page_results.items()} if not offline \
        else previous.get("pages", {})

    for entry in entries:
        entry["_links"] = {
            link["url"]: by_url_links[link["url"]]
            for link in entry.get("links", []) if link["url"] in by_url_links
        }
        own_domains = _entry_domains(entry)
        discovered, signals = [], []
        for url in entry.get("watch", []):
            page = by_url_pages.get(url)
            if not page or not page.get("ok"):
                continue
            for addr in page.get("emails", []):
                if _relevant_email(addr, own_domains):
                    discovered.append([addr, url])
            signals += page.get("signals", [])
        entry["_discovered_emails"] = discovered[:6]
        entry["_signals"] = signals[:6]

    save_state(state)

    run_stats = {
        "links_checked": len(by_url_links),
        "pages_read": sum(1 for p in by_url_pages.values() if p.get("ok")),
        "broken_links": sum(1 for p in by_url_links.values() if not p.get("ok")),
        "changes": len(changes),
        "offline": offline,
    }
    return entries, countries, changes, run_stats


def summarise(entries: list[dict], handle) -> None:
    urgent = [
        e for e in entries
        if e.get("verdict") in ACTIVE_VERDICTS
        and e["_deadline"]["state"] in ("urgent", "open", "soon")
    ]
    if not urgent:
        log(handle, "No deadline inside the next 30 days.")
        return
    log(handle, f"{len(urgent)} deadline(s) needing attention:")
    for entry in sorted(urgent, key=lambda e: e["_deadline"]["days"] or 0):
        log(handle, f"  - {entry['_deadline']['label']}: {entry['name']} ({entry['country']})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the scholarship tracker site.")
    parser.add_argument("--offline", action="store_true",
                        help="skip all network checks and rebuild from cached state")
    parser.add_argument("--open", dest="open_site", action="store_true",
                        help="open the overview page in the default browser when done")
    args = parser.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"update-{date.today():%Y-%m-%d}.log"

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== run started {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
        try:
            entries, countries, changes, run_stats = build(args.offline, handle)
            generated = f"{datetime.now():%d %B %Y at %H:%M}"
            written = render.write_site(
                SITE, countries, entries, changes, generated, run_stats, ASSETS
            )
            log(handle, f"Wrote {len(written)} files to {SITE}")
            if changes:
                log(handle, f"{len(changes)} change(s) flagged on this run:")
                for change in changes[:20]:
                    log(handle, f"  [{change['kind']}] {change['text'].rstrip(' -')}")
            summarise(entries, handle)
            log(handle, "Done.")
        except Exception:  # noqa: BLE001 - a scheduled task must log, not vanish
            handle.write(traceback.format_exc())
            traceback.print_exc()
            return 1

    if args.open_site:
        webbrowser.open((SITE / "index.html").resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
