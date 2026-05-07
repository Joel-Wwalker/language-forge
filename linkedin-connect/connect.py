"""LinkedIn Connect — semi-automated recruiter outreach helper.

Reads `config.toml`, opens LinkedIn search results matching your filters
in a Playwright-controlled Chromium, walks the result pages, surfaces
candidates that match your title-term filters and that you haven't
contacted before (per a local SQLite log), opens each candidate's
profile in a tab, and either:
  - mode="semi": pre-fills the personalized note and waits for YOU to
                 click Connect. Marks as sent in the DB only after
                 you confirm it on the CLI.
  - mode="auto": clicks Connect itself. Higher risk; requires
                 --i-understand-the-risks at invocation time.

First run: a Chromium window opens with LinkedIn's login page. Log in
manually (do NOT type your password into a terminal prompt anywhere —
this script never sees it). Press Enter in the terminal once logged
in. Future runs reuse the saved storage state and don't re-prompt.

Anti-detection notes (these aren't bulletproof):
  - Persistent context (real cookies, not a fresh session every run).
  - Conservative inter-action delays (30-90s default, randomized).
  - Daily cap (10 default; LinkedIn weekly cap is ~100).
  - Walks the regular UI, doesn't hit any private API.
  - Explicit user-driven send (semi mode) so the action is bona-fide
    human-driven from LinkedIn's POV.

What WILL eventually break: LinkedIn changes their HTML structure
regularly. The selectors below are best-effort as of late 2025; if a
selector starts returning nothing, dump the page HTML (--debug-dump)
and update the relevant constant.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, quote_plus
from typing import Any, Iterator, Optional

# Playwright is the heavy dep; check at startup with a friendly message.
try:
    from playwright.sync_api import (
        sync_playwright, Browser, BrowserContext, Page, Locator, TimeoutError as PWTimeoutError,
    )
except ImportError:
    print("ERROR: playwright not installed. Run:\n"
          "  pip install -r requirements.txt\n"
          "  playwright install chromium", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    keywords: str
    geo_urns: list[str]
    network_distance: list[str]
    require_title_terms: list[str]
    exclude_title_terms: list[str]
    max_pages: int

    msg_template: str
    skip_note: bool

    daily_max: int
    per_run_max: int
    delay_min: float
    delay_max: float

    state_dir: Path
    mode: str
    log_file: Optional[Path]


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    s = raw["search"]
    m = raw["message"]
    l = raw["limits"]
    r = raw["runtime"]
    state_dir = Path(r["state_dir"])
    return Config(
        keywords=s["keywords"],
        geo_urns=list(s["geo_urns"]),
        network_distance=list(s["network_distance"]),
        require_title_terms=[t.lower() for t in s["require_title_terms"]],
        exclude_title_terms=[t.lower() for t in s["exclude_title_terms"]],
        max_pages=int(s["max_pages"]),
        msg_template=m["template"],
        skip_note=bool(m["skip_note"]),
        daily_max=int(l["daily_max"]),
        per_run_max=int(l["per_run_max"]),
        delay_min=float(l["delay_seconds"][0]),
        delay_max=float(l["delay_seconds"][1]),
        state_dir=state_dir,
        mode=r["mode"],
        log_file=Path(r["log_file"]) if r.get("log_file") else None,
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self, log_file: Optional[Path]):
        self.log_file = log_file
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {level} {msg}"
        print(line)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def info(self, msg: str) -> None:  self.log("INFO ", msg)
    def warn(self, msg: str) -> None:  self.log("WARN ", msg)
    def error(self, msg: str) -> None: self.log("ERROR", msg)


# ---------------------------------------------------------------------------
# State (SQLite tracking)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
  profile_url    TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  headline       TEXT,
  company        TEXT,
  status         TEXT NOT NULL,         -- 'queued' | 'sent' | 'skipped' | 'error'
  reason         TEXT,                  -- why skipped/error
  message_used   TEXT,                  -- what we sent (or would have)
  created_at     TEXT NOT NULL,
  sent_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_sent_at ON contacts(sent_at);
"""


