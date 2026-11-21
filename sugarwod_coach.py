"""AI-coaching voor fetch_sugarwod.py: herstel-advies, workout-plannen, ACWR en deload-detectie."""
from __future__ import annotations

import logging
import os
from datetime import date as date_cls, datetime, timedelta

from bs4 import BeautifulSoup

from injuries import format_injuries_prompt

from sugarwod_config import (  # noqa: E501
    DINNER_TIME,
    BREAKFAST,
    _MAIN_KEYWORDS,
)

log = logging.getLogger("sugarwod")


# ──────────────────────────────────────────────────────────────
# AI workout plan generation
# ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()


def _detect_team_size(text: str) -> int | None:
    """Return team size (2 or 3) if workout is a partner/team workout, else None."""
    import re
    t = text.lower()
    # Explicit team size: "teams of 3", "team of 2", "pair of 3", etc.
    m = re.search(r'\bteam(?:s)?\s+of\s+(\d+)', t)
    if m:
        return int(m.group(1))
    m = re.search(r'\bpair(?:s)?\s+of\s+(\d+)', t)
    if m:
        return int(m.group(1))
    # "in pairs" / "with a partner" → 2
    if re.search(r'\bin\s+pairs?\b', t) or re.search(r'\bwith\s+a\s+partner\b', t):
        return 2
    # Title contains "team metcon" → likely 2 unless description says otherwise
    if 'team metcon' in t:
        return 2
    return None


def _training_time_context(date_str: str, signed_up_times: dict[str, str] | None = None) -> str:
    """Return a prompt snippet about training time and meal timing for the given date.

    Only uses actual sign-up time from the Gist state; returns empty string if the
    athlete is not signed up for a class on this date.
    """
    try:
        date_cls.fromisoformat(date_str)
    except ValueError:
        return ""
    # Only use actual sign-up time — no fallback to static schedule
    time_str = (signed_up_times or {}).get(date_str)
    if not time_str:
        return ""
    # Compare training time to breakfast and dinner
    train_h, train_m = map(int, time_str.split(":"))
    dinner_h, dinner_m = map(int, DINNER_TIME.split(":"))
    breakfast_h, breakfast_m = map(int, BREAKFAST["time"].split(":"))
    train_minutes = train_h * 60 + train_m
    dinner_minutes = dinner_h * 60 + dinner_m
    breakfast_minutes = breakfast_h * 60 + breakfast_m

    if train_minutes <= breakfast_minutes + 30:
        # Training at or just after breakfast — likely fasted or very light pre-workout
        meal_relation = (
            f"Training is early ({time_str}), around or just after breakfast ({BREAKFAST['time']}). "
            f"Standard breakfast: {BREAKFAST['description']} "
            "The athlete is probably training fasted or semi-fasted. Advise whether to eat something small or train fasted, "
            "and emphasize recovery nutrition afterward."
        )
    elif train_minutes < dinner_minutes - 60:
        # Morning/midday workout well before dinner — had breakfast, dinner is recovery meal
        meal_relation = (
            f"Training is in the morning ({time_str}). "
            f"Standard breakfast (~{BREAKFAST['time']}): {BREAKFAST['description']} "
            "The athlete ate breakfast before training (protein-rich). Dinner is the recovery meal."
        )
    elif train_minutes < dinner_minutes:
        meal_relation = (
            f"Training is shortly before dinner ({time_str}, dinner at {DINNER_TIME}). "
            "The athlete can have dinner immediately after training as a recovery meal — ideal timing window."
        )
    else:
        meal_relation = (
            f"Training is in the evening ({time_str}), after dinner ({DINNER_TIME}). "
            "The athlete has already eaten before training; meal choice is less critical for immediate recovery."
        )
    return f"\nTraining time: {time_str}. {meal_relation}"


_EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_EN_MONTHS = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _nl_date(date_str: str) -> str:
    """Format an ISO date string as 'Weekday D Month' in English, e.g. 'Sunday 12 April'."""
    try:
        d = date_cls.fromisoformat(date_str)
        return f"{_EN_WEEKDAYS[d.weekday()]} {d.day} {_EN_MONTHS[d.month - 1]}"
    except Exception:
        return date_str


def _compute_acwr(
    strava_data: dict | None,
    intervals_data: dict | None = None,
) -> dict | None:
    """Compute a 7:28 Acute:Chronic Workload Ratio.

    Primary source: intervals.icu training_load (covers all Garmin activities incl. CrossFit).
    Fallback: Strava suffer_score (only activities synced to Strava).
    Acute window = last 7 days, chronic window = last 28 days (sports science standard).
    Returns None if insufficient data.
    """
    today = date_cls.today()

    # Build per-day load from intervals.icu (all Garmin activities, most comprehensive)
    intervals_by_date: dict = {}
    if intervals_data:
        for day, acts in (intervals_data.get("activities") or {}).get("by_date", {}).items():
            total_tl = sum((a.get("training_load") or 0) for a in (acts if isinstance(acts, list) else [acts]))
            if total_tl > 0:
                intervals_by_date[day] = total_tl

    # Strava suffer_score as fallback for days not in intervals.icu
    strava_by_date: dict = {}
    if strava_data:
        for day, acts in (strava_data.get("activities_by_date") or {}).items():
            total_ss = sum((a.get("suffer_score") or 0) for a in acts)
            if total_ss > 0:
                strava_by_date[day] = total_ss

    # Prefer intervals.icu; fall back to Strava for missing days
    combined_by_date = {**strava_by_date, **intervals_by_date}
    if len(combined_by_date) < 4:
        return None

    acute_total = 0.0
    chronic_total = 0.0
    for i in range(28):
        d = (today - timedelta(days=i)).isoformat()
        day_score = combined_by_date.get(d, 0.0)
        chronic_total += day_score
        if i < 7:
            acute_total += day_score

    acute_avg = acute_total / 7
    chronic_avg = chronic_total / 28
    if chronic_avg == 0:
        return None
    ratio = round(acute_avg / chronic_avg, 2)
    if ratio < 0.8:
        status = "onderbelast"
    elif ratio <= 1.3:
        status = "optimale zone"
    elif ratio <= 1.5:
        status = "hoge belasting — extra herstel gewenst"
    else:
        status = "overbelasting — blessurerisico verhoogd"
    source = "intervals.icu+Strava" if intervals_by_date and strava_by_date else (
        "intervals.icu" if intervals_by_date else "Strava"
    )
    return {
        "acute_7d": round(acute_avg, 1),
        "chronic_28d": round(chronic_avg, 1),
        "ratio": ratio,
        "status": status,
        "source": source,
    }


