"""
fetch_runna.py — Haalt trainingsdata op uit de Runna web-app via Playwright.

Runna heeft geen publieke API. Dit script logt in op web.runna.com met een
mobiele browser-emulatie (iPhone) en onderschept alle JSON XHR-responses om
het trainingsplan, geplande sessions en recent voltooide runs te extraheren.

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

RUNNA_BASE = "https://web.runna.com"
GIST_FILENAME = "runna_data.json"

# Pagina's om na login te bezoeken (triggert XHR-calls)
PAGES_TO_VISIT = [
    ("", "dashboard"),
    ("/plan", "trainingsplan"),
    ("/schedule", "schema"),
    ("/history", "geschiedenis"),
    ("/runs", "runs"),
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("runna")


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _to_date_str(value: object) -> str | None:
    """Normaliseer diverse datumformaten naar 'YYYY-MM-DD'."""
    if not value:
        return None
    s = str(value)
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return m.group(0) if m else None


def _find_array_in(data: object) -> list:
    """Haal de eerste lijst op uit een JSON-response (data, results, items, enz.)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items", "sessions", "runs", "workouts",
                    "activities", "plans", "weeks", "schedule"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


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


# ── Data-extractie ────────────────────────────────────────────────────────────

def _extract_plan_from_captures(captured: list[dict]) -> dict | None:
    """Scan XHR-captures op trainingsplan-metadata."""
    plan_keys = {"plan_name", "plan", "training_plan", "name", "goal", "current_week",
                 "total_weeks", "phase", "weeks", "target", "title", "description"}
    for item in captured:
        url = item["url"]
        data = item["data"]
        if not isinstance(data, dict):
            continue
        # Zoek in root of in geneste 'plan'/'training_plan' key
        candidates = [data]
        for k in ("plan", "training_plan", "current_plan", "active_plan"):
            if isinstance(data.get(k), dict):
                candidates.append(data[k])

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            matches = plan_keys & set(obj.keys())
            if len(matches) >= 2:
                log.info("[extract] Trainingsplan gevonden via %s: %s", url, list(matches))
                plan = {}
                # Naam
                plan["name"] = (
                    obj.get("plan_name")
                    or obj.get("name")
                    or obj.get("title")
                    or (obj.get("plan") if isinstance(obj.get("plan"), str) else None)
                )
                # Doel
                plan["goal"] = obj.get("goal") or obj.get("target")
                # Weeknummer
                plan["current_week"] = obj.get("current_week") or obj.get("week_number")
                plan["total_weeks"] = obj.get("total_weeks") or obj.get("num_weeks") or obj.get("duration_weeks")
                # Fase
                plan["phase"] = obj.get("phase") or obj.get("phase_name")
                # Verwijder None-waarden
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
    Scant alle XHR-captures op sessie-achtige objecten.
    Geeft (upcoming_sessions, recent_completed) terug.
    """
    today = datetime.now(timezone.utc).date()
    cutoff_past = today - timedelta(days=window_days_past)
    cutoff_future = today + timedelta(days=window_days_future)

    upcoming: list[dict] = []
    completed: list[dict] = []
    seen_dates: set[tuple] = set()  # voorkom duplicaten

    for item in captured:
        data = item["data"]
        arr = _find_array_in(data)
        if not arr:
            continue

        # Controleer of het een lijst van sessie-achtige objecten is
        sample = arr[0] if arr else {}
        if not isinstance(sample, dict):
            continue

        has_date = any(
            k in sample for k in ("date", "scheduled_date", "planned_date",
                                  "activity_date", "start_date", "run_date")
        )
        has_title = any(
            k in sample for k in ("title", "name", "type", "session_type",
                                  "workout_type", "run_type", "description")
        )
        if not (has_date and has_title):
            continue

        log.info("[extract] Sessie-array gevonden in %s (%d items)", item["url"], len(arr))

        for obj in arr:
            if not isinstance(obj, dict):
                continue

            # Datum
            raw_date = (
                obj.get("date") or obj.get("scheduled_date")
                or obj.get("planned_date") or obj.get("activity_date")
                or obj.get("start_date") or obj.get("run_date")
            )
            date_str = _to_date_str(raw_date)
            if not date_str:
                continue

            try:
                session_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Titel / type
            title = (
                obj.get("title") or obj.get("name") or obj.get("session_type")
                or obj.get("run_type") or obj.get("workout_type")
            )
            session_type = _normalize_session_type(
                obj.get("session_type") or obj.get("run_type")
                or obj.get("type") or str(title or "")
            )

            # Is de sessie voltooid?
            is_completed = bool(
                obj.get("completed")
                or obj.get("is_completed")
                or obj.get("status") in ("completed", "done", "finished")
                or obj.get("actual_distance_km")
                or obj.get("actual_duration_min")
            )

            # Afstand en duur
            distance_km = (
                obj.get("distance_km") or obj.get("distance")
                or obj.get("target_distance_km") or obj.get("planned_distance_km")
            )
            duration_min = (
                obj.get("duration_min") or obj.get("duration")
                or obj.get("target_duration_min") or obj.get("planned_duration_min")
            )

            # Omschrijving
            description = obj.get("description") or obj.get("notes") or obj.get("instructions")

            session = {
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

            # Dedupliceer op (datum, titel)
            key = (date_str, session["title"].lower()[:30])
            if key in seen_dates:
                continue
            seen_dates.add(key)

            # Aankomend of voltooid?
            if session_date >= today and session_date <= cutoff_future:
                upcoming.append(session)
            elif session_date < today and session_date >= cutoff_past and is_completed:
                completed.append(session)

    # Sorteer
    upcoming.sort(key=lambda s: s["date"])
    completed.sort(key=lambda s: s["date"], reverse=True)

    return upcoming, completed


def _dom_fallback(page) -> dict:
    """
    DOM-fallback: probeer sessie-informatie te scrapen als XHR-interceptie
    niets bruikbaars opleverde.
    """
    try:
        result = page.evaluate("""
            () => {
                const sessions = [];
                // Zoek op typische selectors voor trainingsschema's
                const cards = document.querySelectorAll(
                    '[data-testid*="session"], [data-testid*="run"], [class*="session"], [class*="run-card"]'
                );
                cards.forEach(card => {
                    const text = card.innerText || card.textContent || '';
                    const dateMatch = text.match(/\\d{4}-\\d{2}-\\d{2}|\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}/);
                    if (dateMatch) {
                        sessions.push({title: text.slice(0, 100).trim(), raw_date: dateMatch[0]});
                    }
                });
                return sessions;
            }
        """)
        log.info("[dom] %d elementen gevonden via DOM-fallback", len(result or []))
        return {"dom_sessions": result or []}
    except Exception as exc:
        log.warning("[dom] DOM-fallback mislukt: %s", exc)
        return {}


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
    Login op web.runna.com, onderschep XHR-calls en extraheer trainingsdata.
    Geeft altijd een dict terug (minimaal met 'fetched_at').
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.error("playwright niet geïnstalleerd")
        return {"error": "playwright niet geïnstalleerd", "fetched_at": datetime.now(timezone.utc).isoformat()}

    log.info("Playwright headless browser starten (mobiele emulatie)")
    captured: list[dict] = []
    debug_urls: list[str] = []

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            # Sla alleen Runna-eigen API-calls op
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

            # Verberg Playwright-detectie
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            page = context.new_page()
            page.on("response", _on_response)

            # ── 1. Inloggen ───────────────────────────────────────────────
            log.info("[browser] Navigeren naar %s", RUNNA_BASE)
            page.goto(RUNNA_BASE, wait_until="domcontentloaded", timeout=30000)

            # Diagnose: log beschikbare inputs
            try:
                inputs = page.evaluate(
                    "() => [...document.querySelectorAll('input')].map(i => "
                    "({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder}))"
                )
                log.info("[browser] Inputs op pagina: %s", inputs)
                buttons = page.evaluate(
                    "() => [...document.querySelectorAll('button')].map(b => "
                    "({id: b.id, type: b.type, text: b.textContent.trim().slice(0,50)}))"
                )
                log.info("[browser] Knoppen op pagina: %s", buttons)
            except Exception as dbg_exc:
                log.warning("[browser] Kon formuliervelden niet loggen: %s", dbg_exc)

            # Vul email en wachtwoord in via type() (React synthetic events)
            try:
                email_input = page.locator('input[type="email"], input[name="email"]').first
                email_input.wait_for(state="visible", timeout=10000)
                email_input.click()
                email_input.type(email)
                log.info("[browser] Email ingevuld")
            except Exception as exc:
                log.warning("[browser] Email-veld niet gevonden: %s", exc)

            try:
                password_input = page.locator('input[type="password"]').first
                password_input.click()
                password_input.type(password)
                log.info("[browser] Wachtwoord ingevuld")
            except Exception as exc:
                log.warning("[browser] Wachtwoord-veld niet gevonden: %s", exc)

            # Klik submit-knop
            try:
                submit = page.locator('button[type="submit"]').first
                submit.wait_for(state="enabled", timeout=5000)
                submit.click()
                log.info("[browser] Submit-knop geklikt")
            except Exception:
                log.info("[browser] Submit-knop niet beschikbaar; Enter indrukken")
                try:
                    page.locator('input[type="password"]').first.press("Enter")
                except Exception:
                    pass

            # Wacht op redirect weg van login/auth
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/login') && "
                    "!window.location.href.includes('/auth') && "
                    "!window.location.href.includes('/sign-in')",
                    timeout=20000,
                )
                log.info("[browser] Ingelogd, huidige URL: %s", page.url)
            except Exception as exc:
                log.warning("[browser] Redirect na login mislukt: %s — %s", page.url, exc)
                if any(p in page.url for p in ("/login", "/auth", "/sign-in")):
                    log.error("[browser] Nog steeds op loginpagina — inloggen mislukt")
                    # Sla debug-HTML op in Gist
                    try:
                        html_content = page.content()
                        if gist_id and token:
                            requests.patch(
                                f"https://api.github.com/gists/{gist_id}",
                                headers={"Authorization": f"token {token}"},
                                json={"files": {"debug_runna_login.html": {"content": html_content[:80000]}}},
                                timeout=15,
                            )
                            log.info("[browser] Debug-HTML opgeslagen in Gist")
                    except Exception as dbg_exc:
                        log.warning("[browser] Kon debug-HTML niet opslaan: %s", dbg_exc)
                    browser.close()
                    return {
                        "error": "Login mislukt",
                        "debug_urls": debug_urls,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }

            # ── 2. Bezoek meerdere pagina's om XHR-calls te triggeren ─────
            all_captured: list[dict] = list(captured)

            for path, label in PAGES_TO_VISIT:
                captured.clear()
                url = f"{RUNNA_BASE}{path}"
                try:
                    log.info("[browser] Navigeren naar %s (%s)", url, label)
                    page.goto(url, wait_until="networkidle", timeout=25000)
                    time.sleep(1)  # kort wachten op trage responses
                    log.info("[browser] %s: %d XHR-responses onderschept", label, len(captured))
                    all_captured.extend(captured)
                except Exception as exc:
                    log.warning("[browser] Navigatie naar %s mislukt: %s", label, exc)

            # ── 3. Extraheer data ─────────────────────────────────────────
            plan = _extract_plan_from_captures(all_captured)
            upcoming, completed_runs = _extract_sessions_from_captures(all_captured)

            # DOM-fallback als niets gevonden
            if not plan and not upcoming and not completed_runs:
                log.info("[browser] Geen data via XHR — probeer DOM-fallback")
                dom_data = _dom_fallback(page)
            else:
                dom_data = {}

            browser.close()

            # ── 4. Stel resultaat samen ───────────────────────────────────
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
            if dom_data:
                result["dom_fallback"] = dom_data

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
        # Lokale test: print naar stdout
        print(json.dumps(data, ensure_ascii=False, indent=2))

    return 1 if "error" in data else 0


if __name__ == "__main__":
    sys.exit(main())
