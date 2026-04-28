#!/usr/bin/env python3
"""
generate_open_gym_program.py — Genereert een persoonlijk Open Gym programma als
professionele CrossFit coach op basis van trainingsbelasting, doelen en recent werk.

Werking:
  1. Haalt alle fitnessdata op uit de GitHub Gist.
  2. Zoekt de eerstvolgende Open Gym inschrijving in sportbit_state.json.
  3. Vraagt Claude AI om een volledig gepersonaliseerd programma.
  4. Slaat het resultaat op als open_gym_program.json in de Gist.

Environment variables:
  GIST_ID           — GitHub Gist ID (vereist)
  GITHUB_TOKEN      — GitHub token met gist scope (vereist)
  ANTHROPIC_API_KEY — Claude API key (vereist)
  PUSHOVER_USER_KEY / PUSHOVER_API_TOKEN — optioneel voor notificatie
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic
import requests

log = logging.getLogger(__name__)
AMS = ZoneInfo("Europe/Amsterdam")

GIST_FILENAME = "open_gym_program.json"
MODEL = "claude-opus-4-7"

# ── Atletenprofiel ─────────────────────────────────────────────────────────────

ATHLETE_PROFILE = {
    "name": "Ralph de Leeuw",
    "age": 47,
    "weight_kg": 77,
    "experience": "intermediate-advanced (4+ jaar CrossFit)",
    "rx_preference": "mix van RX en Scaled — RX wanneer mogelijk",
    "injuries": "geen",
    "gym": "CrossFit Hilversum",
    "doel": "Uiteindelijk alles RX kunnen. Leeftijd 47, voelt zich goed en traint serieus.",
    "skill_focus": [
        "double unders (consistentie en hoog volume)",
        "handstand push-ups (strikt en kipping, richting RX)",
        "pull-ups (kipping en butterfly, richting RX)",
        "handstand walk (afstand opbouwen)",
        "back squat & front squat (techniek + kracht)",
        "hardlooptempo (sneller worden op 400m/800m/1mi)",
    ],
}

BARBELL_LIFTS_FALLBACK = {
    "Back Squat": {"1RM": 67, "3RM": 62, "5RM": 56},
    "Front Squat": {"1RM": 65, "5RM": 57},
    "Deadlift": {"1RM": 100, "5RM": 90},
    "Clean & Jerk": {"1RM": 58},
    "Clean": {"1RM": 50},
    "Snatch": {"1RM": 38},
    "Power Clean": {"1RM": 57},
    "Power Snatch": {"1RM": 43},
    "Shoulder Press": {"1RM": 42.5, "5RM": 27},
    "Push Press": {"1RM": 57.5},
    "Push Jerk": {"1RM": 61},
    "Bench Press": {"1RM": 67.5, "5RM": 50},
    "Thruster": {"1RM": 53, "5RM": 43},
    "Overhead Squat": {"1RM": 48},
}

DAY_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


# ── Gist helpers ───────────────────────────────────────────────────────────────

def _load_gist(gist_id: str, token: str) -> dict[str, str]:
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return {
        name: meta.get("content", "")
        for name, meta in resp.json().get("files", {}).items()
    }


def _save_to_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        json={"files": {filename: {"content": content}}},
        timeout=20,
    )
    resp.raise_for_status()


def _parse_json(raw: str, label: str) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("%s is geen geldig JSON: %s", label, exc)
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


# ── SportBit API client ────────────────────────────────────────────────────────

SPORTBIT_BASE = "https://crossfithilversum.sportbitapp.nl/cbm/api/"
SPORTBIT_ROOSTER_ID = 1


class _SportBitClient:
    def __init__(self, username: str, password: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Referer": "https://crossfithilversum.sportbitapp.nl/web/nl/events",
        })
        self.username = username
        self.password = password

    def _url(self, path: str) -> str:
        from urllib.parse import urljoin
        return urljoin(SPORTBIT_BASE, path)

    def _set_xsrf(self) -> None:
        token = self.session.cookies.get("XSRF-TOKEN")
        if token:
            self.session.headers["X-XSRF-TOKEN"] = token

    def login(self) -> bool:
        self.session.get(self._url("data/heartbeat/"))
        self._set_xsrf()
        resp = self.session.post(
            self._url("data/inloggen/"),
            json={"username": self.username, "password": self.password, "remember": True},
        )
        if resp.status_code == 200:
            self._set_xsrf()
            return True
        log.error("SportBit login mislukt: %s", resp.status_code)
        return False

    def get_events_for_rooster(self, date_str: str, rooster_id: int | None) -> list[dict]:
        params: dict = {"datum": date_str}
        if rooster_id is not None:
            params["rooster"] = rooster_id
        resp = self.session.get(
            self._url("data/events/"),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        events: list[dict] = []
        for period in ("ochtend", "middag", "avond"):
            if isinstance(data.get(period), list):
                events.extend(data[period])
        return events

    def get_all_events(self, date_str: str) -> list[dict]:
        """Haal events op voor alle bekende roosters + zonder filter, dedupliceer op ID."""
        seen_ids: set = set()
        all_events: list[dict] = []
        # Probeer rooster 1 (CrossFit WOD) en 2 (Open Gym), plus zonder filter
        for rooster_id in (SPORTBIT_ROOSTER_ID, 2, None):
            try:
                events = self.get_events_for_rooster(date_str, rooster_id)
                for e in events:
                    eid = e.get("id")
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        all_events.append(e)
            except Exception as exc:
                log.debug("Events ophalen rooster=%s voor %s mislukt: %s", rooster_id, date_str, exc)
        return all_events


def _is_open_gym(title: str) -> bool:
    t = title.lower()
    return "open gym" in t or "open_gym" in t


# ── Open Gym inschrijving zoeken ───────────────────────────────────────────────

def _find_open_gym_in_state(files: dict[str, str]) -> list[dict]:
    """Zoek Open Gym inschrijvingen in sportbit_state.json (alleen al door autosignup gedetecteerde events)."""
    raw = files.get("sportbit_state.json", "")
    if not raw:
        return []
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return []

    today_str = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=7)).isoformat()
    cancelled_ids = set(state.get("cancelled", {}).keys())

    events = []
    for event_id, info in state.get("signed_up", {}).items():
        if event_id in cancelled_ids:
            continue
        title = info.get("title", "")
        event_date = info.get("date", "")
        if not (today_str <= event_date <= cutoff):
            continue
        if _is_open_gym(title):
            events.append({
                "event_id": event_id,
                "date": event_date,
                "time": info.get("time", "?"),
                "title": title,
            })

    return sorted(events, key=lambda x: (x["date"], x["time"]))


def _find_open_gym_via_api(username: str, password: str) -> list[dict]:
    """Bevraag SportBit API direct voor Open Gym inschrijvingen (vandaag t/m +7 dagen)."""
    client = _SportBitClient(username, password)
    if not client.login():
        log.warning("SportBit login mislukt — kan Open Gym niet via API ophalen.")
        return []

    today = date.today()
    found: list[dict] = []
    for offset in range(8):
        d = today + timedelta(days=offset)
        date_str = d.isoformat()
        try:
            events = client.get_all_events(date_str)
        except Exception as exc:
            log.warning("Events ophalen voor %s mislukt: %s", date_str, exc)
            continue
        for event in events:
            title = event.get("titel", "")
            aangemeld = event.get("aangemeld", False)
            event_id = event.get("id")
            start = event.get("start", "")
            time_str = start[11:16] if len(start) > 15 else "?"
            log.info("Event %s: titel='%s' aangemeld=%s tijd=%s", event_id, title, aangemeld, time_str)
            if not aangemeld:
                continue
            if not _is_open_gym(title):
                log.info("  → aangemeld maar geen Open Gym — overgeslagen (titel: '%s')", title)
                continue
            found.append({
                "event_id": str(event_id),
                "date": date_str,
                "time": time_str,
                "title": title,
            })
            log.info("  → Open Gym gevonden op %s om %s", date_str, time_str)

    return sorted(found, key=lambda x: (x["date"], x["time"]))


def _find_open_gym_events(files: dict[str, str]) -> list[dict]:
    """Zoek Open Gym inschrijvingen: eerst in state, daarna direct via SportBit API."""
    # Stap 1: state file (snel, geen credentials nodig)
    events = _find_open_gym_in_state(files)
    if events:
        log.info("Open Gym gevonden in sportbit_state.json.")
        return events

    # Stap 2: fallback — direct SportBit API bevragen
    username = os.environ.get("SPORTBIT_USERNAME", "").strip()
    password = os.environ.get("SPORTBIT_PASSWORD", "").strip()
    if not username or not password:
        log.warning(
            "Niet gevonden in state en SPORTBIT_USERNAME/SPORTBIT_PASSWORD niet ingesteld. "
            "Zorg dat autosignup heeft gedraaid of voeg de SportBit credentials toe als secret."
        )
        return []

    log.info("Niet gevonden in state — SportBit API direct bevragen...")
    return _find_open_gym_via_api(username, password)


# ── Fitnesscontext laden ───────────────────────────────────────────────────────

def _load_fitness_data(files: dict[str, str]) -> dict:
    wod_data = _parse_json(files.get("sugarwod_wod.json", ""), "sugarwod_wod.json") or {}
    health_input_raw = _parse_json(files.get("health_input.json", ""), "health_input.json") or {}
    workout_log_raw = _parse_json(files.get("workout_log.json", ""), "workout_log.json") or {}
    mfp_raw = _parse_json(files.get("myfitnesspal_nutrition.json", ""), "myfitnesspal_nutrition.json") or {}

    intervals_data = wod_data.get("intervals_data") or {}
    strava_data = wod_data.get("strava_data") or {}
    barbell_lifts = wod_data.get("barbell_lifts") or BARBELL_LIFTS_FALLBACK

    # Workout log: {date: entry}
    workout_log: dict = {}
    for entry in (workout_log_raw.get("entries") or []):
        if "date" in entry:
            workout_log[entry["date"]] = entry

    return {
        "wod_by_date": wod_data.get("by_date") or {},
        "barbell_lifts": barbell_lifts,
        "wellness": intervals_data.get("wellness", {}).get("by_date", {}),
        "activities": intervals_data.get("activities", {}).get("by_date", {}),
        "strava": strava_data.get("activities_by_date") or {},
        "health_input": health_input_raw,
        "health_history": health_input_raw.get("history", []),
        "workout_log": workout_log,
        "mfp": (mfp_raw.get("diary") or {}).get("by_date") or {},
    }


# ── Context bouwen voor Claude ─────────────────────────────────────────────────

def _build_context(data: dict, open_gym_event: dict) -> str:
    today = date.today()
    event_date_str = open_gym_event["date"]
    try:
        event_date = date.fromisoformat(event_date_str)
    except ValueError:
        event_date = today

    dag_naam = DAY_NL[event_date.weekday()]
    sections: list[str] = []

    sections.append(
        f"Vandaag: {today.isoformat()} ({DAY_NL[today.weekday()]})\n"
        f"Open Gym datum: {event_date_str} ({dag_naam}) om {open_gym_event['time']}\n"
        f"(De atleet heeft zich NIET ingeschreven voor de reguliere CrossFit les — hij gaat zelf trainen in de Open Gym)"
    )

    # ── WOD van de dag (reguliere les die wordt overgeslagen) ──────────────────
    wod_by_date: dict = data["wod_by_date"]
    wods_today = wod_by_date.get(event_date_str, [])
    if wods_today:
        wod_lines = []
        for w in wods_today:
            name = w.get("name") or w.get("title") or "WOD"
            desc = _strip_html(w.get("description") or "")
            skill = _strip_html(w.get("skill_wod") or "")
            strength = _strip_html(w.get("strength_wod") or "")
            wod_lines.append(f"  {name}: {desc[:300]}")
            if skill:
                wod_lines.append(f"  Skill: {skill[:200]}")
            if strength:
                wod_lines.append(f"  Strength: {strength[:200]}")
        sections.append("WOD van de dag (de les die hij OVERSLAAT):\n" + "\n".join(wod_lines))
    else:
        sections.append("WOD van de dag: niet beschikbaar")

    # ── Wellness / trainingsbelasting ──────────────────────────────────────────
    wellness: dict = data["wellness"]
    recent_w_dates = sorted(wellness.keys(), reverse=True)[:7]
    if recent_w_dates:
        w_lines = []
        for d_str in recent_w_dates:
            w = wellness[d_str]
            parts = [f"  {d_str}:"]
            if w.get("hrv") is not None:       parts.append(f"HRV={w['hrv']}ms")
            if w.get("resting_hr") is not None: parts.append(f"rustpols={w['resting_hr']}bpm")
            if w.get("sleep_hrs") is not None:  parts.append(f"slaap={w['sleep_hrs']}u")
            if w.get("sleep_score") is not None: parts.append(f"slaapscore={w['sleep_score']}")
            if w.get("ctl") is not None:        parts.append(f"CTL={w['ctl']}")
            if w.get("atl") is not None:        parts.append(f"ATL={w['atl']}")
            if w.get("tsb") is not None:        parts.append(f"TSB={w['tsb']}")
            if w.get("spo2") is not None:       parts.append(f"SpO2={w['spo2']}%")
            w_lines.append(" ".join(parts))
        sections.append("Wellness & trainingsbelasting (laatste 7 dagen):\n" + "\n".join(w_lines))
    else:
        sections.append("Wellness data: niet beschikbaar")

    # ── Subjectieve scores ─────────────────────────────────────────────────────
    health_input: dict = data["health_input"]
    health_history: list = data["health_history"]
    all_health = []
    if health_input.get("date"):
        all_health.append(health_input)
    all_health.extend(health_history)
    all_health = sorted(all_health, key=lambda x: x.get("date", ""), reverse=True)[:5]
    if all_health:
        h_lines = []
        for h in all_health:
            parts = [f"  {h.get('date', '?')}:"]
            for k in ("slaap", "energie", "spierpijn", "stress"):
                v = h.get(k)
                if v is not None:
                    parts.append(f"{k}={v}/10")
            h_lines.append(" ".join(parts))
        sections.append("Subjectieve herstelscores (laatste 5 invoeren):\n" + "\n".join(h_lines))

    # ── Recente activiteiten (7 dagen) ─────────────────────────────────────────
    cutoff_7 = (today - timedelta(days=7)).isoformat()
    acts_by_date: dict = data["activities"]
    strava_by_date: dict = data["strava"]
    all_dates = sorted(
        set(list(acts_by_date.keys()) + list(strava_by_date.keys())),
        reverse=True,
    )
    recent_act_dates = [d_str for d_str in all_dates if d_str >= cutoff_7]

    if recent_act_dates:
        act_lines = []
        for d_str in recent_act_dates:
            day_acts = acts_by_date.get(d_str, []) + strava_by_date.get(d_str, [])
            for act in day_acts:
                name = act.get("name") or act.get("type") or "activiteit"
                dur = act.get("duration_min")
                avg_hr = act.get("avg_hr")
                tl = act.get("training_load") or act.get("suffer_score")
                act_type = act.get("type", "")
                parts = [f"  {d_str}: {name} ({act_type})"]
                if dur:
                    parts.append(f"{dur}min")
                if avg_hr:
                    parts.append(f"HR {avg_hr}bpm")
                if tl:
                    parts.append(f"TL {round(tl)}")
                act_lines.append(" ".join(parts))
        sections.append("Recente activiteiten (afgelopen 7 dagen):\n" + "\n".join(act_lines))
    else:
        sections.append("Recente activiteiten: geen data beschikbaar")

    # ── WOD-geschiedenis (afgelopen 14 dagen) ──────────────────────────────────
    cutoff_14 = (today - timedelta(days=14)).isoformat()
    wod_lines = []
    workout_log: dict = data["workout_log"]
    for d_str in sorted(wod_by_date.keys(), reverse=True):
        if d_str < cutoff_14:
            break
        for w in wod_by_date[d_str]:
            name = w.get("name") or w.get("title") or "WOD"
            desc = _strip_html(w.get("description") or "")[:120]
            log_entry = workout_log.get(d_str, {})
            completed = "✓" if log_entry.get("checked") else "—"
            notes = log_entry.get("notes") or ""
            line = f"  {d_str} [{completed}] — {name}"
            if desc:
                line += f": {desc}"
            if notes:
                line += f" | notitie: {notes[:80]}"
            wod_lines.append(line)
    if wod_lines:
        sections.append("CrossFit WOD-geschiedenis (afgelopen 14 dagen):\n" + "\n".join(wod_lines))

    # ── Komende WODs (2 dagen na Open Gym) ────────────────────────────────────
    upcoming_lines = []
    for offset in range(1, 4):
        d_str = (event_date + timedelta(days=offset)).isoformat()
        wods = wod_by_date.get(d_str, [])
        for w in wods:
            name = w.get("name") or w.get("title") or "WOD"
            desc = _strip_html(w.get("description") or "")[:120]
            upcoming_lines.append(f"  {d_str}: {name}" + (f" — {desc}" if desc else ""))
    if upcoming_lines:
        sections.append("Komende CrossFit WODs (2 dagen na Open Gym — houd hier rekening mee):\n" + "\n".join(upcoming_lines))

    # ── Barbell maxima ─────────────────────────────────────────────────────────
    lifts: dict = data["barbell_lifts"]
    lift_lines = []
    for lift_name, rms in sorted(lifts.items()):
        rm_parts = [f"{k}: {v}kg" for k, v in sorted(rms.items())]
        lift_lines.append(f"  {lift_name}: {', '.join(rm_parts)}")
    if lift_lines:
        sections.append("Barbell maxima:\n" + "\n".join(lift_lines))

    # ── Voeding ────────────────────────────────────────────────────────────────
    mfp: dict = data["mfp"]
    mfp_recent = sorted(mfp.keys(), reverse=True)[:3]
    if mfp_recent:
        mfp_lines = []
        for d_str in mfp_recent:
            m = mfp[d_str]
            if not m.get("calories"):
                continue
            prot = round(m.get("protein_g") or 0)
            carbs = round(m.get("carbs_g") or 0)
            fat = round(m.get("fat_g") or 0)
            mfp_lines.append(f"  {d_str}: {m['calories']} kcal, {prot}g eiwit, {carbs}g KH, {fat}g vet")
        if mfp_lines:
            sections.append("Voeding (MyFitnessPal, laatste 3 dagen):\n" + "\n".join(mfp_lines))

    return "\n\n".join(sections)


# ── Claude prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Jij bent een ervaren CrossFit coach die een persoonlijk programma opstelt voor Ralph de Leeuw.

Atleetprofiel:
- Naam: Ralph de Leeuw, 47 jaar, 77 kg
- Ervaring: intermediate-advanced (4+ jaar CrossFit)
- Gym: CrossFit Hilversum
- Doel: uiteindelijk alles RX kunnen
- Skill focus (in volgorde van prioriteit): double unders, handstand push-ups, kipping/butterfly pull-ups, handstand walk, back squat & front squat, hardlooptempo
- RX-voorkeur: RX waar mogelijk, anders scaled

Ralph gaat naar de Open Gym in plaats van de reguliere CrossFit les. Hij wil een volledig uitgewerkt programma dat:
1. Complementair is aan zijn trainingsbelasting (gebruik CTL/ATL/TSB en recente activiteiten)
2. Bijdraagt aan zijn specifieke doelen (skills + kracht)
3. Rekening houdt met de WOD van vandaag (de les die hij overslaat) — vermijd overlap
4. Rekening houdt met komende WODs — bouw geen extra vermoeidheid op als morgen een zware les volgt
5. Past bij zijn herstelniveau (HRV, slaap, subjectieve scores)

Opbouw van het programma:
- **Warming-up** (10-15 min): activatie, mobiliteit, bewegingsvoorbereiding
- **Skill / Techniek** (15-25 min): één skill uit zijn focus, met duidelijke progressie
- **Kracht** (15-25 min): één barbell-oefening of gymnastics strength, met sets/reps/gewicht
- **Conditioning** (10-20 min): een gepersonaliseerde metcon die aansluit op zijn belasting
- **Cool-down** (5-10 min): mobiliteit, rek

Richtlijnen:
- Geef concrete gewichten op basis van zijn barbell-maxima (percentages van 1RM)
- Schrijf in het Nederlands
- Gebruik duidelijke opmaak met Markdown (##, ###, vetgedrukt, opsommingen)
- Voeg coaching cues toe bij technische bewegingen
- Geef altijd een scaled versie voor de conditioning
- Schat de totale tijdsduur in

Schrijf het programma direct en volledig uit — dit is wat Ralph meeneemt naar de gym.\
"""


