#!/usr/bin/env python3
"""
send_preworkout_briefing.py — Stuurt een Web Push notificatie 30 minuten
voor een geplande CrossFit les met WOD-samenvatting en hersteladvies.

Vereiste secrets:
  GIST_ID              — GitHub Gist ID
  GITHUB_TOKEN         — GitHub token met gist read scope
  VAPID_PRIVATE_KEY    — VAPID private key voor Web Push
  VAPID_CLAIMS_EMAIL   — Contactadres voor Web Push (mailto:...)

Optioneel:
  TZ_OFFSET            — tijdzone offset in uren t.o.v. UTC (default: 2 voor CEST)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import notify

log = logging.getLogger(__name__)
AMS = ZoneInfo("Europe/Amsterdam")

WINDOW_MINUTES = 45   # stuur notificatie als les binnen dit aantal minuten begint
BUFFER_MINUTES = 15   # maar niet eerder dan dit aantal minuten


def _load_gist(gist_id: str, token: str) -> dict:
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    files = resp.json().get("files", {})
    return {name: meta.get("content", "") for name, meta in files.items()}


def _tsb_label(tsb: float | None) -> str:
    if tsb is None:
        return ""
    if tsb > 5:
        return "Fris"
    if tsb < -10:
        return "Vermoeid"
    return "Neutraal"


def _hrv_label(hrv: float | None, baseline: float | None) -> str:
    if hrv is None or baseline is None:
        return ""
    ratio = hrv / baseline
    if ratio >= 0.9:
        return "HRV ok"
    if ratio >= 0.75:
        return "HRV laag"
    return "HRV zeer laag"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    if not all([gist_id, token]):
        log.error("Vereiste env vars ontbreken (GIST_ID, GITHUB_TOKEN)")
        return 1

    now = datetime.now(AMS)
    today_str = now.date().isoformat()
    log.info("Huidig tijdstip (AMS): %s", now.strftime("%Y-%m-%d %H:%M"))

    try:
        files = _load_gist(gist_id, token)
    except Exception as exc:
        log.error("Gist laden mislukt: %s", exc)
        return 1

    # Laad CrossFit les data
    wod_raw = files.get("sugarwod_wod.json", "")
    wod_data: dict = {}
    try:
        wod_data = json.loads(wod_raw) if wod_raw else {}
    except json.JSONDecodeError:
        pass

    # Laad inschrijvingsstatus
    state_raw = files.get("sportbit_state.json", "")
    state: dict = {}
    try:
        state = json.loads(state_raw) if state_raw else {}
    except json.JSONDecodeError:
        pass

    signed_up_ids: set[str] = set(state.get("signed_up", []))
    cancelled_ids: set[str] = set(state.get("cancelled", []))

    # Zoek een les die begint in het window [BUFFER_MINUTES, WINDOW_MINUTES] vanaf nu
    workouts: list[dict] = wod_data.get("workouts", [])
    target_workout = None
    target_time_str = None

    for w in workouts:
        if w.get("date") != today_str:
            continue
        event_id = str(w.get("event_id", ""))
        if event_id in cancelled_ids:
            continue
        if event_id and event_id not in signed_up_ids:
            continue

        time_str = w.get("time", "")
        if not time_str or len(time_str) < 5:
            continue

        try:
            hour, minute = int(time_str[:2]), int(time_str[3:5])
        except (ValueError, IndexError):
            continue

        les_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        minutes_until = (les_dt - now).total_seconds() / 60

        if BUFFER_MINUTES <= minutes_until <= WINDOW_MINUTES:
            target_workout = w
            target_time_str = time_str
            log.info("Les gevonden: %s om %s (over %.0f min)", w.get("title"), time_str, minutes_until)
            break

    if not target_workout:
        log.info("Geen les binnen het window van %d–%d minuten — geen notificatie nodig", BUFFER_MINUTES, WINDOW_MINUTES)
        return 0

    # Bouw berichtinhoud
    title = target_workout.get("title", "CrossFit WOD")
    wod_parts = []

    # WOD beschrijving (eerste meaningful sectie)
    by_date = wod_data.get("by_date", {})
    day_wods = by_date.get(today_str, [])
    for wod in day_wods:
        desc_raw = wod.get("description", "") or ""
        # Strip HTML tags
        import re
        desc = re.sub(r"<[^>]+>", "", desc_raw).strip()
        if desc and len(desc) > 10:
            # Neem eerste 120 tekens van de beschrijving
            short = desc[:120].rsplit(" ", 1)[0] + "…" if len(desc) > 120 else desc
            wod_parts.append(short)
            break

    # Herstelstatus (HRV + TSB)
    intervals_data = wod_data.get("intervals_data") or {}
    wellness_by_date = (intervals_data.get("wellness") or {}).get("by_date", {})
    today_wellness = wellness_by_date.get(today_str) or wellness_by_date.get(
        max(wellness_by_date.keys()) if wellness_by_date else "", {}
    )

    hrv = today_wellness.get("hrv")
    tsb = today_wellness.get("tsb")

    # Bereken HRV basislijn voor status
    hrv_dates = sorted(d for d in wellness_by_date if d < today_str)[-28:]
    hrv_vals = [wellness_by_date[d]["hrv"] for d in hrv_dates if wellness_by_date[d].get("hrv")]
    baseline = sum(hrv_vals) / len(hrv_vals) if len(hrv_vals) >= 5 else None

    status_parts = []
    hrv_lbl = _hrv_label(hrv, baseline)
    if hrv_lbl:
        status_parts.append(hrv_lbl)
    tsb_lbl = _tsb_label(tsb)
    if tsb_lbl:
        status_parts.append(f"TSB {tsb_lbl}")

    deload_alert = wod_data.get("deload_alert", False)

    # Stel bericht samen (max ~200 tekens voor leesbaarheid op telefoon)
    lines = [f"💪 {title} om {target_time_str}"]
    if wod_parts:
        lines.append(wod_parts[0])
    if status_parts:
        lines.append(" · ".join(status_parts))
    if deload_alert:
        lines.append("⚠️ Herstelweek: schaal naar 60-70%")

    message = "\n".join(lines)

    if not notify.send_notification("Pre-workout briefing 💪", message):
        log.error("Notificatie versturen mislukt")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
