"""
fetch_runna.py — Haalt trainingsdata op uit de Runna web-app via Playwright.

Runna heeft geen publieke API. Dit script logt in op web.runna.com/sign-in,
onderschept GraphQL-responses van hydra.platform.runna.com/graphql en maakt
daarna ook directe GraphQL-queries met het JWT-token uit localStorage.

Opgeslagen in de GitHub Gist als: runna_data.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ── Constanten ───────────────────────────────────────────────────────────────

RUNNA_BASE    = "https://web.runna.com"
GRAPHQL_URL   = "https://hydra.platform.runna.com/graphql"
GIST_FILENAME = "runna_data.json"

# Pagina's om na login te bezoeken (triggert GraphQL-calls)
# Gebruik "load" + wacht — niet "networkidle" (app blijft pollen)
PAGES_TO_VISIT = [
    ("/plan",     "trainingsplan"),
    ("/schedule", "schema"),
    ("/history",  "geschiedenis"),
]

# GraphQL-queries om te proberen (schema is ongedocumenteerd — breed zoeken)
# Elke query wordt geprobeerd; fouten worden genegeerd
GRAPHQL_QUERIES = [
    ("trainingPlan", """query { trainingPlan { id name goal currentWeek totalWeeks phase status } }"""),
    ("activePlan",   """query { activePlan { id name goal currentWeek totalWeeks phase } }"""),
    ("currentPlan",  """query { currentPlan { id name goal currentWeek totalWeeks phase } }"""),
    ("plan",         """query { plan { id name goal currentWeek totalWeeks } }"""),
    ("getSchedule",  """query { schedule { id sessions { id date title type status targetDistance targetDuration completed description } } }"""),
    ("sessions",     """query { sessions { id date title type status targetDistance targetDuration completed description notes } }"""),
    ("upcomingSessions", """query { upcomingSessions { id date title type targetDistance targetDuration completed description } }"""),
    ("getWeekSessions",  """query { weekSessions { id date title type status targetDistance targetDuration completed } }"""),
    ("completedRuns",    """query { completedRuns { id date title type distance duration pace completed } }"""),
    ("runs",             """query { runs { id date title type distance duration completed } }"""),
    ("userProfile",      """query { userProfile { id email firstName lastName } }"""),
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("runna")


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _to_date_str(value: object) -> str | None:
    """Normaliseer diverse datumformaten naar 'YYYY-MM-DD'."""
    if not value:
        return None
    s = str(value)
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return m.group(0) if m else None


def _normalize_session_type(raw: str | None) -> str:
    """Zet Runna's sessie-types om naar lowercase sleutels."""
    if not raw:
        return "run"
    lower = raw.lower()
    for key in ("easy", "tempo", "long", "interval", "recovery", "race", "threshold",
                "hill", "fartlek", "cross", "rest", "strength"):
        if key in lower:
            return key
    return lower.replace(" ", "_")


def _deep_find_arrays(data: object, max_depth: int = 4) -> list[list]:
    """Zoek recursief alle lijsten in een JSON-object."""
    found = []
    if isinstance(data, list) and data:
        found.append(data)
    if isinstance(data, dict) and max_depth > 0:
        for v in data.values():
            found.extend(_deep_find_arrays(v, max_depth - 1))
    return found


# ── Data-extractie ────────────────────────────────────────────────────────────