def _compute_barbell_trends(history: list[dict], current: dict) -> dict[str, float]:
    """Compare current 1RMs to the closest snapshot from ~4 weeks ago.

    Returns a dict of {lift_name: delta_kg} for lifts that changed.
    """
    if not history or not current:
        return {}
    today = date_cls.today()
    target_date = (today - timedelta(weeks=4)).isoformat()
    past_snapshots = [h for h in history if h.get("date", "") <= target_date]
    if not past_snapshots:
        past_snapshots = sorted(history, key=lambda h: h.get("date", ""))[:1]
    if not past_snapshots:
        return {}
    past = max(past_snapshots, key=lambda h: h.get("date", ""))
    past_lifts = past.get("lifts", {})
    trends: dict[str, float] = {}
    for lift, maxes in current.items():
        c1rm = maxes.get("1RM")
        p1rm = (past_lifts.get(lift) or {}).get("1RM")
        if c1rm and p1rm and c1rm != p1rm:
            trends[lift] = round(c1rm - p1rm, 1)
    return trends


def generate_recovery_advice(
    past_workouts: list[dict],
    upcoming_workout: dict | None,
    barbell_lifts: dict,
    athlete_profile: dict,
    today: "date_cls | None" = None,
    strava_data: "dict | None" = None,
    health_input: "dict | None" = None,
    signed_up_times: dict[str, str] | None = None,
    health_history: list[dict] | None = None,
    previous_advice: list[dict] | None = None,
    barbell_history: list[dict] | None = None,
    personal_records: list[dict] | None = None,
    benchmark_workouts: list[dict] | None = None,
    withings_data: "dict | None" = None,
    environmental_data: "dict | None" = None,
    intervals_data: "dict | None" = None,
    personal_events: list[dict] | None = None,
    running_plan: "dict | None" = None,
    deload_detected: bool = False,
    now_time: str | None = None,
    injuries: list[dict] | None = None,
) -> str:
    """
    Generate a daily recovery/intensity advice based on recent workouts and
    what's coming up next.  Returns a markdown string.

    If strava_data is provided, activity details (HR, duration) per WOD date
    are included to assess training load.

    If health_input is provided (subjectieve scores: energie, spierpijn, stress),
    these are included as primary physiological recovery indicators.
    Sleep quality is sourced exclusively from the automatic Garmin sleep score.

    If health_history is provided (list of past health_input entries), the AI
    can identify trends over time (e.g. recurring low energy on Thursdays).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping recovery advice generation")
        return ""

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping recovery advice generation")
        return ""

    client = anthropic.Anthropic(api_key=api_key)

    # Build activities-by-date lookup for WOD matching (Strava primary, intervals.icu fallback)
    strava_by_date: dict = (strava_data or {}).get("activities_by_date") or {}
    intervals_acts_by_date: dict = (intervals_data or {}).get("activities", {}).get("by_date") or {}
    log.info("Strava matching: %d datums beschikbaar: %s", len(strava_by_date), sorted(strava_by_date.keys()))
    log.info("Intervals.icu activiteiten: %d datums beschikbaar", len(intervals_acts_by_date))

    past_text = ""
    matched_acts = 0
    for w in past_workouts:
        date = w.get("date", "?")
        title = w.get("title", "WOD")
        desc = _strip_html(w.get("description", ""))[:400]
        past_text += f"\n**{_nl_date(date)} — {title}**\n{desc}\n"

        # Strava activiteiten voor deze datum
        if date in strava_by_date:
            matched_acts += 1
            for act in strava_by_date[date]:
                avg_hr = act.get("avg_hr")
                max_hr = act.get("max_hr")
                dur = act.get("duration_min")
                cal = act.get("calories")
                act_name = act.get("name", "")
                suffer = act.get("suffer_score")
                rpe = act.get("perceived_exertion")
                elapsed = act.get("elapsed_min")
                dist_m = act.get("distance_m")
                pace_str = ""
                if dist_m and dur and dur > 0:
                    pace_sec_per_km = (dur * 60) / (dist_m / 1000)
                    pace_min = int(pace_sec_per_km // 60)
                    pace_sec = int(pace_sec_per_km % 60)
                    pace_str = f", {dist_m / 1000:.2f}km @ {pace_min}:{pace_sec:02d}/km"
                strava_line = (
                    f"  ↳ Strava: {dur}min"
                    + (f" (total {elapsed}min)" if elapsed else "")
                    + (f" ({act_name})" if act_name else "")
                    + (f", avg.HR {avg_hr:.0f} bpm" if avg_hr else "")
                    + (f", max.HR {max_hr:.0f} bpm" if max_hr else "")
                    + (f", {cal:.0f} kcal" if cal else "")
                    + (f", RE {suffer:.0f}" if suffer else "")
                    + (f", RPE {rpe}" if rpe else "")
                    + pace_str
                )
                past_text += strava_line + "\n"

        # Intervals.icu activiteiten voor deze datum (altijd tonen — rijker dan Strava voor hardlopen)
        if date in intervals_acts_by_date:
            if date not in strava_by_date:
                matched_acts += 1
            for act in intervals_acts_by_date[date]:
                dur = act.get("duration_min")
                act_name = act.get("name", "") or act.get("type", "")
                avg_hr = act.get("avg_hr")
                max_hr = act.get("max_hr")
                cal = act.get("calories")
                tl = act.get("training_load") or act.get("trimp")
                rpe = act.get("rpe")
                dist_m = act.get("distance_m")
                cadence = act.get("avg_cadence")
                elev = act.get("elevation_m")
                pace_str = ""
                if dist_m and act.get("avg_speed_ms") and act["avg_speed_ms"] > 0:
                    spm = 1000 / act["avg_speed_ms"] / 60
                    pace_str = f", {dist_m / 1000:.1f}km @ {int(spm)}:{int((spm % 1) * 60):02d}/km"
                elif dist_m and dur and dur > 0:
                    pace_sec_per_km = (dur * 60) / (dist_m / 1000)
                    pace_str = f", {dist_m / 1000:.1f}km @ {int(pace_sec_per_km // 60)}:{int(pace_sec_per_km % 60):02d}/km"
                icu_line = (
                    f"  ↳ Intervals.icu ({act_name}): {dur}min"
                    + pace_str
                    + (f", avg.HR {avg_hr} bpm" if avg_hr else "")
                    + (f", max.HR {max_hr} bpm" if max_hr else "")
                    + (f", cadans {round(cadence * 2)}spm" if cadence else "")
                    + (f", +{elev}m" if elev else "")
                    + (f", {cal} kcal" if cal else "")
                    + (f", RPE {rpe}" if rpe else "")
                    + (f", TL {round(tl)}" if tl is not None else "")
                )
                past_text += icu_line + "\n"
                # HR-zone verdeling
                hz = act.get("hr_zone_times")
                if hz and isinstance(hz, list) and sum(hz) > 0:
                    total = sum(hz)
                    zone_str = " ".join(
                        f"Z{i+1}:{round(v/total*100)}%"
                        for i, v in enumerate(hz[:5]) if v > 0
                    )
                    past_text += f"    HR zones: {zone_str}\n"
                # Laps voor hardlopen
                for i, lap in enumerate(act.get("laps", []), 1):
                    lp_parts = [f"    lap {i}:"]
                    if lap.get("distance_m"): lp_parts.append(f"{lap['distance_m']}m")
                    if lap.get("pace_per_km"): lp_parts.append(f"{lap['pace_per_km']}/km")
                    if lap.get("avg_hr"):     lp_parts.append(f"HR {lap['avg_hr']}bpm")
                    if lap.get("avg_cadence"): lp_parts.append(f"{round(lap['avg_cadence'] * 2)}spm")
                    past_text += " ".join(lp_parts) + "\n"

    log.info("Activiteiten gematcht aan WODs: %d van %d", matched_acts, len(past_workouts))

    upcoming_text = ""
    upcoming_timing_context = ""
    upcoming_workout_label = "Next workout"
    if upcoming_workout:
        date = upcoming_workout.get("date", "?")
        title = upcoming_workout.get("title", "WOD")
        desc = _strip_html(upcoming_workout.get("description", ""))[:400]
        upcoming_text = f"**{_nl_date(date)} — {title}**\n{desc}"
        upcoming_timing_context = _training_time_context(date, signed_up_times)
        if today and date == today.isoformat():
            upcoming_workout_label = "Today's workout (this is today — apply intensity advice accordingly)"
    else:
        upcoming_text = "No upcoming workout known."

    barbell_text = (
        "\n".join(
            f"- {lift}: " + ", ".join(f"{rm}: {val}kg" for rm, val in sorted(maxes.items()))
            for lift, maxes in sorted(barbell_lifts.items())
        )
        if barbell_lifts
        else "Niet beschikbaar"
    )

    skill_focus_text = "\n".join(f"- {s}" for s in athlete_profile.get("skill_focus", []))

    today_str = _nl_date(today.isoformat()) if today else "unknown"

    # Build health input block (subjectieve hersteldata van atleet)
    # Sleep quality is intentionally excluded here — use the automatic Garmin sleep
    # score (0-100) from the intervals.icu block below, not the manual slaap field.
    health_block = ""
    if health_input:
        lines = []
        energie = health_input.get("energie")
        spierpijn = health_input.get("spierpijn")
        if energie is not None:
            lines.append(f"- Energy level today: {energie}/5")
        if spierpijn is not None:
            lines.append(f"- Muscle soreness/fatigue today: {spierpijn}/5")
        stress = health_input.get("stress")
        if stress is not None:
            lines.append(f"- Stress today: {stress}/5 (1=no stress, 5=high stress/busy day)")
        # Append recent history trend (last 14 days) — energy/soreness/stress only
        if health_history:
            today_iso = today.isoformat() if today else ""
            recent = [h for h in health_history if h.get("date", "") < today_iso]
            recent = sorted(recent, key=lambda h: h.get("date", ""), reverse=True)[:14]
            if recent:
                lines.append("\nTrend last 14 days (date: energy/soreness/stress; all 1–5, 5=best; a stable value is the athlete's personal baseline, not a problem):")
                for h in reversed(recent):
                    d = h.get("date", "?")
                    e = h.get("energie", "?")
                    p = h.get("spierpijn", "?")
                    st = h.get("stress")
                    stress_str = f" stress={st}" if st is not None else ""
                    lines.append(f"  {d}: energy={e} soreness={p}{stress_str}")
        if lines:
            health_block = (
                "\nSubjective recovery data (filled in by athlete — use this as primary "
                "physiological recovery indicator for energy, soreness and stress):\n"
                + "\n".join(lines)
                + "\n"
            )

    # Actieve blessures (uit health_input.json) — hard constraint voor het advies
    injury_block = format_injuries_prompt(injuries or [], lang="en")

    # Garmin/intervals.icu objectieve hersteldata
    garmin_block = ""
    if intervals_data and intervals_data.get("wellness", {}).get("by_date"):
        today_iso = today.isoformat() if today else ""
        yesterday_iso = (today - timedelta(days=1)).isoformat() if today else ""
        w_by_date = intervals_data["wellness"]["by_date"]
        garmin_entry = w_by_date.get(today_iso) or w_by_date.get(yesterday_iso)

        # HRV baseline: 28-daags gemiddelde ± standaarddeviatie
        _hrv_hist = [w_by_date[d]["hrv"] for d in sorted(w_by_date) if d < today_iso and w_by_date[d].get("hrv") is not None][-28:]
        _hrv_baseline = sum(_hrv_hist) / len(_hrv_hist) if len(_hrv_hist) >= 5 else None
        _hrv_baseline_low = _hrv_baseline_high = None
        if _hrv_baseline and len(_hrv_hist) >= 5:
            _hrv_std = (sum((x - _hrv_baseline) ** 2 for x in _hrv_hist) / len(_hrv_hist)) ** 0.5
            _hrv_baseline_low  = round(_hrv_baseline - _hrv_std)
            _hrv_baseline_high = round(_hrv_baseline + _hrv_std)

        if garmin_entry:
            g_lines = []
            if garmin_entry.get("resting_hr") is not None:
                g_lines.append(f"- Resting HR: {garmin_entry['resting_hr']} bpm")
            if garmin_entry.get("hrv") is not None:
                _hrv_val = garmin_entry["hrv"]
                _hrv_line = f"- HRV (RMSSD): {_hrv_val:.0f} ms"
                if _hrv_baseline:
                    _ratio = _hrv_val / _hrv_baseline
                    if _hrv_baseline_low is not None and _hrv_val >= _hrv_baseline_low:
                        _hrv_status = "Balanced"
                    elif _ratio >= 0.75:
                        _hrv_status = "Unbalanced"
                    else:
                        _hrv_status = "Low"
                    if _hrv_baseline_low is not None and _hrv_baseline_high is not None:
                        _hrv_line += f" — baseline {_hrv_baseline_low}–{_hrv_baseline_high} ms, status: {_hrv_status}"
                    else:
                        _hrv_line += f" — 28d avg: {_hrv_baseline:.0f} ms, status: {_hrv_status}"
                g_lines.append(_hrv_line)
            if garmin_entry.get("hrv_sdnn") is not None:
                g_lines.append(f"- HRV (SDNN): {garmin_entry['hrv_sdnn']:.0f} ms")
            if garmin_entry.get("avg_sleeping_hr") is not None:
                g_lines.append(f"- Avg sleeping HR: {garmin_entry['avg_sleeping_hr']:.0f} bpm")
            if garmin_entry.get("readiness") is not None:
                g_lines.append(f"- Readiness: {garmin_entry['readiness']}/100")
            if garmin_entry.get("sleep_hrs") is not None:
                g_lines.append(f"- Sleep: {garmin_entry['sleep_hrs']:.1f} hours")
            if garmin_entry.get("sleep_score") is not None:
                g_lines.append(f"- Sleep score (Garmin): {garmin_entry['sleep_score']}/100")
            if garmin_entry.get("respiration") is not None:
                g_lines.append(f"- Respiration rate: {garmin_entry['respiration']:.1f} /min")
            ctl = garmin_entry.get("ctl")
            atl = garmin_entry.get("atl")
            tsb = garmin_entry.get("tsb")
            if ctl is not None and atl is not None:
                if tsb is not None:
                    if tsb > 5:
                        tsb_label = "fresh / race-ready"
                    elif tsb > 0:
                        tsb_label = "transitioning (slightly fresh)"
                    elif tsb > -10:
                        tsb_label = "neutral (gray zone)"
                    elif tsb > -30:
                        tsb_label = "optimal training load"
                    else:
                        tsb_label = "high risk / overloaded"
                    g_lines.append(f"- Training Form (TSB): {tsb:+.0f} ({tsb_label}) — fitness {ctl:.0f}, fatigue {atl:.0f}")
                else:
                    g_lines.append(f"- Fitness (CTL): {ctl:.0f}, fatigue (ATL): {atl:.0f}")
            if garmin_entry.get("steps") is not None:
                g_lines.append(f"- Steps: {garmin_entry['steps']:,}")
            if garmin_entry.get("vo2max") is not None:
                g_lines.append(f"- VO2max: {garmin_entry['vo2max']:.1f}")
            if garmin_entry.get("spo2") is not None:
                g_lines.append(f"- SpO₂: {garmin_entry['spo2']:.1f}%")
            # Subjective metrics (scale 1-4 in intervals.icu)
            # Soreness/fatigue/stress: 1=low/good, 4=extreme/bad
            # Mood/motivation: 1=great/very high (BEST), 4=grumpy/low (WORST)
            subj = []
            if garmin_entry.get("soreness") is not None:
                subj.append(f"soreness {garmin_entry['soreness']}/4 (1=none, 4=extreme)")
            if garmin_entry.get("fatigue") is not None:
                subj.append(f"fatigue {garmin_entry['fatigue']}/4 (1=none, 4=extreme)")
            if garmin_entry.get("stress") is not None:
                subj.append(f"stress {garmin_entry['stress']}/4 (1=low, 4=extreme)")
            if garmin_entry.get("mood") is not None:
                subj.append(f"mood {garmin_entry['mood']}/4 (1=great=best, 4=grumpy=worst)")
            if garmin_entry.get("motivation") is not None:
                subj.append(f"motivation {garmin_entry['motivation']}/4 (1=very high=best, 4=low=worst)")
            if subj:
                g_lines.append(f"- Subjective: {', '.join(subj)}")
            if g_lines:
                garmin_block = "\nGarmin recovery data (via intervals.icu):\n" + "\n".join(g_lines) + "\n"

    # Withings lichaamssamenstelling
    withings_block = ""
    if withings_data and withings_data.get("measurements"):
        m = withings_data["measurements"][0]
        w_lines = []
        if m.get("weight_kg") is not None:
            w_lines.append(f"- Weight: {m['weight_kg']} kg")
        if m.get("fat_pct") is not None:
            w_lines.append(f"- Body fat: {m['fat_pct']}%")
        if m.get("muscle_kg") is not None:
            w_lines.append(f"- Muscle mass: {m['muscle_kg']} kg")
        if m.get("hydration_kg") is not None:
            w_lines.append(f"- Hydration: {m['hydration_kg']} kg")
        if m.get("visceral_fat") is not None:
            w_lines.append(f"- Visceral fat: {m['visceral_fat']}")
        if m.get("nerve_health") is not None:
            w_lines.append(f"- Nerve health: {m['nerve_health']}/100")
        if m.get("pwv_ms") is not None:
            w_lines.append(f"- Pulse Wave Velocity: {m['pwv_ms']} m/s")
        if w_lines:
            withings_block = f"\nBody composition (Withings, {m['date']}):\n" + "\n".join(w_lines) + "\n"

    # Omgevingsdata: weer + AQI bij volgende training
    env_block = ""
    if environmental_data:
        aqi = environmental_data.get("aqi") or {}
        conds = environmental_data.get("training_conditions") or {}
        upcoming_date = (upcoming_workout or {}).get("date", "")
        cond = conds.get(upcoming_date)
        env_lines = []
        if cond:
            env_lines.append(
                f"- {cond.get('temp_c')}°C (feels like {cond.get('feels_like_c')}°C), "
                f"humidity {cond.get('humidity_pct')}%, wind {cond.get('wind_kmh')} km/h — "
                f"{cond.get('weather_desc', '')}"
            )
        if aqi.get("value") is not None:
            env_lines.append(f"- Air quality: AQI {aqi['value']} ({aqi.get('category', '')})")
        if env_lines:
            env_block = (
                f"\nConditions next training ({upcoming_date} {(cond or {}).get('training_time', '')}):\n"
                + "\n".join(env_lines) + "\n"
            )

    hr_zones_raw = (strava_data or {}).get("hr_zones", [])
    _zone_names = ["Z1 Recovery", "Z2 Aerobic", "Z3 Tempo", "Z4 Threshold", "Z5 Anaerobic"]
    if hr_zones_raw:
        _zone_lines = []
        for _i, _z in enumerate(hr_zones_raw[:5]):
            _label = _zone_names[_i] if _i < len(_zone_names) else f"Z{_i + 1}"
            _max = _z.get("max", -1)
            _zone_lines.append(f"  {_label}: {_z['min']}–{'∞' if _max == -1 else _max} bpm")
        hr_zones_text = "\nAthlete heart rate zones:\n" + "\n".join(_zone_lines) + "\n"
    else:
        hr_zones_text = ""

    # ACWR trainingsbelasting
    acwr = _compute_acwr(strava_data, intervals_data)
    if acwr:
        acwr_text = (
            f"\nTraining load (ACWR 7:28 days, source: {acwr['source']}): ratio={acwr['ratio']} — {acwr['status']}"
            f" (acute avg/day: {acwr['acute_7d']}, chronic: {acwr['chronic_28d']})\n"
        )
    else:
        acwr_text = ""

    # Krachtontwikkeling vs. 4 weken geleden
    barbell_trend_text = ""
    if barbell_history and barbell_lifts:
        trends = _compute_barbell_trends(barbell_history, barbell_lifts)
        if trends:
            pos = {l: d for l, d in trends.items() if d > 0}
            neg = {l: d for l, d in trends.items() if d < 0}
            parts = []
            if pos:
                parts.append("Increased: " + ", ".join(f"{l} +{d}kg" for l, d in sorted(pos.items())))
            if neg:
                parts.append("Decreased: " + ", ".join(f"{l} {d}kg" for l, d in sorted(neg.items())))
            barbell_trend_text = "\nStrength development vs. ~4 weeks ago:\n" + "\n".join(f"  {p}" for p in parts) + "\n"

    # Vorig advies (continuïteit)
    prev_advice_text = ""
    if previous_advice:
        recent_advice = sorted(previous_advice, key=lambda h: h.get("date", ""), reverse=True)[:2]
        if recent_advice:
            prev_advice_text = "\nPrevious coach advice (for reference — check if patterns repeat):\n"
            for entry in reversed(recent_advice):
                prev_advice_text += f"[{entry['date']}] {entry['advice']}\n"
            prev_advice_text += "\n"

    # Relevante PRs en benchmarks
    pr_text = ""
    if personal_records or benchmark_workouts:
        pr_lines = []
        if benchmark_workouts:
            for bm in (benchmark_workouts or [])[:8]:
                name = bm.get("name", "")
                result = bm.get("result", "")
                scaling = bm.get("scaling", "")
                bdate = bm.get("date", "")
                if name and result:
                    pr_lines.append(f"  {name}: {result}" + (f" ({scaling})" if scaling else "") + (f" — {bdate}" if bdate else ""))
        if personal_records:
            for pr in (personal_records or [])[:5]:
                wod = pr.get("workout", "")
                result = pr.get("result", "")
                pdate = pr.get("date", "")
                if wod and result:
                    pr_lines.append(f"  {wod}: {result}" + (f" — {pdate}" if pdate else ""))
        if pr_lines:
            pr_text = "\nPersonal records & benchmarks (context for intensity advice):\n" + "\n".join(pr_lines) + "\n"

    # Persoonlijke geplande activiteiten (handmatig toegevoegd via dashboard)
    # Split into past (for the past-workouts context) and upcoming (for the next-workout context)
    past_personal_text = ""
    upcoming_personal_text = ""
    if personal_events:
        today_iso = today.isoformat() if today else ""
        upcoming_pe = sorted(
            [e for e in personal_events if e.get("date", "") >= today_iso],
            key=lambda e: (e.get("date", ""), e.get("time", "")),
        )[:7]
        recent_pe = sorted(
            [e for e in personal_events if e.get("date", "") < today_iso],
            key=lambda e: e.get("date", ""),
            reverse=True,
        )[:5]
        if recent_pe:
            lines = ["Recent personal activities (extra training load outside the box):"]
            for e in reversed(recent_pe):
                line = f"  {_nl_date(e['date'])}: {e['title']}"
                if e.get("time"):
                    line += f" at {e['time']}"
                if e.get("location"):
                    line += f" ({e['location']})"
                if e.get("notes"):
                    line += f" — {e['notes'][:80]}"
                lines.append(line)
            past_personal_text = "\n" + "\n".join(lines) + "\n"
        if upcoming_pe:
            lines = [f"Upcoming personal activities (planned, from today {today_iso} onwards):"]
            for e in upcoming_pe:
                line = f"  {_nl_date(e['date'])}: {e['title']}"
                if e.get("time"):
                    line += f" at {e['time']}"
                if e.get("location"):
                    line += f" ({e['location']})"
                if e.get("notes"):
                    line += f" — {e['notes'][:80]}"
                lines.append(line)
            upcoming_personal_text = "\n" + "\n".join(lines) + "\n"

    running_plan_text = ""
    if running_plan and running_plan.get("workouts"):
        today_iso = today.isoformat() if today else ""
        workouts_list = running_plan["workouts"]
        week_nr = running_plan.get("week_number", "?")
        upcoming_runs = sorted(
            [w for w in workouts_list if w.get("date", "") >= today_iso and not w.get("cancelled")],
            key=lambda w: w.get("date", ""),
        )[:3]
        recent_runs = sorted(
            [w for w in workouts_list if w.get("date", "") < today_iso],
            key=lambda w: w.get("date", ""),
            reverse=True,
        )[:2]
        lines = [f"Running plan (5K program week {week_nr}):"]
        if recent_runs:
            lines.append("  Past planned running sessions:")
            for w in reversed(recent_runs):
                status = ""
                if w.get("cancelled"):
                    reason = w.get("cancel_reason", "")
                    status = f" [CANCELLED{': ' + reason if reason else ''}]"
                elif w.get("completed"):
                    status = " [completed]"
                lines.append(f"    {_nl_date(w['date'])}: {w.get('name', w.get('type', 'Run'))} "
                             f"({w.get('total_distance_km', '?')}km, {w.get('session', '')}){status}")
        # Apply health_input run_1/run_2 time overrides (user may have rescheduled
        # via the PWA before the running plan was regenerated server-side)
        _hi = health_input or {}
        def _hi_run_time(key: str) -> str:
            raw = _hi.get(key, "")
            if raw and "T" in raw:
                try:
                    return datetime.fromisoformat(raw).strftime("%H:%M")
                except ValueError:
                    pass
            return ""
        _run1_time_ovr = _hi_run_time("run_1")
        _run2_time_ovr = _hi_run_time("run_2")

        if upcoming_runs:
            lines.append("  Upcoming planned running sessions:")
            for w in upcoming_runs:
                t = w.get("time", "")
                session = w.get("session", "")
                if session == "speed" and _run1_time_ovr:
                    t = _run1_time_ovr
                elif session == "long_run" and _run2_time_ovr:
                    t = _run2_time_ovr
                lines.append(f"    {_nl_date(w['date'])}{' at ' + t if t else ''}: "
                             f"{w.get('name', w.get('type', 'Run'))} "
                             f"({w.get('total_distance_km', '?')}km, {w.get('session', '')})")
        running_plan_text = "\n" + "\n".join(lines) + "\n"

    deload_block = ""
    if deload_detected:
        deload_block = "\n⚠️ OVERTRAINING RISK DETECTED: The athlete is showing signs of overload (TSB below -30 and/or prolonged muscle soreness). STRONGLY advise a recovery week: scale all WODs to 60-70% intensity, prioritize sleep and nutrition, limit extra activities.\n"

    tsb_zone_note = """TSB zone reference (Training Stress Balance = fitness − fatigue):