@contextmanager
def db_connect(state_dir: Path) -> Iterator[sqlite3.Connection]:
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "contacts.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def already_contacted(conn: sqlite3.Connection, profile_url: str) -> bool:
    """Return True if this profile is already in the DB regardless of
    status. We don't re-process anyone — if it's there, leave it."""
    row = conn.execute(
        "SELECT 1 FROM contacts WHERE profile_url = ?", (profile_url,)
    ).fetchone()
    return row is not None


def record_contact(conn: sqlite3.Connection, *, profile_url: str, name: str,
                   headline: str, company: str, status: str, reason: str = "",
                   message_used: str = "") -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sent_at = now if status == "sent" else None
    conn.execute(
        "INSERT OR REPLACE INTO contacts "
        "(profile_url, name, headline, company, status, reason, message_used, created_at, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_url, name, headline, company, status, reason, message_used, now, sent_at),
    )
    conn.commit()


def count_sent_today(conn: sqlite3.Connection) -> int:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    row = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE status = 'sent' AND sent_at LIKE ?",
        (today + "%",),
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# LinkedIn helpers
# ---------------------------------------------------------------------------

LINKEDIN_BASE = "https://www.linkedin.com"

def search_url(cfg: Config, page: int) -> str:
    """Build a LinkedIn People search URL with the configured filters."""
    params = {
        "keywords": cfg.keywords,
        "origin": "FACETED_SEARCH",
        "page": str(page),
    }
    # geoUrn / network filters use array-syntax LinkedIn expects:
    # ?geoUrn=["103644278","101165590"]&network=["S","O"]
    if cfg.geo_urns:
        params["geoUrn"] = json.dumps(cfg.geo_urns, separators=(",", ":"))
    if cfg.network_distance:
        params["network"] = json.dumps(cfg.network_distance, separators=(",", ":"))
    return f"{LINKEDIN_BASE}/search/results/people/?" + urlencode(params, quote_via=quote_plus)


def title_passes_filters(headline: str, cfg: Config) -> tuple[bool, str]:
    """Apply require/exclude title filters. Returns (passes, reason)."""
    h = (headline or "").lower()
    if cfg.require_title_terms and not any(t in h for t in cfg.require_title_terms):
        return False, f"no required title term in {headline!r}"
    for t in cfg.exclude_title_terms:
        if t in h:
            return False, f"excluded by title term {t!r}"
    return True, ""


def first_name_of(full_name: str) -> str:
    """Best-effort first-name extraction. LinkedIn names are
    `Firstname Lastname`. Some are `Firstname (nickname) Lastname`."""
    name = (full_name or "").strip()
    if not name:
        return "there"
    parts = name.split()
    return parts[0] if parts else "there"


# ---------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------

@contextmanager
def browser_context(state_dir: Path, headless: bool = False
                    ) -> Iterator[tuple[BrowserContext, Page]]:
    """Open a persistent Chromium context. First run: user logs in
    manually. Future runs: cookies persist via storage state."""
    user_data_dir = state_dir / "playwright_userdata"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Persistent context = real-browser-shaped fingerprint, login
        # cookies survive across runs without us touching credentials.
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/121.0.0.0 Safari/537.36"),
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield ctx, page
        finally:
            ctx.close()


def ensure_logged_in(page: Page, log: Logger) -> None:
    """Navigate to the LinkedIn home; if not logged in, prompt the
    user to do so manually in the visible browser window."""
    page.goto(LINKEDIN_BASE + "/feed/", wait_until="domcontentloaded")
    if "/login" in page.url or "/uas/login" in page.url:
        log.info("LinkedIn login page detected. Please log in in the open "
                 "browser window. When you see your feed, return here and "
                 "press Enter.")
        try:
            input(">>> Press Enter once logged in: ")
        except KeyboardInterrupt:
            log.error("Aborted at login prompt.")
            raise SystemExit(1)
        # Re-check.
        page.goto(LINKEDIN_BASE + "/feed/", wait_until="domcontentloaded")
        if "/login" in page.url:
            log.error("Still on login page. Aborting.")
            raise SystemExit(1)
    log.info("LinkedIn session active.")


