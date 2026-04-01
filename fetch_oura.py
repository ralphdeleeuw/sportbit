#!/usr/bin/env python3
"""
Oura Ring data fetcher voor het SportBit CrossFit dashboard.

Haalt slaap-, herstel- en stressdata op via de Oura API V2.
Retourneert None als OURA_ACCESS_TOKEN niet is ingesteld — veilig te
importeren voordat de Oura Ring is aangeschaft.

══════════════════════════════════════════════════════════════
EENMALIGE SETUP — Oura Personal Access Token aanmaken
══════════════════════════════════════════════════════════════

1. Zorg dat je een actief Oura Membership hebt (vereist voor Oura Ring 4 API)

2. Log in op cloud.ouraring.com

3. Ga naar: Account → Personal Access Tokens
   https://cloud.ouraring.com/personal-access-tokens

4. Klik "Create New Personal Access Token"
   - Geef het een naam (bijv. "SportBit")
   - Kopieer het token direct — het wordt maar één keer getoond

5. Voeg toe als GitHub Secret:
   Repo → Settings → Secrets and variables → Actions
   OURA_ACCESS_TOKEN = jouw token

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  OURA_ACCESS_TOKEN  - Oura Personal Access Token
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

OURA_BASE = "https://api.ouraring.com"


def _fetch_endpoint(headers: dict, path: str, start: str, end: str) -> list[dict]:
    """Helper: haal data op van een Oura V2 collection endpoint."""
    try:
        resp = requests.get(
            f"{OURA_BASE}{path}",
            headers=headers,
            params={"start_date": start, "end_date": end},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as exc:
        log.warning("Oura %s fetch mislukt: %s", path, exc)
        return []


def fetch_oura_data(days: int = 14) -> dict | None:
    """Haalt slaap-, herstel- en stressdata op van de Oura Ring API.

    Vereist OURA_ACCESS_TOKEN als omgevingsvariabele.
    Retourneert None als het token niet is ingesteld — geen fout.
    """
    token = os.environ.get("OURA_ACCESS_TOKEN", "").strip()
    if not token:
        log.info("OURA_ACCESS_TOKEN niet ingesteld — Oura data overgeslagen")
        return None

    headers = {"Authorization": f"Bearer {token}"}
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    # ── 1. Daily readiness (score 0-100) ─────────────────────────────────
    readiness_by_date: dict[str, dict] = {}
    for item in _fetch_endpoint(headers, "/v2/usercollection/daily_readiness", start, end):
        day = item.get("day")
        if day:
            readiness_by_date[day] = {
                "readiness_score": item.get("score"),
            }

    # ── 2. Sleep sessions (fases, HRV, rustpols) ─────────────────────────
    # Multiple sessions per day possible (nap + night) — sum durations,
    # use last session's efficiency/HRV/RHR as representative value.
    sleep_by_date: dict[str, dict] = {}
    for s in _fetch_endpoint(headers, "/v2/usercollection/sleep", start, end):
        day = s.get("day")
        if not day:
            continue
        prev = sleep_by_date.get(day, {})

        def _add(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        deep_s = s.get("deep_sleep_duration") or 0
        rem_s = s.get("rem_sleep_duration") or 0
        light_s = s.get("light_sleep_duration") or 0
        latency_s = s.get("latency") or 0

        sleep_by_date[day] = {
            "deep_sleep_min": _add(prev.get("deep_sleep_min"), round(deep_s / 60)),
            "rem_sleep_min": _add(prev.get("rem_sleep_min"), round(rem_s / 60)),
            "light_sleep_min": _add(prev.get("light_sleep_min"), round(light_s / 60)),
            "sleep_efficiency": s.get("efficiency"),          # last session wins
            "sleep_latency_min": round(latency_s / 60),       # last session wins
            "average_hrv": s.get("average_hrv"),              # last session wins
            "resting_hr": s.get("lowest_heart_rate"),         # last session wins
        }

    # ── 3. Daily stress (minuten hoge stress / herstel) ───────────────────
    stress_by_date: dict[str, dict] = {}
    for s in _fetch_endpoint(headers, "/v2/usercollection/daily_stress", start, end):
        day = s.get("day")
        if day:
            stress_by_date[day] = {
                "stress_high_min": s.get("stress_high"),
                "recovery_high_min": s.get("recovery_high"),
                "day_summary": s.get("day_summary"),
            }

    # ── 4. Combineer alle datums ──────────────────────────────────────────
    all_dates = set(readiness_by_date) | set(sleep_by_date) | set(stress_by_date)
    by_date: dict[str, dict] = {}
    for d in all_dates:
        entry: dict = {}
        entry.update(readiness_by_date.get(d, {}))
        entry.update(sleep_by_date.get(d, {}))
        entry.update(stress_by_date.get(d, {}))
        by_date[d] = entry

    log.info("Oura data opgehaald: %d dagen", len(by_date))
    return {
        "by_date": by_date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
