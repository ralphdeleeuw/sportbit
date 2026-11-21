#!/usr/bin/env python3
"""
SugarWOD WOD Fetcher for CrossFit Hilversum

Authenticates against SugarWOD's internal REST API, fetches the workout
calendar (the same XHR endpoint the web app uses), and stores the data in a
GitHub Gist for display in the SportBit dashboard.

Usage:
    python3 fetch_sugarwod.py

Environment variables:
    SUGARWOD_EMAIL    - SugarWOD account email (required)
    SUGARWOD_PASSWORD - SugarWOD account password (required)
    GIST_ID          - GitHub Gist ID for storing WOD data
    GITHUB_TOKEN     - GitHub personal access token with gist scope
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from gist_utils import file_content as gist_file_content
from injuries import parse_injuries

from sugarwod_config import (  # noqa: E501
    SUGARWOD_BASE,
    LOGIN_URL,
    WORKOUTS_URL,
    GIST_FILENAME,
    AMS,
    BROWSER_HEADERS,
    BARBELL_LIFTS_FALLBACK,
    ATHLETE_PROFILE,
    _MAIN_KEYWORDS,
)

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sugarwod")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def get_monday(dt: datetime) -> datetime:
    d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


# ──────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────

def login(session: requests.Session, email: str, password: str) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Log in to SugarWOD and return (csrf, session_token, athlete_id, affiliate_id).

    SugarWOD uses "double-submit cookie" CSRF protection:
    1. A GET to any page sets the _csrf cookie.
    2. That value must be included as the _csrf query/body param when POSTing.
    3. After login the same cookie value is used in all subsequent XHR requests.
    """
    log.info("Logging in as %s", email)

    # Step 1: Visit sign-in page to establish session / get CSRF cookie
    resp = session.get(f"{SUGARWOD_BASE}/athletes/sign_in", timeout=30)
    resp.raise_for_status()
    log.info("Sign-in page: HTTP %d, final URL: %s", resp.status_code, resp.url)
    log.info("Cookies after sign-in page: %s", {k: v[:20] + "…" if len(v) > 20 else v
                                                  for k, v in session.cookies.items()})

    csrf = _extract_csrf(session, resp)
    log.info("CSRF token before login: %s", csrf[:20] + "…" if csrf else "none")

    # Step 2: POST credentials with CSRF token.
    #
    # The login endpoint requires a valid CSRF token — without it the server
    # returns HTTP 200 {"success":false,"message":"Your session has expired..."}.
    # With CSRF the token passes validation; we then try multiple credential
    # field-name conventions until one is accepted by Passport.js.
    #
    # Extra browser headers (Origin, Referer) are required: some csurf
    # configurations reject requests that lack them even with a correct token.
    login_headers = {
        "Accept": "application/json",
        "Origin": SUGARWOD_BASE,
        "Referer": f"{SUGARWOD_BASE}/login",
        "X-Requested-With": "XMLHttpRequest",
    }

    attempts = [
        # description, kwargs (csrf added below)
        ("JSON email/password + X-CSRF-Token header",
         dict(json={"email": email, "password": password})),
        ("JSON username/password + X-CSRF-Token header",
         dict(json={"username": email, "password": password})),
        ("JSON nested athlete{email,password} + X-CSRF-Token header",
         dict(json={"athlete": {"email": email, "password": password}})),
        ("JSON email/password/_csrf in body",
         dict(json={"email": email, "password": password, "_csrf": csrf})),
        ("form email/password + X-CSRF-Token header",
         dict(data={"email": email, "password": password})),
        ("form username/password + X-CSRF-Token header",
         dict(data={"username": email, "password": password})),
        ("form athlete[]/password + X-CSRF-Token header",
         dict(data={"athlete[email]": email, "athlete[password]": password})),
    ]

    resp = None
    for desc, kwargs in attempts:
        hdrs = {**login_headers, "X-CSRF-Token": csrf} if csrf else login_headers
        log.info("Trying login: %s", desc)
        r = session.post(LOGIN_URL, headers=hdrs, timeout=30, **kwargs)
        log.info("  → HTTP %d | %s", r.status_code, r.text[:120])
        if r.status_code in (200, 201):
            try:
                body = r.json()
                if isinstance(body, dict) and body.get("success") is True:
                    resp = r
                    break  # real success
                # success:false ("session expired" / wrong creds) → try next
            except ValueError:
                resp = r
                break  # non-JSON 200, assume success
            resp = r
            continue

        # 401 "Missing Credentials" → wrong field names; try next
        # Any other non-401 → unexpected failure, stop
        if r.status_code != 401:
            resp = r
            break
        resp = r  # keep last for error reporting

    log.info("Login response: HTTP %d, Content-Type: %s",
             resp.status_code, resp.headers.get("Content-Type", ""))
    log.info("Cookies after login: %s", {k: v[:30] + "…" if len(v) > 30 else v
                                          for k, v in session.cookies.items()})

    if resp.status_code not in (200, 201):
        log.error("Login failed with HTTP %d", resp.status_code)
        return None, None, None, None

    session_token = None
    athlete_id = None
    affiliate_id = None
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("success") is False:
            log.error("Login rejected: %s", body.get("message", ""))
            return None, None, None, None
        log.info("Login JSON: %s", body)
        # Extract Parse Server session token and user IDs for direct API access
        if isinstance(body, dict):
            data = body.get("data") or body
            session_token = data.get("sessionToken") or body.get("sessionToken")
            if session_token:
                log.info("Got Parse sessionToken: %s…", session_token[:20])
            # Athlete and affiliate object IDs from the Parse pointers
            ath = data.get("athlete") or {}
            aff = data.get("affiliate") or {}
            athlete_id = (
                data.get("athleteId")
                or (ath.get("objectId") if isinstance(ath, dict) else None)
            )
            affiliate_id = (
                data.get("affiliateId")
                or data.get("affiliateName") and None  # affiliateName is a string, skip
                or (aff.get("objectId") if isinstance(aff, dict) else None)
            )
            if athlete_id:
                log.info("Got athlete objectId: %s", athlete_id)
            if affiliate_id:
                log.info("Got affiliate objectId: %s", affiliate_id)
    except ValueError:
        pass

    # Step 3: regenerate CSRF from the (now authenticated) _sw_session cookie
    new_csrf = _generate_csrf_from_session(session)
    if new_csrf:
        log.info("CSRF token after login: %s", new_csrf[:20] + "…")
        return new_csrf, session_token, athlete_id, affiliate_id

    log.warning("Could not generate CSRF token after login")
    return csrf, session_token, athlete_id, affiliate_id


def _generate_csrf_from_session(session: requests.Session) -> str | None:
    """
    SugarWOD uses the Express.js `csurf` middleware.  The CSRF secret is stored
    in the _sw_session cookie as base64-encoded JSON {"csrfSecret": "..."}.
    The token is generated client-side (by the SPA's JS) as:

        salt     = 8 random bytes → base64url (no padding)
        token    = salt + "-" + base64url(SHA1(salt + "-" + secret))

    We replicate this in Python so we can send a valid _csrf without a browser.
    """
    sw_session = session.cookies.get("_sw_session")
    if not sw_session:
        log.warning("No _sw_session cookie found")
        return None

    # URL-decode if needed, then base64-decode
    try:
        from urllib.parse import unquote
        raw = unquote(sw_session)
        # Strip signature part (cookie-session signs as "payload.sig")
        payload = raw.split(".")[0]
        padded = payload + "=" * (4 - len(payload) % 4)
        data = json.loads(base64.b64decode(padded))
        secret = data.get("csrfSecret") or data.get("csrf_secret")
    except Exception as exc:
        log.warning("Could not decode _sw_session cookie: %s", exc)
        log.debug("_sw_session raw value: %s", sw_session[:100])
        return None

    if not secret:
        log.warning("csrfSecret not found in _sw_session cookie. Keys: %s",
                    list(data.keys()) if isinstance(data, dict) else "?")
        return None

    # Generate csurf-compatible token
    salt = base64.urlsafe_b64encode(os.urandom(8)).decode().rstrip("=")
    digest = hashlib.sha1(f"{salt}-{secret}".encode("ascii")).digest()
    token = salt + "-" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    log.info("Generated CSRF token from _sw_session secret")
    return token


def _extract_csrf(session: requests.Session, resp: requests.Response) -> str | None:
    """Try all known CSRF token sources."""
    # 1. Generate from _sw_session cookie (primary method for SugarWOD)
    token = _generate_csrf_from_session(session)
    if token:
        return token

    # 2. Explicit CSRF cookie
    for name in ("_csrf", "csrfToken", "XSRF-TOKEN"):
        val = session.cookies.get(name)
        if val:
            return val

    # 3. JSON response body
    try:
        data = resp.json()
        if isinstance(data, dict):
            for key in ("csrf", "_csrf", "csrfToken", "token", "csrf_token"):
                if data.get(key):
                    return data[key]
    except ValueError:
        pass

    # 4. HTML <meta name="csrf-token">
    soup = BeautifulSoup(resp.text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]

    return None


# ──────────────────────────────────────────────────────────────
# Workout fetching
# ──────────────────────────────────────────────────────────────