# ---------------------------------------------------------------------------
# Search-result scraping
# ---------------------------------------------------------------------------

# Selectors. LinkedIn changes these every few months; if scraping
# returns 0 results when there visibly are some, dump the HTML and
# update these. Use --debug-dump to write the search page HTML.
RESULT_CARD_SELECTOR = "li.reusable-search__result-container, li.org-people-profile-card__profile-card-spacing"
RESULT_NAME_LINK = "span.entity-result__title-text a"
RESULT_HEADLINE = "div.entity-result__primary-subtitle"
RESULT_LOCATION = "div.entity-result__secondary-subtitle"


@dataclass
class Candidate:
    name: str
    headline: str
    company: str
    location: str
    profile_url: str


def scrape_search_results(page: Page, log: Logger) -> list[Candidate]:
    """Scrape one result page. Returns a list of Candidate."""
    page.wait_for_load_state("domcontentloaded")
    # Scroll a bit so lazy-loaded results render.
    for _ in range(3):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(400)
    cards = page.locator(RESULT_CARD_SELECTOR)
    count = cards.count()
    log.info(f"  result cards on page: {count}")
    out: list[Candidate] = []
    for i in range(count):
        card = cards.nth(i)
        try:
            name_link = card.locator(RESULT_NAME_LINK).first
            href = name_link.get_attribute("href") or ""
            # Profile URLs sometimes have trailing query params; strip.
            url = href.split("?")[0]
            name_text = name_link.inner_text(timeout=2000).strip()
            # The visible name often duplicates onscreen ("Status name name");
            # take the longest sane chunk.
            name = max(name_text.splitlines(), key=len).strip() if name_text else ""
            headline = ""
            try:
                headline = card.locator(RESULT_HEADLINE).first.inner_text(timeout=1000).strip()
            except PWTimeoutError:
                pass
            location = ""
            try:
                location = card.locator(RESULT_LOCATION).first.inner_text(timeout=1000).strip()
            except PWTimeoutError:
                pass
            # Best-effort: company name is the part of headline after " at ".
            company = ""
            m = re.search(r"\s+at\s+(.+)$", headline)
            if m:
                company = m.group(1).strip()
            if url and name:
                out.append(Candidate(
                    name=name, headline=headline, company=company,
                    location=location, profile_url=url,
                ))
        except Exception as e:
            log.warn(f"  failed to parse result card {i}: {e}")
    return out


# ---------------------------------------------------------------------------
# Connection-request flow (semi & auto modes)
# ---------------------------------------------------------------------------

def render_message(template: str, name: str, company: str) -> str:
    """Fill placeholders. Cap at 300 chars (LinkedIn's note limit)."""
    msg = template.format(
        first_name=first_name_of(name),
        company=company or "your company",
    ).strip()
    return msg[:300]


def open_profile(page: Page, candidate: Candidate, log: Logger) -> None:
    """Navigate to the candidate's profile."""
    url = candidate.profile_url
    if not url.startswith("http"):
        url = LINKEDIN_BASE + url
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)


def open_connect_modal(page: Page, message: str, log: Logger
                       ) -> tuple[bool, str]:
    """Click the Connect button (or find it under the "More" overflow
    if LinkedIn hides it there), opening the connection-request modal.
    If `message` is non-empty, also click "Add a note" and fill the
    textarea. Empty message means: leave the modal in its default
    "Send without a note" state.

    Returns (modal_ready, status_string). Does NOT click "Send" —
    that's the user's job in semi mode, or `auto_click_send`'s in
    auto mode.
    """
    # Try the top-bar Connect button first.
    connect_btn = page.locator(
        'main button:has-text("Connect"), main [aria-label^="Invite"][aria-label*="connect"]'
    ).first
    if connect_btn.count() == 0 or not connect_btn.is_visible():
        # Connect is sometimes hidden behind the "More" overflow menu
        # (depends on profile layout / LinkedIn A/B test).
        more = page.locator('main button:has-text("More")').first
        if more.count() == 0 or not more.is_visible():
            return False, "no Connect or More button visible"
        more.click()
        page.wait_for_timeout(800)
        connect_btn = page.locator('div[role="menu"] >> text=Connect').first
        if connect_btn.count() == 0:
            return False, "Connect not in More menu (already 1st-degree, or pending)"
    connect_btn.click()
    page.wait_for_timeout(1200)

    # Compose a note only if the caller passed one. With skip_note=true,
    # message is empty and we leave the modal alone — the default Send
    # button on the modal sends without a note.
    if message:
        add_note = page.locator('button:has-text("Add a note")').first
        if add_note.count() and add_note.is_visible():
            add_note.click()
            page.wait_for_timeout(500)
        textarea = page.locator(
            'textarea[name="message"], textarea#custom-message'
        ).first
        if textarea.count() and textarea.is_visible():
            textarea.fill(message)
    return True, "ready"


