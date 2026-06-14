#!/usr/bin/env python3
"""
analyze_running_workout.py — Koppelt voltooide runs aan geplande workouts,
maakt een gepland-vs-werkelijk analyse en stelt (optioneel) toekomstige
aanpassingen voor.

Modi:
  analyze (default): match nieuwe voltooide runs, bereken metrics, vraag Claude
                     om een kwalitatieve analyse + suggesties, schrijf naar
                     running_analysis.json en stuur een push-notificatie.
  apply:             voer goedgekeurde voorstellen (status="applied") door naar
                     running_plan.json en push het bijgewerkte event naar
                     intervals.icu.

Opslag: persistent gist-bestand running_analysis.json (los van het wekelijks
overschreven running_plan.json), gekeyd op datum.

GitHub Secrets vereist:
  INTERVALS_ATHLETE_ID, INTERVALS_API_KEY, ANTHROPIC_API_KEY, GIST_ID, GITHUB_TOKEN
  (optioneel: VAPID_PRIVATE_KEY / VAPID_CLAIMS_EMAIL voor notificaties)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import anthropic
import requests

import notify

from generate_running_workout import (
    AMS,
    INTERVALS_BASE,
    _build_description,
    _build_intervals_event,
    _load_gist,
    _parse_json,
    _push_to_intervals,
    _save_to_gist,
)
from review_running_workout import _format_steps_brief, _validate_steps

log = logging.getLogger(__name__)

RUN_TYPES = {"run", "running", "jog", "trailrun", "treadmill"}
ANALYSIS_FILE = "running_analysis.json"

# Defensie fitnesstest — twee fasen (gelijk aan generate_running_workout.py:62-63)
TEST_DURATION_S = 720          # 12 minuten
PHASE1_GOAL_M = 2200           # fase 1 (weken 1-10): minimumeis
PHASE2_GOAL_M = 2700           # fase 2 (weken 11+): streefdoel

_ANALYSIS_SYSTEM_PROMPT = """You are a professional running coach analysing how Ralph de Leeuw executed a planned workout.
- 47 years old, 77kg, CrossFit 5x/week, runs 1-3x/week
- Current 5K: ~28 min (5:36/km) | Goal: Dutch defensie fitness test — Phase 1 (weeks 1-10): 2200m in 12 min (≈5:27/km) | Phase 2 (weeks 11+): 2700m in 12 min (≈4:26/km)

You receive the PLANNED workout, the ACTUAL activity (laps + HR zones if available),
deterministic comparison metrics, and short recovery context.

Your task:
1. Judge how well the actual run matched the plan (did he hit the interval paces / HR zones / distance?).
2. Optionally propose adjustments to FUTURE workouts (only those listed under "Upcoming workouts").
   Propose an adjustment only when the execution clearly justifies it (e.g. consistently
   well under/over target pace, missed the session, struggled badly, or breezed through).
   Most analyses need NO adjustment — leave proposed_adjustments empty.

Pace zones for reference (defensie fitness test — two phases):
- Conversational (max): 6:40/km | Aerobic: 6:00-6:30/km
- Phase 1 (weeks 1-10, 2200m goal): threshold 5:10-5:30 | test 5:00-5:27 | 600m 4:50-5:10 | 400m 4:40-5:00 | 300m 4:30-4:50 | 200m 4:20-4:40
- Phase 2 (weeks 11+, 2700m goal):  threshold 4:30-4:50 | test 4:15-4:26 | 600m 4:05-4:20 | 400m 3:55-4:10 | 300m 3:45-4:00 | 200m 3:35-3:50

Output: return ONLY valid JSON (no markdown, no explanation):
{
  "summary": "2-3 sentences, Dutch, how the run went vs the plan",
  "execution_score": <int 1-10, 10 = exactly as planned or better>,
  "verdict": "on_target|faster|slower|partial|missed",
  "key_observations": ["short Dutch bullet", "..."],
  "proposed_adjustments": [
    {
      "target_date": "YYYY-MM-DD",
      "session": "speed|long_run",
      "rationale": "1-2 sentences, Dutch, why this change",
      "workout": {
        "date": "YYYY-MM-DD",
        "session": "speed|long_run",
        "type": "easy_run|fartlek|interval_run|progressive_run|tempo_run",
        "name": "Short English session name",
        "description": "1-2 sentences about the goal",
        "total_distance_km": <float>,
        "steps": [<steps — see format below>]
      }
    }
  ]
}

Step formats (PACE IS ALWAYS REQUIRED for run/warmup/cooldown — provide pace_min and pace_max as a range):
  Warm-up:      {"type":"warmup",   "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z1"}
  Easy/long run:{"type":"run",      "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z2"}
  Interval:     {"type":"run",      "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z5"}
  Repeat:       {"type":"repeat",   "count":<int>, "children":[<steps>]}
  Walking rest: {"type":"rest",     "duration_s":<int>}
  Cool-down:    {"type":"cooldown", "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z1"}

If no future adjustment is needed: "proposed_adjustments": []

