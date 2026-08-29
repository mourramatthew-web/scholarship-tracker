"""Network side of the daily run: link health, email discovery, change detection.

Everything here is best-effort. A university web server having a bad morning
must never take the site build down, so every failure becomes a status string
rather than an exception.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import socket
import ssl
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from html.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 ScholarshipTracker/1.0"
)
TIMEOUT = 25
MAX_WORKERS = 8
MAX_BYTES = 3_000_000

# Words worth telling the user about when they appear on a watched page.
SIGNAL_WORDS = [
    "palestin", "gaza", "bachelor", "undergraduate", "laurea triennale",
    "deadline", "scadenza", "plazo", "convocatoria", "bando", "call for applications",
    "fully funded", "borsa di studio", "beca", "stipendium", "apply now",
]


@dataclass
class LinkResult:
    url: str
    ok: bool
    status: str          # "200", "404", "timeout", "ssl error", ...
    final_url: str = ""
    checked: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageResult:
    url: str
    ok: bool
    status: str
    digest: str = ""
    text_length: int = 0
    emails: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    date_tokens: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# Anything that looks like a date, in the four languages these pages are
# written in. A change in this set is the signal worth waking someone up for;
# a rotating news carousel is not.
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre"
    "|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    "|januar|februar|marz|april|mai|juni|juli|august|september|oktober|november|dezember"
)
DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b"),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\b", re.I),
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I),
    re.compile(r"\b20\d{2}\s*[/-]\s*20?\d{2}\b"),
]


def _date_tokens(text: str) -> list[str]:
    found: set[str] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.findall(text):
            found.add(re.sub(r"\s+", " ", match).strip().lower())
    return sorted(found)[:120]


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.mailtos: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value and value.lower().startswith("mailto:"):
                    self.mailtos.append(value[7:].split("?")[0].strip())

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self.chunks.append(stripped)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.chunks))


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_EMAIL_JUNK = (
    "example.com", "domain.com", "email.com", "sentry.io", "wixpress.com",
    "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js",
)


def _clean_emails(candidates) -> list[str]:
    seen: dict[str, None] = {}
    for raw in candidates:
        addr = raw.strip().strip(".,;:<>()[]\"'").lower()
        if not EMAIL_RE.fullmatch(addr):
            continue
        if any(junk in addr for junk in _EMAIL_JUNK):
            continue
        if len(addr) > 80:
            continue
        seen.setdefault(addr, None)
    return list(seen)[:8]


def _decode(raw: bytes, headers) -> str:
    encoding = (headers.get("Content-Encoding") or "").lower()
    try:
        if "gzip" in encoding:
            raw = gzip.decompress(raw)
        elif "deflate" in encoding:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    except OSError:
        pass
    charset = "utf-8"
    ctype = headers.get("Content-Type") or ""
    match = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def _build_context() -> ssl.SSLContext:
    """Verifying context that also trusts the Windows certificate stores.

    Python does not read the Windows store by default, so several European
    university sites fail with "unable to get local issuer certificate" purely
    because their intermediate CA lives there. Pulling ROOT and CA in fixes it
    without weakening verification.
    """
    context = ssl.create_default_context()
    enumerate_certs = getattr(ssl, "enum_certificates", None)
    if enumerate_certs is not None:
        for store in ("ROOT", "CA"):
            try:
                certs = enumerate_certs(store)
            except Exception:  # noqa: BLE001 - not on Windows, or store unreadable
                continue
            for cert, encoding, trust in certs:
                if encoding != "x509_asn":
                    continue
                if trust is not True and "1.3.6.1.5.5.7.3.1" not in (trust or ()):
                    continue
                try:
                    context.load_verify_locations(cadata=cert)
                except ssl.SSLError:
                    pass
    return context


_VERIFYING = _build_context()

_PERMISSIVE = ssl.create_default_context()
_PERMISSIVE.check_hostname = False
_PERMISSIVE.verify_mode = ssl.CERT_NONE

# URLs whose certificate chain could not be verified on this machine. We still
# read them (they are public pages and we send nothing), but the site says so.
CERT_UNVERIFIED: set[str] = set()


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,it;q=0.8,es;q=0.8,hu;q=0.7",
            "Accept-Encoding": "gzip, deflate",
        },
    )


def _open(url: str):
    try:
        return urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=_VERIFYING)
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        # Fall back once, and record that we had to.
        CERT_UNVERIFIED.add(url)
        return urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=_PERMISSIVE)


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return str(exc.code)
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return "timeout"
        if isinstance(reason, ssl.SSLError):
            return "ssl error"
        return f"unreachable ({type(reason).__name__})"
    if isinstance(exc, socket.timeout):
        return "timeout"
    return f"error ({type(exc).__name__})"


def check_link(url: str, stamp: str) -> LinkResult:
    try:
        with _open(url) as response:
            response.read(2048)
            code = getattr(response, "status", 200)
            final = response.geturl()
        status = "cert-unverified" if url in CERT_UNVERIFIED else str(code)
        return LinkResult(url, 200 <= code < 400, status, final, stamp)
    except urllib.error.HTTPError as exc:
        # 403 usually means a bot wall, not a dead page. Say so rather than
        # scaring the reader with a red badge.
        soft = exc.code in (403, 405, 429, 999)
        return LinkResult(url, soft, "bot-blocked" if soft else str(exc.code), url, stamp)
    except Exception as exc:  # noqa: BLE001 - deliberately total
        return LinkResult(url, False, _describe_error(exc), "", stamp)


def fetch_page(url: str) -> PageResult:
    try:
        with _open(url) as response:
            raw = response.read(MAX_BYTES)
            ctype = (response.headers.get("Content-Type") or "").lower()
            html = _decode(raw, response.headers)
    except Exception as exc:  # noqa: BLE001
        return PageResult(url, False, _describe_error(exc))

    if "pdf" in ctype or url.lower().endswith(".pdf"):
        digest = hashlib.sha256(raw).hexdigest()[:16]
        return PageResult(url, True, "200", digest, len(raw), [], [])

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed markup happens
        pass
    text = parser.text()
    lowered = text.lower()

    signals = []
    for word in SIGNAL_WORDS:
        index = lowered.find(word)
        if index == -1:
            continue
        start, end = max(0, index - 90), min(len(text), index + 140)
        snippet = text[start:end].strip()
        signals.append(f"{word}: ...{snippet}...")

    emails = _clean_emails(parser.mailtos + EMAIL_RE.findall(text))
    digest = hashlib.sha256(lowered.encode("utf-8")).hexdigest()[:16]
    return PageResult(url, True, "200", digest, len(text), emails, signals[:6],
                      _date_tokens(lowered))


def check_links(urls, stamp: str) -> dict[str, LinkResult]:
    urls = list(dict.fromkeys(urls))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = pool.map(lambda u: check_link(u, stamp), urls)
    return {r.url: r for r in results}


def fetch_pages(urls) -> dict[str, PageResult]:
    urls = list(dict.fromkeys(urls))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = pool.map(fetch_page, urls)
    return {r.url: r for r in results}
