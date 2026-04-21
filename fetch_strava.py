#!/usr/bin/env python3
"""
Strava data fetcher voor het SportBit CrossFit dashboard.

══════════════════════════════════════════════════════════════
EENMALIGE SETUP — Strava OAuth2 refresh token ophalen
══════════════════════════════════════════════════════════════

1. Maak een Strava API-applicatie aan:
   https://www.strava.com/settings/api
   - Application Name: SportBit (of iets anders)
   - Website: http://localhost
   - Authorization Callback Domain: localhost
   Noteer: Client ID en Client Secret

2. Autoriseer de app en haal de code op:
   Open in browser (vervang CLIENT_ID door jouw ID):
   https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=activity:read_all

   Na het autoriseren word je doorgestuurd naar een URL als:
   http://localhost/exchange_token?state=&code=XXXXX&scope=...
   Kopieer de code-waarde (XXXXX).

3. Wissel de code in voor een refresh token (vervang CLIENT_ID, CLIENT_SECRET, CODE):
   curl -X POST https://www.strava.com/oauth/token \
     -F client_id=CLIENT_ID \
     -F client_secret=CLIENT_SECRET \
     -F code=CODE \
     -F grant_type=authorization_code

   Noteer refresh_token uit het antwoord.

4. Voeg toe als GitHub Secrets:
   Repo → Settings → Secrets and variables → Actions
   - STRAVA_CLIENT_ID    = jouw Client ID (getal)
   - STRAVA_CLIENT_SECRET = jouw Client Secret
   - STRAVA_REFRESH_TOKEN = refresh_token uit stap 3

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  STRAVA_CLIENT_ID      - Strava app Client ID
  STRAVA_CLIENT_SECRET  - Strava app Client Secret
  STRAVA_REFRESH_TOKEN  - OAuth2 refresh token (langlevend)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)


def fetch_strava_data(days: int = 14) -> dict | None:
    """
    Haal Strava-activiteiten op voor de afgelopen `days` dagen.

    Retourneert een dict met:
        activities_by_date: {
            "YYYY-MM-DD": [
                {
                    "date": str,
                    "activity_id": int,
                    "name": str,
                    "type": str,
                    "duration_min": int,
                    "elapsed_min": int | None,
                    "avg_hr": float | None,
                    "max_hr": float | None,
                    "calories": float | None,
                    "distance_m": float | None,
                    "suffer_score": float | None,
                    "perceived_exertion": float | None,
                }
            ]
        }
        hr_zones: lijst van {"min": int, "max": int} (Z1–Z5, -1 = onbeperkt)
        fetched_at: ISO8601 timestamp

    Retourneert None als de secrets niet geconfigureerd zijn of bij een fout.
    """
    client_id = os.environ.get("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        log.info(
            "Strava: geen credentials geconfigureerd "
            "(STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REFRESH_TOKEN)"
        )
        return None

    # ── 1. Ververs access token ────────────────────────────────────────────
    try:
        resp = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        token_data = resp.json()
        access_token = token_data["access_token"]
        log.info("Strava: access token vernieuwd")
    except Exception as exc:
        log.warning("Strava: token refresh mislukt: %s", exc)
        return None

    # ── 2. Haal activiteiten op ────────────────────────────────────────────
    after_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            params={"after": after_ts, "per_page": 100},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        activities = resp.json()
        log.info("Strava: %d activiteiten opgehaald (laatste %d dagen)", len(activities), days)
    except Exception as exc:
        log.warning("Strava: activiteiten ophalen mislukt: %s", exc)
        return None

    # ── 3. Verwerk naar activities_by_date ────────────────────────────────
    activities_by_date: dict[str, list[dict]] = {}
    for act in activities:
        date_str = act.get("start_date_local", "")[:10]
        if not date_str:
            continue

        elapsed_raw = act.get("elapsed_time")
        elapsed_min = round(elapsed_raw / 60) if elapsed_raw else None
        duration_min = round((act.get("moving_time") or 0) / 60)
        start_time = act.get("start_date_local", "")[11:16] or None
        entry = {
            "date": date_str,
            "activity_id": act.get("id"),
            "name": act.get("name", ""),
            "type": act.get("sport_type") or act.get("type", ""),
            "start_time": start_time,
            "duration_min": duration_min,
            "elapsed_min": elapsed_min if elapsed_min and elapsed_min != duration_min else None,
            "avg_hr": act.get("average_heartrate"),
            "max_hr": act.get("max_heartrate"),
            "calories": act.get("calories"),
            "distance_m": act.get("distance") or None,
            "suffer_score": act.get("suffer_score"),
            "perceived_exertion": act.get("perceived_exertion"),
        }
        activities_by_date.setdefault(date_str, []).append(entry)

    # ── 4. Haal hartslagzones op ──────────────────────────────────────────
    hr_zones: list[dict] = []
    try:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/zones",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        hr_zones = resp.json().get("heart_rate", {}).get("zones", [])
        log.info("Strava: %d hartslagzones opgehaald", len(hr_zones))
    except Exception as exc:
        log.warning("Strava: hartslagzones ophalen mislukt: %s", exc)

    return {
        "activities_by_date": activities_by_date,
        "hr_zones": hr_zones,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
