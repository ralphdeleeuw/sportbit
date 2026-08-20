#!/usr/bin/env python3
"""
Huppa API Discovery Script

Dumpt de volledige raw API-responses voor een geboekte les en probeert
potentiële deelnemers-endpoints. Resultaten gaan naar de gist als
'huppa_discovery.json' zodat we kunnen analyseren wat beschikbaar is.

De Huppa-app toont sinds een update ook een 'Participants'-lijst (avatars +
namen als "Erik H, Ralph D, Stef K") in het lesdetail. Dit script probeert
breed te achterhalen via welk endpoint/veld die data binnenkomt, en scant
alle 200-responses op velden die naar deelnemers ruiken.

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

# Sleutelwoorden die duiden op deelnemers-informatie in een response.
PARTICIPANT_HINTS = (
    "participant", "attendee", "attendance", "roster", "member",
    "occurrenceuser", "occurrenceusers", "users", "user", "booking",
    "bookings", "waitlist", "avatar", "profilepicture", "firstname",
    "lastname", "initial",
)

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


def find_participant_fields(body, path: str = "", out: list = None, depth: int = 0) -> list:
    """Loop recursief door een response en verzamel paden die op deelnemers lijken."""
    if out is None:
        out = []
    if depth > 6:
        return out
    if isinstance(body, dict):
        for key, value in body.items():
            child_path = f"{path}.{key}" if path else key
            if any(hint in key.lower() for hint in PARTICIPANT_HINTS):
                preview = str(value)
                out.append({
                    "path": child_path,
                    "type": type(value).__name__,
                    "count": len(value) if isinstance(value, (list, dict)) else None,
                    "preview": preview[:300],
                })
            find_participant_fields(value, child_path, out, depth + 1)
    elif isinstance(body, list):
        # Alleen het eerste element uitdiepen; de rest heeft dezelfde vorm.
        if body:
            find_participant_fields(body[0], f"{path}[0]", out, depth + 1)
    return out


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


def build_probe_endpoints(org_id, occ_id, today) -> list[tuple[str, dict]]:
    """Bouw een brede lijst kandidaat-endpoints voor deelnemers en lesdetail."""
    date_str = today.isoformat()
    probes: list[tuple[str, dict]] = []

    # Lesdetail — de app toont adres, trainer en 'About the class' in één sheet,
    # dus er bestaat vrijwel zeker een detail-endpoint. Ook met include-varianten.
    detail_paths = [
        f"/organizations/{org_id}/occurrences/{occ_id}",
        f"/occurrences/{occ_id}",
        f"/users/me/occurrences/{occ_id}",
    ]
    include_variants = [
        {},
        {"include": "participants"},
        {"include": "users"},
        {"include": "occurrenceUsers"},
        {"include": "bookings"},
        {"with": "participants"},
        {"expand": "participants"},
    ]
    for path in detail_paths:
        for params in include_variants:
            probes.append((path, params))

    # Expliciete deelnemers-endpoints, org-scoped en zonder org.
    sub_resources = [
        "participants", "users", "occurrence-users", "occurrenceUsers",
        "bookings", "booking", "attendees", "attendance", "roster",
        "waitlist", "members", "signups",
    ]
    for sub in sub_resources:
        probes.append((f"/organizations/{org_id}/occurrences/{occ_id}/{sub}", {}))
        probes.append((f"/occurrences/{occ_id}/{sub}", {}))

    # Lijst-endpoints die mogelijk deelnemers meesturen.
    probes += [
        ("/users/me/occurrences", {"date": date_str, "include": "participants"}),
        ("/users/me/occurrences", {"date": date_str, "withParticipants": "true"}),
        ("/users/me/bookings-and-waitlists", {"filter": "upcoming"}),
        ("/users/me/bookings-and-waitlists", {}),
        (f"/organizations/{org_id}/occurrences", {"date": date_str}),
        (f"/organizations/{org_id}/occurrences/{occ_id}/participants", {"limit": "50"}),
        ("/users/me", {}),
        (f"/organizations/{org_id}/settings", {}),
        (f"/organizations/{org_id}", {}),
    ]
    return probes


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
    results = {
        "generated_at": datetime.now().isoformat(),
        "raw_occurrences": {},
        "endpoints": {},
        "participant_findings": {},
    }

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

    # Val terug op een willekeurige les als er niets geboekt staat: deelnemers
    # zijn mogelijk ook zichtbaar zonder eigen boeking.
    fallback_used = False
    if booked_event is None:
        for date_str, items in results["raw_occurrences"].items():
            if items:
                booked_event = items[0]
                fallback_used = True
                log.warning("Geen geboekte les; val terug op %s op %s",
                            booked_event.get("name"), date_str)
                break

    # Stap 2: Probeer deelnemers-gerelateerde endpoints voor de gekozen les
    if booked_event:
        occ_id = booked_event.get("id")
        org_id = (booked_event.get("category") or {}).get("organizationId")
        results["probed_occurrence"] = {
            "id": occ_id,
            "organization_id": org_id,
            "name": booked_event.get("name"),
            "starts_at": booked_event.get("startsAt"),
            "fallback_used": fallback_used,
        }
        log.info("Probing endpoints voor occurrence %s, org %s", occ_id, org_id)

        for path, params in build_probe_endpoints(org_id, occ_id, today):
            url = f"{HUPPA_API_BASE}{path}"
            key = f"{path}" + (f"?{json.dumps(params, sort_keys=True)}" if params else "")
            if key in results["endpoints"]:
                continue
            log.info("Probeer: GET %s %s", path, params or "")
            result = try_endpoint(session, url, params or None)
            results["endpoints"][key] = result
            if result["status"] == 200:
                findings = find_participant_fields(result["body"])
                if findings:
                    results["participant_findings"][key] = findings
    else:
        log.warning("Geen lessen gevonden in de komende 8 dagen.")
        results["note"] = "Geen lessen gevonden — probe endpoints overgeslagen."

    # Stap 3: Print compacte samenvatting naar stdout (leesbaar in Actions logs)
    print("\n" + "=" * 60)
    print("HUPPA DISCOVERY SAMENVATTING")
    print("=" * 60)

    print("\n[RAW OCCURRENCE VELDEN - geprobede les]")
    if booked_event:
        for k, v in booked_event.items():
            preview = str(v)[:200]
            print(f"  {k}: {preview}")

    print("\n[ENDPOINT RESULTATEN]")
    for key, result in results["endpoints"].items():
        status = result["status"]
        body = result["body"]
        body_preview = str(body)[:300].replace("\n", " ")
        marker = "OK " if status == 200 else "-- "
        print(f"  {marker}[{status}] {key}")
        if status == 200:
            print(f"      -> {body_preview}")

    print("\n[MOGELIJKE DEELNEMERS-VELDEN]")
    if results["participant_findings"]:
        for key, findings in results["participant_findings"].items():
            print(f"  {key}")
            for f in findings:
                print(f"      {f['path']} ({f['type']}, n={f['count']}): {f['preview'][:200]}")
    else:
        print("  (geen velden gevonden die op deelnemers lijken)")
    print("=" * 60 + "\n")

    # Stap 4: Opslaan in gist
    if gist_id and github_token:
        save_to_gist(gist_id, github_token, results)
    else:
        print(json.dumps(results, indent=2, default=str))

    log.info("Klaar. Bekijk 'huppa_discovery.json' in de gist.")


if __name__ == "__main__":
    main()
