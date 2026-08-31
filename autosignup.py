#!/usr/bin/env python3
"""
Huppa Auto Sign-Up for CrossFit Hilversum

Automatically signs up for WOD classes on a weekly schedule.
Run via cron or manually. Dry-run mode enabled by default.

Usage:
    python3 autosignup.py                  # dry-run (default)
    python3 autosignup.py --live           # actually sign up
    python3 autosignup.py --days 8         # look ahead 8 days (default: 8)
    python3 autosignup.py --live --sync-calendar  # sign up and sync to Google Calendar

State management:
    A GitHub Gist is used to persist state between runs (signed up / manually cancelled events).
    Set GIST_ID and GITHUB_TOKEN environment variables.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import notify
from gist_utils import file_content as gist_file_content
from google_calendar_sync import GoogleCalendarSync

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

HUPPA_API_BASE = "https://api.huppa.app"

# Weekly schedule: list of (weekday_number, time) pairs
# Weekday numbers: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
SCHEDULE = [
    (0, "20:00"),  # Monday 20:00
    (2, "08:00"),  # Wednesday 08:00
    (3, "20:00"),  # Thursday 20:00
    (6, "09:00"),  # Sunday 09:00
]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Lessen die nooit automatisch geboekt worden
EXCLUDED_CLASS_NAMES = {"Open Gym"}

# Huppa occurrenceUser-statussen die een échte annulering aangeven. Alleen bij
# deze statussen (of een volledig ontbrekende occurrenceUser) beschouwen we een
# inschrijving als opgezegd. Een onbekende status laten we voor de zekerheid
# als "nog ingeschreven" gelden, zodat we niemand ten onrechte uitschrijven.
CANCELLED_USER_STATUSES = {"cancelled", "canceled", "declined", "removed", "rejected"}

# Familieleden waarvan inschrijvingen zichtbaar moeten zijn in de PWA
FAMILY_MEMBERS = [
    {"name": "Laura", "email_env": "HUPPA_EMAIL_LAURA", "password_env": "HUPPA_PASSWORD_LAURA"},
    {"name": "Eva",   "email_env": "HUPPA_EMAIL_EVA",   "password_env": "HUPPA_PASSWORD_EVA"},
]

# Gist filename for state storage
GIST_FILENAME = "sportbit_state.json"

# Amsterdam timezone
AMS = ZoneInfo("Europe/Amsterdam")

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("huppa")


# ──────────────────────────────────────────────────────────────
# Gist State Manager
# ──────────────────────────────────────────────────────────────

class GistStateManager:
    """
    Persists signup state to a GitHub Gist between runs.

    State structure:
    {
        "signed_up": {
            "<occurrence_id>": {
                "date": "2026-03-09",
                "time": "20:00",
                "title": "CrossFit WOD",
                "signed_up_at": "2026-03-02T00:01:00"
            }
        },
        "cancelled": {
            "<occurrence_id>": {
                "date": "2026-03-09",
                "time": "20:00",
                "title": "CrossFit WOD",
                "cancelled_at": "2026-03-02T12:00:00"
            }
        }
    }
    """

    def __init__(self, gist_id: str, github_token: str):
        self.gist_id = gist_id
        self.token = github_token
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github+json",
        }
        self.state = {"signed_up": {}, "cancelled": {}}
        self._load()

    def _load(self):
        """Load state from Gist."""
        try:
            resp = requests.get(
                f"https://api.github.com/gists/{self.gist_id}",
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            files = resp.json().get("files", {})
            if GIST_FILENAME in files:
                # file_content valt terug op raw_url als GitHub het bestand
                # afkapt (>1 MB); anders zouden we state met niets overschrijven.
                content = gist_file_content(files[GIST_FILENAME], self.token) or "{}"
                self.state = json.loads(content)
                self.state.setdefault("signed_up", {})
                self.state.setdefault("cancelled", {})
                self.state.setdefault("exclusions", {})
                # Verwijder SportBit entries (numerieke IDs) van na 1 juni 2026 — historie bewaren
                HUPPA_MIGRATION_DATE = "2026-06-01"
                self.state["signed_up"] = {
                    k: v for k, v in self.state["signed_up"].items()
                    if not k.isdigit() or v.get("date", "") < HUPPA_MIGRATION_DATE
                }
                self.state["cancelled"] = {
                    k: v for k, v in self.state["cancelled"].items()
                    if not k.isdigit() or v.get("date", "") < HUPPA_MIGRATION_DATE
                }
                # Prune stale exclusions and family bookings (past dates)
                today_str = datetime.now(AMS).date().isoformat()
                self.state["exclusions"] = {
                    k: v for k, v in self.state["exclusions"].items()
                    if k[:10] >= today_str
                }
                self.state.setdefault("family_bookings", {})
                self.state["family_bookings"] = {
                    k: v for k, v in self.state["family_bookings"].items()
                    if k[:10] >= today_str
                }
                log.info(
                    "Loaded state: %d signed up, %d cancelled, %d exclusions.",
                    len(self.state["signed_up"]),
                    len(self.state["cancelled"]),
                    len(self.state["exclusions"]),
                )
            else:
                log.info("No existing state found in Gist; starting fresh.")
        except Exception as e:
            log.error("Failed to load state from Gist: %s", e)

    def _save(self):
        """Save state to Gist."""
        try:
            resp = requests.patch(
                f"https://api.github.com/gists/{self.gist_id}",
                headers=self.headers,
                json={"files": {GIST_FILENAME: {"content": json.dumps(self.state, indent=2)}}},
                timeout=10,
            )
            resp.raise_for_status()
            log.info("State saved to Gist.")
        except Exception as e:
            log.error("Failed to save state to Gist: %s", e)

    def is_excluded(self, date: str, time: str) -> bool:
        return f"{date}_{time}" in self.state.get("exclusions", {})

    def is_cancelled(self, occurrence_id: str) -> bool:
        return str(occurrence_id) in self.state["cancelled"]

    def is_signed_up_by_script(self, occurrence_id: str) -> bool:
        return str(occurrence_id) in self.state["signed_up"]

    def mark_signed_up(self, occurrence_id: str, date: str, time: str, title: str):
        self.state["signed_up"][str(occurrence_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "signed_up_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def mark_cancelled(self, occurrence_id: str, date: str, time: str, title: str):
        self.state["cancelled"][str(occurrence_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "cancelled_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.state["signed_up"].pop(str(occurrence_id), None)
        self._save()

    def batch_update_capacity(self, capacity_updates: dict[str, dict]) -> None:
        """Update class capacity data for multiple slots and save once.

        capacity_updates: {"YYYY-MM-DD_HH:MM": {"available": int, "is_full": bool}}
        """
        if not capacity_updates:
            return
        self.state.setdefault("class_capacity", {})
        checked_at = datetime.now().isoformat(timespec="seconds")
        for key, data in capacity_updates.items():
            existing = self.state["class_capacity"].get(key, {})
            self.state["class_capacity"][key] = {
                **existing,
                **data,
                "checked_at": checked_at,
            }
        # Keep only the last 90 days of capacity data
        cutoff = (datetime.now().date() - timedelta(days=90)).isoformat()
        self.state["class_capacity"] = {
            k: v for k, v in self.state["class_capacity"].items()
            if k[:10] >= cutoff
        }
        self._save()
        log.info("Capacity data updated for %d slots.", len(capacity_updates))

    def update_family_bookings(self, bookings: dict[str, list[str]]) -> None:
        """Sla family bookings op in state en persist naar gist."""
        self.state["family_bookings"] = bookings
        self._save()
        log.info("Family bookings opgeslagen: %d slots.", len(bookings))
        for key, members in sorted(bookings.items()):
            log.info("  %s: %s", key, members)

    def detect_manual_cancellations(self, events: list[dict], booked_occurrence_ids: set | None = None):
        booked_occurrence_ids = booked_occurrence_ids or set()
        newly_cancelled = []
        for event in events:
            # Lessen buiten het boekingsvenster komen zonder occurrence-id binnen;
            # daar valt niets aan te matchen.
            if not event.get("id"):
                continue
            eid = str(event["id"])
            if eid in self.state["signed_up"] and eid not in self.state["cancelled"]:
                # Bepaal of de sporter nog ingeschreven staat in Huppa. We schrijven
                # alleen uit bij een ondubbelzinnig signaal:
                #  - geen occurrenceUser meer (booking helemaal verdwenen), of
                #  - een status die expliciet "geannuleerd" betekent.
                # Een wachtlijst-plek of een onbekende status telt als nog ingeschreven,
                # zodat we niemand ten onrechte als uitgeschreven markeren in de PWA.
                # /users/me/occurrences laat occurrenceUser soms ten onrechte leeg zien
                # terwijl er wel een actieve boeking is; bookings-and-waitlists is hier
                # betrouwbaarder, dus die telt als die de booking wél ziet. We matchen
                # op occurrence-id (niet tijdstip), want op hetzelfde tijdstip kan een
                # andere les (bijv. Open Gym naast Workout of the Day) wél geboekt zijn.
                user_status = event.get("occurrence_user_status")
                still_registered = (
                    event.get("is_booked", False)
                    or event.get("is_on_waitlist", False)
                    or eid in booked_occurrence_ids
                    or (user_status is not None
                        and str(user_status).lower() not in CANCELLED_USER_STATUSES)
                )
                if not still_registered:
                    title = event.get("name", "?")
                    starts_at = event.get("starts_at", "")
                    date_str = starts_at[:10] if starts_at else "?"
                    time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
                    log.info(
                        "Detected manual cancellation for occurrence %s (%s %s %s).",
                        eid, title, date_str, time_str,
                    )
                    self.mark_cancelled(eid, date_str, time_str, title)
                    newly_cancelled.append(eid)
        if newly_cancelled:
            log.info("Marked %d occurrence(s) as manually cancelled.", len(newly_cancelled))
        return newly_cancelled


# ──────────────────────────────────────────────────────────────
# Huppa Client
# ──────────────────────────────────────────────────────────────

class HuppaClient:
    def __init__(self, email: str, password: str, subdomain: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Subdomain": subdomain,
            "Origin": f"https://{subdomain}.huppa.app",
            "Referer": f"https://{subdomain}.huppa.app/",
        })
        self.email = email
        self.password = password
        self.subdomain = subdomain

    def login(self) -> bool:
        log.info("Logging in to Huppa as %s ...", self.email)
        resp = self.session.post(
            f"{HUPPA_API_BASE}/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=20,
        )
        if resp.status_code == 200:
            log.info("Huppa login successful.")
            return True
        log.error("Huppa login failed: %s %s", resp.status_code, resp.text[:200])
        return False

    def _get_with_reauth(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, **kwargs)
        if resp.status_code == 401:
            log.info("Session expired, re-authenticating...")
            self.login()
            resp = self.session.get(url, **kwargs)
        return resp

    @staticmethod
    def _normalize_event(evt: dict) -> dict:
        """Convert camelCase API fields to snake_case with Amsterdam-local datetime strings."""
        def parse_utc(s: str) -> str:
            if not s:
                return ""
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(AMS).strftime("%Y-%m-%d %H:%M")

        trainers = [t.get("name") for t in (evt.get("trainers") or []) if t.get("name")]
        occurrence_user_status = (evt.get("occurrenceUser") or {}).get("status")
        # Sinds de Huppa-update levert /users/me/occurrences ook de deelnemers
        # ("Erik H.", "Ralph D.", ...) met avatar-URL mee, net als in de app.
        participants = [
            {"name": p.get("name", ""), "avatar": p.get("avatar")}
            for p in (evt.get("occurrenceParticipants") or [])
            if p.get("name")
        ]
        return {
            "id": evt.get("id"),
            # Huppa maakt een occurrence pas aan zodra iemand de les boekt. Tot
            # dan komt de les binnen als "pattern_slot": geen id, wel een
            # schedulePatternSlotId + datum, waarmee we hem alsnog kunnen boeken.
            "schedule_pattern_slot_id": evt.get("schedulePatternSlotId"),
            "date": evt.get("date") or (evt.get("startsAt") or "")[:10],
            "name": evt.get("name", "CrossFit WOD"),
            "starts_at": parse_utc(evt.get("startsAt", "")),
            "ends_at": parse_utc(evt.get("endsAt", "")),
            "available_slots": evt.get("availableSlots", 0),
            "booked_slots": evt.get("bookedSlots", 0),
            "is_full": evt.get("isFull", False),
            "is_booked": occurrence_user_status == "confirmed",
            "occurrence_user_status": occurrence_user_status,
            "is_on_waitlist": evt.get("occurrenceWaitlistId") is not None,
            "is_eligible_to_book": evt.get("isEligibleToBook", True),
            "organization_id": (evt.get("category") or {}).get("organizationId"),
            "trainers": trainers,
            "participants": participants,
            "description": evt.get("description") or "",
            "room": (evt.get("room") or {}).get("name", ""),
            "location": (evt.get("location") or {}).get("name", ""),
            "credit_cost": evt.get("creditCost"),
            "in_late_cancellation_window": evt.get("isInLateCancellationWindow", False),
        }

    def get_events(self, date: str) -> list[dict]:
        resp = self._get_with_reauth(
            f"{HUPPA_API_BASE}/users/me/occurrences",
            params={"date": date},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data if isinstance(data, list) else data.get("data", data.get("occurrences", []))
        normalized = [self._normalize_event(e) for e in raw]
        log.debug("Fetched %d events for %s: %s", len(normalized), date,
                  [(e["starts_at"], e["name"]) for e in normalized])
        return normalized

    def get_bookings(self) -> list[dict]:
        """Haal actieve boekingen op via bookings-and-waitlists.

        De /users/me/occurrences endpoint laat een occurrenceUser soms leeg
        zien terwijl er wel degelijk een boeking bestaat (gezien bij
        familieleden); deze endpoint geeft het echte boekingsoverzicht zoals
        de Huppa-app dat ook toont. Geeft per niet-geannuleerde boeking een
        dict {"id": occurrence_id, "starts_at": "YYYY-MM-DD HH:MM"} terug.
        We geven ook het occurrence-id mee (niet alleen het tijdstip): op
        hetzelfde tijdstip kunnen meerdere losse lessen staan (bijv. Workout
        of the Day én Open Gym om 20:00), en matchen op alleen het tijdstip
        zou dan ten onrechte ook de les waar je niet voor ingeschreven bent
        als geboekt markeren.
        """
        resp = self._get_with_reauth(
            f"{HUPPA_API_BASE}/users/me/bookings-and-waitlists",
            params={"filter": "upcoming"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        bookings = []
        for group in data.get("data", []):
            for occ in group.get("occurrences", []):
                booking = occ.get("booking")
                if not booking or booking.get("cancelledAt") is not None:
                    continue
                starts_at = occ.get("startsAt", "")
                occ_id = occ.get("id")
                if not starts_at or occ_id is None:
                    continue
                dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                bookings.append({
                    "id": str(occ_id),
                    "starts_at": dt.astimezone(AMS).strftime("%Y-%m-%d %H:%M"),
                })
        return bookings

    def get_booked_slots(self) -> list[str]:
        """Tijdstippen ('YYYY-MM-DD HH:MM') van alle actieve boekingen.

        Gebruikt voor de familie-weergave, waar alleen het tijdstip nodig is
        (niet welke specifieke les). Zie get_bookings() voor id-based matching.
        """
        return [b["starts_at"] for b in self.get_bookings()]

    def get_booked_occurrence_ids(self) -> set[str]:
        """Set van occurrence-ids waarvoor een actieve boeking bestaat."""
        return {b["id"] for b in self.get_bookings()}

    def signup(self, event: dict) -> bool:
        org_id = event.get("organization_id")
        occ_id = event.get("id")
        slot_id = event.get("schedule_pattern_slot_id")
        if not org_id or not (occ_id or slot_id):
            log.error("Cannot sign up: missing organization_id or id in event %s", event)
            return False

        if occ_id:
            # Bestaande occurrence: boeken op het occurrence-id.
            url = f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/{occ_id}/booking"
            payload: dict = {}
            label = f"occurrence {occ_id}"
        else:
            # Nog geen occurrence (pattern slot): Huppa maakt hem aan op basis
            # van het slot-id plus de datum van de les.
            url = f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/booking"
            payload = {
                "schedulePatternSlotId": slot_id,
                "schedulePatternSlotDate": event.get("date") or event.get("starts_at", "")[:10],
            }
            label = f"pattern slot {slot_id} op {payload['schedulePatternSlotDate']}"

        self.last_signup_error = None
        resp = self.session.post(url, json=payload, timeout=20)
        if resp.status_code in (200, 201, 204):
            log.info("Signed up for %s.", label)
            return True
        # Huppa vereist een specifiek abonnement als er meerdere actief zijn
        if resp.status_code == 422:
            body = resp.json()
            # Een les buiten het boekingsvenster is geen fout: de run van de
            # volgende nacht ligt dichter bij de les en kan hem wél boeken.
            if "booking window" in str(body.get("message", "")).lower():
                log.info("Boekingsvenster nog niet open voor %s.", label)
                self.last_signup_error = "outside_window"
                return False
            if body.get("code") == "multiple_booking_products_available":
                products = body.get("data", {}).get("userProducts", [])
                if products:
                    product_id = products[0]["id"]
                    log.info("Meerdere abonnementen beschikbaar, gebruik product %s.", product_id)
                    resp = self.session.post(
                        url, json={**payload, "userProductId": product_id}, timeout=20)
                    if resp.status_code in (200, 201, 204):
                        log.info("Signed up for %s (product %s).", label, product_id)
                        return True
        log.error("Sign-up failed for %s: %s %s", label, resp.status_code, resp.text[:200])
        return False

    def cancel(self, event: dict) -> bool:
        org_id = event.get("organization_id")
        occ_id = event.get("id")
        if not org_id or not occ_id:
            log.error("Cannot cancel: missing organization_id or id in event %s", event)
            return False
        resp = self.session.delete(
            f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/{occ_id}/booking",
            timeout=20,
        )
        if resp.status_code in (200, 204):
            log.info("Cancelled booking for occurrence %s.", occ_id)
            return True
        log.error("Cancel failed for occurrence %s: %s %s", occ_id, resp.status_code, resp.text[:200])
        return False


# ──────────────────────────────────────────────────────────────
# Google Calendar Helper
# ──────────────────────────────────────────────────────────────

def create_calendar_event(event: dict, date: datetime, sync_calendar: bool) -> bool:
    if not sync_calendar:
        return True

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            log.warning("GOOGLE_CREDENTIALS not set; skipping calendar sync.")
            return True

        cal_sync = GoogleCalendarSync(creds_json=creds_json)
        title = event.get("name", "CrossFit WOD")
        starts_at = event.get("starts_at", "")

        # Huppa returns "YYYY-MM-DD HH:MM" in Amsterdam time — add timezone for Google Calendar
        start_dt = datetime.fromisoformat(starts_at).replace(tzinfo=AMS)
        end_dt = start_dt + timedelta(hours=1)

        event_details = {
            "summary": title,
            "description": f"Huppa Occurrence ID: {event.get('id')}",
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }

        result = cal_sync.create_event(
            calendar_id=os.environ.get("CALENDAR_ID", "primary"),
            event_details=event_details
        )
        log.info("Created Google Calendar event: %s", result.get("id"))
        return True

    except Exception as e:
        log.error("Failed to create Google Calendar event: %s", str(e))
        return False


def delete_calendar_event(occurrence_id: str, sync_calendar: bool) -> bool:
    if not sync_calendar:
        return True

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            log.warning("GOOGLE_CREDENTIALS not set; skipping calendar delete.")
            return True

        cal_sync = GoogleCalendarSync(creds_json=creds_json)
        calendar_id = os.environ.get("CALENDAR_ID", "primary")
        calendar_events = cal_sync.find_events_by_huppa_id(occurrence_id, calendar_id)

        if not calendar_events:
            log.info("No Google Calendar event found for Huppa occurrence %s.", occurrence_id)
            return True

        for cal_event in calendar_events:
            cal_sync.delete_event(cal_event["id"], calendar_id)
            log.info("Deleted Google Calendar event %s for Huppa occurrence %s.", cal_event["id"], occurrence_id)

        return True

    except Exception as e:
        log.error("Failed to delete Google Calendar event for Huppa occurrence %s: %s", occurrence_id, str(e))
        return False


# ──────────────────────────────────────────────────────────────
# Core Logic
# ──────────────────────────────────────────────────────────────

def fetch_family_bookings(subdomain: str, days_ahead: int) -> dict[str, list[str]]:
    """Haal inschrijvingen op van familieleden via hun eigen Huppa accounts.

    Geeft een dict terug: {"YYYY-MM-DD_HH:MM": ["Laura", "Eva"]}
    """
    family_bookings: dict[str, list[str]] = {}
    today = datetime.now(AMS).date()
    horizon_str = (today + timedelta(days=days_ahead)).isoformat()
    today_str = today.isoformat()

    for member in FAMILY_MEMBERS:
        email = os.environ.get(member["email_env"])
        password = os.environ.get(member["password_env"])
        if not email or not password:
            log.debug("Familie-inschrijvingen voor %s overgeslagen: geen credentials.", member["name"])
            continue
        try:
            client = HuppaClient(email, password, subdomain)
            if not client.login():
                log.warning("Login mislukt voor %s; inschrijvingen overgeslagen.", member["name"])
                continue
            for starts_at in client.get_booked_slots():
                date_str, time_str = starts_at.split(" ")
                if not (today_str <= date_str <= horizon_str):
                    continue
                key = f"{date_str}_{time_str}"
                family_bookings.setdefault(key, [])
                if member["name"] not in family_bookings[key]:
                    family_bookings[key].append(member["name"])
            log.info("Familie-inschrijvingen opgehaald voor %s.", member["name"])
        except Exception as exc:
            log.error("Fout bij ophalen inschrijvingen voor %s: %s", member["name"], exc)

    return family_bookings


def find_target_slots(days_ahead: int) -> list[tuple]:
    """Return (date, time) pairs for scheduled classes within the look-ahead window."""
    today = datetime.now(AMS).date()
    target_weekdays = {weekday for weekday, _ in SCHEDULE}
    slots = []
    for offset in range(1, days_ahead + 1):  # Start bij 1 om vandaag over te slaan
        d = today + timedelta(days=offset)
        if d.weekday() in target_weekdays:
            for weekday, time in SCHEDULE:
                if d.weekday() == weekday:
                    slots.append((d, time))
    return slots


def find_event_at_time(events: list[dict], date_str: str, target_time: str) -> dict | None:
    # Huppa starts_at format: "YYYY-MM-DD HH:MM"
    # Sla uitgesloten lessen (bijv. Open Gym) over — alleen CrossFit WOD boeken.
    # Geef voorkeur aan een les waar de sporter al voor ingeschreven is.
    prefix = f"{date_str} {target_time}"
    eligible = [e for e in events if e.get("name") not in EXCLUDED_CLASS_NAMES]
    for event in eligible:
        if event.get("starts_at", "").startswith(prefix) and event.get("is_booked", False):
            return event
    for event in eligible:
        if event.get("starts_at", "").startswith(prefix):
            return event
    return None


def send_weekly_summary(email: str, password: str, subdomain: str):
    client = HuppaClient(email, password, subdomain)
    if not client.login():
        log.error("Aborting: login failed.")
        sys.exit(1)

    today = datetime.now(AMS).date()
    day_names_nl = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

    # Collect all registered events for the coming week by scanning every day.
    # This captures both auto-scheduled registrations and manual sign-ups/cancellations.
    registered_events = []
    for offset in range(1, 8):
        d = today + timedelta(days=offset)
        date_str = d.strftime("%Y-%m-%d")
        try:
            events = client.get_events(date_str)
        except Exception as exc:
            log.warning("Could not fetch events for %s: %s", date_str, exc)
            continue
        for event in events:
            if not event.get("is_booked", False) and not event.get("is_on_waitlist", False):
                continue
            starts_at = event.get("starts_at", "")
            time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
            title = event.get("name", "CrossFit WOD")
            available = event.get("available_slots", "?")
            on_waitlist = event.get("is_on_waitlist", False)
            status = "⏳ wachtlijst" if on_waitlist else "✅ ingeschreven"
            day_name_nl = day_names_nl[d.weekday()]
            spots_str = f"{available} vrij" if available != "?" else ""
            registered_events.append((d, time_str, f"{day_name_nl} {d.strftime('%d/%m')} {time_str} — {title} ({spots_str}) {status}"))

    if not registered_events:
        log.info("Geen inschrijvingen gevonden voor de komende week.")
        message = "Komende week: geen inschrijvingen."
        notify.send_notification("CrossFit week overzicht 📅", message)
        return

    registered_events.sort(key=lambda x: (x[0], x[1]))
    lines = [line for _, _, line in registered_events]
    message = "Komende week:\n" + "\n".join(lines)
    log.info("Weekly summary:\n%s", message)
    notify.send_notification("CrossFit week overzicht 📅", message)


def run(email: str, password: str, subdomain: str, dry_run: bool, days_ahead: int,
        sync_calendar: bool, state: GistStateManager | None):
    client = HuppaClient(email, password, subdomain)

    if not client.login():
        log.error("Aborting: login failed.")
        sys.exit(1)

    slots = find_target_slots(days_ahead)
    if not slots:
        log.info("No scheduled classes in the next %d days.", days_ahead)
        return

    log.info(
        "Checking %d slot(s): %s",
        len(slots),
        ", ".join(f"{DAY_NAMES[d.weekday()]} {d} {t}" for d, t in slots),
    )

    results = {"signed_up": [], "already": [], "full_waitlist": [], "not_found": [],
               "failed": [], "skipped": [], "not_open": []}

    events_cache: dict[str, list[dict]] = {}
    capacity_updates: dict[str, dict] = {}  # {"YYYY-MM-DD_HH:MM": {"available": int, "is_full": bool}}

    # /users/me/occurrences laat occurrenceUser soms ten onrechte leeg zien
    # terwijl er wel een actieve boeking is (zie HuppaClient.get_bookings).
    # Haal daarom altijd de betrouwbaardere bookings-and-waitlists op en
    # gebruik die om is_booked te corrigeren voor élk event dat we ophalen —
    # anders proberen we opnieuw in te schrijven voor een les waar we al voor
    # geboekt staan (409), of missen we een handmatige inschrijving in de PWA.
    # We matchen op occurrence-id, niet op tijdstip: op hetzelfde tijdstip kan
    # een andere les (bijv. Open Gym naast Workout of the Day) los geboekt
    # staan, en matchen op tijdstip zou die dan ten onrechte ook als geboekt
    # markeren.
    try:
        booked_occurrence_ids = client.get_booked_occurrence_ids()
    except Exception as exc:
        log.warning("Could not fetch bookings-and-waitlists for cross-check: %s", exc)
        booked_occurrence_ids = set()

    def fetch_events(date_str: str) -> list[dict]:
        events = client.get_events(date_str)
        for event in events:
            if not event.get("is_booked") and str(event.get("id")) in booked_occurrence_ids:
                event["is_booked"] = True
        return events

    # First pass: fetch events and detect manual cancellations.
    # Scan BOTH upcoming slots AND recent past scheduled days (last 14 days)
    # so that late cancellations for already-passed classes are picked up.
    today = datetime.now(AMS).date()

    if state:
        all_events = []
        scheduled_weekdays = {weekday for weekday, _ in SCHEDULE}
        # Past 14 days: check every scheduled weekday
        for offset in range(1, 15):
            d = today - timedelta(days=offset)
            if d.weekday() not in scheduled_weekdays:
                continue
            date_str = d.strftime("%Y-%m-%d")
            if date_str not in events_cache:
                try:
                    events_cache[date_str] = fetch_events(date_str)
                except Exception as exc:
                    log.warning("Could not fetch past events for %s: %s", date_str, exc)
                    events_cache[date_str] = []
            all_events.extend(events_cache[date_str])
        # Upcoming slots
        for date, _ in slots:
            date_str = date.strftime("%Y-%m-%d")
            if date_str not in events_cache:
                events_cache[date_str] = fetch_events(date_str)
            all_events.extend(events_cache[date_str])
        # Also scan upcoming non-scheduled days that have signed_up events,
        # so manual cancellations on those days are detected.
        today_str = today.strftime("%Y-%m-%d")
        signed_up_dates = {
            info["date"]
            for info in state.state["signed_up"].values()
            if info["date"] >= today_str
        }
        for date_str in signed_up_dates:
            if date_str not in events_cache:
                try:
                    events_cache[date_str] = fetch_events(date_str)
                except Exception as exc:
                    log.warning("Could not fetch events for %s: %s", date_str, exc)
                    events_cache[date_str] = []
            all_events.extend(events_cache[date_str])
        newly_cancelled = state.detect_manual_cancellations(all_events, booked_occurrence_ids)
        for eid in newly_cancelled:
            delete_calendar_event(eid, sync_calendar)

    for date, target_time in slots:
        date_str = date.strftime("%Y-%m-%d")
        day_name = DAY_NAMES[date.weekday()]
        label = f"{day_name} {date_str} {target_time}"
        log.info("--- %s ---", label)

        if state and state.is_excluded(date_str, target_time):
            log.info("Skipping %s — excluded by user.", label)
            results["skipped"].append(f"{label} (excluded)")
            continue

        if date_str not in events_cache:
            events_cache[date_str] = fetch_events(date_str)
        events = events_cache[date_str]

        event = find_event_at_time(events, date_str, target_time)

        if not event:
            log.warning("No %s class found on %s.", target_time, date_str)
            results["not_found"].append(label)
            continue

        eid = str(event["id"]) if event.get("id") else None
        title = event.get("name", "?")
        available_slots = event.get("available_slots", 0)
        is_full = event.get("is_full", False)
        spots = f"{available_slots} vrij" if not is_full else "vol"
        already = event.get("is_booked", False)
        on_waitlist = event.get("is_on_waitlist", False)
        # Track capacity + trainer for the dashboard
        capacity_updates[f"{date_str}_{target_time}"] = {
            "available": available_slots,
            "booked": event.get("booked_slots", 0),
            "is_full": is_full,
            "trainers": event.get("trainers", []),
            "participants": event.get("participants", []),
            "room": event.get("room", ""),
        }

        # Zonder occurrence-id én zonder pattern-slot-id valt er niets te boeken.
        if not eid and not event.get("schedule_pattern_slot_id"):
            log.info(
                "Nog niet boekbaar: %s at %s (%s) — geen occurrence-id en geen pattern slot.",
                title, target_time, spots,
            )
            results["not_open"].append(label)
            continue

        if eid and state and state.is_cancelled(eid):
            log.info("Skipping %s at %s — manually cancelled. [%s]", title, target_time, eid)
            results["skipped"].append(f"{label} (manually cancelled)")
            continue

        if already:
            log.info("Already signed up for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["already"].append(label)
            if state and not state.is_signed_up_by_script(eid):
                state.mark_signed_up(eid, date_str, target_time, title)
                if not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for manually enrolled %s.", label)
            continue

        if on_waitlist:
            log.info("Already on waitlist for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["full_waitlist"].append(label)
            continue

        status = "vol (wachtlijst)" if is_full else "open"

        if dry_run:
            log.info(
                "[DRY RUN] Would sign up for %s at %s (%s, %s) [%s].",
                title, target_time, spots, status, eid,
            )
            results["signed_up"].append(f"{label} (dry-run)")
        else:
            log.info("Signing up for %s at %s (%s, %s) [%s] ...", title, target_time, spots, status,
                     eid or f"pattern slot {event.get('schedule_pattern_slot_id')}")
            if client.signup(event):
                results["signed_up"].append(label)
                if not eid:
                    # Bij een pattern slot bestaat de occurrence nu pas: haal de
                    # dag opnieuw op zodat we het verse id hebben voor de state
                    # en het agenda-item.
                    events_cache[date_str] = fetch_events(date_str)
                    booked = find_event_at_time(events_cache[date_str], date_str, target_time)
                    if booked and booked.get("id"):
                        event = booked
                        eid = str(booked["id"])
                        log.info("Occurrence aangemaakt door de boeking: %s", eid)
                    else:
                        log.warning(
                            "Boeking geslaagd, maar geen occurrence-id gevonden voor %s; "
                            "state en agenda worden bij de volgende run bijgewerkt.", label)
                if state and eid:
                    state.mark_signed_up(eid, date_str, target_time, title)
                notify.send_notification(
                    "CrossFit Inschrijving ✅",
                    f"Ingeschreven voor {title} op {day_name} {date_str} om {target_time} 💪",
                )
                if eid and not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for %s, but signup was successful.", label)
            elif getattr(client, "last_signup_error", None) == "outside_window":
                results["not_open"].append(label)
            else:
                results["failed"].append(label)

    # Scan ALL upcoming days for manual enrollments, including today and scheduled days.
    # On scheduled days the main loop only handles the one targeted slot; any
    # other manually enrolled class (e.g. Open Gym at a different time) is detected here.
    for offset in range(0, days_ahead + 1):
        d = today + timedelta(days=offset)
        date_str = d.strftime("%Y-%m-%d")
        if date_str not in events_cache:
            events_cache[date_str] = fetch_events(date_str)
        for event in events_cache[date_str]:
            if not event.get("is_booked", False):
                continue
            # Bewaar ook deelnemers/capaciteit van geboekte lessen buiten het
            # vaste schema (bijv. Open Gym), zodat de PWA die ook kan tonen.
            starts = event.get("starts_at", "")
            if len(starts) > 15:
                capacity_updates[f"{date_str}_{starts[11:16]}"] = {
                    "available": event.get("available_slots", 0),
                    "booked": event.get("booked_slots", 0),
                    "is_full": event.get("is_full", False),
                    "trainers": event.get("trainers", []),
                    "participants": event.get("participants", []),
                    "room": event.get("room", ""),
                }
            eid = str(event["id"])
            if state and state.is_signed_up_by_script(eid):
                continue
            title = event.get("name", "?")
            starts_at = event.get("starts_at", "")
            time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
            day_name = DAY_NAMES[d.weekday()]
            label = f"{day_name} {date_str} {time_str}"
            log.info("Detected manual enrollment for %s at %s [%s].", title, label, eid)
            if state:
                state.mark_signed_up(eid, date_str, time_str, title)
            if not create_calendar_event(event, d, sync_calendar):
                log.warning("Calendar sync failed for manually enrolled %s.", label)
            results["already"].append(f"{label} (manual)")

    # Persist capacity data to gist (single save for all slots)
    if state and capacity_updates:
        state.batch_update_capacity(capacity_updates)

    # Summary
    log.info("=== Summary ===")
    if results["signed_up"]:
        log.info("Signed up:           %s", ", ".join(results["signed_up"]))
    if results["already"]:
        log.info("Already in:          %s", ", ".join(results["already"]))
    if results["full_waitlist"]:
        log.info("On waitlist:         %s", ", ".join(results["full_waitlist"]))
    if results["skipped"]:
        log.info("Skipped (cancelled): %s", ", ".join(results["skipped"]))
    if results["not_found"]:
        log.info("Not found:           %s", ", ".join(results["not_found"]))
    if results["not_open"]:
        log.info("Nog niet boekbaar:   %s", ", ".join(results["not_open"]))
    if results["failed"]:
        log.error("Failed:              %s", ", ".join(results["failed"]))


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Huppa auto sign-up for CrossFit Hilversum")
    parser.add_argument("--live", action="store_true", help="Actually sign up (default: dry-run)")
    parser.add_argument("--days", type=int, default=8, help="Days to look ahead (default: 8)")
    parser.add_argument("--sync-calendar", action="store_true", help="Sync successful signups to Google Calendar")
    parser.add_argument("--email", "-e", help="Huppa email (or set HUPPA_EMAIL env var)")
    parser.add_argument("--password", "-p", help="Huppa password (or set HUPPA_PASSWORD env var)")
    parser.add_argument("--subdomain", "-s", help="Huppa gym subdomain (or set HUPPA_SUBDOMAIN env var)")
    parser.add_argument("--test-notification", action="store_true", help="Stuur een testnotificatie en stop")
    parser.add_argument("--weekly-summary", action="store_true", help="Stuur een weekoverzicht en stop")
    args = parser.parse_args()

    email = args.email or os.environ.get("HUPPA_EMAIL")
    password = args.password or os.environ.get("HUPPA_PASSWORD")
    subdomain = args.subdomain or os.environ.get("HUPPA_SUBDOMAIN")

    if args.test_notification:
        log.info("Sending test notification...")
        success = notify.send_notification("Huppa Test 🎉", "Dit is een testbericht van Huppa")
        sys.exit(0 if success else 1)

    # Weekly summary mode
    if args.weekly_summary:
        if not email or not password or not subdomain:
            log.error("Provide credentials via --email/--password/--subdomain or HUPPA_EMAIL/HUPPA_PASSWORD/HUPPA_SUBDOMAIN env vars.")
            sys.exit(1)
        send_weekly_summary(email, password, subdomain)
        sys.exit(0)

    if not email or not password or not subdomain:
        log.error("Provide credentials via --email/--password/--subdomain or HUPPA_EMAIL/HUPPA_PASSWORD/HUPPA_SUBDOMAIN env vars.")
        sys.exit(1)

    # Initialize Gist state manager if configured
    gist_id = os.environ.get("GIST_ID")
    github_token = os.environ.get("GITHUB_TOKEN")
    state = None
    if gist_id and github_token:
        log.info("Gist state management enabled (Gist ID: %s).", gist_id)
        state = GistStateManager(gist_id, github_token)
    else:
        log.warning("GIST_ID or GITHUB_TOKEN not set; state management disabled.")

    dry_run = not args.live
    if dry_run:
        log.info("DRY RUN mode - no sign-ups will be made. Use --live to actually sign up.")

    run(email, password, subdomain, dry_run, args.days, args.sync_calendar, state)

    if not dry_run and state:
        family = fetch_family_bookings(subdomain, args.days)
        state.update_family_bookings(family)


if __name__ == "__main__":
    main()
