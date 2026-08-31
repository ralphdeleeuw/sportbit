#!/usr/bin/env python3
"""
Huppa pattern-slot probe

Lessen die nog niemand geboekt heeft komen uit de API als `"type": "pattern_slot"`
met `"id": null` en een `schedulePatternSlotId`: Huppa maakt de echte occurrence
pas aan zodra er iets mee gebeurt. autosignup.py kan zo'n les daarom niet boeken.

Dit script zoekt uit hóé de Huppa-app zo'n pattern slot boekt:
  1. het haalt de JS-bundle van de webapp op en zoekt daarin naar de
     endpoints/velden rond 'pattern slot' en 'booking';
  2. het doet read-only GET-verzoeken op kandidaat-endpoints — een 405
     (Method Not Allowed) verraadt een pad dat wél bestaat maar POST vereist.

Er wordt niets geboekt of gewijzigd. Het subdomein wordt niet geprint.

Usage:
    python3 huppa_probe_pattern_slot.py
"""

import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import logging

import requests

HUPPA_API_BASE = "https://api.huppa.app"
AMS = ZoneInfo("Europe/Amsterdam")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("probe")


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
        log.info("Login geslaagd.")
        return True
    log.error("Login mislukt: %s", resp.status_code)
    return False


def find_pattern_slot(session: requests.Session):
    """Zoek de eerste les die als pattern_slot binnenkomt."""
    today = datetime.now(AMS).date()
    for offset in range(1, 11):
        date_str = (today + timedelta(days=offset)).isoformat()
        resp = session.get(f"{HUPPA_API_BASE}/users/me/occurrences",
                           params={"date": date_str}, timeout=20)
        if not resp.ok:
            continue
        payload = resp.json()
        events = payload if isinstance(payload, list) else payload.get("data", [])
        for evt in events:
            if evt.get("id") is None and evt.get("schedulePatternSlotId"):
                return date_str, evt
    return None, None


def scan_frontend(subdomain: str) -> None:
    """Download de JS-bundles van de webapp en zoek naar pattern-slot endpoints."""
    base = f"https://{subdomain}.huppa.app"
    try:
        index = requests.get(base, timeout=20)
    except Exception as exc:
        log.warning("Webapp niet op te halen: %s", exc)
        return
    if not index.ok:
        log.warning("Webapp gaf HTTP %s", index.status_code)
        return

    scripts = re.findall(r'src="([^"]+\.js)"', index.text)
    log.info("Gevonden JS-bundles: %d", len(scripts))
    seen: set[str] = set()
    for src in scripts[:10]:
        url = src if src.startswith("http") else f"{base}/{src.lstrip('/')}"
        try:
            body = requests.get(url, timeout=60).text
        except Exception as exc:
            log.warning("Bundle ophalen mislukt: %s", exc)
            continue
        log.info("Bundle %s: %d tekens", url.split("/")[-1], len(body))

        # Endpoint-achtige strings rond pattern slots en boekingen.
        patterns = [
            r"[`\"'][^`\"']{0,80}(?:pattern[-_]?slot|patternSlot)[^`\"']{0,80}[`\"']",
            r"[`\"'][^`\"']{0,60}occurrences?/[^`\"']{0,60}booking[^`\"']{0,40}[`\"']",
            r"[`\"']/?(?:organizations|users)/[^`\"']{0,90}[`\"']",
        ]
        for pat in patterns:
            for match in re.findall(pat, body):
                text = match if isinstance(match, str) else match[0]
                if len(text) > 200 or text in seen:
                    continue
                if not any(k in text.lower() for k in ("pattern", "booking", "occurrence")):
                    continue
                seen.add(text)
    for text in sorted(seen):
        log.info("    bundle-string: %s", text)


def main():
    email = os.environ["HUPPA_EMAIL"]
    password = os.environ["HUPPA_PASSWORD"]
    subdomain = os.environ["HUPPA_SUBDOMAIN"]

    session = requests.Session()
    if not login(session, email, password, subdomain):
        sys.exit(1)

    date_str, evt = find_pattern_slot(session)
    if not evt:
        log.info("Geen pattern_slot gevonden — alles is al een echte occurrence.")
        return

    org_id = (evt.get("category") or {}).get("organizationId")
    slot_id = evt.get("schedulePatternSlotId")
    log.info("Pattern slot: %s %s (%s), slotId=%s", date_str, evt.get("name"),
             evt.get("startsAt"), slot_id)

    log.info("=== 1. JS-bundle van de webapp ===")
    scan_frontend(subdomain)

    log.info("=== 2. Kandidaat-endpoints (read-only GET; 405 = pad bestaat, POST nodig) ===")
    candidates = [
        f"/organizations/{org_id}/schedule-pattern-slots/{slot_id}/booking",
        f"/organizations/{org_id}/schedule-pattern-slots/{slot_id}/occurrences",
        f"/organizations/{org_id}/schedule-pattern-slots/{slot_id}",
        f"/organizations/{org_id}/schedule-patterns/{slot_id}/booking",
        f"/organizations/{org_id}/pattern-slots/{slot_id}/booking",
        f"/organizations/{org_id}/occurrences/booking",
        f"/organizations/{org_id}/bookings",
        "/users/me/bookings",
        "/users/me/occurrences/booking",
    ]
    for path in candidates:
        try:
            resp = session.get(f"{HUPPA_API_BASE}{path}", timeout=20)
        except Exception as exc:
            log.info("GET %s -> fout: %s", path, exc)
            continue
        note = ""
        if resp.status_code == 405:
            note = "  <-- pad bestaat, andere methode nodig"
        log.info("GET %s -> %s%s", path, resp.status_code, note)
        if resp.status_code == 200:
            log.info("      body: %s", resp.text[:400])


if __name__ == "__main__":
    main()
