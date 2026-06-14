#!/usr/bin/env python3
"""
Huppa API Discovery Script

Dumpt de volledige raw API-responses voor een geboekte les en probeert
potentiële deelnemers-endpoints. Resultaten gaan naar de gist als
'huppa_discovery.json' zodat we kunnen analyseren wat beschikbaar is.

Usage:
    python3 huppa_discover.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

HUPPA_API_BASE = "https://api.huppa.app"
AMS = ZoneInfo("Europe/Amsterdam")
GIST_FILENAME = "huppa_discovery.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("discover")


def login(session: requests.Session, email: str, password: str, subdomain: str) -> bool:
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Subdomain": subdomain,
        "Origin": f"https://{subdomain}.huppa.app",
        "Referer": f"https://{subdomain}.huppa.app/",
    })
    resp = session.post(f"{HUPPA_API_BASE}/auth/login",
                        json={"email": email, "password": password}, timeout=20)
    if resp.status_code == 200:
        log.info("Login geslaagd als %s", email)
        return True
    log.error("Login mislukt: %s %s", resp.status_code, resp.text[:300])
    return False


def try_endpoint(session: requests.Session, url: str, params: dict = None) -> dict:
    """Probeer een GET-endpoint en geef status + response terug."""
    try:
        resp = session.get(url, params=params, timeout=20)
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:2000]
        return {"status": resp.status_code, "body": body}
    except Exception as e:
        return {"status": "error", "body": str(e)}


def save_to_gist(gist_id: str, token: str, data: dict) -> None:
    content = json.dumps(data, indent=2, default=str)
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers=headers,
        json={"files": {GIST_FILENAME: {"content": content}}},
        timeout=15,
    )
    if resp.ok:
        log.info("Resultaten opgeslagen in gist als '%s'.", GIST_FILENAME)
    else:
        log.error("Gist opslaan mislukt: %s", resp.status_code)
        print(json.dumps(data, indent=2, default=str))


def main():
    email = os.environ["HUPPA_EMAIL"]
    password = os.environ["HUPPA_PASSWORD"]
    subdomain = os.environ["HUPPA_SUBDOMAIN"]
    gist_id = os.environ.get("GIST_ID")
    github_token = os.environ.get("GITHUB_TOKEN")

    session = requests.Session()
    if not login(session, email, password, subdomain):
        sys.exit(1)

    today = datetime.now(AMS).date()
    results = {"generated_at": datetime.now().isoformat(), "raw_occurrences": {}, "endpoints": {}}

    # Stap 1: Dump volledige RAW occurrence responses voor komende 7 dagen
    booked_event = None
    for offset in range(0, 8):
        date = today + timedelta(days=offset)
        date_str = date.isoformat()
        resp = session.get(f"{HUPPA_API_BASE}/users/me/occurrences",
                           params={"date": date_str}, timeout=20)
        if not resp.ok:
            continue
        raw = resp.json()
        if isinstance(raw, list):
            items = raw
        else:
            items = raw.get("data", raw.get("occurrences", []))

        results["raw_occurrences"][date_str] = items  # volledig raw, geen normalisatie

        for evt in items:
            status = (evt.get("occurrenceUser") or {}).get("status")
            if status == "confirmed" and booked_event is None:
                booked_event = evt
                log.info("Eerste geboekte les gevonden: %s op %s", evt.get("name"), date_str)

    # Stap 2: Probeer deelnemers-gerelateerde endpoints voor de geboekte les
    if booked_event:
        occ_id = booked_event.get("id")
        org_id = (booked_event.get("category") or {}).get("organizationId")
        log.info("Probing endpoints voor occurrence %s, org %s", occ_id, org_id)

        probe_endpoints = [
            # Enkelvoudige occurrence (mogelijk met deelnemers)
            (f"/organizations/{org_id}/occurrences/{occ_id}", {}),
            # Deelnemers-varianten
            (f"/organizations/{org_id}/occurrences/{occ_id}/users", {}),
            (f"/organizations/{org_id}/occurrences/{occ_id}/bookings", {}),
            (f"/organizations/{org_id}/occurrences/{occ_id}/participants", {}),
            (f"/organizations/{org_id}/occurrences/{occ_id}/booking", {}),
            # User-centric endpoints met filter
            ("/users/me/bookings-and-waitlists", {"filter": "upcoming"}),
            ("/users/me/bookings-and-waitlists", {}),
            # Andere mogelijke paden
            (f"/occurrences/{occ_id}/users", {}),
            (f"/occurrences/{occ_id}/bookings", {}),
            (f"/occurrences/{occ_id}", {}),
            # Public class roster
            (f"/organizations/{org_id}/occurrences", {"date": today.isoformat()}),
        ]

        for path, params in probe_endpoints:
            url = f"{HUPPA_API_BASE}{path}"
            key = f"{path}" + (f"?{json.dumps(params)}" if params else "")
            log.info("Probeer: GET %s %s", path, params or "")
            results["endpoints"][key] = try_endpoint(session, url, params or None)

    else:
        log.warning("Geen geboekte les gevonden in de komende 8 dagen.")
        results["note"] = "Geen geboekte les gevonden — probe endpoints overgeslagen."

    # Stap 3: Opslaan
    if gist_id and github_token:
        save_to_gist(gist_id, github_token, results)
    else:
        print(json.dumps(results, indent=2, default=str))

    log.info("Klaar. Bekijk 'huppa_discovery.json' in de gist.")


if __name__ == "__main__":
    main()
