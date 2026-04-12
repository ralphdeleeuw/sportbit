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
    ("/today",    "vandaag"),
    ("/plan",     "trainingsplan"),
    ("/schedule", "schema"),
    ("/calendar", "kalender"),
    ("/history",  "geschiedenis"),
    ("/runs",     "runs"),
]

# Sleutels die wijzen op race-evenementen (niet op trainings-sessies)
RACE_EVENT_INDICATORS = frozenset({
    "noSponsorName", "imageUrl", "websiteUrl", "elevation",
    "keywords", "weather", "bio", "endDate",
})

# GraphQL-queries via browser-fetch (met app-headers incl. JWT na login).
# Bevestigd werkend op het Runna web-schema (hydra.platform.runna.com/graphql).
# Sessiedata is alleen beschikbaar in de mobile-app API; niet via web-schema.
GRAPHQL_QUERIES = [
    ("getActiveOrderDetails_full", """query {
      getActiveOrderDetails {
        customPlanName
        planV2 {
          shortPlanName planLength raceDistance raceDistName color iconText
        }
      }
    }"""),
    ("getPlanMetadata_full", """query {
      getPlanMetadata {
        id name shortName description
        totalWeeks currentWeek weekNumber
        phase goal raceDate raceDistance
        weeks {
          weekNumber isCurrentWeek label
          sessions { id scheduledDate title sessionType status targetDistance targetDuration }
        }
        currentWeekSessions { id scheduledDate title sessionType status targetDistance targetDuration }
        upcomingSessions { id scheduledDate title sessionType status targetDistance targetDuration }
        completedSessions { id completedDate title sessionType actualDistance actualDuration }
      }
    }"""),
    ("getRace_current", """query {
      getRace {
        id name date distance type goal
      }
    }"""),
    ("userProfile_basic", """query { userProfile { id name email unitOfMeasurementV2 subscriptionStatusV2 } }"""),
]

# Sessie-queries voor het mobile schema (rb-ios / rb-android).
# Werkt als:
#   a) Runna de schemadifferentiatie via de x-rb-platform-source header doet, of
#   b) RUNNA_MOBILE_API_KEY is ingesteld (uit APK-analyse — zie find_runna_mobile_key.py)
MOBILE_SESSION_QUERIES = [
    ("mobile_getActiveOrderDetails_sessions", """query {
      getActiveOrderDetails {
        currentWeekNumber totalWeeks
        weekSessions {
          id scheduledDate title sessionType status
          targetDistance targetDuration description isRestDay completedDate
        }
      }
    }"""),
    ("mobile_getActiveOrderDetails_completed", """query {
      getActiveOrderDetails {
        completedSessions {
          id completedDate title sessionType actualDistance actualDuration
        }
      }
    }"""),
    ("mobile_getActiveOrderDetails_planweeks", """query {
      getActiveOrderDetails {
        currentWeekNumber totalWeeks
        planWeeks {
          weekNumber isCurrentWeek
          sessions {
            id scheduledDate title sessionType status
            targetDistance targetDuration description isRestDay
          }
        }
      }
    }"""),
]