def _extract_barbell_from_page(page) -> dict:
    """Extract the Current Barbell Maxes table from the athlete barbell page."""
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        log.warning("[browser] No table found on barbell page")
        return {}
    try:
        result = page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = [...table.querySelectorAll('th')].map(th => th.textContent.trim());
                const hasBarbell = headers.some(h => /barbell/i.test(h) || /lift/i.test(h));
                const hasRM = headers.some(h => /\\dRM/.test(h));
                if (!hasBarbell && !hasRM) continue;
                const rmHeaders = headers.slice(1).filter(h => /\\dRM/.test(h));
                const rows = [...table.querySelectorAll('tbody tr')];
                const lifts = {};
                for (const row of rows) {
                    const cells = [...row.querySelectorAll('td')];
                    if (cells.length < 2) continue;
                    const liftName = cells[0].textContent.trim();
                    if (!liftName) continue;
                    const values = {};
                    for (let i = 0; i < rmHeaders.length; i++) {
                        const valText = (cells[i + 1] || {textContent: ''}).textContent.trim();
                        const num = parseFloat(valText);
                        if (!isNaN(num) && num > 0) values[rmHeaders[i]] = num;
                    }
                    if (Object.keys(values).length > 0) lifts[liftName] = values;
                }
                if (Object.keys(lifts).length > 0) return lifts;
            }
            return {};
        }
        """)
        return result or {}
    except Exception as exc:
        log.warning("[browser] Failed to extract barbell table: %s", exc)
        return {}


def _extract_prs_from_page(page) -> list[dict]:
    """Extract the Personal Records from the athlete PRs page.

    Tries <table> first; falls back to generic card/row div extraction
    for SPAs that don't use traditional tables.
    """
    # Try table-based layout
    try:
        page.wait_for_selector("table, [class*='pr'], [class*='PR'], [class*='personal'], [class*='record']", timeout=8000)
    except Exception:
        log.warning("[browser] No PR elements found on PRs page")
        return []
    try:
        result = page.evaluate("""
        () => {
            // ── 1. Table-based layout ─────────────────────────────────────
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = [...table.querySelectorAll('th')].map(th => th.textContent.trim());
                const hasPR = headers.some(h => /pr|workout|personal/i.test(h));
                if (!hasPR) continue;
                const rows = [...table.querySelectorAll('tbody tr')];
                const items = rows.map(row => {
                    const cells = [...row.querySelectorAll('td')];
                    return {
                        workout: (cells[0] || {textContent: ''}).textContent.trim(),
                        date:    (cells[1] || {textContent: ''}).textContent.trim(),
                        notes:   (cells[2] || {textContent: ''}).textContent.trim(),
                    };
                }).filter(r => r.workout);
                if (items.length) return items;
            }

            // ── 2. Card/row div layout ────────────────────────────────────
            // SugarWOD renders PR rows as divs with class names like
            // "pr-item", "PRItem", "personal-record", etc.
            const rowSelectors = [
                '[class*="pr-item"]', '[class*="PRItem"]', '[class*="PrItem"]',
                '[class*="personal-record"]', '[class*="PersonalRecord"]',
                '[class*="pr_item"]', '[class*="pr_row"]',
            ];
            for (const sel of rowSelectors) {
                const rows = document.querySelectorAll(sel);
                if (!rows.length) continue;
                const items = [...rows].map(row => {
                    const texts = [...row.querySelectorAll('span, div, p, td')]
                        .map(el => el.childElementCount === 0 ? el.textContent.trim() : '')
                        .filter(Boolean);
                    return {
                        workout: texts[0] || '',
                        date:    texts.find(t => /\\d{4}/.test(t)) || '',
                        notes:   texts.slice(1).filter(t => !/^\\d{4}/.test(t)).join(' ') || '',
                    };
                }).filter(r => r.workout);
                if (items.length) return items;
            }

            // ── 3. Generic list items with workout-like text ──────────────
            const allRows = document.querySelectorAll('li, [role="row"], [role="listitem"]');
            const candidates = [...allRows].filter(el => {
                const t = el.textContent;
                return t.length > 3 && t.length < 200 && /\\d/.test(t);
            });
            if (candidates.length > 3) {
                return candidates.map(el => {
                    const t = el.textContent.trim();
                    const dateMatch = t.match(/\\d{1,2}[\\/-]\\d{1,2}[\\/-]\\d{2,4}|\\d{4}-\\d{2}-\\d{2}/);
                    return {
                        workout: t.replace(dateMatch ? dateMatch[0] : '', '').trim(),
                        date:    dateMatch ? dateMatch[0] : '',
                        notes:   '',
                    };
                }).filter(r => r.workout.length > 1);
            }

            return [];
        }
        """)
        return result or []
    except Exception as exc:
        log.warning("[browser] Failed to extract PRs from page: %s", exc)
        return []


def _scrape_benchmark_table_js(page, category: str) -> list[dict]:
    """Scrape the currently-visible benchmark table and tag rows with the given category."""
    try:
        return page.evaluate("""
        (category) => {
            const tables = document.querySelectorAll('table');
            const RELEVANT = /name|benchmark|workout|result|score|time|reps|scaling|date|datum/i;
            for (const table of tables) {
                const thEls = [...table.querySelectorAll('th')];
                const headers = thEls.map(th => th.textContent.trim().toLowerCase());
                if (!headers.some(h => RELEVANT.test(h))) continue;

                // Build a dynamic column index map based on actual header text
                const idx = {};
                headers.forEach((h, i) => {
                    if (/name|benchmark|workout/i.test(h))       idx.name    = idx.name    ?? i;
                    if (/result|score|time|reps|value/i.test(h)) idx.result  = idx.result  ?? i;
                    if (/scal/i.test(h))                         idx.scaling = idx.scaling ?? i;
                    if (/date|datum/i.test(h))                   idx.date    = idx.date    ?? i;
                });

                const rows = [...table.querySelectorAll('tbody tr')];
                return rows.map(row => {
                    const cells = [...row.querySelectorAll('td')];
                    const cell = (i) => i !== undefined ? (cells[i] || {textContent: ''}).textContent.trim() : '';
                    return {
                        name:     cell(idx.name    ?? 0),
                        result:   cell(idx.result  ?? 1),
                        scaling:  cell(idx.scaling ?? 2),
                        date:     cell(idx.date    ?? 3),
                        category: category,
                    };
                }).filter(r => r.name);
            }
            return [];
        }
        """, category)
    except Exception as exc:
        log.warning("[browser] _scrape_benchmark_table_js error: %s", exc)
        return []



def _benchmarks_from_pr_rows(pr_rows: list[dict], captured: list[dict] | None = None) -> list[dict]:
    """Leid benchmark workouts af uit de PR-XHR (/api/results?prsOnly=true).

    Rijen met een gevuld 'lwId' (library workout id) zijn bibliotheek-workouts
    (Girls, Heroes, Notables, ...). SugarWOD geeft geen categorie mee; de
    bekende Girls worden op naam herkend, de rest heet 'Benchmark'.
    """
    out: list[dict] = []
    for r in pr_rows:
        if not (r.get("lwId") or r.get("libraryWorkout") or r.get("libraryId")):
            continue
        name = (r.get("title") or r.get("workoutTitle") or "").strip()
        if not name:
            continue
        date_raw = str(r.get("dateInt") or r.get("datePerformedInteger") or "")
        date = (f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                if len(date_raw) == 8 and date_raw.isdigit() else date_raw)
        scaling = r.get("scalingOption") or ""
        if isinstance(scaling, dict):
            scaling = scaling.get("name") or ""
        rx = r.get("rx", r.get("isRx"))
        if not scaling and rx is not None:
            scaling = "Rx" if rx else "Scaled"
        out.append({
            "name": name,
            "result": str(r.get("bestResultDisplayString") or r.get("result") or r.get("bestResult") or ""),
            "scaling": str(scaling),
            "date": date,
            "category": "Girls" if name.split()[0].lower() in _GIRLS_WODS else "Benchmark",
        })
    return out


_GIRLS_WODS = {
    "amanda", "angie", "annie", "barbara", "candy", "chelsea", "cindy", "diane",
    "elizabeth", "eva", "fran", "grace", "gwen", "helen", "hope", "isabel",
    "jackie", "karen", "kelly", "linda", "lynne", "maggie", "mary", "nancy", "nicole",
}


def _extract_benchmarks_from_page(page) -> list[dict]:
    """Extract all Benchmark Workouts by iterating through each category.

    Uses proper Playwright click interactions so React re-renders the table
    between category switches.  Falls back to scraping only the visible
    category if the dropdown cannot be found/clicked.
    """
    try:
        page.wait_for_selector(
            "table, [class*='benchmark'], [class*='Benchmark'], [class*='wod'], [class*='girls'], [class*='heroes']",
            timeout=10000,
        )
    except Exception:
        log.warning("[browser] No benchmark elements found on benchmarks page")
        return []

    all_benchmarks: list[dict] = []
    seen: set[str] = set()

    def add_rows(rows: list[dict]) -> None:
        for r in rows:
            key = f"{r['name']}|{r['date']}"
            if key not in seen:
                seen.add(key)
                all_benchmarks.append(r)

    # ── Strategy 1: native <select> element ────────────────────────────────
    try:
        select_el = page.query_selector("select")
        if select_el:
            options = page.evaluate(
                "() => [...document.querySelectorAll('select option')]"
                ".map(o => ({value: o.value, text: o.text.trim()}))"
            )
            log.info("[browser] Benchmark native select: %d options", len(options))
            for opt in options:
                try:
                    page.select_option("select", value=opt["value"])
                    page.wait_for_timeout(700)
                    add_rows(_scrape_benchmark_table_js(page, opt["text"] or opt["value"]))
                except Exception as exc:
                    log.warning("[browser] select option %s failed: %s", opt, exc)
            if all_benchmarks:
                log.info("[browser] Benchmarks via native select: %d", len(all_benchmarks))
                return all_benchmarks
    except Exception as exc:
        log.warning("[browser] Native select benchmark approach failed: %s", exc)

    # ── Strategy 2: custom React/Bootstrap dropdown ─────────────────────────
    try:
        # First scrape the default (already-visible) category
        current_label = page.evaluate(
            "() => {"
            "  const candidates = [...document.querySelectorAll('button')];"
            "  for (const b of candidates) {"
            "    if (/girls|heroes|open|named|other/i.test(b.textContent)) return b.textContent.trim();"
            "  }"
            "  return 'Unknown';"
            "}"
        )
        add_rows(_scrape_benchmark_table_js(page, current_label))
        log.info("[browser] Default category '%s': %d rows", current_label, len(all_benchmarks))

        # Find the dropdown trigger and collect all option texts
        trigger_sel = (
            "button[class*='dropdown'], button[class*='filter'], "
            "div[class*='dropdown'] button, [class*='Dropdown'] button"
        )
        trigger = page.query_selector(trigger_sel)
        if not trigger:
            # Broader fallback: any button whose text matches a known category
            trigger = page.evaluate_handle(
                "() => [...document.querySelectorAll('button')]"
                ".find(b => /girls|heroes|open|named|other/i.test(b.textContent)) || null"
            )

        if trigger:
            trigger.click()
            page.wait_for_timeout(500)
            item_sel = (
                "[class*='dropdown-item'], [class*='dropdown-menu'] li, "
                "[role='option'], [role='menuitem'], [class*='DropdownItem']"
            )
            items = page.query_selector_all(item_sel)
            option_texts = [i.inner_text().strip() for i in items if i.inner_text().strip()]
            log.info("[browser] Benchmark dropdown options: %s", option_texts)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            for text in option_texts:
                if text == current_label:
                    continue
                try:
                    trigger.click()
                    page.wait_for_timeout(400)
                    for item in page.query_selector_all(item_sel):
                        if item.inner_text().strip() == text:
                            item.click()
                            page.wait_for_timeout(800)
                            add_rows(_scrape_benchmark_table_js(page, text))
                            break
                except Exception as exc:
                    log.warning("[browser] Clicking benchmark option '%s' failed: %s", text, exc)
    except Exception as exc:
        log.warning("[browser] Custom dropdown benchmark approach failed: %s", exc)

    log.info("[browser] Total benchmark entries: %d", len(all_benchmarks))
    return all_benchmarks


def _extract_logbook_from_page(page) -> list[dict]:
    """Scrape the Athlete Logbook table (workouts athlete actually logged a score for).

    Returns a list of dicts with keys: date, workout, result.
    """
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        log.warning("[browser] No table found on logbook page")
        return []
    try:
        return page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = [...table.querySelectorAll('th')]
                    .map(th => th.textContent.trim().toLowerCase());
                // Logbook has a date column and a workout/wod column
                if (!headers.some(h => /date|datum/i.test(h))) continue;
                const rows = [...table.querySelectorAll('tbody tr')];
                return rows.map(row => {
                    const cells = [...row.querySelectorAll('td')];
                    return {
                        date:    (cells[0] || {textContent: ''}).textContent.trim(),
                        workout: (cells[1] || {textContent: ''}).textContent.trim(),
                        result:  (cells[2] || {textContent: ''}).textContent.trim(),
                    };
                }).filter(r => r.date && r.workout);
            }
            return [];
        }
        """) or []
    except Exception as exc:
        log.warning("[browser] Failed to extract logbook: %s", exc)
        return []


