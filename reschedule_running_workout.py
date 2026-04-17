#!/usr/bin/env python3
"""
reschedule_running_workout.py — Verplaatst hardloopworkouts in intervals.icu
op basis van run_1/run_2 overrides in health_input.json.

Leest running_plan.json voor de bestaande event_id en workout_doc.
Verwijdert het oude intervals.icu event en maakt een nieuw aan op de nieuwe datum.
Ruimt daarna de overrides op in health_input.json.

GitHub Secrets vereist:
  INTERVALS_ATHLETE_ID, INTERVALS_API_KEY, GIST_ID, GITHUB_TOKEN
"""

from __future__ import annotations

import json
import logging
import os
import sys

import requests

log = logging.getLogger(__name__)
INTERVALS_BASE = "https://intervals.icu/api/v1/athlete"


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


def _patch_gist(gist_id: str, token: str, files: dict[str, str]) -> None:
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        json={"files": {k: {"content": v} for k, v in files.items()}},
        timeout=20,
    )
    resp.raise_for_status()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    missing = [n for n, v in [
        ("INTERVALS_ATHLETE_ID", athlete_id),
        ("INTERVALS_API_KEY", api_key),
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
    ] if not v]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    gist_files = _load_gist(gist_id, github_token)

    try:
        health_input: dict = json.loads(gist_files.get("health_input.json") or "{}")
    except json.JSONDecodeError:
        health_input = {}

    try:
        plan: dict = json.loads(gist_files.get("running_plan.json") or "{}")
    except json.JSONDecodeError:
        plan = {}

    overrides = {k: v for k, v in health_input.items() if k in ("run_1", "run_2")}
    if not overrides:
        log.info("Geen verplaatsingen in health_input.json — niets te doen")
        return

    ints = requests.Session()
    ints.auth = ("API_KEY", api_key)
    ints.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    workouts: list[dict] = plan.get("workouts", [])
    changed = False

    for key, new_datetime in overrides.items():
        session_role = "speed" if key == "run_1" else "long_run"
        workout = next((w for w in workouts if w.get("session") == session_role), None)
        if not workout:
            log.warning("Geen %s workout in running_plan.json — overslaan", session_role)
            continue

        new_date = new_datetime[:10]
        new_time = new_datetime[11:16] if len(new_datetime) >= 16 else (
            "20:00" if key == "run_1" else "09:00"
        )

        log.info(
            "Verplaatsen %s (%s): %s → %s %s",
            key, session_role, workout.get("date"), new_date, new_time,
        )

        # Verwijder oud intervals.icu event
        old_id = workout.get("event_id")
        if old_id:
            try:
                resp = ints.delete(
                    f"{INTERVALS_BASE}/{athlete_id}/events/{old_id}", timeout=20
                )
                if resp.ok:
                    log.info("Oud event %s verwijderd", old_id)
                else:
                    log.warning(
                        "Kon event %s niet verwijderen: %s %s",
                        old_id, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                log.warning("Fout bij verwijderen event %s: %s", old_id, exc)
        else:
            log.info("Geen event_id voor %s — oud event niet verwijderd", key)

        # Maak nieuw event aan op de nieuwe datum
        new_event: dict = {
            "start_date_local": f"{new_date}T{new_time}:00",
            "category": "WORKOUT",
            "type": "Run",
            "name": workout.get("name", "Hardloopworkout"),
            "description": workout.get("description", ""),
        }
        if workout.get("workout_doc"):
            new_event["workout_doc"] = workout["workout_doc"]

        try:
            resp = ints.post(
                f"{INTERVALS_BASE}/{athlete_id}/events", json=new_event, timeout=20
            )
            resp.raise_for_status()
            new_id = resp.json().get("id")
            log.info("Nieuw event aangemaakt: id=%s op %s %s", new_id, new_date, new_time)
            workout["date"] = new_date
            workout["time"] = new_time
            workout["event_id"] = new_id
            del health_input[key]
            changed = True
        except Exception as exc:
            log.error("Fout bij aanmaken nieuw event voor %s: %s", key, exc)

    if changed:
        _patch_gist(gist_id, github_token, {
            "health_input.json": json.dumps(health_input, indent=2, ensure_ascii=False),
            "running_plan.json": json.dumps(plan, indent=2, ensure_ascii=False),
        })
        log.info("Gist bijgewerkt — overrides verwijderd, nieuwe event IDs opgeslagen")

    log.info("Klaar.")


if __name__ == "__main__":
    main()