# Optionele mobile API-key (uit APK-analyse — zie find_runna_mobile_key.py).
# Stel in als GitHub Secret: RUNNA_MOBILE_API_KEY
RUNNA_MOBILE_API_KEY = os.getenv("RUNNA_MOBILE_API_KEY", "")

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

    def _build_plan(order: dict, plan_v2: dict | None) -> dict:
        """Bouw plan-dict op uit getActiveOrderDetails-structuur."""
        p: dict = {}
        if plan_v2:
            p["name"] = (
                order.get("customPlanName")
                or plan_v2.get("shortPlanName")
                or plan_v2.get("id", "").replace("_V2", "").replace("_", " ").title()
            )
            p["total_weeks"] = plan_v2.get("planLength") or order.get("totalWeeks")
        else:
            p["name"] = order.get("customPlanName")
        p["current_week"] = (
            order.get("currentWeekNumber") or order.get("currentWeek")
            or order.get("weekNumber")
        )
        if not p.get("total_weeks"):
            p["total_weeks"] = order.get("totalWeeks")
        return {k: v for k, v in p.items() if v is not None}

    # ── Stap 1: merge ALLE getActiveOrderDetails-responses ───────────────────
    # (app stuurt minimale velden, browser-gql stuurt planLength — beide nodig)
    merged_plan: dict = {}
    for item in captured:
        data = item["data"]
        if not isinstance(data, dict):
            continue
        gql = data.get("data") or {}
        order = gql.get("getActiveOrderDetails") if isinstance(gql, dict) else None
        if isinstance(order, dict):
            plan_v2 = order.get("planV2") if isinstance(order.get("planV2"), dict) else None
            plan = _build_plan(order, plan_v2)
            for k, v in plan.items():
                if v is not None and k not in merged_plan:
                    merged_plan[k] = v
    if merged_plan.get("name"):
        log.info("[extract] Plan via getActiveOrderDetails (merged): %s", merged_plan)
        return merged_plan

    plan_keys = {"plan_name", "planName", "name", "goal", "currentWeek", "current_week",
                 "totalWeeks", "total_weeks", "phase", "weeks", "target", "title",
                 "numWeeks", "durationWeeks", "weekNumber", "shortPlanName"}

    for item in captured:
        url = item["url"]
        data = item["data"]
        if not isinstance(data, dict):
            continue
        gql = data.get("data") or {}

        # ── Generieke search: kandidaat-objecten recursief doorzoeken ──────
        inner = gql if isinstance(gql, dict) else {}
        candidates = [data, inner]
        for v in inner.values() if isinstance(inner, dict) else []:
            if isinstance(v, dict):
                candidates.append(v)
        for k in ("plan", "trainingPlan", "activePlan", "currentPlan",
                  "training_plan", "planV2"):
            for src in (data, inner):
                if isinstance(src.get(k), dict):
                    candidates.append(src[k])

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            matches = plan_keys & set(obj.keys())
            if len(matches) >= 2:
                log.info("[extract] Trainingsplan gevonden via %s: keys=%s", url, list(matches))
                plan = {
                    "name": (obj.get("plan_name") or obj.get("planName")
                             or obj.get("shortPlanName") or obj.get("name") or obj.get("title")),
                    "goal": obj.get("goal") or obj.get("target"),
                    "current_week": (obj.get("current_week") or obj.get("currentWeek")
                                     or obj.get("currentWeekNumber") or obj.get("weekNumber")),
                    "total_weeks": (obj.get("total_weeks") or obj.get("totalWeeks")
                                    or obj.get("num_weeks") or obj.get("numWeeks")
                                    or obj.get("planLength") or obj.get("durationWeeks")),
                    "phase": obj.get("phase") or obj.get("phase_name") or obj.get("phaseName"),
                }
                plan = {k: v for k, v in plan.items() if v is not None}
                if plan.get("name"):
                    return plan
    return None