CRITICAL OUTPUT RULE: Your response must consist of ONLY the JSON object. Begin your response with '{' — no analysis, no explanation, no reasoning, no markdown."""


# ── Data laden ────────────────────────────────────────────────────────────────

def _load_context(gist_id: str, token: str) -> dict:
    """Laad plan, activiteiten (intervals.icu + Strava), wellness en bestaande analyse."""
    files = _load_gist(gist_id, token)

    plan = _parse_json(files.get("running_plan.json", ""), "running_plan.json") or {}
    wod_data = _parse_json(files.get("sugarwod_wod.json", ""), "sugarwod_wod.json") or {}
    analysis = _parse_json(files.get(ANALYSIS_FILE, ""), ANALYSIS_FILE) or {}

    intervals_data = wod_data.get("intervals_data") or {}
    strava_data = wod_data.get("strava_data") or {}

    intervals_by_date: dict = intervals_data.get("activities", {}).get("by_date", {})
    strava_by_date: dict = strava_data.get("activities_by_date", {})
    wellness_by_date: dict = intervals_data.get("wellness", {}).get("by_date", {})

    # Migratie / defaults zodat de structuur altijd compleet is
    analysis.setdefault("version", 1)
    analysis.setdefault("by_date", {})
    analysis.setdefault("pending_adjustments", [])

    return {
        "plan": plan,
        "intervals_by_date": intervals_by_date,
        "strava_by_date": strava_by_date,
        "wellness_by_date": wellness_by_date,
        "analysis": analysis,
    }


# ── Matching ──────────────────────────────────────────────────────────────────

def _is_run(activity: dict) -> bool:
    t = (activity.get("type") or "").lower().replace(" ", "")
    return any(rt in t for rt in RUN_TYPES)


def _run_activities_on(by_date: dict, day: str) -> list[dict]:
    return [a for a in by_date.get(day, []) if _is_run(a)]


def _match_activity_to_workout(
    workout: dict,
    intervals_by_date: dict,
    strava_by_date: dict,
) -> tuple[dict | None, str]:
    """Zoek de activiteit die het best bij de geplande workout past.

    Tolerantie ±1 dag (avond ervoor / ochtend erna). intervals.icu krijgt
    voorrang boven Strava (laps zijn nodig voor interval-analyse). Bij meerdere
    runs op één dag: kies de afstand het dichtst bij total_distance_km.

    Retourneert (activity, source) of (None, "").
    """
    w_date = workout.get("date", "")[:10]
    if not w_date:
        return None, ""
    try:
        d0 = date.fromisoformat(w_date)
    except ValueError:
        return None, ""

    target_m = (workout.get("total_distance_km") or 0) * 1000

    def best(cands: list[dict]) -> dict | None:
        if not cands:
            return None
        if target_m > 0:
            return min(cands, key=lambda a: abs((a.get("distance_m") or 0) - target_m))
        # Geen doelafstand bekend → langste run (meest waarschijnlijk de echte sessie)
        return max(cands, key=lambda a: a.get("distance_m") or 0)

    # Probeer per dag-offset, exacte dag eerst, dan ±1. intervals voor Strava.
    for offset in (0, -1, 1):
        day = (d0 + timedelta(days=offset)).isoformat()
        iv = _run_activities_on(intervals_by_date, day)
        chosen = best(iv)
        if chosen:
            return chosen, "intervals"
        st = _run_activities_on(strava_by_date, day)
        chosen = best(st)
        if chosen:
            return chosen, "strava"
    return None, ""


# ── Deterministische metrics ──────────────────────────────────────────────────

def _pace_to_sec(pace: str | None) -> int | None:
    if not pace or ":" not in str(pace):
        return None
    try:
        m, s = str(pace).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, TypeError):
        return None


def _sec_to_pace(sec: float | None) -> str | None:
    if sec is None or sec <= 0:
        return None
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _flatten_planned_steps(workout: dict) -> list[dict]:
    """Vouw repeats uit tot een platte, geordende lijst afstand-dragende stappen.

    Elke entry: {kind, distance_m, pace_min_sec, pace_max_sec, pace_mid_sec, hr_zone, label}
    kind ∈ {"warmup","work","cooldown"}. Rests worden overgeslagen (zelden als lap).
    """
    steps = workout.get("steps") or (workout.get("workout_doc") or {}).get("steps") or []
    flat: list[dict] = []

    def add(step: dict) -> None:
        stype = step.get("type")
        if stype not in ("warmup", "run", "cooldown"):
            return
        dist = step.get("distance_m")
        pmin = _pace_to_sec(step.get("pace_min"))
        pmax = _pace_to_sec(step.get("pace_max"))
        ptar = _pace_to_sec(step.get("pace_target"))
        if pmin and pmax:
            mid = (pmin + pmax) / 2
        elif ptar:
            mid = pmin = pmax = ptar
        else:
            mid = None
        flat.append({
            "kind": "work" if stype == "run" else stype,
            "distance_m": dist,
            "pace_min_sec": pmin,
            "pace_max_sec": pmax,
            "pace_mid_sec": mid,
            "hr_zone": step.get("hr_zone"),
            "label": step.get("label") or "",
        })

    def walk(seq: list[dict]) -> None:
        for s in seq:
            if s.get("type") == "repeat":
                count = int(s.get("count", 1) or 1)
                for _ in range(count):
                    walk(s.get("children", []))
            else:
                add(s)

    walk(steps)
    return flat


def _planned_avg_pace_sec(flat: list[dict]) -> float | None:
    """Afstand-gewogen gemiddeld doeltempo (sec/km) over alle stappen met pace."""
    num = den = 0.0
    for s in flat:
        if s.get("pace_mid_sec") and s.get("distance_m"):
            num += s["pace_mid_sec"] * s["distance_m"]
            den += s["distance_m"]
    return num / den if den else None


def _activity_avg_pace_sec(activity: dict) -> float | None:
    spd = activity.get("avg_speed_ms")
    if spd and spd > 0:
        return 1000.0 / spd  # sec per km
    dist = activity.get("distance_m")
    dur_min = activity.get("duration_min")
    if dist and dur_min and dist > 0:
        return (dur_min * 60) / (dist / 1000.0)
    return None


def _lap_pace_sec(lap: dict) -> int | None:
    p = _pace_to_sec(lap.get("pace_per_km"))
    if p:
        return p
    dist = lap.get("distance_m")
    dur = lap.get("duration_s") or lap.get("elapsed_time") or lap.get("moving_time")
    if dist and dur and dist > 0:
        return int(round(dur / (dist / 1000.0)))
    return None


def _detect_test_step(workout: dict) -> dict | None:
    """Vind de 12-min defensietest-stap (duration_s≈720 of label/naam)."""
    for s in workout.get("steps") or []:
        if s.get("type") == "run":
            label = (s.get("label") or "").lower()
            dur = s.get("duration_s")
            if (dur and int(dur) == TEST_DURATION_S) or "12-min" in label or "defensie" in label:
                return s
    return None


def _test_result(workout: dict, activity: dict, week_number: int | None) -> dict | None:
    """Bereken het 12-min testresultaat: afstand in de testlap vs fase-doel.

    Kiest de activiteit-lap met duur het dichtst bij 720s (tiebreak: grootste afstand)
    en normaliseert die naar exact 12 minuten. Geen geschikte lap → None (val terug
    op de generieke metrics).
    """
    if not _detect_test_step(workout):
        return None
    cands = [lap for lap in (activity.get("laps") or []) if lap.get("duration_s") and lap.get("distance_m")]
    if not cands:
        return None
    test_lap = min(cands, key=lambda l: (abs(l["duration_s"] - TEST_DURATION_S), -(l.get("distance_m") or 0)))
    # Sanity: testlap moet qua duur in de buurt van 12 min liggen
    if abs(test_lap["duration_s"] - TEST_DURATION_S) > TEST_DURATION_S * 0.35:
        return None

    test_dist = float(test_lap["distance_m"])
    test_dur = float(test_lap["duration_s"])
    projected = round(test_dist / test_dur * TEST_DURATION_S)

    phase = 2 if (week_number or 0) >= 11 else 1
    goal = PHASE2_GOAL_M if phase == 2 else PHASE1_GOAL_M
    return {
        "test_distance_m": round(test_dist),
        "test_duration_s": round(test_dur),
        "projected_12min_m": projected,
        "phase": phase,
        "goal_distance_m": goal,
        "phase1_goal_m": PHASE1_GOAL_M,
        "phase2_goal_m": PHASE2_GOAL_M,
        "goal_met": projected >= goal,
        "phase1_met": projected >= PHASE1_GOAL_M,
        "phase2_met": projected >= PHASE2_GOAL_M,
        "delta_vs_goal_m": projected - goal,
        "avg_pace": _sec_to_pace(test_dur / (test_dist / 1000)),
        "avg_hr": test_lap.get("avg_hr"),
    }


def _compute_metrics(workout: dict, activity: dict, source: str, week_number: int | None = None) -> dict:
    """Bereken deterministische gepland-vs-werkelijk metrics."""
    flat = _flatten_planned_steps(workout)
    planned_total_m = (workout.get("total_distance_km") or 0) * 1000
    if not planned_total_m:
        planned_total_m = sum(s.get("distance_m") or 0 for s in flat)
    actual_m = activity.get("distance_m") or 0

    metrics: dict = {
        "source": source,
        "planned_distance_m": round(planned_total_m) or None,
        "actual_distance_m": round(actual_m) or None,
    }
    if planned_total_m and actual_m:
        metrics["distance_pct"] = round(actual_m / planned_total_m * 100)

    planned_pace = _planned_avg_pace_sec(flat)
    actual_pace = _activity_avg_pace_sec(activity)
    metrics["planned_avg_pace"] = _sec_to_pace(planned_pace)
    metrics["actual_avg_pace"] = _sec_to_pace(actual_pace)
    if planned_pace and actual_pace:
        # Negatief = sneller dan gepland
        metrics["pace_delta_sec"] = round(actual_pace - planned_pace)

    if activity.get("avg_hr"):
        metrics["actual_avg_hr"] = activity["avg_hr"]

    # HR-zone adherentie: aandeel tijd in de door het plan beoogde zones
    target_zones = {s["hr_zone"] for s in flat if s.get("hr_zone")}
    hz = activity.get("hr_zone_times")
    if hz and isinstance(hz, list) and sum(hz) > 0:
        total = sum(hz)
        metrics["hr_zone_pct"] = [round(v / total * 100) for v in hz[:5]]
        if target_zones:
            zone_idx = {f"Z{i+1}": i for i in range(5)}
            in_target = sum(
                hz[zone_idx[z]] for z in target_zones
                if z in zone_idx and zone_idx[z] < len(hz)
            )
            metrics["target_zones"] = sorted(target_zones)
            metrics["hr_zone_adherence_pct"] = round(in_target / total * 100)

    # Lap-uitlijning op de werk-intervallen
    metrics.update(_align_laps(flat, activity))

    # 12-min defensietest: afstand-in-12-min vs fase-doel
    tr = _test_result(workout, activity, week_number)
    if tr:
        metrics["test_result"] = tr

    # Extra werkelijke metrics (alleen meenemen als de fetcher ze leverde)
    for fld in ("max_hr", "avg_watts", "weighted_watts", "intensity_pct",
                "decoupling_pct", "efficiency_factor", "pace_zone_times"):
        if activity.get(fld) is not None:
            metrics[fld] = activity[fld]
    if activity.get("gap_speed_ms"):
        metrics["gap_pace"] = _sec_to_pace(1000.0 / activity["gap_speed_ms"])
    if activity.get("max_speed_ms"):
        metrics["best_pace"] = _sec_to_pace(1000.0 / activity["max_speed_ms"])

    metrics["overall_verdict"] = _overall_verdict(metrics)
    return metrics


def _align_laps(flat: list[dict], activity: dict) -> dict:
    """Lijn activiteit-laps uit op de geplande afstand-stappen.

    Strategie: vergelijk de geplande werk-intervallen (run-stappen met pace) met de
    laps op volgorde. Door warmup/cooldown/handmatige splits matchen tellen zelden
    1:1, dus we vallen terug op 'partial' of 'summary_only'.
    """
    laps = activity.get("laps") or []
    work = [s for s in flat if s["kind"] == "work" and s.get("pace_mid_sec")]
    if not laps:
        return {"lap_alignment": "summary_only"}
    if not work:
        return {"lap_alignment": "summary_only"}

    # Filter laps die plausibel werk-intervallen zijn: niet-triviale afstand.
    run_laps = [lap for lap in laps if (lap.get("distance_m") or 0) >= 100]

    aligned: list[dict] = []
    # Exacte 1:1 als evenveel laps als werk-intervallen
    if len(run_laps) == len(work):
        alignment = "exact"
        pairs = list(zip(work, run_laps))
    elif len(laps) == len(flat):
        # Alle stappen (incl warmup/cooldown) matchen alle laps 1:1
        alignment = "exact"
        work_pairs = []
        for s, lap in zip(flat, laps):
            if s["kind"] == "work" and s.get("pace_mid_sec"):
                work_pairs.append((s, lap))
        pairs = work_pairs
    else:
        # Best-effort: lijn op volgorde uit, markeer als partial
        alignment = "partial"
        n = min(len(work), len(run_laps))
        pairs = list(zip(work[:n], run_laps[:n]))

    hits = 0
    for i, (step, lap) in enumerate(pairs, 1):
        lap_pace = _lap_pace_sec(lap)
        entry: dict = {
            "interval": i,
            "planned_distance_m": step.get("distance_m"),
            "actual_distance_m": lap.get("distance_m"),
            "planned_pace": _sec_to_pace(step.get("pace_mid_sec")),
            "actual_pace": _sec_to_pace(lap_pace),
        }
        if lap.get("avg_hr"):
            entry["actual_hr"] = lap["avg_hr"]
        if lap_pace and step.get("pace_min_sec") and step.get("pace_max_sec"):
            in_band = step["pace_min_sec"] <= lap_pace <= step["pace_max_sec"]
            entry["in_band"] = in_band
            entry["pace_delta_sec"] = round(lap_pace - step["pace_mid_sec"])
            if in_band:
                hits += 1
        aligned.append(entry)

    result = {"lap_alignment": alignment, "intervals": aligned}
    if aligned:
        banded = [a for a in aligned if "in_band" in a]
        if banded:
            result["intervals_in_band"] = hits
            result["intervals_total"] = len(banded)
    return result


def _overall_verdict(metrics: dict) -> str:
    """Deterministisch eindoordeel op basis van afstand en tempo."""
    dist_pct = metrics.get("distance_pct")
    delta = metrics.get("pace_delta_sec")
    if dist_pct is not None and dist_pct < 60:
        return "partial"
    if metrics.get("lap_alignment") == "partial":
        # Mengvorm — laat tempo beslissen maar markeer voorzichtig
        pass
    if delta is None:
        return "on_target"
    if delta <= -15:
        return "faster"
    if delta >= 20:
        return "slower"
    return "on_target"


# ── Claude kwalitatieve analyse ───────────────────────────────────────────────

def _format_activity_brief(activity: dict, source: str) -> list[str]:
    lines = [f"  Source: {source}", f"  Name: {activity.get('name', 'Run')}"]
    if activity.get("distance_m"):
        lines.append(f"  Distance: {round(activity['distance_m']/1000, 2)}km")
    if activity.get("duration_min"):
        lines.append(f"  Duration: {activity['duration_min']}min")
    ap = _activity_avg_pace_sec(activity)
    if ap:
        lines.append(f"  Avg pace: {_sec_to_pace(ap)}/km")
    if activity.get("avg_hr"):
        lines.append(f"  Avg HR: {activity['avg_hr']}bpm")
    if activity.get("max_hr"):
        lines.append(f"  Max HR: {activity['max_hr']}bpm")
    if activity.get("rpe"):
        lines.append(f"  RPE: {activity['rpe']}")
    hz = activity.get("hr_zone_times")
    if hz and isinstance(hz, list) and sum(hz) > 0:
        total = sum(hz)
        zone_str = " ".join(f"Z{i+1}:{round(v/total*100)}%" for i, v in enumerate(hz[:5]) if v > 0)
        lines.append(f"  HR zones: {zone_str}")
    pz = activity.get("pace_zone_times")
    if pz and isinstance(pz, list) and sum(pz) > 0:
        total = sum(pz)
        zone_str = " ".join(f"Z{i+1}:{round(v/total*100)}%" for i, v in enumerate(pz) if v > 0)
        lines.append(f"  Pace zones: {zone_str}")
    for i, lap in enumerate(activity.get("laps", []), 1):
        lp = [f"    lap {i}:"]
        if lap.get("distance_m"):
            lp.append(f"{lap['distance_m']}m")
        lap_pace = _lap_pace_sec(lap)
        if lap_pace:
            lp.append(f"{_sec_to_pace(lap_pace)}/km")
        if lap.get("avg_hr"):
            lp.append(f"HR {lap['avg_hr']}bpm")
        lines.append(" ".join(lp))
    return lines


def _build_analysis_context(
    workout: dict,
    activity: dict,
    source: str,
    metrics: dict,
    upcoming: list[dict],
    wellness_by_date: dict,
) -> str:
    sections: list[str] = []

    sections.append(
        f"Planned workout: [{workout.get('session', '?')}] {workout.get('date')} — "
        f"{workout.get('name', '?')} ({workout.get('total_distance_km', '?')}km)\n"
        + (f"  Goal: {workout['description']}\n" if workout.get("description") else "")
        + "\n".join(_format_steps_brief(workout.get("steps") or [], "  "))
    )

    sections.append("Actual activity:\n" + "\n".join(_format_activity_brief(activity, source)))

    metric_lines = []
    if metrics.get("distance_pct") is not None:
        metric_lines.append(f"  Distance: {metrics['distance_pct']}% of planned")
    if metrics.get("planned_avg_pace") and metrics.get("actual_avg_pace"):
        delta = metrics.get("pace_delta_sec")
        sign = "+" if (delta or 0) >= 0 else ""
        metric_lines.append(
            f"  Avg pace: planned {metrics['planned_avg_pace']}/km vs actual "
            f"{metrics['actual_avg_pace']}/km ({sign}{delta}s/km)"
        )
    if metrics.get("hr_zone_adherence_pct") is not None:
        metric_lines.append(
            f"  HR-zone adherence: {metrics['hr_zone_adherence_pct']}% of time in target "
            f"zones {','.join(metrics.get('target_zones', []))}"
        )
    if metrics.get("intervals_total"):
        metric_lines.append(
            f"  Intervals in pace band: {metrics.get('intervals_in_band', 0)}/"
            f"{metrics['intervals_total']} (alignment: {metrics.get('lap_alignment')})"
        )
    tr = metrics.get("test_result")
    if tr:
        status = "MET" if tr["goal_met"] else "MISSED"
        metric_lines.append(
            f"  12-MIN TEST: {tr['test_distance_m']}m in {tr['test_duration_s']}s "
            f"({tr.get('avg_pace', '?')}/km) — phase {tr['phase']} goal {tr['goal_distance_m']}m "
            f"{status} ({tr['delta_vs_goal_m']:+d}m); phase1(2200) {'✓' if tr['phase1_met'] else '✗'}, "
            f"phase2(2700) {'✓' if tr['phase2_met'] else '✗'}"
        )
    if metrics.get("gap_pace"):
        metric_lines.append(f"  GAP (gradient-adjusted pace): {metrics['gap_pace']}/km")
    if metrics.get("max_hr"):
        metric_lines.append(f"  Max HR: {metrics['max_hr']}bpm")
    if metrics.get("avg_watts"):
        line = f"  Power: avg {metrics['avg_watts']}W"
        if metrics.get("weighted_watts"):
            line += f", weighted {metrics['weighted_watts']}W"
        metric_lines.append(line)
    if metrics.get("decoupling_pct") is not None:
        metric_lines.append(f"  Aerobic decoupling (cardiac drift): {metrics['decoupling_pct']}%")
    if metrics.get("efficiency_factor"):
        metric_lines.append(f"  Efficiency factor (pace/HR): {metrics['efficiency_factor']}")
    metric_lines.append(f"  Deterministic verdict: {metrics.get('overall_verdict')}")
    sections.append("Computed metrics:\n" + "\n".join(metric_lines))

    # Recovery-context (laatste 3 dagen rond de run)
    w_date = workout.get("date", "")[:10]
    well_lines = []
    for d in sorted(wellness_by_date.keys(), reverse=True):
        if d > w_date:
            continue
        ww = wellness_by_date[d]
        parts = [f"  {d}:"]
        if ww.get("hrv"):           parts.append(f"HRV={ww['hrv']}ms")
        if ww.get("resting_hr"):    parts.append(f"RHR={ww['resting_hr']}bpm")
        if ww.get("sleep_hrs"):     parts.append(f"sleep={ww['sleep_hrs']}h")
        if ww.get("tsb") is not None: parts.append(f"TSB={ww['tsb']:+.0f}")
        if len(parts) > 1:
            well_lines.append(" ".join(parts))
        if len(well_lines) >= 3:
            break
    if well_lines:
        sections.append("Recovery context:\n" + "\n".join(well_lines))

    if upcoming:
        up_lines = []
        for w in upcoming:
            up_lines.append(
                f"  [{w.get('session', '?')}] {w.get('date')} — {w.get('name', '?')} "
                f"({w.get('total_distance_km', '?')}km)"
            )
            steps = w.get("steps") or []
            up_lines.extend(_format_steps_brief(steps, "    "))
        sections.append(
            "Upcoming workouts (you may propose adjustments to these):\n" + "\n".join(up_lines)
        )
    else:
        sections.append("Upcoming workouts: none planned")

    return "\n\n".join(sections)


def _analyze_with_claude(context_text: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=_ANALYSIS_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Analyse the following executed workout and return your decision. "
                "Reply with ONLY the JSON object starting with '{'.\n\n" + context_text
            ),
        }],
    )
    raw = msg.content[0].text.strip()
    if msg.stop_reason == "max_tokens":
        log.error("Claude-respons afgekapt door max_tokens — eerste 500: %s", raw[:500])
        raise RuntimeError("Claude response truncated by max_tokens limit")
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    if not raw:
        raise ValueError("Claude gaf een lege respons")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        m = re.search(r'\{\s*"summary"', raw)
        if m:
            try:
                return json.loads(raw[m.start():])
            except json.JSONDecodeError:
                pass
        log.error("Claude gaf geen geldige JSON (%s). Raw:\n%s", exc, raw[:1000])
        raise


# ── Notificatie ───────────────────────────────────────────────────────────────

def _notify_analysis(workout: dict, metrics: dict, coach: dict, has_proposal: bool) -> None:
    dag_nl = ["ma", "di", "wo", "do", "vr", "za", "zo"]
    try:
        d = datetime.strptime(workout["date"][:10], "%Y-%m-%d")
        dag = dag_nl[d.weekday()]
        date_str = f"{dag} {d.day}/{d.month}"
    except (ValueError, KeyError):
        date_str = workout.get("date", "")

    name = workout.get("name", "Run")
    title = f"Run-analyse: {name}"

    verdict_nl = {
        "on_target": "✅ Volgens plan",
        "faster": "⚡ Sneller dan gepland",
        "slower": "🐢 Trager dan gepland",
        "partial": "◑ Deels voltooid",
        "missed": "✕ Gemist",
    }
    verdict = coach.get("verdict") or metrics.get("overall_verdict") or "on_target"
    lines = [f"{date_str} — {verdict_nl.get(verdict, verdict)}"]

    tr = metrics.get("test_result")
    if tr:
        if tr["goal_met"]:
            extra = "✓ fase 2 gehaald!" if tr["phase2_met"] else f"nog {PHASE2_GOAL_M - tr['projected_12min_m']}m tot fase 2"
        else:
            extra = f"nog {-tr['delta_vs_goal_m']}m tot eis"
        lines.append(f"🎯 12-min test: {tr['test_distance_m']}m — {extra}")

    if metrics.get("actual_distance_m"):
        km = metrics["actual_distance_m"] / 1000
        pace = metrics.get("actual_avg_pace")
        lines.append(f"{km:.1f}km" + (f" @ {pace}/km" if pace else ""))
    if metrics.get("hr_zone_adherence_pct") is not None:
        lines.append(f"HR-zones: {metrics['hr_zone_adherence_pct']}% in doel")
    if coach.get("execution_score") is not None:
        lines.append(f"Score: {coach['execution_score']}/10")
    if coach.get("summary"):
        lines.append("")
        lines.append(coach["summary"])
    if has_proposal:
        lines.append("")
        lines.append("Coach stelt aanpassing voor — bekijk in app")

    notify.send_notification(title, "\n".join(lines))


# ── Analyse-modus ─────────────────────────────────────────────────────────────

def _upcoming_workouts(plan: dict, today: str) -> list[dict]:
    return [
        w for w in plan.get("workouts", [])
        if w.get("date", "")[:10] > today and not w.get("cancelled")
    ]


def _run_analyze(gist_id: str, github_token: str) -> None:
    ctx = _load_context(gist_id, github_token)
    plan = ctx["plan"]
    analysis = ctx["analysis"]
    by_date = analysis["by_date"]

    today = date.today().isoformat()
    upcoming = _upcoming_workouts(plan, today)

    run_workouts = [
        w for w in plan.get("workouts", [])
        if (w.get("type") in RUN_TYPES or w.get("session") in ("speed", "long_run", "easy")
            or (w.get("steps") or w.get("total_distance_km")))
        and not w.get("cancelled")
        and w.get("date", "")[:10] <= today
    ]

    changed = False
    notified = 0
    for workout in run_workouts:
        w_date = workout.get("date", "")[:10]
        existing = by_date.get(w_date)
        if existing and existing.get("analyzed_at"):
            continue  # idempotent — al geanalyseerd

        activity, source = _match_activity_to_workout(
            workout, ctx["intervals_by_date"], ctx["strava_by_date"]
        )

        if not activity:
            # Geen match: pas na >2 dagen als gemist markeren (kan nog syncen)
            try:
                age_days = (date.today() - date.fromisoformat(w_date)).days
            except ValueError:
                age_days = 0
            if age_days > 2 and not existing:
                by_date[w_date] = {
                    "date": w_date,
                    "session": workout.get("session"),
                    "workout_name": workout.get("name"),
                    "completed": False,
                    "missed": True,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                }
                changed = True
                log.info("Workout %s gemarkeerd als gemist (geen activiteit)", w_date)
            continue

        log.info("Match: workout %s ↔ %s-activiteit (%s)", w_date, source, activity.get("name"))
        week_number = workout.get("week_number") or plan.get("week_number")
        metrics = _compute_metrics(workout, activity, source, week_number)

        context_text = _build_analysis_context(
            workout, activity, source, metrics, upcoming, ctx["wellness_by_date"]
        )
        log.info("Analyse-context:\n%s", context_text)

        log.info("Claude raadplegen voor analyse %s...", w_date)
        t0 = time.monotonic()
        try:
            result = _analyze_with_claude(context_text)
        except Exception as exc:
            log.error("Claude-analyse mislukt voor %s: %s", w_date, exc)
            continue
        dur_s = round(time.monotonic() - t0)

        coach = {
            "summary": result.get("summary", ""),
            "execution_score": result.get("execution_score"),
            "verdict": result.get("verdict") or metrics.get("overall_verdict"),
            "key_observations": result.get("key_observations", []),
        }

        activity_id = activity.get("intervals_id") or activity.get("activity_id")
        by_date[w_date] = {
            "date": w_date,
            "session": workout.get("session"),
            "workout_name": workout.get("name"),
            "completed": True,
            "missed": False,
            "activity_source": source,
            "activity_id": activity_id,
            "metrics": metrics,
            "coach": coach,
            "verdict": coach["verdict"],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "ai_duration_s": dur_s,
        }
        changed = True

        # Voorstellen toevoegen als pending (suggest-only)
        proposals = result.get("proposed_adjustments", []) or []
        new_proposals = []
        for prop in proposals:
            target_date = (prop.get("target_date") or prop.get("workout", {}).get("date") or "")[:10]
            spec = prop.get("workout") or {}
            if not target_date or not spec.get("steps"):
                continue
            step_errors = _validate_steps(spec.get("steps", []))
            if step_errors:
                log.warning("Voorstel voor %s afgewezen — ongeldige stappen: %s",
                            target_date, "; ".join(step_errors))
                continue
            adj_id = f"adj-{w_date}-{target_date}-{len(analysis['pending_adjustments']) + len(new_proposals)}"
            new_proposals.append({
                "id": adj_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_date": w_date,
                "target_date": target_date,
                "session": prop.get("session") or spec.get("session"),
                "rationale": prop.get("rationale", ""),
                "status": "pending",
                "workout": spec,
            })
        if new_proposals:
            analysis["pending_adjustments"].extend(new_proposals)
            log.info("%d voorstel(len) toegevoegd voor run %s", len(new_proposals), w_date)

        # Notificatie alleen voor nieuw geanalyseerde voltooide run
        try:
            _notify_analysis(workout, metrics, coach, bool(new_proposals))
            notified += 1
        except Exception as exc:
            log.warning("Notificatie mislukt voor %s: %s", w_date, exc)

    if changed:
        analysis["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_to_gist(gist_id, github_token, ANALYSIS_FILE,
                      json.dumps(analysis, indent=2, ensure_ascii=False))
        log.info("%s opgeslagen (%d notificatie(s))", ANALYSIS_FILE, notified)
    else:
        log.info("Geen nieuwe runs om te analyseren")


# ── Apply-modus ───────────────────────────────────────────────────────────────

def _run_apply(gist_id: str, github_token: str, athlete_id: str, api_key: str) -> None:
    """Voer goedgekeurde voorstellen (status='applied') door naar plan + intervals.icu."""
    ctx = _load_context(gist_id, github_token)
    plan = ctx["plan"]
    analysis = ctx["analysis"]

    pending = [
        a for a in analysis.get("pending_adjustments", [])
        if a.get("status") == "applied" and not a.get("applied_pushed_at")
    ]
    if not pending:
        log.info("Geen goedgekeurde voorstellen om door te voeren")
        return

    workouts = list(plan.get("workouts", []))
    plan_changed = False

    for adj in pending:
        target_date = (adj.get("target_date") or "")[:10]
        session = adj.get("session")
        spec = dict(adj.get("workout") or {})
        if not target_date or not spec.get("steps"):
            log.warning("Voorstel %s ongeldig — overgeslagen", adj.get("id"))
            adj["applied_pushed_at"] = datetime.now(timezone.utc).isoformat()
            adj["apply_error"] = "ongeldig voorstel"
            continue

        orig = next(
            (w for w in workouts
             if w.get("date", "")[:10] == target_date
             and (not session or w.get("session") == session)
             and not w.get("cancelled")),
            next((w for w in workouts
                  if w.get("date", "")[:10] == target_date and not w.get("cancelled")), None),
        )
        if orig is None:
            log.warning("Voorstel %s: geen workout op %s — overgeslagen", adj.get("id"), target_date)
            adj["applied_pushed_at"] = datetime.now(timezone.utc).isoformat()
            adj["apply_error"] = "doel-workout niet gevonden"
            continue

        step_errors = _validate_steps(spec.get("steps", []))
        if step_errors:
            log.error("Voorstel %s afgewezen — ongeldige stappen: %s",
                      adj.get("id"), "; ".join(step_errors))
            adj["applied_pushed_at"] = datetime.now(timezone.utc).isoformat()
            adj["apply_error"] = "ongeldige stappen"
            continue

        # Behoud meta-velden van het origineel
        spec["date"] = orig.get("date")
        spec.setdefault("session", orig.get("session"))
        spec.setdefault("time", orig.get("time", "20:00" if spec.get("session") == "speed" else "09:00"))
        spec.setdefault("week_number", orig.get("week_number"))
        spec["full_description"] = _build_description(spec)
        spec["adjusted_from_analysis"] = adj.get("id")

        # Verwijder oud intervals.icu event
        old_event_id = orig.get("event_id")
        if old_event_id:
            try:
                session_req = requests.Session()
                session_req.auth = ("API_KEY", api_key)
                resp = session_req.delete(
                    f"{INTERVALS_BASE}/{athlete_id}/events/{old_event_id}", timeout=20
                )
                if resp.ok:
                    log.info("Oud event %s verwijderd voor %s", old_event_id, target_date)
                else:
                    log.warning("Kon oud event %s niet verwijderen: %s", old_event_id, resp.status_code)
            except Exception as exc:
                log.warning("Fout bij verwijderen event %s: %s", old_event_id, exc)

        # Nieuw event aanmaken
        event = _build_intervals_event(spec)
        results = _push_to_intervals(athlete_id, api_key, [event])
        if results and results[0]:
            spec["event_id"] = results[0].get("id")
            if "workout_doc" in event:
                spec["workout_doc"] = event["workout_doc"]

        # Vervang in plan
        for i, w in enumerate(workouts):
            if w is orig:
                workouts[i] = spec
                break
        plan_changed = True
        adj["applied_pushed_at"] = datetime.now(timezone.utc).isoformat()
        log.info("Voorstel %s toegepast op workout %s", adj.get("id"), target_date)

    if plan_changed:
        plan["workouts"] = workouts
        _save_to_gist(gist_id, github_token, "running_plan.json",
                      json.dumps(plan, indent=2, ensure_ascii=False))
        log.info("running_plan.json bijgewerkt na toepassen voorstel(len)")

    analysis["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_to_gist(gist_id, github_token, ANALYSIS_FILE,
                  json.dumps(analysis, indent=2, ensure_ascii=False))
    log.info("%s bijgewerkt (applied_pushed_at gezet)", ANALYSIS_FILE)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    mode = "analyze"
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg == "--apply":
            mode = "apply"

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    required = [("GIST_ID", gist_id), ("GITHUB_TOKEN", github_token)]
    if mode == "analyze":
        required.append(("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")))
    if mode == "apply":
        required += [("INTERVALS_ATHLETE_ID", athlete_id), ("INTERVALS_API_KEY", api_key)]
    missing = [n for n, v in required if not v]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    log.info("Modus: %s", mode)
    if mode == "apply":
        _run_apply(gist_id, github_token, athlete_id, api_key)
    else:
        _run_analyze(gist_id, github_token)
    log.info("Klaar.")


if __name__ == "__main__":
    main()