def _extract_plan_from_captures(captured: list[dict]) -> dict | None:
    """Scan XHR/GraphQL-captures op trainingsplan-metadata."""
    plan_keys = {"plan_name", "planName", "name", "goal", "currentWeek", "current_week",
                 "totalWeeks", "total_weeks", "phase", "weeks", "target", "title",
                 "numWeeks", "durationWeeks", "weekNumber"}
    for item in captured:
        url = item["url"]
        data = item["data"]
        if not isinstance(data, dict):
            continue

        # GraphQL response: unwrap data.<queryName>
        inner = data.get("data") or {}
        candidates = [data, inner]
        for v in inner.values() if isinstance(inner, dict) else []:
            if isinstance(v, dict):
                candidates.append(v)
        # Ook directe geneste plan-sleutels
        for k in ("plan", "trainingPlan", "activePlan", "currentPlan", "training_plan"):
            if isinstance(data.get(k), dict):
                candidates.append(data[k])
            if isinstance(inner.get(k), dict):
                candidates.append(inner[k])

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            matches = plan_keys & set(obj.keys())
            if len(matches) >= 2:
                log.info("[extract] Trainingsplan gevonden via %s: keys=%s", url, list(matches))
                plan: dict = {}
                plan["name"] = (
                    obj.get("plan_name") or obj.get("planName")
                    or obj.get("name") or obj.get("title")
                )
                plan["goal"] = obj.get("goal") or obj.get("target")
                plan["current_week"] = (
                    obj.get("current_week") or obj.get("currentWeek")
                    or obj.get("week_number") or obj.get("weekNumber")
                )
                plan["total_weeks"] = (
                    obj.get("total_weeks") or obj.get("totalWeeks")
                    or obj.get("num_weeks") or obj.get("numWeeks")
                    or obj.get("duration_weeks") or obj.get("durationWeeks")
                )
                plan["phase"] = obj.get("phase") or obj.get("phase_name") or obj.get("phaseName")
                plan = {k: v for k, v in plan.items() if v is not None}
                if plan:
                    return plan
    return None


def _extract_sessions_from_captures(
    captured: list[dict],
    window_days_future: int = 7,
    window_days_past: int = 14,
) -> tuple[list[dict], list[dict]]:
    """
    Scant alle XHR/GraphQL-captures op sessie-achtige objecten.
    Geeft (upcoming_sessions, recent_completed) terug.
    """
    today = datetime.now(timezone.utc).date()
    cutoff_past = today - timedelta(days=window_days_past)
    cutoff_future = today + timedelta(days=window_days_future)

    upcoming: list[dict] = []
    completed: list[dict] = []
    seen: set[tuple] = set()

    date_keys  = ("date", "scheduled_date", "plannedDate", "scheduledDate",
                  "planned_date", "activity_date", "activityDate", "start_date", "startDate")
    title_keys = ("title", "name", "type", "session_type", "sessionType",
                  "workout_type", "workoutType", "run_type", "runType", "description")

    for item in captured:
        data = item["data"]
        # Zoek recursief alle arrays in de response
        arrays = _deep_find_arrays(data)
        for arr in arrays:
            sample = arr[0] if arr else {}
            if not isinstance(sample, dict):
                continue
            has_date  = any(k in sample for k in date_keys)
            has_title = any(k in sample for k in title_keys)
            if not (has_date and has_title):
                continue

            log.info("[extract] Sessie-array gevonden in %s (%d items)", item["url"], len(arr))

            for obj in arr:
                if not isinstance(obj, dict):
                    continue
                raw_date = next((obj.get(k) for k in date_keys if obj.get(k)), None)
                date_str = _to_date_str(raw_date)
                if not date_str:
                    continue
                try:
                    session_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                title = next((obj.get(k) for k in title_keys if obj.get(k)), None)
                session_type_raw = (
                    obj.get("session_type") or obj.get("sessionType")
                    or obj.get("run_type") or obj.get("runType")
                    or obj.get("type") or str(title or "")
                )
                session_type = _normalize_session_type(str(session_type_raw))

                is_completed = bool(
                    obj.get("completed") or obj.get("isCompleted")
                    or obj.get("is_completed")
                    or obj.get("status") in ("completed", "done", "finished", "COMPLETED")
                    or obj.get("actualDistance") or obj.get("actual_distance_km")
                    or obj.get("actualDuration") or obj.get("actual_duration_min")
                )

                distance_km = (
                    obj.get("distance_km") or obj.get("distanceKm")
                    or obj.get("distance") or obj.get("targetDistance")
                    or obj.get("target_distance_km") or obj.get("planned_distance_km")
                )
                duration_min = (
                    obj.get("duration_min") or obj.get("durationMin")
                    or obj.get("duration") or obj.get("targetDuration")
                    or obj.get("target_duration_min") or obj.get("planned_duration_min")
                )
                description = (
                    obj.get("description") or obj.get("notes")
                    or obj.get("instructions") or obj.get("details")
                )

                session: dict = {
                    "date": date_str,
                    "title": str(title) if title else session_type,
                    "session_type": session_type,
                    "completed": is_completed,
                }
                if distance_km is not None:
                    try:
                        session["distance_km"] = round(float(distance_km), 2)
                    except (ValueError, TypeError):
                        pass
                if duration_min is not None:
                    try:
                        session["duration_min"] = int(float(duration_min))
                    except (ValueError, TypeError):
                        pass
                if description:
                    session["description"] = str(description)[:300]

                key = (date_str, session["title"].lower()[:30])
                if key in seen:
                    continue
                seen.add(key)

                if session_date >= today and session_date <= cutoff_future:
                    upcoming.append(session)
                elif session_date < today and session_date >= cutoff_past and is_completed:
                    completed.append(session)

    upcoming.sort(key=lambda s: s["date"])
    completed.sort(key=lambda s: s["date"], reverse=True)
    return upcoming, completed


