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
from datetime import date as date_cls, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

SUGARWOD_BASE = "https://app.sugarwod.com"
LOGIN_URL = f"{SUGARWOD_BASE}/public/api/v1/login"
WORKOUTS_URL = f"{SUGARWOD_BASE}/workouts"
GIST_FILENAME = "sugarwod_wod.json"
AMS = ZoneInfo("Europe/Amsterdam")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# ──────────────────────────────────────────────────────────────
# Athlete profile (used for AI coaching plans)
# ──────────────────────────────────────────────────────────────

BARBELL_LIFTS_FALLBACK = {
    "3 Position Clean (hang, below knee, floor)": {"1RM": 37.5, "3RM": 37},
    "3 Position Snatch (High Hang, Above the Knee, Floor)": {"1RM": 25, "3RM": 35},
    "Back Pause Squat": {"5RM": 43},
    "Back Rack Lunges": {"1RM": 50, "2RM": 50, "3RM": 50, "5RM": 50},
    "Back Squat": {"1RM": 67, "2RM": 60, "3RM": 62, "5RM": 56},
    "Bench Press": {"1RM": 67.5, "2RM": 55, "3RM": 60, "5RM": 50},
    "Bent Over Row": {"5RM": 30},
    "Box Squat": {"1RM": 90},
    "Clean": {"1RM": 50, "2RM": 53, "3RM": 40},
    "Clean & Jerk": {"1RM": 58, "2RM": 32.5, "3RM": 53},
    "Deadlift": {"1RM": 100, "2RM": 80, "3RM": 80, "5RM": 90},
    "Front Pause Squat": {"2RM": 37.5},
    "Front Rack Lunges": {"1RM": 35, "2RM": 35, "3RM": 35, "5RM": 35},
    "Front Squat": {"1RM": 65, "3RM": 35, "5RM": 57},
    "Front Squat + Jerk": {"5RM": 52.5},
    "Full Grip, No Foot Clean + Tall Jerks": {"5RM": 50},
    "Hang Clean": {"1RM": 55, "3RM": 40},
    "Hang Power Clean": {"1RM": 57.5, "3RM": 43, "5RM": 50},
    "Hang Power Snatch": {"1RM": 40, "2RM": 33, "3RM": 38},
    "Hang Squat Clean": {"3RM": 42.5, "5RM": 30},
    "Hang Squat Snatch": {"1RM": 35, "2RM": 35, "3RM": 32.5},
    "In The Hole Front Squat": {"1RM": 45},
    "Muscle Clean": {"5RM": 35},
    "Overhead Squat": {"1RM": 48, "2RM": 44},
    "Power Clean": {"1RM": 57, "2RM": 57, "3RM": 45},
    "Power Clean & Jerk": {"1RM": 61, "2RM": 61, "3RM": 58},
    "Power Snatch": {"1RM": 43, "2RM": 43, "3RM": 35, "5RM": 35},
    "Pressing Complex": {"1RM": 50},
    "Push Jerk": {"1RM": 61, "2RM": 61, "3RM": 50, "5RM": 40},
    "Push Press": {"1RM": 57.5, "2RM": 50, "5RM": 40},
    "Shoulder Press": {"1RM": 42.5, "2RM": 37.5, "3RM": 35, "5RM": 27},
    "Snatch": {"1RM": 38, "2RM": 34, "3RM": 35},
    "Snatch + Overhead Squat": {"2RM": 25},
    "Snatch Balance": {"1RM": 37.5, "2RM": 30, "3RM": 25},
    "Snatch Deadlift + High Hang Shrug": {"5RM": 37.5},
    "Snatch Grip Deadlift": {"3RM": 37.5},
    "Snatch Grip Push Press": {"5RM": 37.5},
    "Snatch Pull": {"2RM": 40},
    "Snatch Push Press + Overhead Squat": {"2RM": 40, "3RM": 27},
    "Split Jerk": {"1RM": 50, "2RM": 58},
    "Squat Clean": {"1RM": 53, "3RM": 40, "5RM": 35},
    "Squat Snatch": {"1RM": 45, "3RM": 32, "5RM": 30},
    "Sumo Deadlift": {"2RM": 50, "3RM": 50},
    "Sumo Deadlift High Pull": {"5RM": 43},
    "Thruster": {"1RM": 53, "2RM": 43, "3RM": 44, "5RM": 43},
    "Weighted Chin Up": {"1RM": 7.5, "3RM": 7.5},
    "Weighted Hip Thrust": {"5RM": 110},
}

ATHLETE_PROFILE = {
    "name": "Ralph de Leeuw",
    "weight_kg": 77,
    "experience": "intermediate-advanced (4+ jaar CrossFit)",
    "rx_preference": "mix van RX en Scaled — RX wanneer mogelijk",
    "injuries": "geen",
    "gym": "CrossFit Hilversum",
    "doel": "Uiteindelijk alles RX kunnen. Leeftijd 47, voelt zich goed en traint serieus.",
    "skill_focus": [
        "hardlooptempo (sneller worden op 400m/800m/1mi)",
        "back squat & front squat (techniek + kracht)",
        "double unders (consistentie en hoog volume)",
        "handstand push-ups (strikt en kipping, richting RX)",
        "pull-ups (kipping en butterfly, richting RX)",
        "handstand walk (afstand opbouwen)",
    ],
}

# Weekly training schedule: weekday (0=Mon) → start time
# Mirrors the SCHEDULE in autosignup.py
TRAINING_SCHEDULE: dict[int, str] = {
    0: "20:00",  # Monday
    2: "08:00",  # Wednesday
    3: "20:00",  # Thursday
    5: "09:00",  # Saturday
    6: "09:00",  # Sunday
}

# Dinner time — used to reason about pre/post-workout nutrition
DINNER_TIME = "18:00"

