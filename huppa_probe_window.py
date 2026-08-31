#!/usr/bin/env python3
"""
Huppa boekingsvenster-probe

Zoekt uit waarom lessen soms zonder occurrence-id binnenkomen (waardoor
autosignup.py niet kan boeken). Print per dag in de komende 10 dagen welke
lessen wél en niet een id hebben, welke velden de API meestuurt, en of het
id eventueel via een ander endpoint of onder een andere naam beschikbaar is.

Geen persoonsgegevens in de output: deelnemers en occurrenceUser worden
weggelaten, alleen aantallen.

Usage:
    python3 huppa_probe_window.py
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

# Velden die persoonsgegevens bevatten — die printen we nooit uit.
REDACT_KEYS = {"occurrenceParticipants", "occurrenceUser", "participants", "users"}

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
    log.error("Login mislukt: %s %s", resp.status_code, resp.text[:300])
    return False


def redact(evt: dict) -> dict:
    """Kopie van een event zonder persoonsgegevens."""
    out = {}
    for key, value in evt.items():
        if key in REDACT_KEYS:
            out[key] = f"<{len(value) if isinstance(value, (list, dict)) else '?'} items, weggelaten>"
        else:
            out[key] = value
    return out


def items_of(payload) -> list:
    if isinstance(payload, list):
        return payload
    return payload.get("data", payload.get("occurrences", []))


def main():
    email = os.environ["HUPPA_EMAIL"]
    password = os.environ["HUPPA_PASSWORD"]
    subdomain = os.environ["HUPPA_SUBDOMAIN"]

    session = requests.Session()
    if not login(session, email, password, subdomain):
        sys.exit(1)

    now = datetime.now(AMS)
    today = now.date()
    log.info("Nu: %s (Amsterdam)", now.strftime("%Y-%m-%d %H:%M:%S %Z"))

    org_id = None
    first_missing = None  # (date_str, event) van de eerste les zonder id

    # ── 1. Per dag: welke lessen hebben een id? ────────────────────────
    for offset in range(0, 11):
        date_str = (today + timedelta(days=offset)).isoformat()
        resp = session.get(f"{HUPPA_API_BASE}/users/me/occurrences",
                           params={"date": date_str}, timeout=20)
        if not resp.ok:
            log.warning("dag +%d (%s): HTTP %s", offset, date_str, resp.status_code)
            continue
        events = items_of(resp.json())
        log.info("--- dag +%d (%s): %d lessen ---", offset, date_str, len(events))
        for evt in events:
            eid = evt.get("id")
            org_id = org_id or (evt.get("category") or {}).get("organizationId")
            starts = (evt.get("startsAt") or "")[:16]
            log.info(
                "    %-16s %-22s id=%-38s eligible=%-5s vrij=%s",
                starts, (evt.get("name") or "")[:22], str(eid),
                evt.get("isEligibleToBook"), evt.get("availableSlots"),
            )
            if eid is None and first_missing is None:
                first_missing = (date_str, evt)

    # ── 2. Welke velden stuurt de API mee bij een les zónder id? ───────
    if first_missing is None:
        log.info("Geen enkele les zonder id gevonden — alles binnen het venster is boekbaar.")
        return

    date_str, evt = first_missing
    log.info("=== Eerste les zonder id: %s %s ===", date_str, evt.get("name"))
    log.info("Alle velden:\n%s", json.dumps(redact(evt), indent=2, default=str, sort_keys=True))
    id_like = {k: v for k, v in evt.items() if "id" in k.lower()}
    log.info("Velden met 'id' in de naam: %s", json.dumps(id_like, default=str))

    # ── 3. Staat het id wél in een ander endpoint? ─────────────────────
    if org_id:
        for path, params in [
            (f"/organizations/{org_id}/occurrences", {"date": date_str}),
            (f"/organizations/{org_id}/schedule", {"date": date_str}),
            ("/users/me/occurrences", {"date": date_str, "include": "id"}),
        ]:
            try:
                resp = session.get(f"{HUPPA_API_BASE}{path}", params=params, timeout=20)
            except Exception as exc:
                log.warning("%s %s -> fout: %s", path, params, exc)
                continue
            if not resp.ok:
                log.info("%s %s -> HTTP %s", path, params, resp.status_code)
                continue
            try:
                events = items_of(resp.json())
            except Exception:
                log.info("%s -> HTTP 200, geen JSON-lijst", path)
                continue
            ids = [(e.get("startsAt", "")[:16], e.get("id")) for e in events]
            log.info("%s %s -> HTTP 200, %d lessen: %s", path, params, len(events), ids)

        # ── 4. Staat het boekingsvenster ergens in de org-instellingen? ─
        for path in [f"/organizations/{org_id}", f"/organizations/{org_id}/settings"]:
            resp = session.get(f"{HUPPA_API_BASE}{path}", timeout=20)
            if not resp.ok:
                log.info("%s -> HTTP %s", path, resp.status_code)
                continue
            try:
                body = resp.json()
            except Exception:
                continue
            body = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(body, dict):
                hits = {
                    k: v for k, v in body.items()
                    if any(h in k.lower() for h in ("book", "window", "advance", "open", "days", "horizon"))
                }
                log.info("%s -> venster-achtige velden: %s", path, json.dumps(hits, default=str)[:1500])


if __name__ == "__main__":
    main()