# ── Directe GraphQL-queries ───────────────────────────────────────────────────

def _get_auth_headers(page) -> dict | None:
    """
    Extraheer JWT-token uit localStorage en cookies voor directe API-calls.
    Geeft een dict met Authorization-header terug, of None als niet gevonden.
    """
    # Zoek in localStorage
    try:
        ls = page.evaluate(
            "() => { const r = {}; "
            "for (let i = 0; i < localStorage.length; i++) { "
            "  const k = localStorage.key(i); r[k] = localStorage.getItem(k); "
            "} return r; }"
        )
        log.info("[auth] localStorage sleutels: %s", list(ls.keys()))
        token_keys = [k for k in ls if any(
            t in k.lower() for t in ("token", "auth", "jwt", "cognito", "id_token",
                                     "access_token", "bearer", "session")
        )]
        for k in token_keys:
            val = ls.get(k, "")
            # JWT begint met "ey" (base64-encoded JSON)
            if isinstance(val, str) and val.startswith("ey") and len(val) > 50:
                log.info("[auth] JWT gevonden in localStorage[%s] (len=%d)", k, len(val))
                return {"Authorization": f"Bearer {val}"}
            # Probeer als JSON-string (bijv. Cognito: {"idToken": "ey..."})
            if isinstance(val, str) and val.startswith("{"):
                try:
                    obj = json.loads(val)
                    for sub_k, sub_v in obj.items():
                        if isinstance(sub_v, str) and sub_v.startswith("ey") and len(sub_v) > 50:
                            log.info("[auth] JWT gevonden in localStorage[%s].%s", k, sub_k)
                            return {"Authorization": f"Bearer {sub_v}"}
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        log.warning("[auth] localStorage lezen mislukt: %s", exc)

    # Zoek in cookies
    try:
        cookies = page.context.cookies()
        for c in cookies:
            if any(t in c["name"].lower() for t in ("token", "auth", "jwt", "session", "access")):
                val = c.get("value", "")
                if val.startswith("ey") and len(val) > 50:
                    log.info("[auth] JWT gevonden in cookie '%s'", c["name"])
                    return {"Authorization": f"Bearer {val}"}
    except Exception as exc:
        log.warning("[auth] Cookies lezen mislukt: %s", exc)

    log.warning("[auth] Geen JWT-token gevonden")
    return None