- TSB > +5: Fresh / race-ready — body is recovered, great for competition or testing
- TSB 0 to +5: Transition — slightly fresh, good for intensity
- TSB -10 to 0: Neutral / gray zone — normal training state
- TSB -30 to -10: OPTIMAL training load — productive adaptation zone; negative TSB here is normal and desired, NOT a sign of overtraining
- TSB < -30: High risk — genuine overload, real fatigue requiring recovery
A negative TSB within the optimal range (-10 to -30) means the athlete is accumulating productive training stress. Do NOT treat this as a reason to hold back unless combined with HRV suppression, sleep disruption, or subjective fatigue markers."""

    prompt = f"""You are an experienced CrossFit coach. Give short, personal recovery advice for today.

{tsb_zone_note}

Today is: {today_str}{f", current time: {now_time}" if now_time else ""}

IMPORTANT: Only workouts listed under "Past CrossFit box sessions the athlete ACTUALLY attended" have already occurred. A workout mentioned in "Previous coach advice" was upcoming at the time that advice was generated — it may or may not have happened since then. Never conclude a workout has already happened based solely on it appearing in previous advice. Use the current time and the scheduled training time to determine whether today's workout has occurred yet.

IMPORTANT: "Previous coach advice" is a record of what was said before, not a verified fact about training history. Any claim it makes about which muscle groups are fatigued or which sessions caused that fatigue must be re-derived from today's "Past CrossFit box sessions" list — do not repeat a previous day's muscle-group or recovery conclusion unless today's actual past-workout list still supports it.