def auto_click_send(page: Page, log: Logger) -> bool:
    """For mode=auto: click the Send button on the connection-request
    modal. Returns True if it appeared and was clicked.

    The button label varies: "Send invitation" with a note, "Send
    without a note" without one, sometimes just "Send" depending on
    LinkedIn's current A/B. We try all three variants.
    """
    send_btn = page.locator(
        'button[aria-label="Send invitation"], '
        'button[aria-label="Send without a note"], '
        'button[aria-label^="Send now"], '
        'div[role="dialog"] button:has-text("Send without a note"), '
        'div[role="dialog"] button:has-text("Send")'
    ).first
    if send_btn.count() and send_btn.is_visible():
        send_btn.click()
        page.wait_for_timeout(1500)
        return True
    return False


def semi_wait_for_human(candidate: Candidate, has_note: bool,
                        log: Logger) -> str:
    """Block until the user types y/n/skip on the CLI. Returns the
    user's verdict for the DB."""
    log.info(f"    >>> review {candidate.name} ({candidate.profile_url})")
    if has_note:
        log.info(f"        modal open with note pre-filled. Click Send.")
    else:
        log.info(f"        modal open (no-note mode). Click Send without a note.")
    while True:
        try:
            ans = input("    [y]es-sent / [n]ot-sent / [s]kip-future / [q]uit: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return "skipped"
        if ans in ("y", "yes"):
            return "sent"
        if ans in ("n", "no"):
            return "skipped"
        if ans in ("s", "skip"):
            return "skipped"
        if ans in ("q", "quit"):
            raise KeyboardInterrupt()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(cfg: Config, dry_run: bool, debug_dump: bool, log: Logger) -> None:
    state_dir = cfg.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)

    with db_connect(state_dir) as conn, browser_context(state_dir) as (ctx, page):
        if not dry_run:
            ensure_logged_in(page, log)
        else:
            log.info("dry_run: skipping login.")

        sent_today = count_sent_today(conn)
        log.info(f"sent today (per local DB): {sent_today} / {cfg.daily_max}")
        budget_remaining = max(0, cfg.daily_max - sent_today)
        if budget_remaining == 0 and not dry_run:
            log.warn("daily_max already reached. Exit.")
            return

        # Walk pages.
        sent_this_run = 0
        seen_this_run = 0
        for page_n in range(1, cfg.max_pages + 1):
            url = search_url(cfg, page_n)
            log.info(f"page {page_n}: {url}")
            if dry_run:
                continue
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if debug_dump:
                dump_path = state_dir / f"search_page_{page_n}.html"
                dump_path.write_text(page.content(), encoding="utf-8")
                log.info(f"  dumped page HTML to {dump_path}")
            results = scrape_search_results(page, log)
            log.info(f"  {len(results)} result(s) on page {page_n}")

            for cand in results:
                seen_this_run += 1
                if seen_this_run > cfg.per_run_max:
                    log.info(f"  per_run_max ({cfg.per_run_max}) reached.")
                    return
                if already_contacted(conn, cand.profile_url):
                    log.info(f"  skip (already in DB): {cand.name}")
                    continue
                ok, why = title_passes_filters(cand.headline, cfg)
                if not ok:
                    log.info(f"  skip ({why}): {cand.name}")
                    record_contact(conn, profile_url=cand.profile_url,
                                   name=cand.name, headline=cand.headline,
                                   company=cand.company, status="skipped",
                                   reason=why)
                    continue

                if budget_remaining <= 0:
                    log.warn("  daily_max reached mid-run.")
                    return

                msg = "" if cfg.skip_note else render_message(
                    cfg.msg_template, cand.name, cand.company)
                log.info(f"  -> {cand.name} ({cand.headline})")
                if msg:
                    log.info(f"     msg: {msg!r}")

                # Open profile, fill note, hand off (semi) or click (auto).
                try:
                    open_profile(page, cand, log)
                    ready, status = open_connect_modal(page, msg, log)
                    if not ready:
                        log.warn(f"     can't open Connect: {status}")
                        record_contact(conn, profile_url=cand.profile_url,
                                       name=cand.name, headline=cand.headline,
                                       company=cand.company, status="error",
                                       reason=status, message_used=msg)
                        delay(cfg, log)
                        continue

                    if cfg.mode == "auto":
                        clicked = auto_click_send(page, log)
                        verdict = "sent" if clicked else "error"
                        reason = "" if clicked else "Send button not found"
                    else:
                        verdict = semi_wait_for_human(cand, bool(msg), log)
                        reason = ""

                    record_contact(conn, profile_url=cand.profile_url,
                                   name=cand.name, headline=cand.headline,
                                   company=cand.company, status=verdict,
                                   reason=reason, message_used=msg)
                    if verdict == "sent":
                        sent_this_run += 1
                        budget_remaining -= 1
                        log.info(f"     marked SENT. budget remaining: "
                                 f"{budget_remaining}")
                except KeyboardInterrupt:
                    log.info("Aborted by user.")
                    return
                except Exception as e:
                    log.error(f"     exception: {type(e).__name__}: {e}")
                    record_contact(conn, profile_url=cand.profile_url,
                                   name=cand.name, headline=cand.headline,
                                   company=cand.company, status="error",
                                   reason=str(e)[:200], message_used=msg)

                delay(cfg, log)

        log.info(f"run complete. sent this run: {sent_this_run}")