def fetch_all_workouts_playwright(
    email: str,
    password: str,
    weeks: list[datetime],
    gist_id: str = "",
    token: str = "",
) -> dict | None:
    """
    Use a headless Chromium browser to log in via the real HTML form and then
    intercept the XHR calls the SPA makes to load workout data.  Also scrapes
    barbell lifts and personal records from the athlete profile pages.

    Returns a dict with keys "workouts", "barbell_lifts", "personal_records",
    or None if the overall fetch failed.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.warning("playwright not installed; skipping browser approach")
        return None

    log.info("Starting Playwright headless browser")
    captured: list[dict] = []

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            # Skip third-party analytics calls
            if "sugarwod.com" not in url:
                return
            data = response.json()
            log.info("  [browser] %s → %s", url, str(data)[:200])
            captured.append({"url": url, "data": data})
        except Exception:
            pass

    all_workouts: list[dict] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("response", _on_response)

            # ── 1. Log in via the real HTML form ─────────────────────────
            # The browser handles CSRF tokens and cookies automatically.
            log.info("[browser] Navigating to login page")
            page.goto(f"{SUGARWOD_BASE}/login", wait_until="domcontentloaded",
                      timeout=30000)

            log.info("[browser] Filling login form")
            # Log all input fields found on the page for diagnostics
            try:
                inputs = page.evaluate("""
                    () => [...document.querySelectorAll('input')].map(i =>
                        ({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder}))
                """)
                log.info("[browser] Inputs on login page: %s", inputs)
                buttons = page.evaluate("""
                    () => [...document.querySelectorAll('button')].map(b =>
                        ({id: b.id, type: b.type, text: b.textContent.trim().slice(0,50)}))
                """)
                log.info("[browser] Buttons on login page: %s", buttons)
            except Exception as dbg_exc:
                log.warning("[browser] Could not log form fields: %s", dbg_exc)
            # Use type() (character-by-character) instead of fill() to ensure
            # React's synthetic onChange events fire on every keystroke.
            email_input = page.locator(
                'input[type="email"], input[name="email"], input[name="username"]'
            ).first
            email_input.click()
            email_input.type(email)

            # SugarWOD now uses a two-step login: email → CONTINUE → password.
            # Click CONTINUE and wait for the password field to become visible.
            try:
                cont = page.locator('#continue-button')
                cont.wait_for(state="visible", timeout=5000)
                cont.click()
                log.info("[browser] Clicked CONTINUE (two-step login)")
                page.locator('input[type="password"]').first.wait_for(
                    state="visible", timeout=10000
                )
                log.info("[browser] Password field now visible")
            except Exception as cont_exc:
                log.info("[browser] No CONTINUE step: %s", cont_exc)

            password_input = page.locator('input[type="password"]').first
            password_input.click()
            password_input.type(password)

            # Wait for React to re-enable the submit button (it starts disabled),
            # then click it. If it never enables, fall back to pressing Enter.
            try:
                page.locator('#login-button').wait_for(state="enabled", timeout=5000)
                page.locator('#login-button').click()
                log.info("[browser] Clicked enabled submit button")
            except Exception:
                log.info("[browser] Submit button still disabled; pressing Enter")
                password_input.press("Enter")

            # Wait for the SPA to redirect away from the login page
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/login')",
                    timeout=15000,
                )
                log.info("[browser] Login successful, now at: %s", page.url)
            except Exception as exc:
                log.warning("[browser] Login did not redirect: %s — %s", page.url, exc)
                # Check if we're still on login page (auth failed)
                if "/login" in page.url:
                    log.warning("[browser] Aborting — still on login page")
                    # Save page HTML to gist for diagnosis
                    try:
                        html_content = page.content()
                        if gist_id and token:
                            requests.patch(
                                f"https://api.github.com/gists/{gist_id}",
                                headers={"Authorization": f"token {token}"},
                                json={"files": {"debug_login.html": {"content": html_content[:80000]}}},
                                timeout=15,
                            )
                            log.info("[browser] Saved login debug HTML to gist")
                    except Exception as dbg_exc:
                        log.warning("[browser] Could not save debug HTML: %s", dbg_exc)
                    browser.close()
                    return None

            # ── 2. Scrape barbell lifts ───────────────────────────────────────
            barbell_lifts: dict = {}
            log.info("[browser] Navigating to barbell lifts page")
            captured.clear()
            try:
                page.goto(
                    f"{SUGARWOD_BASE}/athletes/me#barbell",
                    wait_until="networkidle",
                    timeout=30000,
                )
                # First check if any intercepted XHR contained barbell data
                for item in captured:
                    url_lower = item["url"].lower()
                    if any(k in url_lower for k in ("barbell", "lift_max", "liftmax")):
                        log.info("[browser] Barbell data found in XHR: %s", item["url"])
                        data = item["data"]
                        if isinstance(data, dict):
                            results = data.get("data") or data.get("results") or []
                            for r in results:
                                name = r.get("name") or r.get("title") or ""
                                if name:
                                    # API returns rep1PR/rep2PR/rep3PR/rep4PR/rep5PR
                                    barbell_lifts[name] = {
                                        f"{n}RM": r[f"rep{n}PR"]
                                        for n in (1, 2, 3, 4, 5)
                                        if r.get(f"rep{n}PR")
                                    }
                        break
                # Fall back to DOM parsing if XHR didn't yield usable data
                if not barbell_lifts or not any(v for v in barbell_lifts.values()):
                    barbell_lifts = _extract_barbell_from_page(page)
                log.info("[browser] Extracted %d barbell lifts", len(barbell_lifts))
            except Exception as exc:
                log.warning("[browser] Barbell lifts fetch failed: %s", exc)

            # ── 3b. Pre-extract PRs and benchmarks from barbell page XHRs ────
            # The athletes/me page fires all athlete-data XHRs on first load.
            # We scan captured now (before it's cleared) so we don't lose data
            # that won't be re-fetched when React uses its client-side cache.
            _barbell_page_captured = list(captured)

            # ── 4. Scrape personal records ────────────────────────────────────
            personal_records: list[dict] = []
            _pr_raw_rows: list[dict] = []  # ruwe PR-XHR rijen (voor benchmarks)
            debug_html: dict[str, str] = {}  # saved to gist for diagnostics
            log.info("[browser] Navigating to personal records page")
            try:
                from_date = "20100101"  # fetch all-time PRs
                to_date = datetime.now(AMS).strftime("%Y%m%d")
                # Navigate away first so the SPA re-fetches data when we return
                page.goto(f"{SUGARWOD_BASE}/workouts", wait_until="domcontentloaded", timeout=15000)
                captured.clear()
                page.goto(
                    f"{SUGARWOD_BASE}/athletes/me?date_from={from_date}&date_to={to_date}#prs",
                    wait_until="networkidle",
                    timeout=30000,
                )
                # Save page HTML for diagnostics (truncated to keep gist small)
                try:
                    debug_html["prs"] = page.content()[:80000]
                except Exception:
                    pass

                log.info("[browser] Captured %d XHRs on PR page; URLs: %s",
                         len(captured), [c["url"] for c in captured])

                # Combine current + barbell-page captured (React may skip re-fetching)
                all_captured_for_prs = _barbell_page_captured + captured

                # Strategy 1: URL-keyword match
                for item in all_captured_for_prs:
                    url_lower = item["url"].lower()
                    if any(k in url_lower for k in ("personal_record", "/prs", "prsonly", "athlete_pr")):
                        log.info("[browser] PR data found by URL: %s", item["url"])
                        data = item["data"]
                        arr = data if isinstance(data, list) else (
                            data.get("data") or data.get("results") or data.get("personal_records") or []
                        )
                        for r in arr:
                            personal_records.append({
                                "workout": r.get("workoutTitle") or r.get("workout") or r.get("workout_name") or r.get("name") or r.get("title") or "",
                                "date": str(r.get("dateInt") or r.get("date") or r.get("achieved_at") or r.get("performed_at") or ""),
                                "result": str(r.get("bestResultDisplayString") or r.get("bestResult") or r.get("result") or r.get("score") or ""),
                                "notes": str(r.get("notes") or ""),
                            })
                        if personal_records:
                            _pr_raw_rows = [r for r in arr if isinstance(r, dict)]
                            break

                # Strategy 2: shape-based match across ALL captured XHRs
                if not personal_records:
                    log.info("[browser] URL-match failed; trying shape-based XHR scan for PRs")
                    for item in all_captured_for_prs:
                        data = item["data"]
                        arr = data if isinstance(data, list) else (
                            data.get("data") or data.get("results") or data.get("personal_records") or []
                        )
                        if not arr or not isinstance(arr, list):
                            continue
                        sample = arr[0] if arr else {}
                        if not isinstance(sample, dict):
                            continue
                        has_name = any(k in sample for k in ("workout", "workout_name", "name", "title", "exercise"))
                        has_date = any(k in sample for k in ("date", "achieved_at", "performed_at", "logged_at"))
                        if has_name and has_date:
                            log.info("[browser] Shape-matched PR data from %s (%d items)", item["url"], len(arr))
                            for r in arr:
                                personal_records.append({
                                    "workout": r.get("workoutTitle") or r.get("workout") or r.get("workout_name") or r.get("name") or r.get("title") or r.get("exercise") or "",
                                    "date": str(r.get("dateInt") or r.get("date") or r.get("achieved_at") or r.get("performed_at") or ""),
                                    "result": str(r.get("bestResultDisplayString") or r.get("bestResult") or r.get("result") or r.get("score") or ""),
                                    "notes": str(r.get("notes") or ""),
                                })
                            if personal_records:
                                break

                # Strategy 3: DOM scraping
                if not personal_records:
                    log.info("[browser] XHR scan empty; falling back to DOM scraping")
                    personal_records = _extract_prs_from_page(page)

                log.info("[browser] Extracted %d personal records", len(personal_records))
            except Exception as exc:
                log.warning("[browser] Personal records fetch failed: %s", exc)

            # ── 5. Scrape benchmark workouts ──────────────────────────────────
            benchmark_workouts: list[dict] = []
            # Strategy 0: de PR-XHR bevat 'libraryWorkout' — PR's van Girls/Heroes/
            # Notables zijn de benchmarks. De benchmarks-pagina laadt zelf geen
            # benchmark-XHR meer, dus dit is de betrouwbare bron.
            try:
                benchmark_workouts = _benchmarks_from_pr_rows(
                    _pr_raw_rows, _barbell_page_captured + captured)
                log.info("[browser] Benchmarks afgeleid uit PR-data: %d", len(benchmark_workouts))
            except Exception as exc:
                log.warning("[browser] Benchmarks uit PR-data mislukt: %s", exc)
            if not benchmark_workouts:
                log.info("[browser] Navigating to benchmark workouts page")
                try:
                    # Navigate away first to force fresh XHRs
                    page.goto(f"{SUGARWOD_BASE}/workouts", wait_until="domcontentloaded", timeout=15000)
                    captured.clear()
                    page.goto(
                        f"{SUGARWOD_BASE}/athletes/me?date_from=20100101&date_to={datetime.now(AMS).strftime('%Y%m%d')}#benchmarks",
                        wait_until="networkidle",
                        timeout=30000,
                    )
                    try:
                        debug_html["benchmarks"] = page.content()[:80000]
                    except Exception:
                        pass

                    log.info("[browser] Captured %d XHRs on benchmarks page; URLs: %s",
                             len(captured), [c["url"] for c in captured])

                    # Combine current + barbell-page captured (React may skip re-fetching)
                    all_captured_for_benchmarks = _barbell_page_captured + captured

                    # Strategy 1: dedicated extractor (tries select + click interactions)
                    benchmark_workouts = _extract_benchmarks_from_page(page)

                    # Strategy 2: shape-based XHR scan if DOM gave nothing
                    if not benchmark_workouts:
                        log.info("[browser] DOM extraction empty; trying shape-based XHR scan for benchmarks")
                        for item in all_captured_for_benchmarks:
                            data = item["data"]
                            arr = data if isinstance(data, list) else (
                                data.get("data") or data.get("results") or data.get("benchmarks") or []
                            )
                            if not arr or not isinstance(arr, list):
                                continue
                            sample = arr[0] if arr else {}
                            if not isinstance(sample, dict):
                                continue
                            has_name = any(k in sample for k in ("name", "workout", "benchmark", "title"))
                            has_result = any(k in sample for k in ("result", "score", "time", "reps", "value"))
                            if has_name and has_result:
                                log.info("[browser] Shape-matched benchmark data from %s (%d items)", item["url"], len(arr))
                                for r in arr:
                                    benchmark_workouts.append({
                                        "name": r.get("name") or r.get("workout") or r.get("benchmark") or r.get("title") or "",
                                        "result": str(r.get("result") or r.get("score") or r.get("time") or r.get("reps") or ""),
                                        "scaling": r.get("scaling") or r.get("scaled") or "",
                                        "date": str(r.get("date") or r.get("achieved_at") or r.get("performed_at") or ""),
                                        "category": r.get("category") or r.get("type") or r.get("workout_type") or "Benchmark",
                                    })
                                if benchmark_workouts:
                                    break

                    log.info("[browser] Extracted %d benchmark workouts", len(benchmark_workouts))
                except Exception as exc:
                    log.warning("[browser] Benchmark workouts fetch failed: %s", exc)

            # ── 6. Scrape athlete logbook (actual attended workouts) ──────────
            athlete_logbook: list[dict] = []
            log.info("[browser] Navigating to athlete logbook page")
            try:
                four_weeks_ago = (datetime.now(AMS) - timedelta(weeks=4)).strftime("%Y%m%d")
                today_str = datetime.now(AMS).strftime("%Y%m%d")
                # Navigate away first so the SPA re-fetches data
                page.goto(f"{SUGARWOD_BASE}/workouts", wait_until="domcontentloaded", timeout=15000)
                captured.clear()
                page.goto(
                    f"{SUGARWOD_BASE}/athletes/me?date_from={four_weeks_ago}&date_to={today_str}#logbook",
                    wait_until="networkidle",
                    timeout=30000,
                )
                log.info("[browser] Captured %d XHRs on logbook page; URLs: %s",
                         len(captured), [c["url"] for c in captured])

                # Strategy 1: URL-keyword match
                for item in captured:
                    url_lower = item["url"].lower()
                    if any(k in url_lower for k in ("logbook", "/logs", "/log", "athlete_log", "results")):
                        log.info("[browser] Logbook data found by URL: %s", item["url"])
                        data = item["data"]
                        arr = data if isinstance(data, list) else (
                            data.get("data") or data.get("results") or data.get("logs") or []
                        )
                        for r in arr:
                            athlete_logbook.append({
                                "date": str(r.get("date") or r.get("performed_at") or r.get("logged_at") or r.get("scheduledDate") or r.get("scheduledDateInteger") or ""),
                                "workout": r.get("workout") or r.get("workout_name") or r.get("title") or r.get("name") or "",
                                "result": str(r.get("result") or r.get("score") or r.get("notes") or ""),
                            })
                        if athlete_logbook:
                            break

                # Strategy 2: DOM scraping (table-based fallback)
                if not athlete_logbook:
                    log.info("[browser] XHR scan empty; falling back to DOM scraping for logbook")
                    athlete_logbook = _extract_logbook_from_page(page)

                # Save debug HTML if logbook still empty
                if not athlete_logbook:
                    try:
                        debug_html["logbook"] = page.content()[:80000]
                    except Exception:
                        pass

                log.info("[browser] Extracted %d logbook entries", len(athlete_logbook))
            except Exception as exc:
                log.warning("[browser] Athlete logbook fetch failed: %s", exc)

            # Save debug HTML to gist if PRs, benchmarks, or logbook are still empty
            if debug_html and (not personal_records or not benchmark_workouts or not athlete_logbook):
                try:
                    debug_payload: dict = {}
                    if not personal_records and "prs" in debug_html:
                        debug_payload["debug_prs.html"] = {"content": debug_html["prs"]}
                    if not benchmark_workouts and "benchmarks" in debug_html:
                        debug_payload["debug_benchmarks.html"] = {"content": debug_html["benchmarks"]}
                    if not athlete_logbook and "logbook" in debug_html:
                        debug_payload["debug_logbook.html"] = {"content": debug_html["logbook"]}
                    if debug_payload and gist_id and token:
                        r = requests.patch(
                            f"https://api.github.com/gists/{gist_id}",
                            json={"files": debug_payload},
                            headers={"Authorization": f"token {token}"},
                            timeout=30,
                        )
                        if r.ok:
                            log.info("[browser] Debug HTML saved to gist (%s)", list(debug_payload))
                        else:
                            log.warning("[browser] Failed to save debug HTML: %s", r.status_code)
                except Exception as exc:
                    log.warning("[browser] Could not save debug HTML: %s", exc)

            # ── 3. Fetch workouts via HTTP using browser session cookies ──────
            # Navigate to /workouts once to ensure the browser has loaded the
            # workout page and fired the /api/workouts XHR (which embeds the
            # CSRF token + trackId in its URL parameters).  Then close the
            # browser and make direct HTTP requests for each week.  This
            # approach is more reliable than staying in the browser because
            # React's in-memory cache can suppress repeated XHR calls when
            # navigating between week params within the same session.

            # Load /workouts so the /api/workouts XHR fires and we can capture
            # the CSRF token and trackId before closing the browser.
            captured.clear()
            log.info("[browser] Loading /workouts to capture auth tokens")
            try:
                page.goto(
                    f"{SUGARWOD_BASE}/workouts",
                    wait_until="networkidle",
                    timeout=30000,
                )
                log.info("[browser] /workouts: %d XHR responses captured",
                         len(captured))
            except Exception as exc:
                log.warning("[browser] /workouts navigation failed: %s", exc)

            # ── 3a. Click workout cards to capture athlete notes via XHR ─────────
            # Athlete notes (timecap, coach info) are only loaded when the user
            # clicks an individual workout card. We click each visible card and
            # wait for the resulting detail XHR which contains athleteNotes.
            athlete_notes_map: dict[str, str] = {}  # objectId or "date|title" → notes
            try:
                log.info("[athlete_notes] Scanning %d page-load XHRs for embedded notes", len(captured))

                # First pass: notes sometimes in the bulk /api/workouts response
                for cap_item in captured:
                    cap_data = cap_item["data"]
                    bulk_items = None
                    if isinstance(cap_data, dict):
                        bulk_items = cap_data.get("data") or cap_data.get("workouts") or cap_data.get("results")
                    if isinstance(bulk_items, list):
                        for w in bulk_items:
                            if not isinstance(w, dict):
                                continue
                            notes = _extract_athlete_notes(w)
                            if not notes:
                                continue
                            oid = w.get("objectId") or w.get("id") or ""
                            title = w.get("title") or w.get("name") or ""
                            date_int = w.get("scheduledDateInteger")
                            date_s = ""
                            if date_int:
                                try:
                                    date_s = datetime.strptime(str(date_int), "%Y%m%d").strftime("%Y-%m-%d")
                                except ValueError:
                                    pass
                            key = str(oid) if oid else f"{date_s}|{title}"
                            if key:
                                athlete_notes_map[key] = notes
                                log.info("[athlete_notes] Bulk XHR notes: %s '%s' (%d chars)", date_s, title, len(notes))

                # Second pass: click each visible workout card to trigger detail XHR
                card_loc = None
                for selector in [
                    # Confirmed real class from JS discovery (SugarWOD uses .cal-workout)
                    '.cal-workout:not(.cal-workout-content)',
                    '.cal-workout',
                    '[class*="WorkoutCard"]',
                    '[class*="workout-card"]',
                    '[class*="WodCard"]',
                    '[class*="wod-card"]',
                    '[data-testid*="workout"]',
                    '[class*="EventCard"]',
                    'article[class*="Card"]',
                    '[class*="ScheduleCard"]',
                ]:
                    try:
                        loc = page.locator(selector)
                        if loc.count() > 0:
                            card_loc = loc
                            log.info("[athlete_notes] Card selector '%s' found %d elements", selector, loc.count())
                            break
                    except Exception:
                        pass

                if card_loc is None:
                    log.info("[athlete_notes] No card selector matched; trying JS element discovery")
                    try:
                        js_info = page.evaluate("""
                            () => {
                                const els = [...document.querySelectorAll('div, article, li')];
                                const cards = els.filter(el => {
                                    const c = el.className || '';
                                    return /workout|wod|card|event/i.test(c) && el.offsetHeight > 40 && el.offsetWidth > 40;
                                });
                                return cards.slice(0, 8).map(el => ({
                                    tag: el.tagName, cls: el.className.slice(0, 80),
                                    txt: el.textContent.trim().slice(0, 60)
                                }));
                            }
                        """)
                        log.info("[athlete_notes] JS card candidates: %s", js_info)
                    except Exception:
                        pass

                pre_map_size = len(athlete_notes_map)
                if card_loc is not None:
                    n_cards = min(card_loc.count(), 7)
                    log.info("[athlete_notes] Clicking %d workout cards for detail XHRs", n_cards)
                    for i in range(n_cards):
                        try:
                            card = card_loc.nth(i)
                            pre_count = len(captured)
                            card.scroll_into_view_if_needed(timeout=2000)
                            card.click(timeout=3000)
                            page.wait_for_timeout(1800)

                            # Scan newly captured XHRs for notes
                            for new_item in captured[pre_count:]:
                                new_data = new_item["data"]
                                if not isinstance(new_data, dict):
                                    continue
                                detail = new_data.get("data") or new_data
                                if not isinstance(detail, dict):
                                    continue
                                notes = _extract_athlete_notes(detail)
                                if not notes:
                                    continue
                                oid = detail.get("objectId") or detail.get("id") or ""
                                title = detail.get("title") or detail.get("name") or ""
                                date_int = detail.get("scheduledDateInteger")
                                date_s = ""
                                if date_int:
                                    try:
                                        date_s = datetime.strptime(str(date_int), "%Y%m%d").strftime("%Y-%m-%d")
                                    except ValueError:
                                        pass
                                key = str(oid) if oid else f"{date_s}|{title}"
                                if key:
                                    athlete_notes_map[key] = notes
                                    log.info("[athlete_notes] Card %d click → notes: %s '%s' (%d chars)",
                                             i, date_s, title, len(notes))

                            # Dismiss any modal that may have opened
                            for close_sel in [
                                '[aria-label="Close"]', '[aria-label="close"]',
                                'button.close', '.modal-close', '[data-dismiss="modal"]',
                            ]:
                                try:
                                    btn = page.locator(close_sel).first
                                    if btn.is_visible(timeout=400):
                                        btn.click(timeout=1000)
                                        page.wait_for_timeout(400)
                                        break
                                except Exception:
                                    pass
                        except Exception as exc:
                            log.debug("[athlete_notes] Card %d click failed: %s", i, exc)

                log.info("[athlete_notes] Notes map: %d entries (%d from clicks)",
                         len(athlete_notes_map), len(athlete_notes_map) - pre_map_size)
            except Exception as exc:
                athlete_notes_map = {}
                log.warning("[athlete_notes] Click-based notes fetch failed: %s", exc)

            # ── 3b. Navigate to each week to capture its XHR ─────────────────
            # We've already loaded the current week above. For other weeks,
            # navigate away first (unmount React) then to the target week URL
            # so the SPA fires a fresh XHR rather than serving cached data.
            log.info("[browser] Navigating to each requested week to capture XHRs")
            for monday_w in weeks:
                week_str_w = monday_w.strftime("%Y%m%d")
                week_url = (
                    f"{SUGARWOD_BASE}/workouts"
                    f"?week={week_str_w}&track=workout-of-the-day"
                )
                pre_count = len(captured)
                try:
                    # Navigate away to force React to unmount the calendar
                    page.goto(
                        f"{SUGARWOD_BASE}/athletes/me",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    page.goto(week_url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(1500)
                    log.info("[browser] Week %s: captured %d new XHRs",
                             week_str_w, len(captured) - pre_count)
                except Exception as exc_w:
                    log.warning("[browser] Week %s navigation failed: %s",
                                week_str_w, exc_w)

            # Capture session cookies before closing the browser
            browser_cookies = {
                c["name"]: c["value"] for c in context.cookies()
                if "sugarwod.com" in c.get("domain", "")
            }
            log.info("[browser] Captured %d session cookies", len(browser_cookies))

            # Log all captured XHR URLs for diagnostics
            all_captured_urls = [item["url"] for item in captured]
            log.info("[browser] All captured XHR URLs (%d): %s",
                     len(all_captured_urls), all_captured_urls)

            # Try to extract CSRF and trackId from any /api/workouts or
            # /api/ XHR URL in the captured list
            api_csrf: str | None = None
            track_id: str | None = None
            for item in list(captured) + _barbell_page_captured:
                url = item["url"]
                if "/api/" not in url:
                    continue
                p = dict(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
                if not api_csrf and p.get("_csrf"):
                    api_csrf = p["_csrf"][0]
                if not track_id and p.get("trackId"):
                    track_id = p["trackId"][0]
                if api_csrf and track_id:
                    log.info("[browser] Extracted _csrf=…%s trackId=%s from %s",
                             api_csrf[-6:], track_id, url)
                    break

            # Fallback: get CSRF from a cookie (SugarWOD sets _csrf as a cookie)
            if not api_csrf:
                api_csrf = browser_cookies.get("_csrf") or browser_cookies.get("XSRF-TOKEN")
                if api_csrf:
                    log.info("[browser] CSRF token from cookie")

            log.info("[browser] CSRF: %s, trackId: %s",
                     (api_csrf[:10] + "…" if api_csrf else "none"), track_id)
            browser.close()

            # ── 3c. Harvest workouts from ALL captured XHRs (shape-based) ────
            # Detect workout entries by their field names rather than by URL,
            # so this works even if the /api/workouts endpoint URL changes.
            fetched_weeks: set[str] = set()
            all_xhr_items = list(captured) + _barbell_page_captured
            log.info("[browser] Scanning %d captured XHRs for workout data",
                     len(all_xhr_items))
            for item in all_xhr_items:
                xhr_url = item["url"]
                xhr_data = item["data"]

                # Extract candidate results array from various response shapes
                if isinstance(xhr_data, list):
                    xhr_results = xhr_data
                elif isinstance(xhr_data, dict):
                    xhr_results = (
                        xhr_data.get("data") or xhr_data.get("workouts")
                        or xhr_data.get("results") or []
                    )
                else:
                    continue

                if not isinstance(xhr_results, list) or not xhr_results:
                    continue

                # Only treat as workout data if items have SugarWOD-specific
                # scheduling fields (avoids false-positives from PR/benchmark XHRs)
                sample = xhr_results[0] if isinstance(xhr_results[0], dict) else {}
                if not any(k in sample for k in (
                    "scheduledDateInteger", "scheduledDate", "workoutDate",
                    "TBWorkout",
                )):
                    continue

                xp = dict(urllib.parse.parse_qs(
                    urllib.parse.urlparse(xhr_url).query))
                ws = xp.get("week", [None])[0]
                parsed = _parse_parse_workouts(xhr_results, ws)
                if parsed:
                    all_workouts.extend(parsed)
                    if ws:
                        fetched_weeks.add(ws)
                    log.info("[browser] XHR harvest: %d workouts from %s (week=%s)",
                             len(parsed), xhr_url, ws)

            log.info("[browser] XHR harvest total: %d workouts, weeks covered: %s",
                     len(all_workouts), sorted(fetched_weeks))

            # Set up HTTP session with browser cookies
            api_session = requests.Session()
            api_session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{SUGARWOD_BASE}/workouts",
            })
            requests.utils.add_dict_to_cookiejar(api_session.cookies, browser_cookies)

            for monday in weeks:
                week_str = monday.strftime("%Y%m%d")
                if week_str in fetched_weeks:
                    log.info("[http] Week %s already fetched via XHR, skipping", week_str)
                    continue
                ts = str(int(time.time() * 1000))
                params: dict = {
                    "week": week_str,
                    "track": "workout-of-the-day",
                    "_": ts,
                }
                if api_csrf:
                    params["_csrf"] = api_csrf
                if track_id:
                    params["trackId"] = track_id
                log.info("[http] Fetching workouts week %s", week_str)
                try:
                    resp = api_session.get(
                        f"{SUGARWOD_BASE}/api/workouts",
                        params=params,
                        timeout=30,
                    )
                    log.info("[http] Week %s: HTTP %d | %s",
                             week_str, resp.status_code, resp.text[:400])
                    if resp.status_code == 200:
                        data = resp.json()
                        results = (
                            data.get("data") or data.get("workouts")
                            or data.get("results") or []
                        )
                        if isinstance(results, list) and results:
                            log.info("[http] Week %s: first item keys: %s",
                                     week_str,
                                     list(results[0].keys())
                                     if isinstance(results[0], dict) else type(results[0]))
                            parsed = _parse_parse_workouts(results, week_str)
                            if parsed:
                                all_workouts.extend(parsed)
                                fetched_weeks.add(week_str)
                                log.info("[http] Week %s: %d workout(s) added",
                                         week_str, len(parsed))
                            else:
                                log.info("[http] Week %s: 0 workouts parsed from %d results",
                                         week_str, len(results))
                        else:
                            log.info("[http] Week %s: no workouts in response",
                                     week_str)
                    else:
                        log.warning("[http] Week %s: HTTP %d — %s",
                                    week_str, resp.status_code, resp.text[:200])
                except Exception as exc:
                    log.warning("[http] Week %s failed: %s", week_str, exc)

            # ── Apply Playwright-captured athlete notes to workouts ────────────
            # Playwright clicked cards above and stored notes in athlete_notes_map.
            # Match by objectId first, then fall back to "date|title".
            today_iso = datetime.now(timezone.utc).date().isoformat()
            if athlete_notes_map:
                applied = 0
                for w in all_workouts:
                    if w.get("athlete_notes"):
                        continue
                    oid = w.get("object_id", "")
                    title = w.get("title", "")
                    date = w.get("date", "")
                    notes = (
                        athlete_notes_map.get(oid)
                        or athlete_notes_map.get(f"{date}|{title}")
                    )
                    if notes:
                        w["athlete_notes"] = notes
                        applied += 1
                        log.info("[athlete_notes] Applied: %s '%s' (%d chars)", date, title, len(notes))
                log.info("[athlete_notes] Applied notes to %d/%d workouts", applied, len(all_workouts))

            # Fallback: HTTP detail fetch for upcoming workouts that still lack notes
            # (only works if object_id was available from the weekly XHR)
            missing_notes = [
                w for w in all_workouts
                if w.get("object_id") and not w.get("athlete_notes")
                and w.get("date", "") >= today_iso
            ][:10]
            if missing_notes:
                log.info("[athlete_notes] HTTP fallback for %d workouts with object_id", len(missing_notes))
            for w in missing_notes:
                oid = w["object_id"]
                for detail_url in [
                    f"{SUGARWOD_BASE}/api/workouts/{oid}",
                    f"{SUGARWOD_BASE}/public/api/v1/workouts/{oid}",
                ]:
                    try:
                        dr = api_session.get(detail_url, timeout=15,
                                             headers={"Accept": "application/json",
                                                      "X-Requested-With": "XMLHttpRequest"})
                        if dr.status_code == 200:
                            ddata = dr.json()
                            detail_item = ddata.get("data") or ddata if isinstance(ddata, dict) else {}
                            notes = _extract_athlete_notes(detail_item)
                            if notes:
                                w["athlete_notes"] = notes
                                log.info("[athlete_notes] HTTP: %s '%s': %d chars",
                                         w.get("date"), w.get("title", "")[:30], len(notes))
                                break
                    except Exception as exc:
                        log.debug("[athlete_notes] %s failed: %s", detail_url, exc)

    except Exception as exc:
        log.warning("Playwright error: %s", exc)
        return None

    if not all_workouts:
        return None
    return {
        "workouts": all_workouts,
        "barbell_lifts": barbell_lifts,
        "personal_records": personal_records,
        "benchmark_workouts": benchmark_workouts,
        "athlete_logbook": athlete_logbook,
    }


def fetch_workouts_week(
    session: requests.Session,
    monday: datetime,
    csrf: str | None,
    session_token: str | None = None,
    athlete_id: str | None = None,
    affiliate_id: str | None = None,
) -> list[dict]:
    """
    Fetch workouts for one week.

    Tries in order:
    1. SugarWOD custom /public/api/v1/ endpoints (affiliate/athlete-scoped)
    2. HTML calendar endpoint (fallback with structure-aware parsing)
    """
    week_str = monday.strftime("%Y%m%d")

    # ── 1. Custom JSON API endpoint ─────────────────────────────────────
    workouts = _fetch_via_json_api(
        session, monday, week_str, csrf, session_token,
        athlete_id=athlete_id, affiliate_id=affiliate_id,
    )
    if workouts is not None:
        return workouts

    # ── 2. HTML calendar (scraping fallback) ────────────────────────────
    return _fetch_via_html(session, monday, week_str, csrf)



def _fetch_via_json_api(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    csrf: str | None,
    session_token: str | None,
    athlete_id: str | None = None,
    affiliate_id: str | None = None,
) -> list[dict] | None:
    """
    Try several approaches to get workout JSON from the workouts endpoint.

    Key insight: GET /workouts returns 401 JSON when *not* authenticated, but
    200 HTML (the SPA shell) when authenticated via cookies. To get JSON we
    either need to avoid triggering the "serve SPA" code path, or find the
    correct sub-API URL.
    """
    ts = str(int(time.time() * 1000))
    base_params = {"week": week_str, "track": "workout-of-the-day", "_": ts}
    base_referer = f"{SUGARWOD_BASE}/workouts?week={week_str}&track=workout-of-the-day"
    json_headers = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base_referer,
        "Origin": SUGARWOD_BASE,
    }

    # IMPORTANT: never manually set a "Cookie" header — doing so causes
    # requests to send a partial cookie alongside the session jar, which
    # triggers the server to clear _sw_ath/_sw_aff via Set-Cookie and
    # corrupts the session for all subsequent calls.

    # Build dynamic affiliate/athlete endpoints from login data
    _aff = affiliate_id or "oqCrVKvRUY"
    _ath = athlete_id or "8lDP7kJHFN"

    attempts = [
        # ── A. Affiliate-scoped workouts (most likely correct endpoint)
        ("affiliate workouts API",
         f"{SUGARWOD_BASE}/public/api/v1/affiliates/{_aff}/workouts", dict(
            params={"week": week_str, "track": "workout-of-the-day"},
            headers=json_headers,
        )),
        # ── B. Affiliate workouts with flat affiliateId param
        ("affiliate workouts flat param",
         f"{SUGARWOD_BASE}/public/api/v1/workouts", dict(
            params={"week": week_str, "track": "workout-of-the-day",
                    "affiliateId": _aff},
            headers=json_headers,
        )),
        # ── C. Athlete-scoped workouts endpoint
        ("athlete workouts API",
         f"{SUGARWOD_BASE}/public/api/v1/athletes/{_ath}/workouts", dict(
            params={"week": week_str},
            headers=json_headers,
        )),
        # ── D. XHR request to the workouts page (no _csrf needed for GET)
        ("workouts XHR no _csrf", WORKOUTS_URL, dict(
            params=base_params,
            headers=json_headers,
        )),
        # ── E. Whiteboard endpoint (athlete-facing view)
        ("whiteboard", f"{SUGARWOD_BASE}/whiteboard", dict(
            params=base_params,
            headers=json_headers,
        )),
    ]

    for desc, url, kwargs in attempts:
        log.info("Trying: %s", desc)
        try:
            resp = session.get(url, timeout=30, **kwargs)
        except Exception as exc:
            log.warning("  Error: %s", exc)
            continue

        ct = resp.headers.get("Content-Type", "")
        set_cookie = resp.headers.get("Set-Cookie", "")
        log.info("  → HTTP %d, Content-Type: %s | %s",
                 resp.status_code, ct, resp.text[:200])
        if set_cookie:
            log.info("  Set-Cookie: %s", set_cookie[:200])

        if resp.status_code == 200 and "json" in ct:
            data = resp.json()
            results = (
                data.get("results") or data.get("workouts")
                or data.get("data")
                or (data if isinstance(data, list) else None)
            )
            if results:
                log.info("  Got %d workouts from '%s'", len(results), desc)
                return _parse_workouts_json({"workouts": results}, monday)
            # 200 JSON but empty / unexpected shape
            log.info("  200 JSON keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

    return None


def _fetch_via_html(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    csrf: str | None,
) -> list[dict]:
    """Fetch the HTML calendar page and scrape workout content."""
    params: dict = {
        "week": week_str,
        "track": "workout-of-the-day",
        "_": str(int(time.time() * 1000)),
    }
    if csrf:
        params["_csrf"] = csrf

    headers = {
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Referer": f"{SUGARWOD_BASE}/workouts",
    }

    log.info("Fetching workouts (HTML) for week %s", week_str)
    resp = session.get(WORKOUTS_URL, params=params, headers=headers, timeout=30)
    log.info("  → HTTP %d, Content-Type: %s",
             resp.status_code, resp.headers.get("Content-Type", ""))
    csp = resp.headers.get("Content-Security-Policy", "")
    if csp:
        # connect-src tells us which API origins the SPA calls
        import re as _re2
        m = _re2.search(r'connect-src([^;]+)', csp)
        if m:
            log.info("  CSP connect-src: %s", m.group(1).strip())
    resp.raise_for_status()

    # Log body text to aid debugging (skip <head> boilerplate)
    soup_debug = BeautifulSoup(resp.text, "html.parser")
    body = soup_debug.find("body")
    if body:
        body_text = body.get_text(separator="\n", strip=True)
        log.info("Body text (first 3000 chars):\n%s", body_text[:3000])
    else:
        log.info("HTML snippet (first 2000 chars):\n%s", resp.text[:2000])

    return _parse_workouts_html(resp.text, monday)


_SKIP_TITLES = ("warm",)  # warming up only; accessory workouts are now shown in the UI


def _extract_athlete_notes(item: dict) -> str:
    """Extract athlete/coach notes from a SugarWOD workout object.
    The weekly API returns 'athletesNotes'/'coachesNotes' (plural);
    detail XHRs use singular 'athleteNotes'/'coachNotes'.
    """
    return (
        item.get("athletesNotes")
        or item.get("coachesNotes")
        or item.get("athleteNotes")
        or item.get("programNotes")
        or item.get("coachNotes")
        or item.get("athlete_notes")
        or item.get("notes")
        or item.get("comment")
        or ""
    )


def _parse_parse_workouts(results: list[dict], week_str: str | None = None) -> list[dict]:
    """Convert Parse Server workout objects to our standard format."""
    # Derive monday from week_str (YYYYMMDD) as fallback date source
    monday_fallback: datetime | None = None
    if week_str and len(week_str) == 8:
        try:
            monday_fallback = datetime.strptime(week_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    workouts = []
    for item in results:
        title_raw = item.get("title") or item.get("name") or "WOD"
        # Skip warming-up entries (accessory workouts are now shown in the UI)
        if any(kw in title_raw.lower() for kw in _SKIP_TITLES):
            continue

        # scheduledDateInteger is SugarWOD's primary date field (e.g. 20260322)
        date_int = item.get("scheduledDateInteger")
        date_str = ""
        if date_int:
            try:
                date_str = datetime.strptime(str(date_int), "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

        if not date_str:
            # Fallback: try other known field names
            date_val = (
                item.get("scheduledDate")
                or item.get("date")
                or item.get("workoutDate")
                or item.get("scheduledAt")
            )
            if isinstance(date_val, dict):
                date_val = date_val.get("iso", "") or date_val.get("value", "")
            if date_val:
                try:
                    date_str = datetime.fromisoformat(
                        str(date_val).replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        if not date_str and monday_fallback:
            # Fallback: assign Monday of the requested week
            log.info("  No date for '%s' — assigning Monday %s",
                     title_raw, monday_fallback.strftime("%Y-%m-%d"))
            date_str = monday_fallback.strftime("%Y-%m-%d")

        description = (
            item.get("description")
            or item.get("content")
            or item.get("workout")
            or ""
        )
        athlete_notes = _extract_athlete_notes(item)
        object_id = item.get("objectId") or item.get("id") or item.get("_id") or ""
        entry: dict = {"date": date_str, "title": title_raw, "description": description}
        if athlete_notes:
            entry["athlete_notes"] = athlete_notes
        if object_id:
            entry["object_id"] = str(object_id)
        workouts.append(entry)
    return workouts


def _parse_workouts_json(data, monday: datetime) -> list[dict]:
    """Parse JSON workout response."""
    log.debug("JSON response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

    workouts = []

    # Common SugarWOD JSON shapes
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("workouts")
            or data.get("data")
            or data.get("days")
            or data.get("results")
            or []
        )
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue

        date_str = (
            item.get("date")
            or item.get("scheduled_date")
            or item.get("workout_date")
        )
        title = item.get("title") or item.get("name") or "WOD"
        description = (
            item.get("description")
            or item.get("content")
            or item.get("workout")
            or ""
        )

        athlete_notes = _extract_athlete_notes(item)
        object_id = item.get("objectId") or item.get("id") or item.get("_id") or ""
        entry: dict = {"date": date_str, "title": title, "description": description}
        if athlete_notes:
            entry["athlete_notes"] = athlete_notes
        if object_id:
            entry["object_id"] = str(object_id)
        workouts.append(entry)

    log.info("Parsed %d workout(s) from JSON", len(workouts))
    return workouts


def _parse_workouts_html(html: str, monday: datetime) -> list[dict]:
    """
    Parse a full Whiteboard Calendar HTML page or XHR fragment.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── 1. JSON embedded in <script> tags ───────────────────────────────
    import re as _re
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for a JSON object/array that mentions workouts
        if not any(k in text for k in ("workout", "WOD", "scheduledDate", "TBWorkout")):
            continue
        # Try to extract JSON blobs
        for m in _re.finditer(r'(\{[^<]{20,}\}|\[[^<]{20,}\])', text):
            try:
                data = json.loads(m.group(0))
                results = (
                    (data.get("workouts") or data.get("results") or data.get("data"))
                    if isinstance(data, dict) else data if isinstance(data, list) else None
                )
                if results and isinstance(results, list) and len(results) > 0:
                    log.info("Found %d workouts in <script> JSON", len(results))
                    return _parse_parse_workouts(results)
            except (ValueError, AttributeError):
                pass

    workouts = []

    # ── 2. data-date elements ────────────────────────────────────────────
    day_elements = soup.find_all(attrs={"data-date": True})
    if day_elements:
        for el in day_elements[:7]:
            raw = el["data-date"].replace("-", "")
            try:
                date = datetime.strptime(raw, "%Y%m%d")
            except ValueError:
                continue
            content = "\n".join(el.stripped_strings)
            workouts.append(_build_workout(date, content))
        if workouts:
            log.info("HTML: extracted %d days via data-date", len(workouts))
            return workouts

    # Slice by day-of-week header text (MON 16, TUE 17, …)
    import re
    full_text = soup.get_text(separator="\n")
    # Try multiple day-header formats SugarWOD has used over time
    days_abbr = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    days_full = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    positions = []
    for i in range(7):
        date = monday + timedelta(days=i)
        abbr = days_abbr[i]
        full = days_full[i]
        day_n = date.day
        patterns = [
            rf"\b{abbr}\s+{day_n}\b",                         # MON 25
            rf"\b{full}\s+{day_n}\b",                          # Monday 25
            rf"\b{full},?\s+{date.strftime('%B')}\s+{day_n}\b", # Monday, May 25
            rf"\b{date.strftime('%m/%d/%Y')}\b",               # 05/25/2026
            rf"\b{date.strftime('%Y-%m-%d')}\b",               # 2026-05-25
            rf"\b{day_n}\s+{date.strftime('%B')}\b",           # 25 May
        ]
        for pat in patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                positions.append((i, m.start(), m.end()))
                break

    for idx, (day_i, start, end) in enumerate(positions):
        next_start = positions[idx + 1][1] if idx + 1 < len(positions) else len(full_text)
        content = full_text[end:next_start].strip()
        date = monday + timedelta(days=day_i)
        workouts.append(_build_workout(date, content))

    log.info("HTML: extracted %d days via text headers", len(workouts))
    return workouts