# Fixed breakfast — always the same high-protein meal, eaten around 07:00
BREAKFAST = {
    "time": "07:00",
    "description": (
        "Vast ontbijt (~838 kcal | ~56g eiwit | ~61g KH | ~36g vet): "
        "Alpro Mild & Creamy zonder suikers (200ml) met Holie's Granola Protein Crunch (75g) "
        "en Upfront Vegan Eiwit Shake chocolade (30g). "
        "Daarnaast 2 volkoren boterhammen met AH amandelpasta (~15g) en een beetje pure hagelslag (~10g)."
    ),
}

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
            email_input = page.locator('input[type="email"], input[name="email"]').first
            email_input.click()
            email_input.type(email)

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

            # Capture session cookies before closing the browser
            browser_cookies = {
                c["name"]: c["value"] for c in context.cookies()
                if "sugarwod.com" in c.get("domain", "")
            }
            log.info("[browser] Captured %d session cookies", len(browser_cookies))

            # Try to extract CSRF and trackId from the /api/workouts XHR URL
            api_csrf: str | None = None
            track_id: str | None = None
            for item in list(captured) + _barbell_page_captured:
                url = item["url"]
                if "/api/workouts" in url:
                    p = dict(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
                    if not api_csrf:
                        api_csrf = p.get("_csrf", [None])[0]
                    if not track_id:
                        track_id = p.get("trackId", [None])[0]
                    if api_csrf:
                        log.info("[browser] Extracted _csrf=…%s trackId=%s",
                                 api_csrf[-6:] if api_csrf else "none", track_id)
                        break

            # Fallback: get CSRF from a cookie (SugarWOD sets _csrf as a cookie)
            if not api_csrf:
                api_csrf = browser_cookies.get("_csrf") or browser_cookies.get("XSRF-TOKEN")
                if api_csrf:
                    log.info("[browser] CSRF token from cookie")

            log.info("[browser] CSRF: %s, trackId: %s",
                     (api_csrf[:10] + "…" if api_csrf else "none"), track_id)
            browser.close()

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

# Keywords that identify a "main" workout (METCON, strength, etc.) vs accessories
_MAIN_KEYWORDS = ("metcon", "weightlifting", "team metcon", "strength", "conditioning")


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
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    positions = []
    for i, abbr in enumerate(days):
        date = monday + timedelta(days=i)
        m = re.search(rf"\b{abbr}\s+{date.day}\b", full_text)
        if m:
            positions.append((i, m.start(), m.end()))

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


# ──────────────────────────────────────────────────────────────
# AI workout plan generation
# ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()


def _detect_team_size(text: str) -> int | None:
    """Return team size (2 or 3) if workout is a partner/team workout, else None."""
    import re
    t = text.lower()
    # Explicit team size: "teams of 3", "team of 2", "pair of 3", etc.
    m = re.search(r'\bteam(?:s)?\s+of\s+(\d+)', t)
    if m:
        return int(m.group(1))
    m = re.search(r'\bpair(?:s)?\s+of\s+(\d+)', t)
    if m:
        return int(m.group(1))
    # "in pairs" / "with a partner" → 2
    if re.search(r'\bin\s+pairs?\b', t) or re.search(r'\bwith\s+a\s+partner\b', t):
        return 2
    # Title contains "team metcon" → likely 2 unless description says otherwise
    if 'team metcon' in t:
        return 2
    return None


def _training_time_context(date_str: str, signed_up_times: dict[str, str] | None = None) -> str:
    """Return a prompt snippet about training time and meal timing for the given date.

    Only uses actual sign-up time from the Gist state; returns empty string if the
    athlete is not signed up for a class on this date.
    """
    try:
        date_cls.fromisoformat(date_str)
    except ValueError:
        return ""
    # Only use actual sign-up time — no fallback to static schedule
    time_str = (signed_up_times or {}).get(date_str)
    if not time_str:
        return ""
    # Compare training time to breakfast and dinner
    train_h, train_m = map(int, time_str.split(":"))
    dinner_h, dinner_m = map(int, DINNER_TIME.split(":"))
    breakfast_h, breakfast_m = map(int, BREAKFAST["time"].split(":"))
    train_minutes = train_h * 60 + train_m
    dinner_minutes = dinner_h * 60 + dinner_m
    breakfast_minutes = breakfast_h * 60 + breakfast_m

    if train_minutes <= breakfast_minutes + 30:
        # Training at or just after breakfast — likely fasted or very light pre-workout
        meal_relation = (
            f"Training is early ({time_str}), around or just after breakfast ({BREAKFAST['time']}). "
            f"Standard breakfast: {BREAKFAST['description']} "
            "The athlete is probably training fasted or semi-fasted. Advise whether to eat something small or train fasted, "
            "and emphasize recovery nutrition afterward."
        )
    elif train_minutes < dinner_minutes - 60:
        # Morning/midday workout well before dinner — had breakfast, dinner is recovery meal
        meal_relation = (
            f"Training is in the morning ({time_str}). "
            f"Standard breakfast (~{BREAKFAST['time']}): {BREAKFAST['description']} "
            "The athlete ate breakfast before training (protein-rich). Dinner is the recovery meal."
        )
    elif train_minutes < dinner_minutes:
        meal_relation = (
            f"Training is shortly before dinner ({time_str}, dinner at {DINNER_TIME}). "
            "The athlete can have dinner immediately after training as a recovery meal — ideal timing window."
        )
    else:
        meal_relation = (
            f"Training is in the evening ({time_str}), after dinner ({DINNER_TIME}). "
            "The athlete has already eaten before training; meal choice is less critical for immediate recovery."
        )
    return f"\nTraining time: {time_str}. {meal_relation}"


_EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_EN_MONTHS = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _nl_date(date_str: str) -> str:
    """Format an ISO date string as 'Weekday D Month' in English, e.g. 'Sunday 12 April'."""
    try:
        d = date_cls.fromisoformat(date_str)
        return f"{_EN_WEEKDAYS[d.weekday()]} {d.day} {_EN_MONTHS[d.month - 1]}"
    except Exception:
        return date_str


def _compute_acwr(strava_data: dict | None) -> dict | None:
    """Compute a 7:14 Acute:Chronic Workload Ratio from Strava suffer scores.

    Uses the 14-day Strava window: acute = last 7 days, chronic = last 14 days.
    Returns None if insufficient data.
    """
    if not strava_data:
        return None
    activities_by_date = strava_data.get("activities_by_date") or {}
    if len(activities_by_date) < 4:
        return None
    today = date_cls.today()
    acute_total = 0.0
    chronic_total = 0.0
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        day_score = sum((a.get("suffer_score") or 0) for a in activities_by_date.get(d, []))
        chronic_total += day_score
        if i < 7:
            acute_total += day_score
    acute_avg = acute_total / 7
    chronic_avg = chronic_total / 14
    if chronic_avg == 0:
        return None
    ratio = round(acute_avg / chronic_avg, 2)
    if ratio < 0.8:
        status = "onderbelast"
    elif ratio <= 1.3:
        status = "optimale zone"
    elif ratio <= 1.5:
        status = "hoge belasting — extra herstel gewenst"
    else:
        status = "overbelasting — blessurerisico verhoogd"
    return {
        "acute_7d": round(acute_avg, 1),
        "chronic_14d": round(chronic_avg, 1),
        "ratio": ratio,
        "status": status,
    }


def _compute_barbell_trends(history: list[dict], current: dict) -> dict[str, float]:
    """Compare current 1RMs to the closest snapshot from ~4 weeks ago.

    Returns a dict of {lift_name: delta_kg} for lifts that changed.
    """
    if not history or not current:
        return {}
    today = date_cls.today()
    target_date = (today - timedelta(weeks=4)).isoformat()
    past_snapshots = [h for h in history if h.get("date", "") <= target_date]
    if not past_snapshots:
        past_snapshots = sorted(history, key=lambda h: h.get("date", ""))[:1]
    if not past_snapshots:
        return {}
    past = max(past_snapshots, key=lambda h: h.get("date", ""))
    past_lifts = past.get("lifts", {})
    trends: dict[str, float] = {}
    for lift, maxes in current.items():
        c1rm = maxes.get("1RM")
        p1rm = (past_lifts.get(lift) or {}).get("1RM")
        if c1rm and p1rm and c1rm != p1rm:
            trends[lift] = round(c1rm - p1rm, 1)
    return trends


# ──────────────────────────────────────────────────────────────
# Keukenbaas meal data
# ──────────────────────────────────────────────────────────────

def fetch_keukenbaas_meals() -> list[dict]:
    """
    Fetch meal plan data from Keukenbaas (Supabase) for the past 14 days
    and the next 7 days.  Returns a list of dicts:
        {date, meal_name, category, description}
    Returns an empty list if credentials are missing or the request fails.
    """
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        log.warning("SUPABASE_URL or SUPABASE_KEY not set — skipping Keukenbaas fetch")
        return []

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=14)).isoformat()
    end = (today + timedelta(days=7)).isoformat()

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(
            f"{url}/rest/v1/meal_plans",
            headers=headers,
            params=[
                ("select", "date,custom_text,notes,recipes(title,description,category,energy_kcal,proteins_g,carbohydrates_g,fat_g,fiber_g,recipe_ingredients(name,quantity,unit,order_index))"),
                ("date", f"gte.{start}"),
                ("date", f"lte.{end}"),
                ("order", "date.asc"),
            ],
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Keukenbaas fetch failed: %s", exc)
        return []

    meals: list[dict] = []
    for row in resp.json():
        recipe = row.get("recipes") or {}
        meal_name = recipe.get("title") or row.get("custom_text") or "Maaltijd"
        raw_ingredients = recipe.get("recipe_ingredients") or []
        raw_ingredients.sort(key=lambda i: i.get("order_index") or 0)
        ingredients = [
            {
                "name": i.get("name", ""),
                "quantity": i.get("quantity"),
                "unit": i.get("unit") or "",
            }
            for i in raw_ingredients
        ]
        meals.append({
            "date": row.get("date", ""),
            "meal_name": meal_name,
            "category": recipe.get("category") or "",
            "description": recipe.get("description") or "",
            "energy_kcal": recipe.get("energy_kcal"),
            "proteins_g": recipe.get("proteins_g"),
            "carbohydrates_g": recipe.get("carbohydrates_g"),
            "fat_g": recipe.get("fat_g"),
            "fiber_g": recipe.get("fiber_g"),
            "ingredients": ingredients,
        })

    log.info("Keukenbaas: %d meals fetched (%s → %s)", len(meals), start, end)
    return meals


def generate_recovery_advice(
    past_workouts: list[dict],
    upcoming_workout: dict | None,
    barbell_lifts: dict,
    athlete_profile: dict,
    today: "date_cls | None" = None,
    meals: list[dict] | None = None,
    strava_data: "dict | None" = None,
    health_input: "dict | None" = None,
    signed_up_times: dict[str, str] | None = None,
    health_history: list[dict] | None = None,
    previous_advice: list[dict] | None = None,
    barbell_history: list[dict] | None = None,
    personal_records: list[dict] | None = None,
    benchmark_workouts: list[dict] | None = None,
    withings_data: "dict | None" = None,
    environmental_data: "dict | None" = None,
    intervals_data: "dict | None" = None,
    personal_events: list[dict] | None = None,
    running_plan: "dict | None" = None,
    deload_detected: bool = False,
) -> str:
    """
    Generate a daily recovery/intensity advice based on recent workouts and
    what's coming up next.  Returns a markdown string.

    If strava_data is provided, activity details (HR, duration) per WOD date
    are included to assess training load.

    If health_input is provided (subjectieve scores: slaap, energie, spierpijn),
    these are included as primary physiological recovery indicators.

    If health_history is provided (list of past health_input entries), the AI
    can identify trends over time (e.g. recurring low energy on Thursdays).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping recovery advice generation")
        return ""

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping recovery advice generation")
        return ""

    client = anthropic.Anthropic(api_key=api_key)

    # Build activities-by-date lookup for WOD matching (Strava primary, intervals.icu fallback)
    strava_by_date: dict = (strava_data or {}).get("activities_by_date") or {}
    intervals_acts_by_date: dict = (intervals_data or {}).get("activities", {}).get("by_date") or {}
    log.info("Strava matching: %d datums beschikbaar: %s", len(strava_by_date), sorted(strava_by_date.keys()))
    log.info("Intervals.icu activiteiten: %d datums beschikbaar", len(intervals_acts_by_date))

    past_text = ""
    matched_acts = 0
    for w in past_workouts:
        date = w.get("date", "?")
        title = w.get("title", "WOD")
        desc = _strip_html(w.get("description", ""))[:400]
        past_text += f"\n**{date} — {title}**\n{desc}\n"

        # Strava activiteiten voor deze datum
        if date in strava_by_date:
            matched_acts += 1
            for act in strava_by_date[date]:
                avg_hr = act.get("avg_hr")
                max_hr = act.get("max_hr")
                dur = act.get("duration_min")
                cal = act.get("calories")
                act_name = act.get("name", "")
                suffer = act.get("suffer_score")
                rpe = act.get("perceived_exertion")
                elapsed = act.get("elapsed_min")
                dist_m = act.get("distance_m")
                pace_str = ""
                if dist_m and dur and dur > 0:
                    pace_sec_per_km = (dur * 60) / (dist_m / 1000)
                    pace_min = int(pace_sec_per_km // 60)
                    pace_sec = int(pace_sec_per_km % 60)
                    pace_str = f", {dist_m / 1000:.2f}km @ {pace_min}:{pace_sec:02d}/km"
                strava_line = (
                    f"  ↳ Strava: {dur}min"
                    + (f" (total {elapsed}min)" if elapsed else "")
                    + (f" ({act_name})" if act_name else "")
                    + (f", avg.HR {avg_hr:.0f} bpm" if avg_hr else "")
                    + (f", max.HR {max_hr:.0f} bpm" if max_hr else "")
                    + (f", {cal:.0f} kcal" if cal else "")
                    + (f", RE {suffer:.0f}" if suffer else "")
                    + (f", RPE {rpe}" if rpe else "")
                    + pace_str
                )
                past_text += strava_line + "\n"

        # Intervals.icu activiteiten voor deze datum (altijd tonen — rijker dan Strava voor hardlopen)
        if date in intervals_acts_by_date:
            if date not in strava_by_date:
                matched_acts += 1
            for act in intervals_acts_by_date[date]:
                dur = act.get("duration_min")
                act_name = act.get("name", "") or act.get("type", "")
                avg_hr = act.get("avg_hr")
                max_hr = act.get("max_hr")
                cal = act.get("calories")
                tl = act.get("training_load") or act.get("trimp")
                rpe = act.get("rpe")
                dist_m = act.get("distance_m")
                cadence = act.get("avg_cadence")
                elev = act.get("elevation_m")
                pace_str = ""
                if dist_m and act.get("avg_speed_ms") and act["avg_speed_ms"] > 0:
                    spm = 1000 / act["avg_speed_ms"] / 60
                    pace_str = f", {dist_m / 1000:.1f}km @ {int(spm)}:{int((spm % 1) * 60):02d}/km"
                elif dist_m and dur and dur > 0:
                    pace_sec_per_km = (dur * 60) / (dist_m / 1000)
                    pace_str = f", {dist_m / 1000:.1f}km @ {int(pace_sec_per_km // 60)}:{int(pace_sec_per_km % 60):02d}/km"
                icu_line = (
                    f"  ↳ Intervals.icu ({act_name}): {dur}min"
                    + pace_str
                    + (f", avg.HR {avg_hr} bpm" if avg_hr else "")
                    + (f", max.HR {max_hr} bpm" if max_hr else "")
                    + (f", cadans {round(cadence * 2)}spm" if cadence else "")
                    + (f", +{elev}m" if elev else "")
                    + (f", {cal} kcal" if cal else "")
                    + (f", RPE {rpe}" if rpe else "")
                    + (f", TL {round(tl)}" if tl is not None else "")
                )
                past_text += icu_line + "\n"
                # HR-zone verdeling
                hz = act.get("hr_zone_times")
                if hz and isinstance(hz, list) and sum(hz) > 0:
                    total = sum(hz)
                    zone_str = " ".join(
                        f"Z{i+1}:{round(v/total*100)}%"
                        for i, v in enumerate(hz[:5]) if v > 0
                    )
                    past_text += f"    HR zones: {zone_str}\n"
                # Laps voor hardlopen
                for i, lap in enumerate(act.get("laps", []), 1):
                    lp_parts = [f"    lap {i}:"]
                    if lap.get("distance_m"): lp_parts.append(f"{lap['distance_m']}m")
                    if lap.get("pace_per_km"): lp_parts.append(f"{lap['pace_per_km']}/km")
                    if lap.get("avg_hr"):     lp_parts.append(f"HR {lap['avg_hr']}bpm")
                    if lap.get("avg_cadence"): lp_parts.append(f"{round(lap['avg_cadence'] * 2)}spm")
                    past_text += " ".join(lp_parts) + "\n"

    log.info("Activiteiten gematcht aan WODs: %d van %d", matched_acts, len(past_workouts))

    upcoming_text = ""
    upcoming_timing_context = ""
    if upcoming_workout:
        date = upcoming_workout.get("date", "?")
        title = upcoming_workout.get("title", "WOD")
        desc = _strip_html(upcoming_workout.get("description", ""))[:400]
        upcoming_text = f"**{date} — {title}**\n{desc}"
        upcoming_timing_context = _training_time_context(date, signed_up_times)
    else:
        upcoming_text = "No upcoming workout known."

    barbell_text = (
        "\n".join(
            f"- {lift}: " + ", ".join(f"{rm}: {val}kg" for rm, val in sorted(maxes.items()))
            for lift, maxes in sorted(barbell_lifts.items())
        )
        if barbell_lifts
        else "Niet beschikbaar"
    )

    skill_focus_text = "\n".join(f"- {s}" for s in athlete_profile.get("skill_focus", []))

    today_str = today.isoformat() if today else "unknown"

    # Build meal context: recent dinners + upcoming dinner on next workout day
    meals_text = ""
    if meals:
        today_iso = today.isoformat() if today else ""
        upcoming_date = upcoming_workout.get("date", "") if upcoming_workout else ""
        recent = [m for m in meals if m["date"] < today_iso][-5:]
        upcoming_meal = next((m for m in meals if m["date"] == upcoming_date), None)
        if recent or upcoming_meal:
            meals_text = "\n\nMeal information (evening meals from Keukenbaas):\n"
            if recent:
                meals_text += "Recent meals:\n"
                for m in recent:
                    meals_text += f"- {m['date']}: {m['meal_name']}"
                    if m['category']:
                        meals_text += f" ({m['category']})"
                    meals_text += "\n"
            if upcoming_meal:
                meals_text += f"Evening meal on the day of the next workout ({upcoming_date}): {upcoming_meal['meal_name']}"
                if upcoming_meal['category']:
                    meals_text += f" ({upcoming_meal['category']})"
                meals_text += "\n"
                nutrition_parts = []
                for label, key in [("kcal", "energy_kcal"), ("protein", "proteins_g"), ("carbs", "carbohydrates_g"), ("fat", "fat_g"), ("fiber", "fiber_g")]:
                    val = upcoming_meal.get(key)
                    if val is not None:
                        nutrition_parts.append(f"{label}: {val}")
                if nutrition_parts:
                    meals_text += f"  Nutritional values: {', '.join(nutrition_parts)}\n"
                if upcoming_meal.get("ingredients"):
                    for ing in upcoming_meal["ingredients"]:
                        qty = f"{ing['quantity']} {ing['unit']}".strip() if ing.get("quantity") else ""
                        meals_text += f"  • {ing['name']}{': ' + qty if qty else ''}\n"

    # Build health input block (subjectieve hersteldata van atleet)
    health_block = ""
    if health_input:
        lines = []
        slaap = health_input.get("slaap")
        energie = health_input.get("energie")
        spierpijn = health_input.get("spierpijn")
        if slaap is not None:
            lines.append(f"- Sleep quality today: {slaap}/5")
        if energie is not None:
            lines.append(f"- Energy level today: {energie}/5")
        if spierpijn is not None:
            lines.append(f"- Muscle soreness/fatigue today: {spierpijn}/5")
        stress = health_input.get("stress")
        if stress is not None:
            lines.append(f"- Stress today: {stress}/5 (1=no stress, 5=high stress/busy day)")
        # Append recent history trend (last 14 days)
        if health_history:
            today_iso = today.isoformat() if today else ""
            recent = [h for h in health_history if h.get("date", "") < today_iso]
            recent = sorted(recent, key=lambda h: h.get("date", ""), reverse=True)[:14]
            if recent:
                lines.append("\nTrend last 14 days (date: sleep/energy/muscle soreness/stress):")
                for h in reversed(recent):
                    d = h.get("date", "?")
                    s = h.get("slaap", "?")
                    e = h.get("energie", "?")
                    p = h.get("spierpijn", "?")
                    st = h.get("stress")
                    stress_str = f" stress={st}" if st is not None else ""
                    lines.append(f"  {d}: sleep={s} energy={e} soreness={p}{stress_str}")
        if lines:
            health_block = (
                "\nSubjective recovery data (filled in by athlete — use this as primary "
                "physiological recovery indicator):\n"
                + "\n".join(lines)
                + "\n"
            )

    # Garmin/intervals.icu objectieve hersteldata
    garmin_block = ""
    if intervals_data and intervals_data.get("wellness", {}).get("by_date"):
        today_iso = today.isoformat() if today else ""
        yesterday_iso = (today - timedelta(days=1)).isoformat() if today else ""
        w_by_date = intervals_data["wellness"]["by_date"]
        garmin_entry = w_by_date.get(today_iso) or w_by_date.get(yesterday_iso)

        # HRV baseline: 28-daags gemiddelde ± standaarddeviatie
        _hrv_hist = [w_by_date[d]["hrv"] for d in sorted(w_by_date) if d < today_iso and w_by_date[d].get("hrv") is not None][-28:]
        _hrv_baseline = sum(_hrv_hist) / len(_hrv_hist) if len(_hrv_hist) >= 5 else None
        _hrv_baseline_low = _hrv_baseline_high = None
        if _hrv_baseline and len(_hrv_hist) >= 5:
            _hrv_std = (sum((x - _hrv_baseline) ** 2 for x in _hrv_hist) / len(_hrv_hist)) ** 0.5
            _hrv_baseline_low  = round(_hrv_baseline - _hrv_std)
            _hrv_baseline_high = round(_hrv_baseline + _hrv_std)

        if garmin_entry:
            g_lines = []
            if garmin_entry.get("resting_hr") is not None:
                g_lines.append(f"- Resting HR: {garmin_entry['resting_hr']} bpm")
            if garmin_entry.get("hrv") is not None:
                _hrv_val = garmin_entry["hrv"]
                _hrv_line = f"- HRV (RMSSD): {_hrv_val:.0f} ms"
                if _hrv_baseline:
                    _ratio = _hrv_val / _hrv_baseline
                    if _hrv_baseline_low is not None and _hrv_val >= _hrv_baseline_low:
                        _hrv_status = "Balanced"
                    elif _ratio >= 0.75:
                        _hrv_status = "Unbalanced"
                    else:
                        _hrv_status = "Low"
                    if _hrv_baseline_low is not None and _hrv_baseline_high is not None:
                        _hrv_line += f" — baseline {_hrv_baseline_low}–{_hrv_baseline_high} ms, status: {_hrv_status}"
                    else:
                        _hrv_line += f" — 28d avg: {_hrv_baseline:.0f} ms, status: {_hrv_status}"
                g_lines.append(_hrv_line)
            if garmin_entry.get("hrv_sdnn") is not None:
                g_lines.append(f"- HRV (SDNN): {garmin_entry['hrv_sdnn']:.0f} ms")
            if garmin_entry.get("avg_sleeping_hr") is not None:
                g_lines.append(f"- Avg sleeping HR: {garmin_entry['avg_sleeping_hr']:.0f} bpm")
            if garmin_entry.get("readiness") is not None:
                g_lines.append(f"- Readiness: {garmin_entry['readiness']}/100")
            if garmin_entry.get("sleep_hrs") is not None:
                g_lines.append(f"- Sleep: {garmin_entry['sleep_hrs']:.1f} hours")
            if garmin_entry.get("sleep_score") is not None:
                g_lines.append(f"- Sleep score: {garmin_entry['sleep_score']}/100")
            if garmin_entry.get("sleep_quality") is not None:
                g_lines.append(f"- Sleep quality: {garmin_entry['sleep_quality']}/5")
            if garmin_entry.get("respiration") is not None:
                g_lines.append(f"- Respiration rate: {garmin_entry['respiration']:.1f} /min")
            ctl = garmin_entry.get("ctl")
            atl = garmin_entry.get("atl")
            tsb = garmin_entry.get("tsb")
            if ctl is not None and atl is not None:
                if tsb is not None:
                    if tsb > 5:
                        tsb_label = "fresh / race-ready"
                    elif tsb > 0:
                        tsb_label = "transitioning (slightly fresh)"
                    elif tsb > -10:
                        tsb_label = "neutral (gray zone)"
                    elif tsb > -30:
                        tsb_label = "optimal training load"
                    else:
                        tsb_label = "high risk / overloaded"
                    g_lines.append(f"- Training Form (TSB): {tsb:+.0f} ({tsb_label}) — fitness {ctl:.0f}, fatigue {atl:.0f}")
                else:
                    g_lines.append(f"- Fitness (CTL): {ctl:.0f}, fatigue (ATL): {atl:.0f}")
            if garmin_entry.get("steps") is not None:
                g_lines.append(f"- Steps: {garmin_entry['steps']:,}")
            if garmin_entry.get("vo2max") is not None:
                g_lines.append(f"- VO2max: {garmin_entry['vo2max']:.1f}")
            if garmin_entry.get("spo2") is not None:
                g_lines.append(f"- SpO₂: {garmin_entry['spo2']:.1f}%")
            # Subjective metrics (scale 1-4 in intervals.icu)
            # Soreness/fatigue/stress: 1=low/good, 4=extreme/bad
            # Mood/motivation: 1=great/very high (BEST), 4=grumpy/low (WORST)
            subj = []
            if garmin_entry.get("soreness") is not None:
                subj.append(f"soreness {garmin_entry['soreness']}/4 (1=none, 4=extreme)")
            if garmin_entry.get("fatigue") is not None:
                subj.append(f"fatigue {garmin_entry['fatigue']}/4 (1=none, 4=extreme)")
            if garmin_entry.get("stress") is not None:
                subj.append(f"stress {garmin_entry['stress']}/4 (1=low, 4=extreme)")
            if garmin_entry.get("mood") is not None:
                subj.append(f"mood {garmin_entry['mood']}/4 (1=great=best, 4=grumpy=worst)")
            if garmin_entry.get("motivation") is not None:
                subj.append(f"motivation {garmin_entry['motivation']}/4 (1=very high=best, 4=low=worst)")
            if subj:
                g_lines.append(f"- Subjective: {', '.join(subj)}")
            if g_lines:
                garmin_block = "\nGarmin recovery data (via intervals.icu):\n" + "\n".join(g_lines) + "\n"

    # Withings lichaamssamenstelling
    withings_block = ""
    if withings_data and withings_data.get("measurements"):
        m = withings_data["measurements"][0]
        w_lines = []
        if m.get("weight_kg") is not None:
            w_lines.append(f"- Weight: {m['weight_kg']} kg")
        if m.get("fat_pct") is not None:
            w_lines.append(f"- Body fat: {m['fat_pct']}%")
        if m.get("muscle_kg") is not None:
            w_lines.append(f"- Muscle mass: {m['muscle_kg']} kg")
        if m.get("hydration_kg") is not None:
            w_lines.append(f"- Hydration: {m['hydration_kg']} kg")
        if m.get("visceral_fat") is not None:
            w_lines.append(f"- Visceral fat: {m['visceral_fat']}")
        if m.get("nerve_health") is not None:
            w_lines.append(f"- Nerve health: {m['nerve_health']}/100")
        if m.get("pwv_ms") is not None:
            w_lines.append(f"- Pulse Wave Velocity: {m['pwv_ms']} m/s")
        if w_lines:
            withings_block = f"\nBody composition (Withings, {m['date']}):\n" + "\n".join(w_lines) + "\n"

    # Omgevingsdata: weer + AQI bij volgende training
    env_block = ""
    if environmental_data:
        aqi = environmental_data.get("aqi") or {}
        conds = environmental_data.get("training_conditions") or {}
        upcoming_date = (upcoming_workout or {}).get("date", "")
        cond = conds.get(upcoming_date)
        env_lines = []
        if cond:
            env_lines.append(
                f"- {cond.get('temp_c')}°C (feels like {cond.get('feels_like_c')}°C), "
                f"humidity {cond.get('humidity_pct')}%, wind {cond.get('wind_kmh')} km/h — "
                f"{cond.get('weather_desc', '')}"
            )
        if aqi.get("value") is not None:
            env_lines.append(f"- Air quality: AQI {aqi['value']} ({aqi.get('category', '')})")
        if env_lines:
            env_block = (
                f"\nConditions next training ({upcoming_date} {(cond or {}).get('training_time', '')}):\n"
                + "\n".join(env_lines) + "\n"
            )

    hr_zones_raw = (strava_data or {}).get("hr_zones", [])
    _zone_names = ["Z1 Recovery", "Z2 Aerobic", "Z3 Tempo", "Z4 Threshold", "Z5 Anaerobic"]
    if hr_zones_raw:
        _zone_lines = []
        for _i, _z in enumerate(hr_zones_raw[:5]):
            _label = _zone_names[_i] if _i < len(_zone_names) else f"Z{_i + 1}"
            _max = _z.get("max", -1)
            _zone_lines.append(f"  {_label}: {_z['min']}–{'∞' if _max == -1 else _max} bpm")
        hr_zones_text = "\nAthlete heart rate zones:\n" + "\n".join(_zone_lines) + "\n"
    else:
        hr_zones_text = ""

    # ACWR trainingsbelasting
    acwr = _compute_acwr(strava_data)
    if acwr:
        acwr_text = (
            f"\nTraining load (ACWR 7:14 days): ratio={acwr['ratio']} — {acwr['status']}"
            f" (acute avg RE/day: {acwr['acute_7d']}, chronic: {acwr['chronic_14d']})\n"
        )
    else:
        acwr_text = ""

    # Krachtontwikkeling vs. 4 weken geleden
    barbell_trend_text = ""
    if barbell_history and barbell_lifts:
        trends = _compute_barbell_trends(barbell_history, barbell_lifts)
        if trends:
            pos = {l: d for l, d in trends.items() if d > 0}
            neg = {l: d for l, d in trends.items() if d < 0}
            parts = []
            if pos:
                parts.append("Increased: " + ", ".join(f"{l} +{d}kg" for l, d in sorted(pos.items())))
            if neg:
                parts.append("Decreased: " + ", ".join(f"{l} {d}kg" for l, d in sorted(neg.items())))
            barbell_trend_text = "\nStrength development vs. ~4 weeks ago:\n" + "\n".join(f"  {p}" for p in parts) + "\n"

    # Vorig advies (continuïteit)
    prev_advice_text = ""
    if previous_advice:
        recent_advice = sorted(previous_advice, key=lambda h: h.get("date", ""), reverse=True)[:2]
        if recent_advice:
            prev_advice_text = "\nPrevious coach advice (for reference — check if patterns repeat):\n"
            for entry in reversed(recent_advice):
                prev_advice_text += f"[{entry['date']}] {entry['advice']}\n"
            prev_advice_text += "\n"

    # Relevante PRs en benchmarks
    pr_text = ""
    if personal_records or benchmark_workouts:
        pr_lines = []
        if benchmark_workouts:
            for bm in (benchmark_workouts or [])[:8]:
                name = bm.get("name", "")
                result = bm.get("result", "")
                scaling = bm.get("scaling", "")
                bdate = bm.get("date", "")
                if name and result:
                    pr_lines.append(f"  {name}: {result}" + (f" ({scaling})" if scaling else "") + (f" — {bdate}" if bdate else ""))
        if personal_records:
            for pr in (personal_records or [])[:5]:
                wod = pr.get("workout", "")
                result = pr.get("result", "")
                pdate = pr.get("date", "")
                if wod and result:
                    pr_lines.append(f"  {wod}: {result}" + (f" — {pdate}" if pdate else ""))
        if pr_lines:
            pr_text = "\nPersonal records & benchmarks (context for intensity advice):\n" + "\n".join(pr_lines) + "\n"

    # Persoonlijke geplande activiteiten (handmatig toegevoegd via dashboard)
    # Split into past (for the past-workouts context) and upcoming (for the next-workout context)
    past_personal_text = ""
    upcoming_personal_text = ""
    if personal_events:
        today_iso = today.isoformat() if today else ""
        upcoming_pe = sorted(
            [e for e in personal_events if e.get("date", "") > today_iso],
            key=lambda e: (e.get("date", ""), e.get("time", "")),
        )[:7]
        recent_pe = sorted(
            [e for e in personal_events if e.get("date", "") <= today_iso],
            key=lambda e: e.get("date", ""),
            reverse=True,
        )[:5]
        if recent_pe:
            lines = ["Recent personal activities (extra training load outside the box):"]
            for e in reversed(recent_pe):
                line = f"  {_nl_date(e['date'])}: {e['title']}"
                if e.get("time"):
                    line += f" at {e['time']}"
                if e.get("location"):
                    line += f" ({e['location']})"
                if e.get("notes"):
                    line += f" — {e['notes'][:80]}"
                lines.append(line)
            past_personal_text = "\n" + "\n".join(lines) + "\n"
        if upcoming_pe:
            lines = [f"Upcoming personal activities (planned, date AFTER today {today_iso}):"]
            for e in upcoming_pe:
                line = f"  {_nl_date(e['date'])}: {e['title']}"
                if e.get("time"):
                    line += f" at {e['time']}"
                if e.get("location"):
                    line += f" ({e['location']})"
                if e.get("notes"):
                    line += f" — {e['notes'][:80]}"
                lines.append(line)
            upcoming_personal_text = "\n" + "\n".join(lines) + "\n"

    running_plan_text = ""
    if running_plan and running_plan.get("workouts"):
        today_iso = today.isoformat() if today else ""
        workouts_list = running_plan["workouts"]
        week_nr = running_plan.get("week_number", "?")
        upcoming_runs = sorted(
            [w for w in workouts_list if w.get("date", "") > today_iso],
            key=lambda w: w.get("date", ""),
        )[:3]
        recent_runs = sorted(
            [w for w in workouts_list if w.get("date", "") <= today_iso],
            key=lambda w: w.get("date", ""),
            reverse=True,
        )[:2]
        lines = [f"Running plan (5K program week {week_nr}):"]
        if recent_runs:
            lines.append("  Past planned running sessions:")
            for w in reversed(recent_runs):
                lines.append(f"    {_nl_date(w['date'])}: {w.get('name', w.get('type', 'Run'))} "
                             f"({w.get('total_distance_km', '?')}km, {w.get('session', '')})")
        if upcoming_runs:
            lines.append("  Upcoming planned running sessions:")
            for w in upcoming_runs:
                t = w.get("time", "")
                lines.append(f"    {_nl_date(w['date'])}{' at ' + t if t else ''}: "
                             f"{w.get('name', w.get('type', 'Run'))} "
                             f"({w.get('total_distance_km', '?')}km, {w.get('session', '')})")
        running_plan_text = "\n" + "\n".join(lines) + "\n"

    deload_block = ""
    if deload_detected:
        deload_block = "\n⚠️ OVERTRAINING RISK DETECTED: The athlete is showing signs of overload (TSB below -30 and/or prolonged muscle soreness). STRONGLY advise a recovery week: scale all WODs to 60-70% intensity, prioritize sleep and nutrition, limit extra activities.\n"

    tsb_zone_note = """TSB zone reference (Training Stress Balance = fitness − fatigue):
- TSB > +5: Fresh / race-ready — body is recovered, great for competition or testing
- TSB 0 to +5: Transition — slightly fresh, good for intensity
- TSB -10 to 0: Neutral / gray zone — normal training state
- TSB -30 to -10: OPTIMAL training load — productive adaptation zone; negative TSB here is normal and desired, NOT a sign of overtraining
- TSB < -30: High risk — genuine overload, real fatigue requiring recovery
A negative TSB within the optimal range (-10 to -30) means the athlete is accumulating productive training stress. Do NOT treat this as a reason to hold back unless combined with HRV suppression, sleep disruption, or subjective fatigue markers."""

    prompt = f"""You are an experienced CrossFit coach. Give short, personal recovery advice for today.

{tsb_zone_note}

Today is: {today_str}

Athlete: {athlete_profile['name']}, {athlete_profile['weight_kg']} kg, age 47
Experience: {athlete_profile['experience']}
Focus areas:
{skill_focus_text}
{health_block}{garmin_block}{withings_block}{acwr_text}
Barbell maxima (kg):
{barbell_text}{barbell_trend_text}

Weight notation: If weights are noted as "X/Y lbs" or "X/Y kg", always use the first number (X) — that is the men's weight.

Past CrossFit box sessions the athlete ACTUALLY attended (most recent first).
These are all real CrossFit WODs — even if the WOD description is missing or empty.
Where available, Strava data (↳) has been added: heart rate, duration, calories, Relative Effort (RE) and RPE.
Use this to assess the actual intensity, NOT just the WOD description:
{hr_zones_text}
{past_text if past_text.strip() else "No recent workouts known."}
{past_personal_text}
Next workout:
{upcoming_text}{upcoming_timing_context}{upcoming_personal_text}{running_plan_text}{meals_text}{env_block}
{pr_text}{prev_advice_text}{deload_block}
Provide advice on:
1. **Recovery level** — are there muscle groups that need extra rest based on recent workouts?{"  Use the subjective recovery data (sleep, energy, muscle soreness) as the primary physiological recovery indicator. Use the Strava workout data (heart rate, duration) to assess the actual training load per session." if health_input else ""}{"  The ACWR ratio indicates training load: check if there is a pattern with the previous advice." if acwr else ""}
2. **Intensity advice** — go full throttle, train controlled, or deliberately scale today?
3. **One concrete tip** for the next workout taking recovery into account (e.g. pacing, scaling choice, specific movement)
4. **Nutrition** — include this section only if meal information is available: consider the training time (see above) — is the meal a good recovery meal (evening training) or pre-workout preparation (morning training)? One sentence, only if relevant.

When referring to dates, always use the exact date (e.g. "Thursday 19 March"), NEVER vague terms like "yesterday" or "the day before yesterday".
Be direct, practical and concise. Maximum 200 words. Write in English. No introduction."""

    try:
        log.info("Generating recovery advice")
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        advice = message.content[0].text.strip()
        log.info("Recovery advice generated (%d chars)", len(advice))
        return advice
    except Exception as exc:
        log.warning("Failed to generate recovery advice: %s", exc)
        return ""


def generate_workout_plans(
    upcoming_workouts: list[dict],
    barbell_lifts: dict,
    athlete_profile: dict,
    meals: list[dict] | None = None,
    signed_up_times: dict[str, str] | None = None,
    health_input: dict | None = None,
    health_history: list[dict] | None = None,
    strava_data: dict | None = None,
    past_workouts: list[dict] | None = None,
    workout_log: dict | None = None,
    barbell_history: list[dict] | None = None,
    personal_records: list[dict] | None = None,
    intervals_data: dict | None = None,
    environmental_data: dict | None = None,
    personal_events: list[dict] | None = None,
) -> dict[str, str]:
    """
    Call the Claude API to generate a personalised execution plan for each
    upcoming workout.  Requires ANTHROPIC_API_KEY to be set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping workout plan generation")
        return {}

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping workout plan generation")
        return {}

    client = anthropic.Anthropic(api_key=api_key)

    barbell_text = (
        "\n".join(
            f"- {lift}: " + ", ".join(f"{rm}: {val}kg" for rm, val in sorted(maxes.items()))
            for lift, maxes in sorted(barbell_lifts.items())
        )
        if barbell_lifts
        else "Niet beschikbaar"
    )

    # Krachtontwikkeling t.o.v. ~4 weken geleden
    barbell_trend_text = ""
    if barbell_history and barbell_lifts:
        trends = _compute_barbell_trends(barbell_history, barbell_lifts)
        if trends:
            pos = {l: d for l, d in trends.items() if d > 0}
            neg = {l: d for l, d in trends.items() if d < 0}
            parts = []
            if pos:
                parts.append("Increased: " + ", ".join(f"{l} +{d}kg" for l, d in sorted(pos.items())))
            if neg:
                parts.append("Decreased: " + ", ".join(f"{l} {d}kg" for l, d in sorted(neg.items())))
            barbell_trend_text = "\nStrength development vs. ~4 weeks ago:\n" + "\n".join(f"  {p}" for p in parts) + "\n"

    # Herstelstatus van de atleet (health scores + ACWR + Oura)
    recovery_status_text = ""
    if health_input:
        slaap = health_input.get("slaap")
        energie = health_input.get("energie")
        spierpijn = health_input.get("spierpijn")
        stress = health_input.get("stress")
        parts = []
        if slaap is not None:
            parts.append(f"sleep {slaap}/5")
        if energie is not None:
            parts.append(f"energy {energie}/5")
        if spierpijn is not None:
            parts.append(f"soreness {spierpijn}/5")
        if stress is not None:
            parts.append(f"stress {stress}/5")
        if parts:
            recovery_status_text = "\nCurrent athlete recovery status: " + ", ".join(parts) + "\n"
    if intervals_data and intervals_data.get("wellness", {}).get("by_date"):
        from datetime import date as _date_cls_wod  # noqa: PLC0415
        _today_iso = _date_cls_wod.today().isoformat()
        _yesterday_iso = (_date_cls_wod.today() - timedelta(days=1)).isoformat()
        _w = intervals_data["wellness"]["by_date"]
        _ge = _w.get(_today_iso) or _w.get(_yesterday_iso)
        if _ge:
            _gp = []
            if _ge.get("resting_hr") is not None:
                _gp.append(f"resting_hr {_ge['resting_hr']}bpm")
            if _ge.get("hrv") is not None:
                _gp.append(f"HRV {_ge['hrv']:.0f}ms")
            if _ge.get("tsb") is not None:
                _gp.append(f"TSB {_ge['tsb']:+.0f}")
            if _ge.get("sleep_hrs") is not None:
                _gp.append(f"sleep {_ge['sleep_hrs']:.1f}h")
            if _ge.get("sleep_score") is not None:
                _gp.append(f"sleep_score {_ge['sleep_score']}/100")
            if _ge.get("steps") is not None:
                _gp.append(f"steps {_ge['steps']:,}")
            if _ge.get("vo2max") is not None:
                _gp.append(f"VO2max {_ge['vo2max']:.1f}")
            if _ge.get("spo2") is not None:
                _gp.append(f"SpO₂ {_ge['spo2']:.1f}%")
            for _field, _label, _scale in [
                ("soreness", "soreness", "/4(1=none,4=extreme)"),
                ("fatigue", "fatigue", "/4(1=none,4=extreme)"),
                ("stress", "stress", "/4(1=low,4=extreme)"),
                ("mood", "mood", "/4(1=great=best,4=grumpy=worst)"),
                ("motivation", "motivation", "/4(1=high=best,4=low=worst)"),
            ]:
                if _ge.get(_field) is not None:
                    _gp.append(f"{_label} {_ge[_field]}{_scale}")
            if _gp:
                recovery_status_text += "Garmin: " + ", ".join(_gp) + "\n"
    acwr = _compute_acwr(strava_data)
    if acwr:
        recovery_status_text += (
            f"Training load (ACWR 7:14d): ratio={acwr['ratio']} — {acwr['status']}"
            f" (acute: {acwr['acute_7d']} RE/day, chronic: {acwr['chronic_14d']} RE/day)\n"
        )

    # Recente workout-lognotities (wat de atleet daadwerkelijk deed + gewichten)
    recent_log_text = ""
    if workout_log:
        log_entries = sorted(
            [(d, e) for d, e in workout_log.items()],
            key=lambda x: x[0],
            reverse=True,
        )[:5]
        if log_entries:
            log_lines = []
            for d, entry in reversed(log_entries):
                notes = entry.get("notes", "")
                wods_done = entry.get("workouts_done") or []
                if notes or wods_done:
                    wod_str = ", ".join(wods_done) if wods_done else ""
                    log_lines.append(f"  {d}: {wod_str}" + (f" — {notes}" if notes else ""))
            if log_lines:
                recent_log_text = "\nRecent workout log (actually done + weights/notes):\n" + "\n".join(log_lines) + "\n"

    # Relevante PRs
    pr_text = ""
    if personal_records:
        pr_lines = [
            f"  {pr.get('workout', '')}: {pr.get('result', '')}" + (f" — {pr.get('date', '')}" if pr.get("date") else "")
            for pr in (personal_records or [])[:8]
            if pr.get("workout") and pr.get("result")
        ]
        if pr_lines:
            pr_text = "\nPersonal records (context for weights/pacing):\n" + "\n".join(pr_lines) + "\n"

    # Group workouts by date so we can pick the main one per date
    by_date: dict[str, list[dict]] = {}
    for w in upcoming_workouts:
        d = w.get("date", "")
        if d:
            by_date.setdefault(d, []).append(w)

    def _pick_main(ws: list[dict]) -> dict:
        """Return the main workout from a list of workouts for a single date."""
        for kw in _MAIN_KEYWORDS:
            for w in ws:
                if kw in w.get("title", "").lower():
                    return w
        # Fallback: pick the one with the longest description
        return max(ws, key=lambda w: len(w.get("description", "")))

    plans: dict[str, str] = {}
    for date, day_workouts in sorted(by_date.items()):
        main = _pick_main(day_workouts)
        title = main.get("title", "WOD")
        description = _strip_html(main.get("description", ""))
        if not description:
            continue

        # Athlete/coach notes: timecap, RX weights in kg, scaling options
        notes_raw = main.get("athlete_notes", "").strip()
        notes_context = f"\nCoach-/athlete notes (official weights in kg, timecap, scaling):\n{notes_raw}\n" if notes_raw else ""

        # Detect team/partner format from description or title
        team_size = _detect_team_size(description + " " + title)

        # Collect accessory titles so the coach has context but stays focused on the main WOD
        accessory_titles = [
            w["title"] for w in day_workouts
            if w is not main and w.get("title")
        ]
        accessory_context = (
            f"\nAccessory work on this day (for context, not the primary focus): {', '.join(accessory_titles)}"
            if accessory_titles else ""
        )

        # Meal context for this workout day
        meal_context = ""
        if meals:
            day_meal = next((m for m in meals if m["date"] == date), None)
            if day_meal:
                meal_context = (
                    f"\nEvening meal on this day (Keukenbaas): {day_meal['meal_name']}"
                    + (f" ({day_meal['category']})" if day_meal.get("category") else "")
                )

        skill_focus_text = "\n".join(
            f"- {s}" for s in athlete_profile.get("skill_focus", [])
        )
        if team_size:
            team_context = (
                f"\nNOTE: This is a team workout with {team_size} people. "
                f"The athlete therefore does only 1/{team_size} of the total volume (reps/rounds divided by {team_size}). "
                f"Base pacing and weight advice on this individual share."
            )
        else:
            team_context = ""

        timing_context = _training_time_context(date, signed_up_times)

        # Environmental conditions for this specific training day
        env_context = ""
        if environmental_data:
            aqi = environmental_data.get("aqi") or {}
            cond = (environmental_data.get("training_conditions") or {}).get(date)
            env_parts = []
            if cond:
                env_parts.append(
                    f"{cond.get('temp_c')}°C (feels like {cond.get('feels_like_c')}°C), "
                    f"humidity {cond.get('humidity_pct')}%, wind {cond.get('wind_kmh')} km/h — "
                    f"{cond.get('weather_desc', '')}"
                )
            if aqi.get("value") is not None:
                env_parts.append(f"AQI {aqi['value']} ({aqi.get('category', '')})")
            if env_parts:
                env_context = "\nConditions on training day: " + " | ".join(env_parts) + "\n"

        # Persoonlijke geplande activiteiten rondom deze trainingsdatum
        personal_event_context = ""
        if personal_events:
            nearby = [
                e for e in personal_events
                if abs((date_cls.fromisoformat(e["date"]) - date_cls.fromisoformat(date)).days) <= 3
                and e.get("date") != date
            ]
            if nearby:
                nearby.sort(key=lambda e: e["date"])
                lines = ["Other planned activities near this training (±3 days, consider recovery):"]
                for e in nearby:
                    diff = (date_cls.fromisoformat(e["date"]) - date_cls.fromisoformat(date)).days
                    when = f"{abs(diff)} day{'s' if abs(diff) != 1 else ''} {'after' if diff > 0 else 'before'} this training"
                    line = f"  {e['date']} ({when}): {e['title']}"
                    if e.get("time"):
                        line += f" at {e['time']}"
                    if e.get("notes"):
                        line += f" — {e['notes'][:60]}"
                    lines.append(line)
                personal_event_context = "\n" + "\n".join(lines) + "\n"

        prompt = f"""You are an experienced CrossFit coach. Generate a concise, practical execution plan.

Athlete: {athlete_profile['name']}
Body weight: {athlete_profile['weight_kg']} kg
Experience: {athlete_profile['experience']}
Goal: {athlete_profile.get('doel', '')}
RX/Scaled preference: {athlete_profile['rx_preference']}
Injuries: {athlete_profile['injuries']}
{recovery_status_text}
Personal focus areas (movements where improvement is desired):
{skill_focus_text}

Barbell maxima (kg):
{barbell_text}{barbell_trend_text}
{pr_text}{recent_log_text}{personal_event_context}
Weight notation: If weights are noted as "X/Y lbs" or "X/Y kg", always use the first number (X) — that is the men's weight.

Main workout ({date} — {title}):
{description}{notes_context}{accessory_context}{meal_context}
{team_context}{timing_context}{env_context}
The execution plan must ONLY cover the main workout above. Do not address accessory work.

Provide a plan with:
1. Recommended weights for barbell movements (with % of 1RM as reference)
2. Pacing strategy and sets/reps breakdown — adjust for recovery status if relevant
3. 1–2 concrete tips for this specific workout
4. **Skill tip**: If one or more focus areas appear in this workout, give one targeted improvement tip specifically aimed at reaching RX level for that movement faster (technique, drills, mindset). Skip this section if none of the focus areas are present.
5. **Nutrition**: include this section only if a dinner meal is known — consider the training time: is the meal a good recovery meal (evening training) or proper preparation (morning training)? One sentence.

Be direct and concise. Maximum 260 words. No introduction."""

        try:
            log.info("Generating AI plan for %s (%s)", date, title)
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            plan_text = message.content[0].text.strip()
            plans[date] = plan_text
            log.info("Plan generated for %s (%d chars)", date, len(plan_text))
        except Exception as exc:
            log.warning("Failed to generate plan for %s: %s", date, exc)

    return plans


def detect_deload(intervals_data: "dict | None", health_history: list[dict]) -> bool:
    """
    Detecteer overtraining risico op basis van TSB-trend en subjectieve spierpijn.

    Triggercondities (één van beide voldoende):
      - TSB < -20 voor 3+ opeenvolgende recente dagen
      - Spierpijn >= 4/5 voor 3+ recente dagen EN TSB < -10
    """
    tsb_values: list[float] = []
    if intervals_data:
        by_date = (intervals_data.get("wellness") or {}).get("by_date", {})
        recent_dates = sorted(by_date.keys())[-5:]
        for d in recent_dates:
            tsb = by_date[d].get("tsb")
            if tsb is not None:
                tsb_values.append(float(tsb))

    # Check TSB < -20 voor 3+ achtereenvolgende dagen
    if len(tsb_values) >= 3 and all(v < -20 for v in tsb_values[-3:]):
        log.info("[deload] TSB < -20 voor 3+ dagen: %s", tsb_values[-3:])
        return True

    # Check spierpijn >= 4 voor 3+ dagen én TSB < -10
    if health_history:
        recent_scores = [h.get("spierpijn") for h in sorted(health_history, key=lambda h: h.get("date", ""))[-3:]]
        high_soreness = sum(1 for s in recent_scores if s is not None and int(s) >= 4) >= 3
        avg_tsb = sum(tsb_values[-3:]) / len(tsb_values[-3:]) if len(tsb_values) >= 3 else 0
        if high_soreness and avg_tsb < -10:
            log.info("[deload] Hoge spierpijn + TSB < -10: soreness=%s tsb=%.1f", recent_scores, avg_tsb)
            return True

    return False


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
        raw = files.get("health_input.json", {}).get("content", "")
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


def load_sportbit_attended_dates(gist_id: str, token: str) -> tuple[set[str], dict[str, str]]:
    """Read sportbit_state.json from the shared gist and return:
    - A set of ISO dates where the athlete was signed up (and did NOT cancel),
      filtered to scheduled class days (Mon/Wed/Thu/Sat).
    - A dict of {date: time} for ALL non-cancelled signups (past + future),
      used to look up actual training times.

    Returns (set[str], dict[str, str]).
    """
    # Weekdays (0=Mon … 6=Sun) that are scheduled CrossFit class days
    SCHEDULED_WEEKDAYS = {0, 2, 3, 5, 6}  # Mon, Wed, Thu, Sat, Sun

    if not gist_id or not token:
        return set(), {}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        raw = files.get("sportbit_state.json", {}).get("content", "")
        if not raw:
            log.warning("[gist] sportbit_state.json not found or empty")
            return set(), {}
        state = json.loads(raw)
        signed_up: dict = state.get("signed_up", {})
        cancelled: dict = state.get("cancelled", {})
        attended: set[str] = set()
        signed_up_times: dict[str, str] = {}
        skipped = 0
        for event_id, info in signed_up.items():
            if event_id not in cancelled:
                date = info.get("date", "")
                time = info.get("time", "")
                if date:
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
                        log.info("[gist] Skipping %s (weekday %d, not a scheduled class day)", date, weekday)
        log.info("[gist] Sportbit attended dates: %d (skipped %d non-class-day signups)", len(attended), skipped)
        log.info("[gist] Signed-up times: %d dates with known training time", len(signed_up_times))
        return attended, signed_up_times
    except Exception as exc:
        log.warning("[gist] Failed to load sportbit_state.json: %s", exc)
        return set(), {}


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
        raw = resp.json().get("files", {}).get("workout_log.json", {}).get("content", "")
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
      - _keukenbaas: cached meals from keukenbaas_meals.json
    """
    empty = {"barbell_lifts_history": [], "recovery_advice_history": [], "_full": {}, "_keukenbaas": [], "_mfp": None, "_personal_events": [], "_running_plan": {}}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        raw = files.get(GIST_FILENAME, {}).get("content", "")
        if not raw:
            return empty
        existing = json.loads(raw)
        meals_raw = files.get("keukenbaas_meals.json", {}).get("content", "")
        cached_meals = json.loads(meals_raw).get("meals", []) if meals_raw else []
        mfp_raw = files.get("myfitnesspal_nutrition.json", {}).get("content", "")
        cached_mfp = json.loads(mfp_raw) if mfp_raw else None
        personal_events_raw = files.get("personal_events.json", {}).get("content", "")
        personal_events = json.loads(personal_events_raw).get("events", []) if personal_events_raw else []
        running_plan_raw = files.get("running_plan.json", {}).get("content", "")
        running_plan = json.loads(running_plan_raw) if running_plan_raw else {}
        return {
            "barbell_lifts_history": existing.get("barbell_lifts_history", []),
            "recovery_advice_history": existing.get("recovery_advice_history", []),
            "_full": existing,
            "_keukenbaas": cached_meals,
            "_mfp": cached_mfp,
            "_personal_events": personal_events,
            "_running_plan": running_plan,
        }
    except Exception as exc:
        log.warning("[gist] Could not load previous coach context: %s", exc)
        return empty


def save_to_gist(gist_id: str, token: str, wod_data: dict, meals: list[dict] | None = None, mfp_data: dict | None = None) -> None:
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

    files: dict = {
        GIST_FILENAME: {
            "content": json.dumps(wod_data, ensure_ascii=False, indent=2)
        }
    }
    if meals is not None:
        files["keukenbaas_meals.json"] = {
            "content": json.dumps(
                {"meals": meals, "fetched_at": datetime.now(timezone.utc).isoformat()},
                ensure_ascii=False,
                indent=2,
            )
        }
    if mfp_data is not None:
        files["myfitnesspal_nutrition.json"] = {
            "content": json.dumps(mfp_data, ensure_ascii=False, indent=2)
        }
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
    cached_keukenbaas: list = []
    cached_mfp_data: dict | None = None
    personal_events: list[dict] = []
    running_plan: dict = {}
    if gist_id and token:
        full_ctx = _load_previous_coach_context(gist_id, token)
        cached_gist = full_ctx.pop("_full", {})
        cached_keukenbaas = full_ctx.pop("_keukenbaas", [])
        cached_mfp_data = full_ctx.pop("_mfp", None)
        personal_events = full_ctx.pop("_personal_events", [])
        running_plan = full_ctx.pop("_running_plan", {})
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

        # Fetch Keukenbaas meal data (past 14 days + next 7 days)
        keukenbaas_meals = fetch_keukenbaas_meals()

    else:
        # ── HEALTH_ONLY MODE: Use cached SugarWOD data from Gist ────────────
        log.info("HEALTH_ONLY modus: gecachte SugarWOD data geladen uit Gist")
        workouts = cached_gist.get("workouts", [])
        barbell_lifts = cached_gist.get("barbell_lifts") or BARBELL_LIFTS_FALLBACK
        barbell_source = "cache"
        personal_records = cached_gist.get("personal_records", [])
        benchmark_workouts = cached_gist.get("benchmark_workouts", [])
        athlete_logbook = []
        keukenbaas_meals = cached_keukenbaas
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

        # MyFitnessPal (via python-myfitnesspal library, geen Playwright nodig)
        skip_mfp = os.environ.get("SKIP_MYFITNESSPAL", "false").lower() in ("true", "1", "yes")
        mfp_data: dict | None = None
        if skip_mfp:
            log.info("MyFitnessPal fetch overgeslagen (SKIP_MYFITNESSPAL=true)")
            mfp_data = cached_mfp_data
        else:
            try:
                from fetch_myfitnesspal import fetch_myfitnesspal_data  # noqa: PLC0415
                mfp_data = fetch_myfitnesspal_data(days=7)
                if mfp_data:
                    n_days = len((mfp_data.get("diary") or {}).get("by_date") or {})
                    log.info("MyFitnessPal data opgehaald: %d dagen", n_days)
                else:
                    log.info("Geen MyFitnessPal data beschikbaar (secrets ontbreken of geen data)")
                    mfp_data = cached_mfp_data
            except Exception as exc:
                log.warning("MyFitnessPal fetch mislukt: %s", exc)
                mfp_data = cached_mfp_data

    else:
        # ── SUGARWOD MODE: Use cached health data from Gist ─────────────────
        strava_data = cached_gist.get("strava_data")
        intervals_data = cached_gist.get("intervals_data")
        withings_data = cached_gist.get("withings_data")
        mfp_data = cached_mfp_data
        log.info("SugarWOD modus: gecachte health data (Strava/Intervals/Withings/MFP) geladen uit Gist")

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
    sportbit_attended, signed_up_times = load_sportbit_attended_dates(gist_id, token)

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
    if skip_ai:
        log.info("AI coaching overgeslagen (SKIP_AI=true)")
        workout_plans = {}
    else:
        workout_plans = generate_workout_plans(
            upcoming_workouts, barbell_lifts, ATHLETE_PROFILE,
            meals=keukenbaas_meals,
            signed_up_times=signed_up_times,
            health_input=health_input,
            health_history=health_history,
            strava_data=strava_data,
            workout_log=workout_log,
            barbell_history=prev_coach_ctx["barbell_lifts_history"],
            personal_records=personal_records,
            intervals_data=intervals_data,
            environmental_data=env_data,
            personal_events=personal_events,
        )
    past_sportbit_dates = sorted(
        [d for d in sportbit_attended if d < today.isoformat()],
        reverse=True,
    )
    # Use next Sportbit signup as next_workout so the coach addresses the actual
    # next planned class, not just the first programmed SugarWOD on or after today
    # (which may be a day without a class, e.g. Sunday).
    future_sportbit_dates = sorted(d for d in sportbit_attended if d >= today.isoformat())
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
        recovery_advice = None
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
        log.info("Coach advice: %d Sportbit attended dates → %d workouts with descriptions",
                 len(past_sportbit_dates), len([w for w in attended_workouts if w.get("description")]))
        recovery_advice = generate_recovery_advice(
            attended_workouts[:10], next_workout, barbell_lifts, ATHLETE_PROFILE, today,
            meals=keukenbaas_meals,
            strava_data=strava_data,
            health_input=health_input,
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
            meals=keukenbaas_meals,
            strava_data=strava_data,
            health_input=health_input,
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
            meals=keukenbaas_meals,
            strava_data=strava_data,
            health_input=health_input,
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
        )

    ai_generated_at = datetime.now(AMS).isoformat() if not skip_ai else None
    wod_data = {
        "workouts": workouts,
        "by_date": by_date,
        "barbell_lifts": barbell_lifts,
        "barbell_source": barbell_source,
        "deload_alert": deload_detected,
        "personal_records": personal_records,
        "benchmark_workouts": benchmark_workouts,
        "workout_plans": workout_plans,
        "workout_plans_generated_at": ai_generated_at if workout_plans else None,
        "recovery_advice": recovery_advice,
        "recovery_advice_generated_at": ai_generated_at if recovery_advice else None,
        "strava_data": strava_data,
        "intervals_data": intervals_data,
        "withings_data": withings_data,
        "environmental_data": env_data,
        "myfitnesspal_data": mfp_data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        # Internal keys consumed by save_to_gist() — removed before saving
        "_barbell_lifts_history_prev": prev_coach_ctx["barbell_lifts_history"],
        "_recovery_advice_history_prev": prev_coach_ctx["recovery_advice_history"],
    }

    if gist_id and token:
        try:
            save_to_gist(gist_id, token, wod_data, meals=keukenbaas_meals, mfp_data=mfp_data)
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
