#!/usr/bin/env python3
"""Wekelijkse review — elke zondagavond een samenvatting van de afgelopen week.

Verzamelt uit de Gist: aantal CrossFit-lessen, hardloopkilometers, gemiddelde
slaap en HRV (t.o.v. de week ervoor), gewichtstrend, trainingsbelasting
(acuut:chronisch) en actieve blessures. Eén Claude-call maakt daar een kort advies
voor de komende week van. Resultaat gaat naar `weekly_review.json` in de Gist (de
PWA toont het) en als pushmelding naar de telefoon.

Environment:
    GIST_ID, GITHUB_TOKEN           — vereist
    ANTHROPIC_API_KEY               — optioneel (zonder: alleen cijfers, geen advies)
    VAPID_PRIVATE_KEY, VAPID_CLAIMS_EMAIL — optioneel (pushmelding)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from gist_utils import load_gist, patch_gist
from injuries import parse_injuries

log = logging.getLogger("weekly_review")
AMS = ZoneInfo("Europe/Amsterdam")
MODEL = "claude-sonnet-4-6"
OUTPUT_FILE = "weekly_review.json"
HISTORY_WEEKS = 12

RUN_TYPES = ("run", "trailrun", "treadmill", "virtualrun")


def _json(files: dict, name: str):
    try:
        return json.loads(files.get(name) or "null")
    except json.JSONDecodeError:
        log.warning("%s is geen geldige JSON", name)
        return None


def _days(end: date, n: int) -> list[str]:
    return [(end - timedelta(days=i)).isoformat() for i in range(n)]


def _avg(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _activities_for(day: str, intervals: dict, strava: dict) -> list[dict]:
    """Activiteiten van één dag; intervals.icu heeft voorrang (geen dubbeltelling)."""
    i_acts = ((intervals or {}).get("activities") or {}).get("by_date", {}).get(day) or []
    if i_acts:
        return i_acts
    return ((strava or {}).get("activities_by_date") or {}).get(day) or []


def _load(act: dict) -> float:
    """Trainingsbelasting van één activiteit (Garmin/intervals load, anders duur als proxy)."""
    tl = act.get("training_load")
    if tl:
        return float(tl)
    return float(act.get("duration_min") or 0) * 1.2


def collect(files: dict, today: date) -> dict:
    wod = _json(files, "sugarwod_wod.json") or {}
    state = _json(files, "sportbit_state.json") or {}
    health = _json(files, "health_input.json") or {}
    intervals = wod.get("intervals_data") or {}
    strava = wod.get("strava_data") or {}
    withings = wod.get("withings_data") or {}
    wellness = (intervals.get("wellness") or {}).get("by_date") or {}

    week = _days(today, 7)
    prev_week = _days(today - timedelta(days=7), 7)
    month = _days(today, 28)

    # CrossFit-lessen: "niet gedaan" in de PWA verplaatst een les naar cancelled,
    # dus wat in signed_up staat is ook echt gevolgd.
    classes = [v for v in (state.get("signed_up") or {}).values() if v.get("date") in week]

    # Hardlopen
    run_km, run_count = 0.0, 0
    sport_minutes: dict[str, int] = {}
    for d in week:
        for a in _activities_for(d, intervals, strava):
            t = (a.get("type") or "").lower()
            sport_minutes[a.get("type") or "Overig"] = sport_minutes.get(a.get("type") or "Overig", 0) + int(a.get("duration_min") or 0)
            if any(rt in t for rt in RUN_TYPES):
                run_count += 1
                run_km += (a.get("distance_m") or 0) / 1000

    def wavg(days: list[str], key: str):
        return _avg([wellness.get(d, {}).get(key) for d in days])

    acute = sum(_load(a) for d in week for a in _activities_for(d, intervals, strava)) / 7
    chronic = sum(_load(a) for d in month for a in _activities_for(d, intervals, strava)) / 28
    acwr = round(acute / chronic, 2) if chronic else None

    weights = sorted(
        [m for m in (withings.get("measurements") or []) if m.get("weight_kg") and m.get("date")],
        key=lambda m: m["date"],
    )
    w_now = next((m["weight_kg"] for m in reversed(weights) if m["date"] in week), None)
    w_prev = next((m["weight_kg"] for m in reversed(weights) if m["date"] < week[-1]), None)

    injuries = parse_injuries(health)  # zonder herstelde blessures

    return {
        "week_start": week[-1],
        "week_end": week[0],
        "crossfit_classes": len(classes),
        "runs": run_count,
        "run_km": round(run_km, 1),
        "sport_minutes": sport_minutes,
        "sleep_avg_h": wavg(week, "sleep_hrs"),
        "sleep_avg_h_prev": wavg(prev_week, "sleep_hrs"),
        "hrv_avg": wavg(week, "hrv"),
        "hrv_avg_prev": wavg(prev_week, "hrv"),
        "resting_hr_avg": wavg(week, "resting_hr"),
        "weight_kg": w_now,
        "weight_kg_prev": w_prev,
        "acwr": acwr,
        "tsb": (wellness.get(week[0]) or wellness.get(week[1]) or {}).get("tsb"),
        "active_injuries": [f"{i.get('area')} ({i.get('severity') or '?'})" for i in injuries],
    }


def ai_advice(stats: dict) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        log.info("Geen ANTHROPIC_API_KEY — review zonder AI-advies")
        return ""
    import anthropic  # noqa: PLC0415

    system = (
        "Je bent de persoonlijke coach van Ralph (47, CrossFit 4-5x per week, hardlopen met doel 5K "
        "van 28:00 naar 26:00, 78 kg, 1,89 m). Schrijf in het Nederlands, kort en concreet: "
        "maximaal 5 bullets. 1) wat ging goed, 2) wat valt op (slaap/HRV/belasting/gewicht), "
        "3) één concrete focus voor komende week, 4) waarschuwing als belasting (ACWR > 1,3) of "
        "blessures dat vragen. Geen inleiding, geen afsluiting."
    )
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": "Weekcijfers (JSON):\n" + json.dumps(stats, ensure_ascii=False, indent=2)}],
    )
    return resp.content[0].text.strip()


def push_body(s: dict) -> str:
    parts = [f"{s['crossfit_classes']}× CrossFit", f"{s['run_km']} km hardlopen"]
    if s.get("sleep_avg_h"):
        parts.append(f"slaap {s['sleep_avg_h']}u")
    if s.get("acwr"):
        parts.append(f"belasting {s['acwr']}")
    return " · ".join(parts).replace(".", ",")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not gist_id or not token:
        log.error("GIST_ID en GITHUB_TOKEN zijn vereist")
        return 1

    files = load_gist(gist_id, token)
    today = datetime.now(AMS).date()
    stats = collect(files, today)
    log.info("Weekcijfers: %s", json.dumps(stats, ensure_ascii=False))

    try:
        advice = ai_advice(stats)
    except Exception as e:  # noqa: BLE001 — cijfers zijn ook zonder advies nuttig
        log.warning("AI-advies mislukt: %s", e)
        advice = ""

    review = {**stats, "advice": advice, "generated_at": datetime.now(AMS).isoformat()}
    prev = _json(files, OUTPUT_FILE) or {}
    history = [h for h in (prev.get("history") or []) if h.get("week_end") != review["week_end"]]
    history = (history + [review])[-HISTORY_WEEKS:]
    patch_gist(gist_id, token, {OUTPUT_FILE: json.dumps({"latest": review, "history": history}, ensure_ascii=False, indent=2)})
    log.info("%s bijgewerkt", OUTPUT_FILE)

    try:
        from notify import send_notification  # noqa: PLC0415
        send_notification("📈 Weekreview", push_body(stats))
    except Exception as e:  # noqa: BLE001
        log.warning("Pushmelding mislukt: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