def _build_workout(date: datetime, description: str) -> dict:
    return {
        "date": date.strftime("%Y-%m-%d"),
        "title": f"WOD {date.strftime('%A %d %B %Y')}",
        "description": description,
    }


from sugarwod_coach import (  # noqa: E501
    generate_recovery_advice,
    generate_workout_plans,
    detect_deload,
)


# ──────────────────────────────────────────────────────────────
# Gist storage
# ──────────────────────────────────────────────────────────────

def load_health_input(gist_id: str, token: str) -> tuple[dict | None, list[dict]]:
    """Lees health_input.json uit de gist.

    Retourneert een tuple (today_entry, history):
    - today_entry: {"slaap": 3, "energie": 4, "spierpijn": 2, "date": "YYYY-MM-DD"} of None
    - history: lijst van dagentries uit "history" array (kan leeg zijn)
    """
    if not gist_id or not token:
        return None, []
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        raw = gist_file_content(files.get("health_input.json", {}), token)
        if not raw:
            log.info("[gist] health_input.json niet gevonden — geen subjectieve hersteldata")
            return None, []
        data = json.loads(raw)
        # Extract today entry (top-level fields)
        today_entry: dict | None = None
        if data.get("date"):
            today_entry = {
                "date": data.get("date"),
                "slaap": data.get("slaap"),
                "energie": data.get("energie"),
                "spierpijn": data.get("spierpijn"),
            }
            log.info(
                "[gist] health_input geladen: slaap=%s energie=%s spierpijn=%s (datum: %s)",
                today_entry.get("slaap"), today_entry.get("energie"),
                today_entry.get("spierpijn"), today_entry.get("date"),
            )
        history: list[dict] = data.get("history", [])
        log.info("[gist] health_input history: %d entries", len(history))
        return today_entry, history
    except Exception as exc:
        log.warning("[gist] health_input.json laden mislukt: %s", exc)
        return None, []


