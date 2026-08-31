#!/usr/bin/env python3
"""
Huppa pattern-slot boekingsprobe

De admin-webapp identificeert een les die nog geen occurrence is als
{schedulePatternSlotId, startsAt} in plaats van {occurrenceId}. Dit script
zoekt uit welk boekings-endpoint diezelfde vorm accepteert, zodat
autosignup.py zo'n les alsnog kan boeken.

Het probeert kandidaten op volgorde en stopt bij het eerste succes. Het doelwit
is bewust een les uit Ralphs vaste schema (Workout of the day op ma 20:00,
do 20:00 of zo 09:00), zodat een geslaagde boeking gewenst is en niet
teruggedraaid hoeft te worden. Foutieve pogingen leveren alleen een
foutmelding op; die melding verraadt meestal de juiste veldnamen.

Usage:
    python3 huppa_probe_book_pattern.py            # alleen kijken, niets boeken
    python3 huppa_probe_book_pattern.py --book     # boekingspogingen doen
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

# (weekdag, tijd) uit het vaste schema van autosignup.py — woensdag laten we
# weg omdat die slot handmatig is uitgesloten.
TARGET_SLOTS = {(0, "20:00"), (3, "20:00"), (6, "09:00")}
TARGET_NAME = "Workout of the day"

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


def occurrences_on(session: requests.Session, date_str: str) -> list:
    resp = session.get(f"{HUPPA_API_BASE}/users/me/occurrences",
                       params={"date": date_str}, timeout=20)
    if not resp.ok:
        return []
    payload = resp.json()
    return payload if isinstance(payload, list) else payload.get("data", [])


def local_time(evt: dict) -> datetime:
    return datetime.fromisoformat(evt["startsAt"].replace("Z", "+00:00")).astimezone(AMS)


def find_target(session: requests.Session):
    """Eerste pattern slot uit het vaste schema (dus een les die we willen)."""
    today = datetime.now(AMS).date()
    for offset in range(1, 15):
        date_str = (today + timedelta(days=offset)).isoformat()
        for evt in occurrences_on(session, date_str):
            if evt.get("id") is not None or not evt.get("schedulePatternSlotId"):
                continue
            if evt.get("name") != TARGET_NAME:
                continue
            start = local_time(evt)
            if (start.weekday(), start.strftime("%H:%M")) in TARGET_SLOTS:
                return date_str, evt
    return None, None


def main():
    do_book = "--book" in sys.argv
    email = os.environ["HUPPA_EMAIL"]
    password = os.environ["HUPPA_PASSWORD"]
    subdomain = os.environ["HUPPA_SUBDOMAIN"]

    session = requests.Session()
    if not login(session, email, password, subdomain):
        sys.exit(1)

    # Eerst: welke boekingen staan er volgens Huppa écht op naam?
    resp = session.get(f"{HUPPA_API_BASE}/users/me/bookings-and-waitlists",
                       params={"filter": "upcoming"}, timeout=20)
    log.info("=== Huidige boekingen (bookings-and-waitlists) -> HTTP %s ===", resp.status_code)
    if resp.ok:
        for group in resp.json().get("data", []):
            for occ in group.get("occurrences", []):
                booking = occ.get("booking") or {}
                starts = occ.get("startsAt", "")
                when = (datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(AMS)
                        .strftime("%a %Y-%m-%d %H:%M") if starts else "?")
                log.info("    %s  %-22s id=%s cancelledAt=%s",
                         when, (occ.get("name") or "")[:22], occ.get("id"),
                         booking.get("cancelledAt"))

    date_str, evt = find_target(session)
    if not evt:
        log.info("Geen pattern slot uit het vaste schema gevonden.")
        return

    org_id = (evt.get("category") or {}).get("organizationId")
    slot_id = evt["schedulePatternSlotId"]
    starts_at = evt["startsAt"]
    log.info("Doelwit: %s om %s (%s), slotId=%s, vrij=%s",
             evt.get("name"), local_time(evt).strftime("%a %Y-%m-%d %H:%M"),
             starts_at, slot_id, evt.get("availableSlots"))

    # IJkpunt: wat geeft een GET op een boekingspad dat zéker bestaat?
    real_id = next((e.get("id") for e in occurrences_on(session, date_str) if e.get("id")), None)
    if real_id:
        resp = session.get(
            f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/{real_id}/booking", timeout=20)
        log.info("IJkpunt GET op bestaand boekingspad -> %s (dus 404 zegt niets over bestaan)",
                 resp.status_code)

    candidates = [
        (f"/organizations/{org_id}/occurrences/booking",
         {"schedulePatternSlotId": slot_id, "startsAt": starts_at}),
        (f"/organizations/{org_id}/schedule-pattern-slots/{slot_id}/booking",
         {"startsAt": starts_at}),
        (f"/organizations/{org_id}/occurrences/{slot_id}/booking",
         {"startsAt": starts_at, "schedulePatternSlotId": slot_id}),
        (f"/organizations/{org_id}/occurrences/{slot_id}/booking",
         {"startsAt": starts_at}),
        ("/users/me/occurrences/booking",
         {"schedulePatternSlotId": slot_id, "startsAt": starts_at}),
    ]

    if not do_book:
        log.info("Dry run — deze kandidaten zouden geprobeerd worden:")
        for path, body in candidates:
            log.info("    POST %s  %s", path, json.dumps(body))
        return

    for path, body in candidates:
        try:
            resp = session.post(f"{HUPPA_API_BASE}{path}", json=body, timeout=20)
        except Exception as exc:
            log.info("POST %s -> fout: %s", path, exc)
            continue
        log.info("POST %s %s -> %s %s", path, json.dumps(body), resp.status_code,
                 resp.text[:300])
        if resp.status_code in (200, 201, 204):
            log.info("GELUKT met %s", path)
            break

    # Wat is de stand na afloop?
    for e in occurrences_on(session, date_str):
        if e.get("schedulePatternSlotId") == slot_id or e.get("startsAt") == starts_at:
            log.info("Na afloop: %s id=%s status=%s vrij=%s",
                     e.get("name"), e.get("id"),
                     (e.get("occurrenceUser") or {}).get("status"), e.get("availableSlots"))


if __name__ == "__main__":
    main()