def _run_graphql_queries(auth_headers: dict, captured: list[dict]) -> None:
    """
    Voer directe GraphQL-queries uit en voeg de resultaten toe aan `captured`.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **auth_headers,
    }
    for query_name, query in GRAPHQL_QUERIES:
        try:
            resp = requests.post(
                GRAPHQL_URL,
                json={"query": query},
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                log.debug("[graphql] %s → HTTP %d", query_name, resp.status_code)
                continue
            data = resp.json()
            # Sla op als errors-only response
            if data.get("errors") and not data.get("data"):
                log.debug("[graphql] %s → alleen errors: %s",
                          query_name, [e.get("message") for e in data["errors"]])
                continue
            log.info("[graphql] %s → %s", query_name, str(data)[:300])
            captured.append({"url": f"{GRAPHQL_URL}#{query_name}", "data": data})
        except Exception as exc:
            log.debug("[graphql] %s mislukt: %s", query_name, exc)


# ── Gist opslaan ─────────────────────────────────────────────────────────────

def save_to_gist(gist_id: str, token: str, data: dict) -> None:
    """Sla runna_data.json op in de GitHub Gist."""
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(data, ensure_ascii=False, indent=2)
            }
        }
    }
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
    log.info("Opgeslagen in Gist als %s", GIST_FILENAME)


# ── Hoofdfunctie ──────────────────────────────────────────────────────────────

def fetch_runna_data(
    email: str,
    password: str,
    gist_id: str = "",
    token: str = "",
) -> dict:
    """
    Login op web.runna.com/sign-in, onderschep GraphQL-calls en extraheer
    trainingsdata. Geeft altijd een dict terug (minimaal met 'fetched_at').
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.error("playwright niet geïnstalleerd")
        return {"error": "playwright niet geïnstalleerd",
                "fetched_at": datetime.now(timezone.utc).isoformat()}

    log.info("Playwright headless browser starten (mobiele emulatie)")
    captured: list[dict] = []
    debug_urls: list[str] = []

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            if "runna" not in url.lower():
                return
            data = response.json()
            log.info("  [xhr] %s → %s", url, str(data)[:300])
            captured.append({"url": url, "data": data})
            debug_urls.append(url)
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
                is_mobile=True,
                has_touch=True,
                device_scale_factor=3,
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            page = context.new_page()
            page.on("response", _on_response)

            # ── 1. Navigeer direct naar de inlogpagina ────────────────────
            log.info("[browser] Navigeren naar inlogpagina: %s/sign-in", RUNNA_BASE)
            page.goto(f"{RUNNA_BASE}/sign-in", wait_until="domcontentloaded", timeout=30000)

            # Wacht op het loginformulier
            try:
                page.wait_for_selector(
                    '[data-testid="sign-in-email"], input[name="email"]',
                    state="visible", timeout=10000,
                )
                log.info("[browser] Loginformulier zichtbaar — URL: %s", page.url)
            except Exception:
                log.warning("[browser] Loginformulier niet direct zichtbaar")

            # ── 2. CookieBot-banner wegklikken ────────────────────────────
            # De banner onderschept alle pointer-events; klik via JavaScript.
            try:
                clicked = page.evaluate("""
                    () => {
                        const btn = document.getElementById(
                            'CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll'
                        );
                        if (btn) { btn.click(); return true; }
                        return false;
                    }
                """)
                if clicked:
                    log.info("[browser] CookieBot-banner geaccepteerd")
                    page.wait_for_timeout(1500)  # wacht op weganimatie
            except Exception as exc:
                log.debug("[browser] CookieBot klik mislukt (misschien al weg): %s", exc)

            # ── 3. Formulier invullen via JavaScript ──────────────────────
            # Gebruik React's native input setter + bubbelende events, zodat
            # pointer-event interceptie geen probleem is.
            email_js   = json.dumps(email)
            password_js = json.dumps(password)

            filled = page.evaluate(f"""
                () => {{
                    const setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value'
                    ).set;
                    const trigger = (el, val) => {{
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }};
                    const emailEl = document.querySelector(
                        '[data-testid="sign-in-email"], input[name="email"]'
                    );
                    const passEl  = document.querySelector(
                        '[data-testid="sign-in-password"], input[type="password"]'
                    );
                    if (!emailEl || !passEl) return false;
                    trigger(emailEl, {email_js});
                    trigger(passEl,  {password_js});
                    return true;
                }}
            """)
            if filled:
                log.info("[browser] Email + wachtwoord ingevuld via JavaScript")
            else:
                log.warning("[browser] Formuliervelden niet gevonden via JavaScript")

            # ── 4. Submit via JavaScript ──────────────────────────────────
            page.evaluate("""
                () => {
                    // Klik de eerste submit-knop die NIET van CookieBot is
                    const btns = [...document.querySelectorAll('button[type="submit"]')];
                    const loginBtn = btns.find(b => !b.id.includes('Cybot'));
                    if (loginBtn) { loginBtn.click(); return true; }
                    return false;
                }
            """)
            log.info("[browser] Login-submit geklikt via JavaScript")

            # ── 5. Wacht op succesvolle redirect ─────────────────────────
            login_failed = False
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/sign-in') && "
                    "!window.location.href.includes('/login') && "
                    "!window.location.href.includes('/auth') && "
                    "!window.location.href.includes('/welcome')",
                    timeout=20000,
                )
                log.info("[browser] Ingelogd — URL: %s", page.url)
            except Exception as exc:
                log.warning("[browser] Redirect na login mislukt: %s — %s", page.url, exc)
                if any(p in page.url for p in ("/sign-in", "/login", "/auth", "/welcome")):
                    log.error("[browser] Inloggen mislukt — pagina: %s", page.url)
                    login_failed = True
                    try:
                        html_content = page.content()
                        if gist_id and token:
                            requests.patch(
                                f"https://api.github.com/gists/{gist_id}",
                                headers={"Authorization": f"token {token}"},
                                json={"files": {"debug_runna_login.html": {
                                    "content": html_content[:80000]
                                }}},
                                timeout=15,
                            )
                            log.info("[browser] Debug-HTML opgeslagen in Gist")
                    except Exception as dbg_exc:
                        log.warning("[browser] Kon debug-HTML niet opslaan: %s", dbg_exc)

            if login_failed:
                browser.close()
                return {
                    "error": "Login mislukt",
                    "debug_urls": debug_urls,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }

            # ── 6. JWT-token extraheren ───────────────────────────────────
            auth_headers = _get_auth_headers(page)

            # ── 7. Bezoek pagina's om meer XHR/GraphQL te triggeren ───────
            all_captured: list[dict] = list(captured)

            for path, label in PAGES_TO_VISIT:
                captured.clear()
                url = f"{RUNNA_BASE}{path}"
                try:
                    log.info("[browser] Navigeren naar %s (%s)", url, label)
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(4000)  # wacht op async data-laden
                    log.info("[browser] %s: %d XHR-responses onderschept", label, len(captured))
                    all_captured.extend(captured)
                except Exception as exc:
                    log.warning("[browser] Navigatie naar %s mislukt: %s", label, exc)

            browser.close()

            # ── 8. Directe GraphQL-queries (als JWT beschikbaar) ──────────
            if auth_headers:
                log.info("[graphql] Directe queries uitvoeren met JWT-token")
                _run_graphql_queries(auth_headers, all_captured)
            else:
                log.info("[graphql] Geen JWT — alleen XHR-interceptie gebruikt")

            # ── 9. Extraheer data ─────────────────────────────────────────
            plan = _extract_plan_from_captures(all_captured)
            upcoming, completed_runs = _extract_sessions_from_captures(all_captured)

            # ── 10. Stel resultaat samen ──────────────────────────────────
            result: dict = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "debug_urls": debug_urls,
            }
            if plan:
                result["training_plan"] = plan
            if upcoming:
                result["upcoming_sessions"] = upcoming
            if completed_runs:
                result["recent_completed"] = completed_runs

            log.info(
                "Klaar: plan=%s, aankomend=%d, voltooid=%d, debug_urls=%d",
                bool(plan), len(upcoming), len(completed_runs), len(debug_urls),
            )
            return result

    except Exception as exc:
        log.exception("Onverwachte fout in fetch_runna_data: %s", exc)
        return {
            "error": str(exc),
            "debug_urls": debug_urls,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> int:
    email    = os.environ.get("RUNNA_EMAIL", "").strip()
    password = os.environ.get("RUNNA_PASSWORD", "").strip()
    gist_id  = os.environ.get("GIST_ID", "").strip()
    token    = os.environ.get("GITHUB_TOKEN", "").strip()

    if not email or not password:
        log.error("RUNNA_EMAIL en RUNNA_PASSWORD zijn vereist")
        return 1

    data = fetch_runna_data(email, password, gist_id=gist_id, token=token)

    if gist_id and token:
        try:
            save_to_gist(gist_id, token, data)
        except Exception as exc:
            log.error("Gist opslaan mislukt: %s", exc)
            return 1
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))

    return 1 if "error" in data else 0


if __name__ == "__main__":
    sys.exit(main())