# Activity type keywords (Strava `type` / intervals.icu `type`, lowercased)
# that indicate a cardio/non-CrossFit session.  Checked first so things like
# "Workout" recorded on a treadmill run don't get misclassified.
_CARDIO_ACTIVITY_KEYWORDS = (
    "run", "ride", "bike", "cycling", "swim", "hike", "walk", "ski",
    "elliptical", "rowing", "sup", "paddle", "yoga",
)
# Keywords that indicate an actual CrossFit/strength session.
_CROSSFIT_ACTIVITY_KEYWORDS = ("crossfit", "weighttraining", "weight training", "workout")


def _is_crossfit_activity(activities: list[dict]) -> bool:
    """True if any of the given Strava/intervals.icu activities looks like a
    CrossFit/strength session, based on its recorded type.

    Used to decide whether the box's programmed WOD for a date may be
    attributed to the athlete — having logged *some* activity on a date is
    not, by itself, evidence he attended class there (the box posts a WOD on
    days he's never scheduled for, e.g. Tuesday).
    """
    for act in activities:
        t = (act.get("type") or "").lower()
        if not t:
            continue
        if any(k in t for k in _CARDIO_ACTIVITY_KEYWORDS):
            continue
        if any(k in t for k in _CROSSFIT_ACTIVITY_KEYWORDS):
            return True
    return False