Athlete: {athlete_profile['name']}, {athlete_profile['weight_kg']} kg, age 47
Experience: {athlete_profile['experience']}
Focus areas:
{skill_focus_text}
{injury_block}{health_block}{garmin_block}{withings_block}{acwr_text}
Barbell maxima (kg):
{barbell_text}{barbell_trend_text}

Weight notation: The workout description may use lbs (American notation). The "Coach-/athlete notes" section ALWAYS uses KILOGRAMS — treat every number there as kg, never as lbs. In both sections, "X/Y" means X kg for men and Y kg for women — always use X (the men's weight) for this athlete. When coach notes specify different weights than the workout description, the coach notes always take priority (and are in kg).

Past CrossFit box sessions the athlete ACTUALLY attended (most recent first).
These are all real CrossFit WODs — even if the WOD description is missing or empty.
Where available, Strava data (↳) has been added: heart rate, duration, calories, Relative Effort (RE) and RPE.
Use this to assess the actual intensity, NOT just the WOD description:
{hr_zones_text}
{past_text if past_text.strip() else "No recent workouts known."}
{past_personal_text}
{upcoming_workout_label}:
{upcoming_text}{upcoming_timing_context}{upcoming_personal_text}{running_plan_text}{env_block}
{pr_text}{prev_advice_text}{deload_block}
Provide advice on:
1. **Recovery level** — are there muscle groups that need extra rest based on recent workouts?{"  Use the subjective recovery data (sleep, energy, muscle soreness) as the primary physiological recovery indicator. Use the Strava workout data (heart rate, duration) to assess the actual training load per session. If a subjective metric (e.g. sleep) is consistently at the same level over multiple weeks, treat it as the athlete's personal baseline — do not flag it as a persistent problem unless it has clearly worsened." if health_input else ""}{"  The ACWR ratio indicates training load: check if there is a pattern with the previous advice." if acwr else ""}
2. **Intensity advice** — go full throttle, train controlled, or deliberately scale today?
3. **One concrete tip** for the next workout taking recovery into account (e.g. pacing, scaling choice, specific movement){"  If 'Conditions next training' is provided, factor the weather and air quality into this tip: heat (feels-like > 25°C) or high humidity → emphasise hydration and consider scaling intensity; storm/heavy rain → flag this for outdoor/conditioning work; AQI > 100 → advise caution with high-intensity breathing-heavy efforts." if env_block else ""}

When referring to dates, always use the exact date (e.g. "Thursday 19 March"), NEVER vague terms like "yesterday" or "the day before yesterday".
Be direct, practical and concise. Maximum 160 words. Write in English. No introduction."""

    try:
        log.info("Generating recovery advice")
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        advice = message.content[0].text.strip()
        log.info("Recovery advice generated (%d chars)", len(advice))
        return advice
    except Exception as exc:
        log.warning("Failed to generate recovery advice: %s", exc)
        return ""


def generate_workout_plans(
    upcoming_workouts: list[dict],
    barbell_lifts: dict,
    athlete_profile: dict,
    signed_up_times: dict[str, str] | None = None,
    health_input: dict | None = None,
    health_history: list[dict] | None = None,
    strava_data: dict | None = None,
    past_workouts: list[dict] | None = None,
    workout_log: dict | None = None,
    barbell_history: list[dict] | None = None,
    personal_records: list[dict] | None = None,
    intervals_data: dict | None = None,
    environmental_data: dict | None = None,
    personal_events: list[dict] | None = None,
    running_plan: "dict | None" = None,
    withings_data: "dict | None" = None,
    injuries: list[dict] | None = None,
) -> dict[str, str]:
    """
    Call the Claude API to generate a personalised execution plan for each
    upcoming workout.  Requires ANTHROPIC_API_KEY to be set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping workout plan generation")
        return {}

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping workout plan generation")
        return {}

    client = anthropic.Anthropic(api_key=api_key)

    barbell_text = (
        "\n".join(
            f"- {lift}: " + ", ".join(f"{rm}: {val}kg" for rm, val in sorted(maxes.items()))
            for lift, maxes in sorted(barbell_lifts.items())
        )
        if barbell_lifts
        else "Niet beschikbaar"
    )

    # Krachtontwikkeling t.o.v. ~4 weken geleden
    barbell_trend_text = ""
    if barbell_history and barbell_lifts:
        trends = _compute_barbell_trends(barbell_history, barbell_lifts)
        if trends:
            pos = {l: d for l, d in trends.items() if d > 0}
            neg = {l: d for l, d in trends.items() if d < 0}
            parts = []
            if pos:
                parts.append("Increased: " + ", ".join(f"{l} +{d}kg" for l, d in sorted(pos.items())))
            if neg:
                parts.append("Decreased: " + ", ".join(f"{l} {d}kg" for l, d in sorted(neg.items())))
            barbell_trend_text = "\nStrength development vs. ~4 weeks ago:\n" + "\n".join(f"  {p}" for p in parts) + "\n"

    # Herstelstatus van de atleet (health scores + ACWR + Oura)
    # Sleep quality is excluded — only use automatic Garmin sleep score.
    recovery_status_text = ""
    if health_input:
        energie = health_input.get("energie")
        spierpijn = health_input.get("spierpijn")
        stress = health_input.get("stress")
        parts = []
        if energie is not None:
            parts.append(f"energy {energie}/5")
        if spierpijn is not None:
            parts.append(f"soreness {spierpijn}/5")
        if stress is not None:
            parts.append(f"stress {stress}/5")
        if parts:
            recovery_status_text = "\nCurrent athlete recovery status: " + ", ".join(parts) + "\n"

    # Actieve blessures (uit health_input.json) — gaan vóór elk ander advies
    injury_block = format_injuries_prompt(injuries or [], lang="en")
    if not injury_block:
        injury_block = f"\nInjuries: {athlete_profile['injuries']}\n"

    if intervals_data and intervals_data.get("wellness", {}).get("by_date"):
        from datetime import date as _date_cls_wod  # noqa: PLC0415
        _w = intervals_data["wellness"]["by_date"]
        _recent_dates = sorted(_w.keys(), reverse=True)[:7]
        _trend_lines = []
        for _d in reversed(_recent_dates):
            _ge = _w[_d]
            _gp = [f"  {_d}:"]
            if _ge.get("hrv") is not None:
                _gp.append(f"HRV {_ge['hrv']:.0f}ms")
            if _ge.get("resting_hr") is not None:
                _gp.append(f"resting_hr {_ge['resting_hr']}bpm")
            if _ge.get("tsb") is not None:
                _gp.append(f"TSB {_ge['tsb']:+.0f}")
            if _ge.get("sleep_hrs") is not None:
                _gp.append(f"sleep {_ge['sleep_hrs']:.1f}h")
            if _ge.get("sleep_score") is not None:
                _gp.append(f"sleep_score {_ge['sleep_score']}/100")
            if _ge.get("spo2") is not None:
                _gp.append(f"SpO₂ {_ge['spo2']:.1f}%")
            for _field, _label, _scale in [
                ("soreness", "soreness", "/4(1=none,4=extreme)"),
                ("fatigue", "fatigue", "/4(1=none,4=extreme)"),
                ("stress", "stress", "/4(1=low,4=extreme)"),
                ("mood", "mood", "/4(1=great=best,4=grumpy=worst)"),
                ("motivation", "motivation", "/4(1=high=best,4=low=worst)"),
            ]:
                if _ge.get(_field) is not None:
                    _gp.append(f"{_label} {_ge[_field]}{_scale}")
            _trend_lines.append(" ".join(_gp))
        if _trend_lines:
            recovery_status_text += "Garmin wellness trend (last 7 days):\n" + "\n".join(_trend_lines) + "\n"
    acwr = _compute_acwr(strava_data, intervals_data)
    if acwr:
        recovery_status_text += (
            f"Training load (ACWR 7:28d, source: {acwr['source']}): ratio={acwr['ratio']} — {acwr['status']}"
            f" (acute: {acwr['acute_7d']}/day, chronic: {acwr['chronic_28d']}/day)\n"
        )

    # Lichaamssamenstelling (Withings)
    withings_block = ""
    if withings_data and withings_data.get("measurements"):
        _m = withings_data["measurements"][0]
        _w_lines = []
        if _m.get("weight_kg") is not None:
            _w_lines.append(f"  Weight: {_m['weight_kg']} kg")
        if _m.get("fat_pct") is not None:
            _w_lines.append(f"  Body fat: {_m['fat_pct']}%")
        if _m.get("muscle_kg") is not None:
            _w_lines.append(f"  Muscle mass: {_m['muscle_kg']} kg")
        if _m.get("hydration_pct") is not None:
            _w_lines.append(f"  Hydration: {_m['hydration_pct']}%")
        if _w_lines:
            withings_block = f"\nBody composition (Withings, {_m.get('date', '')}):\n" + "\n".join(_w_lines) + "\n"

    # Aankomende hardloopsessies (zodat de coach weet of er morgen een lange duurloop staat)
    running_plan_text = ""
    if running_plan and running_plan.get("workouts"):
        from datetime import date as _date_cls_rp  # noqa: PLC0415
        _today_rp = _date_cls_rp.today().isoformat()
        _upcoming_runs = sorted(
            [w for w in running_plan["workouts"] if w.get("date", "") >= _today_rp and not w.get("cancelled")],
            key=lambda w: w["date"],
        )[:3]
        if _upcoming_runs:
            _run_lines = ["Upcoming running sessions (consider recovery impact on CrossFit performance):"]
            for _w in _upcoming_runs:
                _t = _w.get("time", "")
                _line = f"  {_w['date']}{' at ' + _t if _t else ''}: {_w.get('name', _w.get('type', 'Run'))} ({_w.get('total_distance_km', '?')}km, {_w.get('session', '')})"
                _run_lines.append(_line)
            running_plan_text = "\n" + "\n".join(_run_lines) + "\n"

    # Recente workout-lognotities (wat de atleet daadwerkelijk deed + gewichten)
    recent_log_text = ""
    if workout_log:
        log_entries = sorted(
            [(d, e) for d, e in workout_log.items()],
            key=lambda x: x[0],
            reverse=True,
        )[:5]
        if log_entries:
            log_lines = []
            for d, entry in reversed(log_entries):
                notes = entry.get("notes", "")
                wods_done = entry.get("workouts_done") or []
                if notes or wods_done:
                    wod_str = ", ".join(wods_done) if wods_done else ""
                    log_lines.append(f"  {_nl_date(d)}: {wod_str}" + (f" — {notes}" if notes else ""))
            if log_lines:
                recent_log_text = "\nRecent workout log (actually done + weights/notes):\n" + "\n".join(log_lines) + "\n"

    # Relevante PRs
    pr_text = ""
    if personal_records:
        pr_lines = [
            f"  {pr.get('workout', '')}: {pr.get('result', '')}" + (f" — {pr.get('date', '')}" if pr.get("date") else "")
            for pr in (personal_records or [])[:8]
            if pr.get("workout") and pr.get("result")
        ]
        if pr_lines:
            pr_text = "\nPersonal records (context for weights/pacing):\n" + "\n".join(pr_lines) + "\n"

    # Group workouts by date so we can pick the main one per date
    by_date: dict[str, list[dict]] = {}
    for w in upcoming_workouts:
        d = w.get("date", "")
        if d:
            by_date.setdefault(d, []).append(w)

    def _pick_main(ws: list[dict]) -> dict:
        """Return the main workout from a list of workouts for a single date."""
        for kw in _MAIN_KEYWORDS:
            for w in ws:
                if kw in w.get("title", "").lower():
                    return w
        # Fallback: pick the one with the longest description
        return max(ws, key=lambda w: len(w.get("description", "")))

    plans: dict[str, str] = {}
    for date, day_workouts in sorted(by_date.items()):
        main = _pick_main(day_workouts)
        title = main.get("title", "WOD")
        description = _strip_html(main.get("description", ""))
        if not description:
            continue

        # Athlete/coach notes: timecap, RX weights in kg, scaling options
        notes_raw = main.get("athlete_notes", "").strip()
        notes_context = f"\nCoach-/athlete notes (official weights in kg, timecap, scaling):\n{notes_raw}\n" if notes_raw else ""

        # Detect team/partner format from description or title
        team_size = _detect_team_size(description + " " + title)

        # Collect accessory titles so the coach has context but stays focused on the main WOD
        accessory_titles = [
            w["title"] for w in day_workouts
            if w is not main and w.get("title")
        ]
        accessory_context = (
            f"\nAccessory work on this day (for context, not the primary focus): {', '.join(accessory_titles)}"
            if accessory_titles else ""
        )

        skill_focus_text = "\n".join(
            f"- {s}" for s in athlete_profile.get("skill_focus", [])
        )
        if team_size:
            team_context = (
                f"\nNOTE: This is a team workout with {team_size} people. "
                f"The athlete therefore does only 1/{team_size} of the total volume (reps/rounds divided by {team_size}). "
                f"Base pacing and weight advice on this individual share."
            )
        else:
            team_context = ""

        timing_context = _training_time_context(date, signed_up_times)

        # Environmental conditions for this specific training day
        env_context = ""
        if environmental_data:
            aqi = environmental_data.get("aqi") or {}
            cond = (environmental_data.get("training_conditions") or {}).get(date)
            env_parts = []
            if cond:
                env_parts.append(
                    f"{cond.get('temp_c')}°C (feels like {cond.get('feels_like_c')}°C), "
                    f"humidity {cond.get('humidity_pct')}%, wind {cond.get('wind_kmh')} km/h — "
                    f"{cond.get('weather_desc', '')}"
                )
            if aqi.get("value") is not None:
                env_parts.append(f"AQI {aqi['value']} ({aqi.get('category', '')})")
            if env_parts:
                env_context = "\nConditions on training day: " + " | ".join(env_parts) + "\n"

        # Persoonlijke geplande activiteiten rondom deze trainingsdatum
        personal_event_context = ""
        if personal_events:
            nearby = [
                e for e in personal_events
                if abs((date_cls.fromisoformat(e["date"]) - date_cls.fromisoformat(date)).days) <= 3
                and e.get("date") != date
            ]
            if nearby:
                nearby.sort(key=lambda e: e["date"])
                lines = ["Other planned activities near this training (±3 days, consider recovery):"]
                for e in nearby:
                    diff = (date_cls.fromisoformat(e["date"]) - date_cls.fromisoformat(date)).days
                    when = f"{abs(diff)} day{'s' if abs(diff) != 1 else ''} {'after' if diff > 0 else 'before'} this training"
                    line = f"  {_nl_date(e['date'])} ({when}): {e['title']}"
                    if e.get("time"):
                        line += f" at {e['time']}"
                    if e.get("notes"):
                        line += f" — {e['notes'][:60]}"
                    lines.append(line)
                personal_event_context = "\n" + "\n".join(lines) + "\n"

        prompt = f"""You are an experienced CrossFit coach. Generate a concise, practical execution plan.

Athlete: {athlete_profile['name']}
Body weight: {athlete_profile['weight_kg']} kg
Experience: {athlete_profile['experience']}
Goal: {athlete_profile.get('doel', '')}
RX/Scaled preference: {athlete_profile['rx_preference']}{injury_block}{recovery_status_text}
Personal focus areas (movements where improvement is desired):
{skill_focus_text}

Barbell maxima (kg):
{barbell_text}{barbell_trend_text}
{withings_block}{pr_text}{recent_log_text}{running_plan_text}{personal_event_context}
Weight notation: The workout description may use lbs (American notation). The "Coach-/athlete notes" section ALWAYS uses KILOGRAMS — treat every number there as kg, never as lbs. In both sections, "X/Y" means X kg for men and Y kg for women — always use X (the men's weight) for this athlete. When coach notes specify different weights than the workout description, the coach notes always take priority (and are in kg).

Main workout ({_nl_date(date)} — {title}):
{description}{notes_context}{accessory_context}
{team_context}{timing_context}{env_context}
The execution plan must ONLY cover the main workout above. Do not address accessory work.

Provide a plan with:
1. Recommended weights for barbell movements (with % of 1RM as reference)
2. Pacing strategy and sets/reps breakdown — adjust for recovery status if relevant
3. 1–2 concrete tips for this specific workout
4. **Skill tip**: If one or more focus areas appear in this workout, give one targeted improvement tip specifically aimed at reaching RX level for that movement faster (technique, drills, mindset). Skip this section if none of the focus areas are present.
5. **Nutrition**: include this section only if a dinner meal is known — consider the training time: is the meal a good recovery meal (evening training) or proper preparation (morning training)? One sentence.

Be direct and concise. Maximum 210 words. No introduction."""

        try:
            log.info("Generating AI plan for %s (%s)", date, title)
            message = client.messages.create(
                # Kostenbesparing: Sonnet 4.6 ($3/$15 per 1M tokens) i.p.v. Opus ($5/$25).
                model="claude-sonnet-4-6",
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            plan_text = message.content[0].text.strip()
            plans[date] = plan_text
            log.info("Plan generated for %s (%d chars)", date, len(plan_text))
        except Exception as exc:
            log.warning("Failed to generate plan for %s: %s", date, exc)

    return plans


def detect_deload(intervals_data: "dict | None", health_history: list[dict]) -> bool:
    """
    Detecteer overtraining risico op basis van TSB-trend en subjectieve spierpijn.

    Triggercondities (één van beide voldoende):
      - TSB < -20 voor 3+ opeenvolgende recente dagen
      - Spierpijn >= 4/5 voor 3+ recente dagen EN TSB < -10
    """
    tsb_values: list[float] = []
    if intervals_data:
        by_date = (intervals_data.get("wellness") or {}).get("by_date", {})
        recent_dates = sorted(by_date.keys())[-5:]
        for d in recent_dates:
            tsb = by_date[d].get("tsb")
            if tsb is not None:
                tsb_values.append(float(tsb))

    # Check TSB < -20 voor 3+ achtereenvolgende dagen
    if len(tsb_values) >= 3 and all(v < -20 for v in tsb_values[-3:]):
        log.info("[deload] TSB < -20 voor 3+ dagen: %s", tsb_values[-3:])
        return True

    # Check spierpijn >= 4 voor 3+ dagen én TSB < -10
    if health_history:
        recent_scores = [h.get("spierpijn") for h in sorted(health_history, key=lambda h: h.get("date", ""))[-3:]]
        high_soreness = sum(1 for s in recent_scores if s is not None and int(s) >= 4) >= 3
        avg_tsb = sum(tsb_values[-3:]) / len(tsb_values[-3:]) if len(tsb_values) >= 3 else 0
        if high_soreness and avg_tsb < -10:
            log.info("[deload] Hoge spierpijn + TSB < -10: soreness=%s tsb=%.1f", recent_scores, avg_tsb)
            return True

    return False
