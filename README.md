# Fully-funded BSc scholarship tracker

Computer engineering and mechatronics, bachelor level, open to Palestinian students,
in **Hungary, Italy, Spain, Switzerland, Greece, Cyprus, France, Germany, UAE and Poland**.
One site per country, rebuilt every day.

```
C:\Users\matth\scholarship-tracker
├── data\
│   ├── scholarships.json     <- the dataset. This is the file you edit.
│   └── countries.json        <- country headers, accent colours, honest summaries
├── tracker\
│   ├── dates.py              <- deadline maths (rollover, countdowns, windows)
│   ├── net.py                <- link checking, email scraping, change detection
│   ├── render.py             <- HTML generation
│   └── assets\style.css      <- the stylesheet (inlined into every page at build)
├── site\                     <- generated output; open any file, they all work
│   ├── index.html            <- opens on the overview
│   └── hungary|italy|spain|switzerland|greece|cyprus|france|germany|uae|poland.html
│       <- each opens on that country; all ten live inside every file
├── state\watch.json          <- yesterday's fingerprints, for diffing
├── logs\                     <- one log per day, 60 kept
├── update.py                 <- the program
├── run_daily.ps1             <- what the scheduled task runs
└── install_daily_task.ps1    <- registers / removes the daily task
```

## Running it

```powershell
python update.py            # full run: check links, read pages, rebuild the site
python update.py --offline  # rebuild from cached state, no network
python update.py --open     # rebuild, then open the overview in your browser
```

No pip install required. It is stdlib-only on purpose, so an unattended daily task
cannot break because a package changed.

### Every file is the whole app

There is no such thing as a broken country link here, because **no page ever links
to another page**. Each of the eleven HTML files contains all ten countries plus the
overview, and the tabs switch between them in JavaScript. The files differ only in
which tab opens first: `index.html` starts on the overview, `spain.html` starts on
Spain, and so on.

That means you can open any one of them from anywhere - the folder, a preview pane,
an email attachment, a USB stick, a download folder with no other files next to it -
and every tab, every country card and every deadline link still works.

The router handles clicks directly rather than relying on the URL hash, because some
viewers silently swallow hash navigation, which is what made the tabs look dead in
earlier versions.

## Running it every day

```powershell
powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1
powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -At 07:30
powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -Remove
```

The task runs under your own account, catches up if the machine was asleep at the
scheduled time, and will not stack two runs on top of each other.

## What the daily run actually does

1. **Recomputes every deadline.** Annual dates roll forward once they pass, so a
   15 January deadline becomes next January's automatically. Application windows
   flip to `OPEN NOW` on the day they open and start counting down to the close.
2. **Checks all official links** (86 and counting as entries are added). Dead ones
   get a red badge on the page and a line in the changes feed. Sites that block bots
   are labelled as such rather than being reported as broken.
3. **Re-reads the watched official pages** and scrapes contact addresses off them.
   An address confirmed on the page today is shown as verified; a curated address
   that has not been confirmed is shown with a caution note. Addresses that belong
   to a different institution are filtered out — the Stipendium Hungaricum partners
   page lists a contact desk for every sending country on earth, and showing you
   Albania's is worse than showing nothing.
4. **Diffs those pages against yesterday.** It only speaks up when the *dates* on a
   page changed, or when a substantial block of text appeared or disappeared.
   University sites shuffle a news carousel every night; that is not news.
5. **Rebuilds the eleven HTML pages** and writes `site\data.json` if you want the raw
   data for something else.

## What it does not do

It does not discover new scholarships on its own. Scraping arbitrary university
sites for "is this a new fully funded bachelor scholarship for Palestinians" is
not something a script can do reliably, and a tracker that quietly invents entries
is worse than no tracker. What it does instead is watch the official pages that
*would* announce one, and tell you when they change.

## Editing the data

`data\scholarships.json` is the single source of truth. Each entry:

| Field | Meaning |
|---|---|
| `verdict` | `eligible`, `eligible-conditional`, `partial`, `not-bachelor`, `residency-required` |
| `priority` | 1 = apply to this first; 9 = listed only so you know to skip it |
| `funding.tier` | `full`, `near-full`, `partial-to-full`, `partial`, `varies` |
| `palestine.status` | drives the eligibility badge, e.g. `palestine-only`, `nationality-blind` |
| `deadline.kind` | `annual` (MM-DD), `window` (from/to MM-DD), `fixed` (YYYY-MM-DD), `rolling`, `varies` |
| `deadline.confidence` | `confirmed`, `typical`, `estimate` — shown under the countdown |
| `links` / `emails` | official URLs and contacts; `verified: true` means checked by hand |
| `watch` | pages the daily job re-reads for changes and contact addresses |
| `sources` | where the entry's claims came from |
| `last_verified` | date you last hand-checked it |

Add an entry, run `python update.py --offline`, and it appears on the right country
page. Entries marked `not-bachelor` or `residency-required` are rendered dimmed and
sorted last, on purpose: knowing what to skip saves an application cycle.

## Honesty notes baked into the data

- **Hungary** is the strongest route. Stipendium Hungaricum names Palestine as a
  sending partner, funds bachelor's degrees, teaches in English, and lists both
  Mechatronical Engineering and Computer Science Engineering BSc at Óbuda University.
  The bottleneck is nomination by the Palestinian Ministry of Education and Higher
  Education, not the Hungarian form.
- **Italy** has two independent routes worth running in parallel: IUPALS, written
  specifically for Palestinian students and explicitly covering bachelor's degrees,
  and the regional right-to-study (DSU) grants, which are need-based and do not
  filter by nationality. MAECI is listed but does **not** fund bachelor's degrees.
- **Spain** has no national grant reachable from abroad — Beca MEC needs Spanish
  residence — but several universities run Palestine/Gaza refuge programmes that
  reach near-full funding. The real barriers are Spanish-language teaching and the
  UNEDasiss credential.
- **Switzerland** has no fully funded bachelor route for an applicant abroad. The
  federal Excellence Scholarship is postgraduate only, ETH aid needs Swiss residence
  and comes after the first-year exam, and cantonal grants need a residence permit.
- **Germany** is the strongest financial fact on the whole site, and it is not a
  scholarship — every public university charges zero tuition at bachelor level,
  for every nationality. The real cost is living expenses, gated behind a
  ~EUR 12,000/year blocked account for the visa, and the real barrier is language:
  most bachelor's are German-taught. DAAD's Bridge Scholarship only helps Palestinians
  already studying in Germany, not a way to get in.
- **Greece** runs a genuine Palestine-only route through its Jerusalem consulate —
  three scholarships a year, EUR 650/month, plus a free Greek course — small but real.
- **France** ran a genuine Gaza-specific bachelor scholarship for 2024/25. No renewal
  for the current cycle has been confirmed — the tracker watches the Campus France page
  and will flag it the moment that changes.
- **UAE** has a real merit route at Khalifa University (full tuition, no confirmed
  living stipend) and a Palestinian Embassy community scholarship whose current status
  could not be verified past 2021-era reporting — worth a direct call to the embassy.
- **Cyprus** and **Poland** have nothing fully funded and bachelor-level reachable by
  an applicant abroad, after a thorough search of both. Cyprus's one Palestine-specific
  programme (University of Cyprus) is postgraduate only; Poland's one bachelor-level
  government scholarship is restricted to applicants of Polish descent. Both stay on
  this site, like Switzerland, so a real route appearing gets noticed.
  It stays in the tracker so you can see the day that changes.