def load_sportbit_attended_dates(gist_id: str, token: str) -> tuple[set[str], dict[str, str], set[str], set[str]]:
    """Read sportbit_state.json from the shared gist and return:
    - A set of ISO dates where the athlete was signed up (and did NOT cancel),
      filtered to regular class days (Mon/Wed/Thu/Sat/Sun) for past-attendance tracking.
    - A dict of {date: time} for ALL non-cancelled signups (past + future),
      used to look up actual training times.
    - A set of ISO dates where the athlete HAD signed up but cancelled,
      with no remaining active signup on that date.
    - A set of ALL non-cancelled signup dates regardless of weekday (for future
      workout detection — covers manually registered special/Friday classes).

    Returns (set[str], dict[str, str], set[str], set[str]).
    """
    # Weekdays (0=Mon … 6=Sun) that count as regular past-attendance days.
    # Manually registered classes on other days (e.g. Fri) are still captured
    # in all_signed_up_dates so the coach sees them as upcoming workouts.
    SCHEDULED_WEEKDAYS = {0, 2, 3, 5, 6}  # Mon, Wed, Thu, Sat, Sun

    if not gist_id or not token:
        return set(), {}, set(), set()
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        raw = gist_file_content(files.get("sportbit_state.json", {}), token)
        if not raw:
            log.warning("[gist] sportbit_state.json not found or empty")
            return set(), {}, set(), set()
        state = json.loads(raw)
        signed_up: dict = state.get("signed_up", {})
        cancelled: dict = state.get("cancelled", {})
        attended: set[str] = set()
        all_signed_up_dates: set[str] = set()
        signed_up_times: dict[str, str] = {}
        skipped = 0
        for event_id, info in signed_up.items():
            if event_id not in cancelled:
                date = info.get("date", "")
                time = info.get("time", "")
                if date:
                    all_signed_up_dates.add(date)
                    # Build full date→time map for all non-cancelled signups
                    if time:
                        signed_up_times[date] = time
                    try:
                        weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
                    except ValueError:
                        weekday = -1
                    if weekday in SCHEDULED_WEEKDAYS:
                        attended.add(date)
                    else:
                        skipped += 1
                        log.info("[gist] %s (weekday %d) not in regular schedule — tracked in all_signed_up_dates", date, weekday)
        # Dates with a cancelled signup but no remaining active signup on that date
        cancelled_dates: set[str] = {
            info.get("date", "")
            for info in cancelled.values()
            if info.get("date") and info["date"] not in attended
        }
        cancelled_dates.discard("")
        log.info("[gist] Sportbit attended dates: %d (skipped %d non-regular-day signups)", len(attended), skipped)
        log.info("[gist] All non-cancelled signup dates: %d (incl. non-regular days)", len(all_signed_up_dates))
        log.info("[gist] Signed-up times: %d dates with known training time", len(signed_up_times))
        log.info("[gist] Cancelled CF dates (no active signup): %d", len(cancelled_dates))
        return attended, signed_up_times, cancelled_dates, all_signed_up_dates
    except Exception as exc:
        log.warning("[gist] Failed to load sportbit_state.json: %s", exc)
        return set(), {}, set(), set()


def load_workout_log(gist_id: str, token: str) -> dict[str, dict]:
    """Read workout_log.json from the gist. Returns {date: entry}."""
    if not gist_id or not token:
        return {}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        raw = gist_file_content(resp.json().get("files", {}).get("workout_log.json", {}), token)
        if not raw:
            log.info("[gist] workout_log.json not found or empty")
            return {}
        entries = json.loads(raw).get("entries", [])
        result = {e["date"]: e for e in entries if "date" in e}
        log.info("[gist] workout_log.json loaded: %d entries", len(result))
        return result
    except Exception as exc:
        log.warning("[gist] Failed to load workout_log.json: %s", exc)
        return {}


def _load_previous_coach_context(gist_id: str, token: str) -> dict:
    """Load historical coaching data + full cached Gist data (single API call).

    Returns a dict with:
      - barbell_lifts_history: list of daily barbell snapshots
      - recovery_advice_history: list of {date, advice} entries (last 3 days)
      - _full: full contents of sugarwod_wod.json (used for HEALTH_ONLY / SugarWOD-only caching)
      - _injuries: active injuries from health_input.json (see injuries.py)
    """
    empty = {"barbell_lifts_history": [], "recovery_advice_history": [], "_full": {},
             "_personal_events": [], "_running_plan": {}, "_injuries": []}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        # Blessures staan los van sugarwod_wod.json — altijd lezen, ook als die
        # nog leeg is, anders mist de coach ze bij een eerste run.
        health_raw = gist_file_content(files.get("health_input.json", {}), token)
        try:
            active_injuries = parse_injuries(json.loads(health_raw) if health_raw else {})
        except (ValueError, TypeError):
            active_injuries = []
        if active_injuries:
            log.info("[gist] %d actieve blessure(s) geladen uit health_input.json", len(active_injuries))

        raw = gist_file_content(files.get(GIST_FILENAME, {}), token)
        if not raw:
            log.warning("[gist] %s is leeg of onleesbaar — cache wordt niet hergebruikt", GIST_FILENAME)
            return {**empty, "_injuries": active_injuries}
        existing = json.loads(raw)
        personal_events_raw = gist_file_content(files.get("personal_events.json", {}), token)
        personal_events = json.loads(personal_events_raw).get("events", []) if personal_events_raw else []
        running_plan_raw = gist_file_content(files.get("running_plan.json", {}), token)
        running_plan = json.loads(running_plan_raw) if running_plan_raw else {}
        return {
            "barbell_lifts_history": existing.get("barbell_lifts_history", []),
            "recovery_advice_history": existing.get("recovery_advice_history", []),
            "_full": existing,
            "_personal_events": personal_events,
            "_running_plan": running_plan,
            "_injuries": active_injuries,
        }
    except Exception as exc:
        log.warning("[gist] Could not load previous coach context: %s", exc)
        return empty