def _generate_program(context: str, open_gym_event: dict) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    event_date_str = open_gym_event["date"]
    try:
        event_date = date.fromisoformat(event_date_str)
        dag_naam = DAY_NL[event_date.weekday()]
        datum_label = f"{dag_naam} {event_date.day} {['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december'][event_date.month-1]} {event_date.year}"
    except ValueError:
        datum_label = event_date_str

    user_message = (
        f"Maak een Open Gym programma voor {datum_label} om {open_gym_event['time']}.\n\n"
        f"Hier is de volledige fitnesscontext:\n\n{context}"
    )

    log.info("Claude aanroepen voor Open Gym programma (model: %s)...", MODEL)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ── Pushover ───────────────────────────────────────────────────────────────────

def _send_pushover(title: str, message: str) -> None:
    user_key = os.environ.get("PUSHOVER_USER_KEY")
    api_token = os.environ.get("PUSHOVER_API_TOKEN")
    if not user_key or not api_token:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            json={"token": api_token, "user": user_key, "title": title, "message": message},
            timeout=10,
        ).raise_for_status()
        log.info("Pushover notificatie verstuurd.")
    except Exception as exc:
        log.warning("Pushover mislukt: %s", exc)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not gist_id or not token:
        log.error("GIST_ID en GITHUB_TOKEN zijn vereist.")
        return 1
    if not anthropic_key:
        log.error("ANTHROPIC_API_KEY is vereist.")
        return 1

    log.info("Gist data ophalen...")
    try:
        files = _load_gist(gist_id, token)
    except Exception as exc:
        log.error("Gist laden mislukt: %s", exc)
        return 1

    # Open Gym inschrijving zoeken
    open_gym_events = _find_open_gym_events(files)
    if not open_gym_events:
        log.warning("Geen Open Gym inschrijving gevonden voor vandaag of de komende 7 dagen.")
        log.info("Controleer of je je hebt ingeschreven voor een 'Open Gym' les in SportBit.")
        return 1

    open_gym_event = open_gym_events[0]
    log.info(
        "Open Gym gevonden: %s op %s om %s (event_id: %s)",
        open_gym_event["title"],
        open_gym_event["date"],
        open_gym_event["time"],
        open_gym_event["event_id"],
    )

    # Fitnessdata laden
    log.info("Fitnessdata laden...")
    data = _load_fitness_data(files)

    # Context bouwen
    context = _build_context(data, open_gym_event)
    log.info("Context gebouwd (%d tekens).", len(context))

    # Programma genereren
    try:
        program_markdown = _generate_program(context, open_gym_event)
    except Exception as exc:
        log.error("Claude aanroep mislukt: %s", exc)
        return 1

    log.info("Programma gegenereerd (%d tekens).", len(program_markdown))

    # Opslaan in Gist
    now_ams = datetime.now(AMS)
    output = {
        "generated_at": now_ams.isoformat(timespec="seconds"),
        "for_date": open_gym_event["date"],
        "for_time": open_gym_event["time"],
        "event_title": open_gym_event["title"],
        "event_id": open_gym_event["event_id"],
        "program_markdown": program_markdown,
        "generated_with_model": MODEL,
    }

    try:
        _save_to_gist(gist_id, token, GIST_FILENAME, json.dumps(output, ensure_ascii=False, indent=2))
        log.info("Programma opgeslagen als %s in Gist.", GIST_FILENAME)
    except Exception as exc:
        log.error("Gist opslaan mislukt: %s", exc)
        return 1

    # Pushover notificatie
    try:
        event_date = date.fromisoformat(open_gym_event["date"])
        dag_naam = DAY_NL[event_date.weekday()]
        datum_label = f"{dag_naam} {event_date.strftime('%d/%m')}"
    except ValueError:
        datum_label = open_gym_event["date"]

    _send_pushover(
        "Open Gym Programma 🏋️",
        f"Programma klaar voor {datum_label} om {open_gym_event['time']} — check de SportBit app!",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