def _extract_sessions_from_captures(
    captured: list[dict],
    window_days_future: int = 28,
    window_days_past: int = 90,
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

            # Sla race-evenement-arrays over (getTrendingRaceEvents e.d.)
            if RACE_EVENT_INDICATORS & set(sample.keys()):
                log.debug(
                    "[extract] Race-evenement-array overgeslagen in %s — sample keys: %s",
                    item["url"], list(sample.keys())[:12]
                )
                continue

            log.info(
                "[extract] Sessie-array gevonden in %s (%d items) — sample keys: %s",
                item["url"], len(arr), list(sample.keys())[:12]
            )

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

                # Sla rust-dagen over
                if obj.get("isRestDay") or obj.get("is_rest_day"):
                    continue

                if session_date >= today and session_date <= cutoff_future:
                    upcoming.append(session)
                elif session_date < today and session_date >= cutoff_past:
                    # Verleden sessies tonen ook als niet expliciet 'completed'
                    # (Runna markeert gemiste sessions mogelijk anders)
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


def _run_graphql_in_browser(
    page,
    captured: list[dict],
    app_headers: dict | None = None,
) -> None:
    """
    Voer GraphQL-queries uit via page.evaluate(fetch(...)) met dezelfde
    headers als de Runna-app zelf (inclusief Authorization-token).
    """
    # Bouw de headers op die de browser meestuurt
    headers_to_use: dict = {"Content-Type": "application/json"}
    if app_headers:
        for k, v in app_headers.items():
            if k.lower() in ("authorization", "x-api-key", "x-amz-user-agent", "x-rb-platform-source"):
                headers_to_use[k] = v
    log.info("[browser-gql] Headers voor directe queries: %s", list(headers_to_use.keys()))
    headers_json = json.dumps(headers_to_use)

    for query_name, query in GRAPHQL_QUERIES:
        try:
            query_json = json.dumps(query)   # veilig escapen voor JS-inlining
            data = page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch('{GRAPHQL_URL}', {{
                            method: 'POST',
                            headers: {headers_json},
                            body: JSON.stringify({{ query: {query_json} }})
                        }});
                        // Lees body eenmalig — AppSync geeft bij 400 JSON-errors terug
                        let body;
                        try {{ body = await resp.json(); }} catch(_) {{ body = null; }}
                        if (!resp.ok) return {{ _httpError: resp.status, _body: body }};
                        return body;
                    }} catch (e) {{
                        return {{ _fetchError: e.toString() }};
                    }}
                }}
            """)
            if not isinstance(data, dict):
                continue
            if data.get("_httpError"):
                body = data.get("_body") or {}
                errs = [e.get("message", "") for e in (body.get("errors") or [])]
                if errs:
                    log.info("[browser-gql] %s → HTTP %s: %s",
                             query_name, data["_httpError"], errs[:3])
                else:
                    log.info("[browser-gql] %s → HTTP %s (body: %s)",
                             query_name, data["_httpError"], str(body)[:200])
                continue
            if data.get("_fetchError"):
                log.info("[browser-gql] %s → fetch-fout: %s", query_name, data["_fetchError"])
                continue
            if data.get("errors") and not data.get("data"):
                err_msgs = [e.get("message", "") for e in data.get("errors", [])]
                log.info("[browser-gql] %s → GraphQL errors: %s", query_name, err_msgs[:3])
                continue

            log.info("[browser-gql] %s → %s", query_name, str(data)[:800])

            captured.append({"url": f"{GRAPHQL_URL}#{query_name}", "data": data})
        except Exception as exc:
            log.info("[browser-gql] %s → Python-uitzondering: %s", query_name, exc)

    # ── Mobile schema — extra pass met mobile API-key ────────────────────────
    # Alleen uitvoeren als RUNNA_MOBILE_API_KEY is ingesteld.
    # De web API-key (rb-web) blokkeert sessievelden zoals weekSessions/currentWeekNumber.
    # De x-rb-platform-source header verandert het schema NIET — dat is API-key afhankelijk.
    # Gebruik find_runna_mobile_key.py om de mobile API-key uit de APK te extraheren.
    mobile_header_sets: list[tuple[str, dict]] = []

    if RUNNA_MOBILE_API_KEY:
        key_headers: dict = {
            "Content-Type": "application/json",
            "x-api-key": RUNNA_MOBILE_API_KEY,
            "x-rb-platform-source": "rb-ios",
        }
        mobile_header_sets.append(("ios-apikey", key_headers))

    for pass_name, mheaders in mobile_header_sets:
        mheaders_json = json.dumps(mheaders)
        log.info("[mobile-gql] Pass '%s' starten (headers: %s)",
                 pass_name, [k for k in mheaders if k != "Content-Type"])
        found_any = False
        for query_name, query in MOBILE_SESSION_QUERIES:
            try:
                query_json = json.dumps(query)
                data = page.evaluate(f"""
                    async () => {{
                        try {{
                            const resp = await fetch('{GRAPHQL_URL}', {{
                                method: 'POST',
                                headers: {mheaders_json},
                                body: JSON.stringify({{ query: {query_json} }})
                            }});
                            let body;
                            try {{ body = await resp.json(); }} catch(_) {{ body = null; }}
                            if (!resp.ok) return {{ _httpError: resp.status, _body: body }};
                            return body;
                        }} catch (e) {{
                            return {{ _fetchError: e.toString() }};
                        }}
                    }}
                """)
                if not isinstance(data, dict):
                    continue
                if data.get("_httpError"):
                    body = data.get("_body") or {}
                    errs = [e.get("message", "") for e in (body.get("errors") or [])]
                    log.info("[mobile-gql] %s/%s → HTTP %s: %s",
                             pass_name, query_name, data["_httpError"], errs[:2])
                    continue
                if data.get("_fetchError"):
                    log.info("[mobile-gql] %s/%s → fetch-fout: %s",
                             pass_name, query_name, data["_fetchError"])
                    continue
                if data.get("errors") and not data.get("data"):
                    errs = [e.get("message", "") for e in data.get("errors", [])]
                    log.info("[mobile-gql] %s/%s → GraphQL errors: %s",
                             pass_name, query_name, errs[:2])
                    continue
                log.info("[mobile-gql] %s/%s → %s", pass_name, query_name, str(data)[:800])
                captured.append({"url": f"{GRAPHQL_URL}#{query_name}", "data": data})
                found_any = True
            except Exception as exc:
                log.info("[mobile-gql] %s/%s → uitzondering: %s",
                         pass_name, query_name, exc)
        if found_any:
            log.info("[mobile-gql] Pass '%s': sessiedata gevonden — overige passes overgeslagen",
                     pass_name)
            break


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


# ── Web JS-bundle scanner ─────────────────────────────────────────────────────

_API_KEY_RE = re.compile(rb"da2-[a-zA-Z0-9]{26}")
_KNOWN_WEB_KEY = "da2-p6hunb5zafhn7ngpf6jtotnjvm"


def _scan_web_bundles() -> dict:
    """
    Haal de Runna web-app HTML op en scan alle JS-bundles op AppSync API-keys.
    Geeft {'extra_api_keys': [...], 'bundles_scanned': N} terug.
    Loopt nooit langer dan ~15 seconden.
    """
    import html.parser

    class ScriptParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts: list[str] = []
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                d = dict(attrs)
                src = d.get("src", "")
                if src:
                    self.scripts.append(src)

    try:
        log.info("[bundle-scan] Ophalen web.runna.com HTML …")
        html_resp = requests.get(RUNNA_BASE, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; fetch_runna/1.0)"
        })
        html_resp.raise_for_status()
        parser = ScriptParser()
        parser.feed(html_resp.text)

        script_urls = []
        for src in parser.scripts:
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = RUNNA_BASE + src
            if "runna" in src or src.startswith(RUNNA_BASE):
                script_urls.append(src)

        log.info("[bundle-scan] %d Runna JS-bundles gevonden", len(script_urls))

        found_keys: set[str] = set()
        scanned = 0
        for url in script_urls[:15]:           # max 15 bundles
            try:
                r = requests.get(url, timeout=8, stream=True, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; fetch_runna/1.0)"
                })
                r.raise_for_status()
                chunk = b""
                for blk in r.iter_content(chunk_size=65536):
                    chunk += blk
                    if len(chunk) >= 200_000:   # max 200 KB per bundle
                        break
                for m in _API_KEY_RE.finditer(chunk):
                    key = m.group(0).decode()
                    if key != _KNOWN_WEB_KEY:
                        found_keys.add(key)
                        log.info("[bundle-scan] Extra API-key gevonden in %s: %s", url, key)
                scanned += 1
            except Exception as exc:
                log.debug("[bundle-scan] %s overgeslagen: %s", url, exc)

        log.info("[bundle-scan] Klaar: %d bundles gescand, %d extra keys gevonden",
                 scanned, len(found_keys))
        return {"extra_api_keys": sorted(found_keys), "bundles_scanned": scanned}

    except Exception as exc:
        log.warning("[bundle-scan] Mislukt: %s", exc)
        return {"extra_api_keys": [], "bundles_scanned": 0}


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

    # Scan web JS-bundles op extra API-keys (vóór browser start; geen auth nodig)
    bundle_scan = _scan_web_bundles()

    log.info("Playwright headless browser starten (mobiele emulatie)")
    captured: list[dict] = []
    debug_urls: list[str] = []
    graphql_req_headers: dict = {}   # auth-headers van het eerste geslaagde GQL-verzoek

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            if "runna" not in url.lower():
                return
            data = response.json()

            # Voeg operatienaam toe voor GraphQL-calls (staat in request POST-body)
            op_name = ""
            if "graphql" in url.lower():
                try:
                    post_raw = response.request.post_data
                    if post_raw:
                        body = json.loads(post_raw)
                        op_name = body.get("operationName") or ""
                        if not op_name:
                            m = re.search(r'query\s+(\w+)', body.get("query", ""))
                            if m:
                                op_name = m.group(1)
                except Exception:
                    pass

            url_label = f"{url}#{op_name}" if op_name else url
            log.info("  [xhr] %s → %s", url_label, str(data)[:400])
            captured.append({"url": url_label, "data": data})
            debug_urls.append(url_label)
        except Exception:
            pass

    def _on_graphql_request(request) -> None:
        """Leg GraphQL-request-headers vast; update altijd als Authorization aanwezig is."""
        try:
            if "hydra.platform.runna.com/graphql" not in request.url:
                return
            h = dict(request.headers)
            has_auth = any(k.lower() == "authorization" for k in h)
            # Altijd updaten als we Authorization (JWT) zien, anders alleen als nog leeg
            if has_auth or not graphql_req_headers:
                graphql_req_headers.clear()
                graphql_req_headers.update(h)
                interesting = {
                    k: v[:40] + "…" if len(v) > 40 else v
                    for k, v in h.items()
                    if k.lower() in (
                        "authorization", "content-type", "x-api-key",
                        "origin", "referer", "x-amz-user-agent", "x-rb-platform-source",
                    )
                }
                log.info("[req] GraphQL-headers bijgewerkt (auth=%s): %s", has_auth, interesting)
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
            page.on("request",  _on_graphql_request)

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

            # ── 5b. Onboarding-redirect overslaan ────────────────────────
            # Op de web-app kan het zijn dat de gebruiker in een onboarding-flow
            # terechtkomt (/onboarding/...). We navigeren er direct doorheen.
            if "/onboarding" in page.url:
                log.info("[browser] Onboarding gedetecteerd (%s) — naar /today navigeren", page.url)
                try:
                    page.goto(f"{RUNNA_BASE}/today", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)
                    log.info("[browser] Na onboarding-bypass — URL: %s", page.url)
                except Exception as exc:
                    log.warning("[browser] Onboarding-bypass mislukt: %s", exc)

            # ── 6. (Gereserveerd voor toekomstige auth-logica) ────────────

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

            # ── 8. Browser-gebaseerde GraphQL-queries (app-headers kopiëren) ──
            log.info("[browser-gql] Directe queries uitvoeren (app-headers: %s)",
                     list(graphql_req_headers.keys())[:8])
            _run_graphql_in_browser(page, all_captured, app_headers=graphql_req_headers or None)

            browser.close()

            # ── 9. Extraheer data ─────────────────────────────────────────
            plan = _extract_plan_from_captures(all_captured)
            upcoming, completed_runs = _extract_sessions_from_captures(all_captured)

            # ── 10. Verzamel debug-informatie ─────────────────────────────
            # Sla de volledige getActiveOrderDetails op (niet afgekapt)
            raw_active_order: dict | None = None
            for cap in all_captured:
                gql_data = (cap.get("data") or {}).get("data") or {}
                if isinstance(gql_data, dict) and "getActiveOrderDetails" in gql_data:
                    raw_active_order = gql_data["getActiveOrderDetails"]
                    break
            if raw_active_order:
                log.info("[debug] getActiveOrderDetails (volledig): %s", raw_active_order)

            # Als geen sessies: sla eerste niet-race array op voor diagnose
            debug_extra: dict = {}
            if not upcoming and not completed_runs:
                for cap in all_captured:
                    arrays = _deep_find_arrays(cap["data"])
                    for arr in arrays:
                        s = arr[0] if arr else None
                        if isinstance(s, dict) and len(arr) >= 3:
                            # Sla race-arrays over in debug ook
                            if not (RACE_EVENT_INDICATORS & set(s.keys())):
                                debug_extra = {
                                    "debug_sample": s,
                                    "debug_array_len": len(arr),
                                    "debug_array_source": cap["url"],
                                }
                                log.info("[debug] Sample array: %s", str(s)[:500])
                                break
                    else:
                        continue
                    break

            # ── 11. Stel resultaat samen ──────────────────────────────────
            # debug_captures: compacte samenvatting van elke onderschepte response
            # zodat we kunnen zien welke GraphQL-operaties data retourneren.
            debug_captures = []
            for cap in all_captured:
                op = cap["url"].split("#")[-1] if "#" in cap["url"] else ""
                data_node = cap.get("data") or {}
                top_keys = list(data_node.keys()) if isinstance(data_node, dict) else []
                gql_keys: list[str] = []
                gql_data = data_node.get("data") if isinstance(data_node, dict) else None
                if isinstance(gql_data, dict):
                    gql_keys = list(gql_data.keys())
                debug_captures.append({
                    "op": op,
                    "url": cap["url"].split("?")[0],
                    "top_keys": top_keys,
                    "gql_keys": gql_keys,
                })

            result: dict = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "debug_urls": debug_urls,
                "debug_captures": debug_captures,
                "bundle_scan": bundle_scan,
                **debug_extra,
            }
            if raw_active_order is not None:
                result["debug_active_order"] = raw_active_order
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