def save_to_gist(gist_id: str, token: str, wod_data: dict) -> None:
    today_str = datetime.now(AMS).date().isoformat()

    # Accumulate barbell lifts history (passed via wod_data to avoid extra gist read)
    barbell_lifts = wod_data.get("barbell_lifts", {})
    history = wod_data.pop("_barbell_lifts_history_prev", [])
    history = [h for h in history if h.get("date") != today_str]
    if barbell_lifts:
        history.append({"date": today_str, "lifts": barbell_lifts})
    history = sorted(history, key=lambda h: h.get("date", ""))[-365:]
    wod_data["barbell_lifts_history"] = history
    log.info("[gist] Barbell history: %d snapshots (latest: %s)", len(history), today_str)

    # Accumulate recovery advice history (keep last 3 days for continuity)
    recovery_advice = wod_data.get("recovery_advice", "")
    advice_history = wod_data.pop("_recovery_advice_history_prev", [])
    advice_history = [h for h in advice_history if h.get("date") != today_str]
    if recovery_advice:
        ts = wod_data.get("recovery_advice_generated_at")
        entry = {"date": today_str, "advice": recovery_advice}
        if ts:
            entry["timestamp"] = ts
        advice_history.append(entry)
    advice_history = sorted(advice_history, key=lambda h: h.get("date", ""))[-3:]
    wod_data["recovery_advice_history"] = advice_history
    log.info("[gist] Recovery advice history: %d entries", len(advice_history))

    content = json.dumps(wod_data, ensure_ascii=False, indent=2)
    size_kb = len(content.encode()) / 1024
    if size_kb > 900:
        # Boven ~1 MB levert de Gist-API het bestand afgekapt uit; lezers vallen
        # dan terug op raw_url (zie gist_utils.file_content).
        log.warning("[gist] %s is %.0f KB — dicht bij of over de 1 MB API-limiet",
                    GIST_FILENAME, size_kb)
    else:
        log.info("[gist] %s is %.0f KB", GIST_FILENAME, size_kb)
    files: dict = {GIST_FILENAME: {"content": content}}
    payload = {"files": files}
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        json=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    log.info("WOD data saved to Gist %s as '%s'", gist_id, GIST_FILENAME)


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main() -> int:
    email = os.environ.get("SUGARWOD_EMAIL", "").strip()
    password = os.environ.get("SUGARWOD_PASSWORD", "").strip()
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    skip_strava = os.environ.get("SKIP_STRAVA", "false").lower() in ("true", "1", "yes")
    skip_ai = os.environ.get("SKIP_AI", "false").lower() in ("true", "1", "yes")
    # HEALTH_ONLY=true → skip SugarWOD scraping, fetch only health data (Strava/Intervals/Withings/Environmental)
    # Default (false) → fetch only SugarWOD, use cached health data from Gist
    health_only = os.environ.get("HEALTH_ONLY", "false").lower() in ("true", "1", "yes")

    if not health_only and (not email or not password):
        log.error("SUGARWOD_EMAIL and SUGARWOD_PASSWORD are required")
        return 1

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    now = datetime.now(AMS)
    this_monday = get_monday(now)
    next_monday = this_monday + timedelta(weeks=1)
    # Always fetch the past 4 weeks so the recovery coach has real WOD descriptions
    # for attended dates instead of falling back on empty "CrossFit WOD" entries.
    # Always include next week: auto-signup looks 8 days ahead, so upcoming
    # class signups can span into next week on any day of the week.  Without
    # next week's workouts in by_date, those cards would show no WOD info.
    weeks = [this_monday - timedelta(weeks=i) for i in range(3, 0, -1)] + [this_monday, next_monday]
    log.info("Fetching %d weeks: %s … %s",
             len(weeks), weeks[0].strftime("%Y%m%d"), weeks[-1].strftime("%Y%m%d"))

    # Load Gist cache once — used by both modes to avoid duplicate API calls.
    prev_coach_ctx: dict = {"barbell_lifts_history": [], "recovery_advice_history": []}
    cached_gist: dict = {}
    personal_events: list[dict] = []
    running_plan: dict = {}
    active_injuries: list[dict] = []
    if gist_id and token:
        full_ctx = _load_previous_coach_context(gist_id, token)
        cached_gist = full_ctx.pop("_full", {})
        personal_events = full_ctx.pop("_personal_events", [])
        running_plan = full_ctx.pop("_running_plan", {})
        active_injuries = full_ctx.pop("_injuries", [])
        prev_coach_ctx = full_ctx
        log.info("[gist] personal_events.json: %d events geladen", len(personal_events))
        log.info(
            "Gist cache geladen: %d barbell snapshots, %d advice entries",
            len(prev_coach_ctx["barbell_lifts_history"]),
            len(prev_coach_ctx["recovery_advice_history"]),
        )

    if not health_only:
        # ── SUGARWOD MODE: Fetch fresh SugarWOD data via Playwright ─────────
        barbell_lifts: dict = {}
        personal_records: list[dict] = []
        benchmark_workouts: list[dict] = []
        athlete_logbook: list[dict] = []

        playwright_result = fetch_all_workouts_playwright(email, password, weeks, gist_id, token)
        if playwright_result is not None:
            workouts = playwright_result["workouts"]
            scraped = playwright_result.get("barbell_lifts", {})
            has_values = scraped and any(v for v in scraped.values())
            barbell_lifts = scraped if has_values else BARBELL_LIFTS_FALLBACK
            barbell_source = "scraper" if has_values else "fallback"
            personal_records = playwright_result.get("personal_records", [])
            benchmark_workouts = playwright_result.get("benchmark_workouts", [])
            athlete_logbook = playwright_result.get("athlete_logbook", [])
            log.info(
                "Playwright fetched %d workouts, %d barbell lifts, %d PRs",
                len(workouts), len(barbell_lifts), len(personal_records),
            )
        else:
            # ── Fallback: direct HTTP requests (workouts only) ────────────────
            barbell_source = "fallback"
            barbell_lifts = BARBELL_LIFTS_FALLBACK
            log.info("Falling back to HTTP request approach")
            csrf, session_token, athlete_id, affiliate_id = login(session, email, password)
            if csrf is None:
                log.warning("Proceeding without CSRF token — requests may be rejected")

            workouts = []
            for monday in weeks:
                try:
                    week_workouts = fetch_workouts_week(
                        session, monday, csrf,
                        session_token=session_token,
                        athlete_id=athlete_id,
                        affiliate_id=affiliate_id,
                    )
                    workouts.extend(week_workouts)
                    log.info("Week %s: %d workout(s)", monday.strftime("%Y%m%d"), len(week_workouts))
                except Exception as exc:
                    log.warning("Failed to fetch week %s: %s", monday.strftime("%Y%m%d"), exc)

        if not workouts:
            log.error("No workouts fetched")
            return 1

    else:
        # ── HEALTH_ONLY MODE: Use cached SugarWOD data from Gist ────────────
        log.info("HEALTH_ONLY modus: gecachte SugarWOD data geladen uit Gist")
        workouts = cached_gist.get("workouts", [])
        barbell_lifts = cached_gist.get("barbell_lifts") or BARBELL_LIFTS_FALLBACK
        barbell_source = "cache"
        personal_records = cached_gist.get("personal_records", [])
        benchmark_workouts = cached_gist.get("benchmark_workouts", [])
        athlete_logbook = []
        if not workouts:
            log.warning("HEALTH_ONLY: geen gecachte workouts in Gist — coach context beperkt")

    # Build a date-keyed index so the PWA can look up workouts by date
    # without iterating the full list.
    today = now.date()
    by_date: dict[str, list[dict]] = {}
    for w in workouts:
        d = w.get("date")
        if d:
            entry: dict = {"title": w["title"], "description": w["description"]}
            if w.get("athlete_notes"):
                entry["athlete_notes"] = w["athlete_notes"]
            by_date.setdefault(d, []).append(entry)

    # Generate AI coaching plans for upcoming workouts (moved below load_sportbit_attended_dates
    # so that signed_up_times is available)
    upcoming_workouts = [w for w in workouts if w.get("date", "") >= today.isoformat()]

    if health_only:
        # ── HEALTH_ONLY: Fetch fresh health data ────────────────────────────
        # Strava
        if skip_strava:
            log.info("Strava fetch overgeslagen (SKIP_STRAVA=true)")
            strava_data = None
        else:
            try:
                from fetch_strava import fetch_strava_data  # noqa: PLC0415
                strava_data = fetch_strava_data()
                if strava_data:
                    n_acts = sum(len(v) for v in strava_data.get("activities_by_date", {}).values())
                    log.info("Strava data opgehaald: %d activiteiten", n_acts)
                else:
                    log.info("Geen Strava data beschikbaar — coach gebruikt alleen workoutgeschiedenis")
            except Exception as exc:
                log.warning("Strava fetch mislukt: %s", exc)
                strava_data = None

        # Intervals.icu
        skip_intervals = os.environ.get("SKIP_INTERVALS", "false").lower() in ("true", "1", "yes")
        intervals_data = None
        if skip_intervals:
            log.info("Intervals.icu fetch overgeslagen (SKIP_INTERVALS=true)")
        else:
            try:
                from fetch_intervals import fetch_intervals_data  # noqa: PLC0415
                intervals_data = fetch_intervals_data()
                if intervals_data:
                    n_days = len((intervals_data.get("wellness") or {}).get("by_date") or {})
                    n_acts = sum(
                        len(v) for v in ((intervals_data.get("activities") or {}).get("by_date") or {}).values()
                    )
                    log.info("Intervals.icu data opgehaald: %d wellness-dagen, %d activiteiten", n_days, n_acts)
                else:
                    log.info("Geen intervals.icu data beschikbaar (API key ontbreekt of geen data)")
            except Exception as exc:
                log.warning("Intervals.icu fetch mislukt: %s", exc)

        # Huidtemperatuur (Fenix 8) verrijken via directe Garmin Connect-fetch.
        # intervals.icu synct skin temperature niet; Garmin bewaart het in de
        # slaapdata. Alleen uitvoeren als Garmin-credentials aanwezig zijn; de
        # waarde wordt niet-destructief in de intervals-wellness gemerged.
        if os.environ.get("GARMIN_EMAIL") or os.environ.get("GARMIN_TOKENS") or os.environ.get("GARMIN_SESSION_ID"):
            try:
                from fetch_garmin import fetch_garmin_data  # noqa: PLC0415
                garmin_data = fetch_garmin_data()
                skin_temp = (garmin_data or {}).get("skin_temp")
                g_date = (garmin_data or {}).get("date")
                if skin_temp is not None and g_date:
                    if intervals_data is None:
                        intervals_data = {"wellness": {"by_date": {}}, "activities": {"by_date": {}}}
                    intervals_data.setdefault("wellness", {}).setdefault("by_date", {})
                    intervals_data["wellness"]["by_date"].setdefault(g_date, {})["skin_temp_c"] = skin_temp
                    log.info("Garmin huidtemperatuur gemerged in wellness %s: %s °C", g_date, skin_temp)
                else:
                    log.info("Geen Garmin huidtemperatuur beschikbaar in slaapdata")
            except Exception as exc:
                log.warning("Garmin huidtemperatuur-fetch mislukt: %s", exc)

        # Verwijder geplande workout-events waarvan de activiteit al geregistreerd is
        _iv_id    = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
        _iv_key   = os.environ.get("INTERVALS_API_KEY", "").strip()
        _gist_id  = os.environ.get("GIST_ID", "").strip()
        _gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
        if _iv_id and _iv_key and _gist_id and _gh_token:
            try:
                from generate_running_workout import cleanup_completed_events  # noqa: PLC0415
                cleanup_completed_events(_iv_id, _iv_key, _gist_id, _gh_token)
            except Exception as exc:
                log.warning("Workout event cleanup mislukt: %s", exc)

        # Withings
        skip_withings = os.environ.get("SKIP_WITHINGS", "false").lower() in ("true", "1", "yes")
        withings_data = None
        if not skip_withings:
            try:
                from fetch_withings import fetch_withings_data  # noqa: PLC0415
                withings_data = fetch_withings_data()
                if withings_data:
                    log.info("Withings data opgehaald: %d metingen", len(withings_data.get("measurements", [])))
                else:
                    log.info("Geen Withings data beschikbaar (secrets ontbreken of geen data)")
            except Exception as exc:
                log.warning("Withings fetch mislukt: %s", exc)

    else:
        # ── SUGARWOD MODE: Use cached health data from Gist ─────────────────
        strava_data = cached_gist.get("strava_data")
        intervals_data = cached_gist.get("intervals_data")
        withings_data = cached_gist.get("withings_data")
        log.info("SugarWOD modus: gecachte health data (Strava/Intervals/Withings) geladen uit Gist")

    # Subjectieve hersteldata (sliders) is verwijderd uit de UI — niet meer gebruiken.
    health_input: dict | None = None
    health_history: list[dict] = []

    # Generate daily recovery advice.
    # Priority for "which days did the athlete actually train":
    #   1. Sportbit signup data (most reliable — sign-up = went to the box)
    #   2. SugarWOD logbook (workouts actually scored; athlete doesn't always log)
    #   3. All programmed past WODs (last resort)

    # Per date: prefer the main workout (METCON/WEIGHTLIFTING/TEAM METCON) over
    # accessories (Bird Dog, Prone Extensions, etc. which have empty descriptions).
    def _pick_main_workout(workouts_for_date: list[dict]) -> dict:
        for kw in _MAIN_KEYWORDS:
            for w in workouts_for_date:
                if kw in w.get("title", "").lower():
                    return w
        # fallback: pick the one with the longest description
        return max(workouts_for_date, key=lambda w: len(w.get("description", "")))

    _by_date_all: dict[str, list[dict]] = {}
    for w in workouts:
        _by_date_all.setdefault(w["date"], []).append(w)
    date_to_workout = {d: _pick_main_workout(ws) for d, ws in _by_date_all.items()}

    # 1. Sportbit attended dates (signed up, not cancelled) + actual training times
    sportbit_attended, signed_up_times, cancelled_cf_dates, all_sportbit_signed_up = load_sportbit_attended_dates(gist_id, token)

    # Environmental data (weer + AQI) — opgehaald na signed_up_times zodat trainingsdagen bekend zijn
    env_data = None
    if health_only:
        try:
            from fetch_environmental import fetch_environmental_data  # noqa: PLC0415
            env_data = fetch_environmental_data(signed_up_times)
            if env_data:
                log.info("Environmental data opgehaald (AQI: %s)", (env_data.get("aqi") or {}).get("value", "n/a"))
        except Exception as exc:
            log.warning("Environmental fetch mislukt: %s", exc)
    else:
        env_data = cached_gist.get("environmental_data")
        log.info("SugarWOD modus: gecachte environmental data geladen uit Gist")

    # Load workout log early — needed by both generate_workout_plans and recovery advice
    workout_log = load_workout_log(gist_id, token)

    # Generate AI coaching plans for upcoming workouts (requires signed_up_times)
    # Only generate plans for dates the athlete has an active (non-cancelled) signup.
    if signed_up_times:
        _signed_up_upcoming = [w for w in upcoming_workouts if w.get("date", "") in signed_up_times]
        _plans_input = _signed_up_upcoming if _signed_up_upcoming else upcoming_workouts
    else:
        _plans_input = upcoming_workouts
    if skip_ai:
        # AI overslaan om kosten te besparen — behoud de eerder gegenereerde plannen
        # uit de Gist zodat het dashboard niet leeg raakt (save_to_gist overschrijft
        # het hele bestand, dus None/{} zou de bestaande coaching wissen).
        log.info("AI coaching overgeslagen (SKIP_AI=true) — vorige workout-plannen behouden")
        workout_plans = cached_gist.get("workout_plans") or {}
    else:
        workout_plans = generate_workout_plans(
            _plans_input, barbell_lifts, ATHLETE_PROFILE,
            signed_up_times=signed_up_times,
            health_input=health_input,
            health_history=health_history,
            injuries=active_injuries,
            strava_data=strava_data,
            workout_log=workout_log,
            barbell_history=prev_coach_ctx["barbell_lifts_history"],
            personal_records=personal_records,
            intervals_data=intervals_data,
            environmental_data=env_data,
            personal_events=personal_events,
            running_plan=running_plan,
            withings_data=withings_data,
        )
    past_sportbit_dates = sorted(
        [d for d in sportbit_attended if d < today.isoformat()],
        reverse=True,
    )
    # Use next Sportbit signup as next_workout so the coach addresses the actual
    # next planned class, not just the first programmed SugarWOD on or after today.
    # Use all_sportbit_signed_up (no weekday filter) so manually registered classes
    # on non-regular days (e.g. Friday) are also picked up.
    future_sportbit_dates = sorted(d for d in all_sportbit_signed_up if d >= today.isoformat())
    if future_sportbit_dates:
        next_date = future_sportbit_dates[0]
        next_workout = date_to_workout.get(next_date) or {
            "date": next_date, "title": "CrossFit WOD", "description": ""
        }
        log.info("Next workout from Sportbit signup: %s", next_date)
    else:
        # Only use workouts strictly after today as fallback — avoids presenting
        # today's programmed WOD as "next workout" when the athlete has no signup for it.
        next_workout = next((w for w in upcoming_workouts if w.get("date", "") > today.isoformat()), None)
        log.info("Next workout from SugarWOD schedule: %s",
                 next_workout.get("date") if next_workout else "none")
    # All main workouts per date (METCON + TEAM METCON + WEIGHTLIFTING, etc.) so the
    # recovery coach sees every WOD the athlete could have done on a given day.
    date_to_all_main_workouts: dict[str, list[dict]] = {}
    for w in workouts:
        if w.get("description") or any(kw in w.get("title", "").lower() for kw in _MAIN_KEYWORDS):
            date_to_all_main_workouts.setdefault(w["date"], []).append(w)

    deload_detected = detect_deload(intervals_data, health_history)
    if deload_detected:
        log.info("[deload] Overtraining risico gedetecteerd — herstelweek aanbevolen")

    if skip_ai:
        # Behoud het eerder gegenereerde herstel-advies (zie toelichting hierboven).
        recovery_advice = cached_gist.get("recovery_advice")
    elif past_sportbit_dates:
        attended_workouts = []
        for d in past_sportbit_dates[:5]:
            log_entry = workout_log.get(d)
            if log_entry:
                # Athlete explicitly logged which workouts they did + weights
                workouts_done = log_entry.get("workouts_done") or []
                notes = log_entry.get("notes", "")
                if workouts_done:
                    for title in workouts_done:
                        base = next(
                            (w for w in date_to_all_main_workouts.get(d, []) if w.get("title") == title),
                            {"date": d, "title": title, "description": ""},
                        )
                        extra = f"\nGebruikte gewichten/notities: {notes}" if notes else ""
                        attended_workouts.append({**base, "description": base.get("description", "") + extra})
                else:
                    # Log entry exists but no workout selected — use notes only
                    main_wods = date_to_all_main_workouts.get(d) or [{"date": d, "title": "CrossFit WOD", "description": ""}]
                    for w in main_wods:
                        extra = f"\nNotities atleet: {notes}" if notes else ""
                        attended_workouts.append({**w, "description": w.get("description", "") + extra})
            else:
                main_wods = date_to_all_main_workouts.get(d)
                if main_wods:
                    attended_workouts.extend(main_wods)
                else:
                    attended_workouts.append({"date": d, "title": "CrossFit WOD", "description": ""})
        attended_workouts.sort(key=lambda w: w["date"], reverse=True)

        # Also include recent Strava/intervals.icu activities from dates NOT in the
        # Sportbit signup (e.g. special holiday WODs like Pinksterwod, open-gym days).
        # Without this, workouts done outside of the normal class signup are invisible
        # to the AI coach and lead to wrong recovery calculations.
        _strava_by_date_main = (strava_data or {}).get("activities_by_date") or {}
        _intervals_acts_main = (intervals_data or {}).get("activities", {}).get("by_date") or {}
        _covered_dates = {w["date"] for w in attended_workouts}
        _lookback_start = (today - timedelta(days=14)).isoformat()
        _extra_dates = sorted(
            {
                d for d in (set(_strava_by_date_main) | set(_intervals_acts_main))
                if _lookback_start <= d < today.isoformat() and d not in _covered_dates
            },
            reverse=True,
        )
        for _d in _extra_dates[:3]:
            _acts_for_date = _strava_by_date_main.get(_d, []) + _intervals_acts_main.get(_d, [])
            # Don't attach the box's programmed WOD description to a date unless
            # there's positive evidence the athlete actually did a CrossFit-style
            # session that day. The box posts a WOD every weekday (including days
            # the athlete is never scheduled — e.g. Tuesday isn't part of his
            # SCHEDULE at all), so merely having *some* logged activity on a date
            # is not evidence he did that WOD — a run or ride logged on an
            # off-schedule day must not be presented to the AI coach as CrossFit.
            # This also covers dates where he had signed up but cancelled.
            if _d in cancelled_cf_dates or not _is_crossfit_activity(_acts_for_date):
                _title = _acts_for_date[0].get("name", "activity") if _acts_for_date else "activity"
                attended_workouts.append({"date": _d, "title": _title, "description": ""})
                log.info("Extra date %s: skipping WOD description (%s)", _d,
                         "cancelled CF signup" if _d in cancelled_cf_dates else "no CrossFit-type activity logged")
                continue
            _main_wods = date_to_all_main_workouts.get(_d)
            if _main_wods:
                attended_workouts.extend(_main_wods)
            else:
                _title = _acts_for_date[0].get("name", "CrossFit WOD") if _acts_for_date else "CrossFit WOD"
                attended_workouts.append({"date": _d, "title": _title, "description": ""})
        if _extra_dates:
            attended_workouts.sort(key=lambda w: w["date"], reverse=True)
            log.info("Coach advice: %d extra non-Sportbit activity dates toegevoegd: %s",
                     len(_extra_dates[:3]), _extra_dates[:3])

        log.info("Coach advice: %d Sportbit attended dates → %d workouts with descriptions",
                 len(past_sportbit_dates), len([w for w in attended_workouts if w.get("description")]))
        recovery_advice = generate_recovery_advice(
            attended_workouts[:10], next_workout, barbell_lifts, ATHLETE_PROFILE, today,
            strava_data=strava_data,
            health_input=health_input,
            injuries=active_injuries,
            signed_up_times=signed_up_times,
            health_history=health_history,
            previous_advice=prev_coach_ctx["recovery_advice_history"],
            barbell_history=prev_coach_ctx["barbell_lifts_history"],
            personal_records=personal_records,
            benchmark_workouts=benchmark_workouts,
            intervals_data=intervals_data,
            withings_data=withings_data,
            environmental_data=env_data,
            personal_events=personal_events,
            running_plan=running_plan,
            deload_detected=deload_detected,
            now_time=now.strftime("%H:%M"),
        )

    # 2. SugarWOD logbook (athlete scored a result)
    elif athlete_logbook:
        attended_workouts = []
        for entry in sorted(athlete_logbook, key=lambda e: e.get("date", ""), reverse=True):
            raw_date = entry.get("date", "")
            iso_date = raw_date
            if raw_date and not raw_date[:4].isdigit():
                for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%d-%m-%Y"):
                    try:
                        iso_date = datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        pass
            full = date_to_workout.get(iso_date)
            attended_workouts.append(full or {
                "date": iso_date,
                "title": entry.get("workout", "WOD"),
                "description": entry.get("result", ""),
            })
        log.info("Coach advice: %d SugarWOD logbook entries", len(attended_workouts))
        recovery_advice = generate_recovery_advice(
            attended_workouts[:5], next_workout, barbell_lifts, ATHLETE_PROFILE, today,
            strava_data=strava_data,
            health_input=health_input,
            injuries=active_injuries,
            signed_up_times=signed_up_times,
            health_history=health_history,
            previous_advice=prev_coach_ctx["recovery_advice_history"],
            barbell_history=prev_coach_ctx["barbell_lifts_history"],
            personal_records=personal_records,
            benchmark_workouts=benchmark_workouts,
            intervals_data=intervals_data,
            withings_data=withings_data,
            environmental_data=env_data,
            personal_events=personal_events,
            running_plan=running_plan,
            deload_detected=deload_detected,
            now_time=now.strftime("%H:%M"),
        )

    # 3. Fallback: all programmed past workouts
    else:
        past_workouts_sorted = sorted(
            [w for w in workouts if w.get("date", "") < today.isoformat()],
            key=lambda w: w.get("date", ""),
            reverse=True,
        )
        log.info("Coach advice fallback: %d programmed past workouts", len(past_workouts_sorted))
        recovery_advice = generate_recovery_advice(
            past_workouts_sorted[:3], next_workout, barbell_lifts, ATHLETE_PROFILE,
            strava_data=strava_data,
            health_input=health_input,
            injuries=active_injuries,
            signed_up_times=signed_up_times,
            health_history=health_history,
            previous_advice=prev_coach_ctx["recovery_advice_history"],
            barbell_history=prev_coach_ctx["barbell_lifts_history"],
            personal_records=personal_records,
            benchmark_workouts=benchmark_workouts,
            intervals_data=intervals_data,
            withings_data=withings_data,
            environmental_data=env_data,
            personal_events=personal_events,
            running_plan=running_plan,
            deload_detected=deload_detected,
            now_time=now.strftime("%H:%M"),
        )

    if skip_ai:
        # Behoud de tijdstempels van de eerder gegenereerde (en hierboven overgenomen)
        # coaching, zodat het dashboard "gegenereerd …" correct blijft tonen.
        workout_plans_generated_at = cached_gist.get("workout_plans_generated_at")
        recovery_advice_generated_at = cached_gist.get("recovery_advice_generated_at")
    else:
        ai_generated_at = datetime.now(AMS).isoformat()
        workout_plans_generated_at = ai_generated_at if workout_plans else None
        recovery_advice_generated_at = ai_generated_at if recovery_advice else None
    # Nieuwe PR's sinds de vorige echte SugarWOD-run → pushmelding.
    if not health_only:
        try:
            from pr_alerts import notify_new_prs  # noqa: PLC0415
            n_new = notify_new_prs(cached_gist.get("personal_records") or [], personal_records)
            if n_new:
                log.info("%d nieuwe PR('s) gedetecteerd", n_new)
        except Exception as exc:  # noqa: BLE001 — melding mag de sync nooit breken
            log.warning("PR-detectie mislukt: %s", exc)

    wod_data = {
        "workouts": workouts,
        "by_date": by_date,
        "barbell_lifts": barbell_lifts,
        "barbell_source": barbell_source,
        "deload_alert": deload_detected,
        "personal_records": personal_records,
        "benchmark_workouts": benchmark_workouts,
        "workout_plans": workout_plans,
        "workout_plans_generated_at": workout_plans_generated_at,
        "recovery_advice": recovery_advice,
        "recovery_advice_generated_at": recovery_advice_generated_at,
        "strava_data": strava_data,
        "intervals_data": intervals_data,
        "withings_data": withings_data,
        "environmental_data": env_data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        # Moment van de laatste échte SugarWOD-scrape (de 4-uurlijkse health-run
        # scrapet niet en neemt de vorige waarde over). De PWA toont hiermee de
        # versheid per databron.
        "sugarwod_fetched_at": (cached_gist.get("sugarwod_fetched_at") or cached_gist.get("fetched_at"))
        if health_only else datetime.now(timezone.utc).isoformat(),
        # Internal keys consumed by save_to_gist() — removed before saving
        "_barbell_lifts_history_prev": prev_coach_ctx["barbell_lifts_history"],
        "_recovery_advice_history_prev": prev_coach_ctx["recovery_advice_history"],
    }

    if gist_id and token:
        try:
            save_to_gist(gist_id, token, wod_data)
        except requests.HTTPError as exc:
            log.error("Failed to save WOD to Gist: %s", exc)
            return 1
    else:
        log.warning("GIST_ID or GITHUB_TOKEN not set — printing to stdout")
        print(json.dumps(wod_data, indent=2, ensure_ascii=False))

    # ── GitHub Actions step summary ───────────────────────────────────────
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if step_summary:
        upcoming_dates = sorted(w["date"] for w in workouts if w.get("date", "") >= today.isoformat())
        past_dates = sorted((w["date"] for w in workouts if w.get("date", "") < today.isoformat()), reverse=True)
        pr_count = len(personal_records)
        bm_count = len(benchmark_workouts)
        barbell_count = len(barbell_lifts)
        bm_cats = sorted({b.get("category", "?") for b in benchmark_workouts}) if benchmark_workouts else []
        pr_preview = "\n".join(
            f"| {p.get('workout', '?')} | {p.get('notes', '')} | {p.get('date', '')} |"
            for p in sorted(personal_records, key=lambda p: p.get("date", ""), reverse=True)[:10]
        )
        bm_preview = "\n".join(
            f"| {b.get('name', '?')} | {b.get('result', '')} | {b.get('category', '')} | {b.get('date', '')} |"
            for b in sorted(benchmark_workouts, key=lambda b: b.get("date", ""), reverse=True)[:10]
        )
        lines = [
            "## SugarWOD fetch resultaat",
            "",
            f"**Datum:** {today.isoformat()}",
            "",
            "### Workouts",
            f"- Aankomend: {len(upcoming_dates)} dag(en) — {', '.join(upcoming_dates) or '—'}",
            f"- Verleden (in gist): {len(past_dates)} dag(en)",
            "",
            "### Barbell lifts",
            f"- {barbell_count} bewegingen geladen" if barbell_count else "- ⚠️ Geen barbell lifts gevonden",
            "",
            "### Personal Records",
            f"- **{pr_count}** PRs gevonden" if pr_count else "- ⚠️ Geen PRs gevonden (fetch mislukt?)",
        ]
        if pr_count:
            lines += [
                "",
                "| Workout | Notes | Datum |",
                "|---------|-------|-------|",
                pr_preview,
                f"{'_(en meer…)_' if pr_count > 10 else ''}",
            ]
        lines += [
            "",
            "### Benchmark Workouts",
            f"- **{bm_count}** benchmarks gevonden in {len(bm_cats)} categorie(ën): {', '.join(bm_cats)}" if bm_count
            else "- ⚠️ Geen benchmarks gevonden (fetch mislukt?)",
        ]
        if bm_count:
            lines += [
                "",
                "| Naam | Resultaat | Categorie | Datum |",
                "|------|-----------|-----------|-------|",
                bm_preview,
                f"{'_(en meer…)_' if bm_count > 10 else ''}",
            ]
        lines += [
            "",
            "### Coach advies",
            "- ✅ Gegenereerd" if recovery_advice else "- ⚠️ Niet gegenereerd",
        ]
        try:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            log.info("Step summary written")
        except Exception as exc:
            log.warning("Failed to write step summary: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