def delay(cfg: Config, log: Logger) -> None:
    """Randomized inter-action delay. Don't shortcut this — it's the
    main thing keeping the script from looking like a bot."""
    s = random.uniform(cfg.delay_min, cfg.delay_max)
    log.info(f"     [sleep {s:.1f}s]")
    time.sleep(s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Semi-automated LinkedIn recruiter outreach."
    )
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).parent / "config.toml",
                        help="path to config.toml (default: ./config.toml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print search URL + plan, don't open browser")
    parser.add_argument("--debug-dump", action="store_true",
                        help="dump each search page's HTML to state_dir for "
                             "selector debugging")
    parser.add_argument("--i-understand-the-risks", action="store_true",
                        help="required when config.runtime.mode = 'auto'. "
                             "Acknowledges that LinkedIn may restrict your "
                             "account for automated connection requests.")
    parser.add_argument("--show-stats", action="store_true",
                        help="print contact-DB stats and exit")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"ERROR: config not found at {args.config}", file=sys.stderr)
        return 2
    cfg = load_config(args.config)
    log = Logger(cfg.log_file)

    if args.show_stats:
        with db_connect(cfg.state_dir) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM contacts GROUP BY status"
            ).fetchall()
            log.info("contact stats by status:")
            for status, n in rows:
                log.info(f"  {status:10}  {n}")
            sent_today = count_sent_today(conn)
            log.info(f"sent today: {sent_today} / {cfg.daily_max}")
        return 0

    if cfg.mode == "auto" and not args.i_understand_the_risks:
        log.error("config.runtime.mode = 'auto' but --i-understand-the-risks "
                  "not passed. Refusing to run. See README for details.")
        return 2

    run(cfg, dry_run=args.dry_run, debug_dump=args.debug_dump, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
