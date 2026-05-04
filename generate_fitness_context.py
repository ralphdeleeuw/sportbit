#!/usr/bin/env python3
"""
generate_fitness_context.py — Genereert een fitness context markdown voor Claude.

Haalt data op uit de GitHub Gist (sugarwod_wod.json, health_input.json)
en combineert dit met het vaste atletenprofiel om een
volledig overzicht te maken dat als context dient bij het genereren van
een persoonlijk fitnessplan.

Gebruik:
    python3 generate_fitness_context.py

Environment variables:
    GIST_ID       - GitHub Gist ID (vereist voor live data)
    GITHUB_TOKEN  - GitHub personal access token met gist scope (vereist)

Output:
    fitness_context.md  (ook uitgeprint naar stdout)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

# ──────────────────────────────────────────────────────────────────────────────
# Atletenprofiel (hardcoded fallback — identiek aan fetch_sugarwod.py)
# ──────────────────────────────────────────────────────────────────────────────

AMS = ZoneInfo("Europe/Amsterdam")

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
        "hardlooptempo (sneller worden op 400m/800m/1mi)",
        "back squat & front squat (techniek + kracht)",
        "double unders (consistentie en hoog volume)",
        "handstand push-ups (strikt en kipping, richting RX)",
        "pull-ups (kipping en butterfly, richting RX)",
        "handstand walk (afstand opbouwen)",
    ],
}

TRAINING_SCHEDULE = {
    "Maandag": "20:00",
    "Woensdag": "08:00",
    "Donderdag": "20:00",
    "Zaterdag": "09:00",
    "Zondag": "09:00",
}

BREAKFAST = {
    "time": "07:00",
    "description": (
        "~838 kcal | ~56g eiwit | ~61g KH | ~36g vet: "
        "Alpro Mild & Creamy zonder suikers (200ml) met Holie's Granola Protein Crunch (75g) "
        "en Upfront Vegan Eiwit Shake chocolade (30g). "
        "Daarnaast 2 volkoren boterhammen met AH amandelpasta (~15g) en een beetje pure hagelslag (~10g)."
    ),
}
DINNER_TIME = "18:00"

BARBELL_LIFTS_FALLBACK = {
    "3 Position Clean (hang, below knee, floor)": {"1RM": 37.5, "3RM": 37},
    "3 Position Snatch (High Hang, Above the Knee, Floor)": {"1RM": 25, "3RM": 35},
    "Back Pause Squat": {"5RM": 43},
    "Back Rack Lunges": {"1RM": 50, "2RM": 50, "3RM": 50, "5RM": 50},
    "Back Squat": {"1RM": 67, "2RM": 60, "3RM": 62, "5RM": 56},
    "Bench Press": {"1RM": 67.5, "2RM": 55, "3RM": 60, "5RM": 50},
    "Bent Over Row": {"5RM": 30},
    "Box Squat": {"1RM": 90},
    "Clean": {"1RM": 50, "2RM": 53, "3RM": 40},
    "Clean & Jerk": {"1RM": 58, "2RM": 32.5, "3RM": 53},
    "Deadlift": {"1RM": 100, "2RM": 80, "3RM": 80, "5RM": 90},
    "Front Pause Squat": {"2RM": 37.5},
    "Front Rack Lunges": {"1RM": 35, "2RM": 35, "3RM": 35, "5RM": 35},
    "Front Squat": {"1RM": 65, "3RM": 35, "5RM": 57},
    "Front Squat + Jerk": {"5RM": 52.5},
    "Full Grip, No Foot Clean + Tall Jerks": {"5RM": 50},
    "Hang Clean": {"1RM": 55, "3RM": 40},
    "Hang Power Clean": {"1RM": 57.5, "3RM": 43, "5RM": 50},
    "Hang Power Snatch": {"1RM": 40, "2RM": 33, "3RM": 38},
    "Hang Squat Clean": {"3RM": 42.5, "5RM": 30},
    "Hang Squat Snatch": {"1RM": 35, "2RM": 35, "3RM": 32.5},
    "In The Hole Front Squat": {"1RM": 45},
    "Muscle Clean": {"5RM": 35},
    "Overhead Squat": {"1RM": 48, "2RM": 44},
    "Power Clean": {"1RM": 57, "2RM": 57, "3RM": 45},
    "Power Clean & Jerk": {"1RM": 61, "2RM": 61, "3RM": 58},
    "Power Snatch": {"1RM": 43, "2RM": 43, "3RM": 35, "5RM": 35},
    "Pressing Complex": {"1RM": 50},
    "Push Jerk": {"1RM": 61, "2RM": 61, "3RM": 50, "5RM": 40},
    "Push Press": {"1RM": 57.5, "2RM": 50, "5RM": 40},
    "Shoulder Press": {"1RM": 42.5, "2RM": 37.5, "3RM": 35, "5RM": 27},
    "Snatch": {"1RM": 38, "2RM": 34, "3RM": 35},
    "Snatch + Overhead Squat": {"2RM": 25},
    "Snatch Balance": {"1RM": 37.5, "2RM": 30, "3RM": 25},
    "Snatch Deadlift + High Hang Shrug": {"5RM": 37.5},
    "Snatch Grip Deadlift": {"3RM": 37.5},
    "Snatch Grip Push Press": {"5RM": 37.5},
    "Snatch Pull": {"2RM": 40},
    "Snatch Push Press + Overhead Squat": {"2RM": 40, "3RM": 27},
    "Split Jerk": {"1RM": 50, "2RM": 58},
    "Squat Clean": {"1RM": 53, "3RM": 40, "5RM": 35},
    "Squat Snatch": {"1RM": 45, "3RM": 32, "5RM": 30},
    "Sumo Deadlift": {"2RM": 50, "3RM": 50},
    "Sumo Deadlift High Pull": {"5RM": 43},
    "Thruster": {"1RM": 53, "2RM": 43, "3RM": 44, "5RM": 43},
    "Weighted Chin Up": {"1RM": 7.5, "3RM": 7.5},
    "Weighted Hip Thrust": {"5RM": 110},
}


# ──────────────────────────────────────────────────────────────────────────────
# Gist helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_gist(gist_id: str, token: str) -> dict[str, str]:
    """Laad alle bestanden uit de Gist. Retourneert {filename: content}."""
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


def _parse_json(raw: str, label: str) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[waarschuwing] {label} is geen geldig JSON: {exc}", file=sys.stderr)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Markdown builders
# ──────────────────────────────────────────────────────────────────────────────

def _section(title: str) -> str:
    return f"\n## {title}\n"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    sep = "|".join("---" for _ in headers)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + sep + " |"
    data_rows = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([header_row, sep_row] + data_rows) + "\n"


def _fmt_kg(val) -> str:
    if val is None:
        return "—"
    return f"{val} kg"


def _fmt_val(val, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{val}{suffix}"


# ──────────────────────────────────────────────────────────────────────────────
# Section generators
# ──────────────────────────────────────────────────────────────────────────────

def section_profile() -> str:
    p = ATHLETE_PROFILE
    lines = [_section("Atletenprofiel")]
    lines.append(_table(
        ["Eigenschap", "Waarde"],
        [
            ["Naam", p["name"]],
            ["Leeftijd", str(p["age"])],
            ["Gewicht (referentie)", f"{p['weight_kg']} kg"],
            ["Ervaring", p["experience"]],
            ["Sportschool", p["gym"]],
            ["RX-voorkeur", p["rx_preference"]],
            ["Blessures", p["injuries"]],
        ],
    ))
    lines.append(f"\n**Doel:** {p['doel']}\n")
    lines.append("\n**Skill focus (prioriteit):**")
    for skill in p["skill_focus"]:
        lines.append(f"- {skill}")
    return "\n".join(lines)


def section_schedule() -> str:
    lines = [_section("Wekelijks Trainingsschema")]
    lines.append(_table(
        ["Dag", "Tijd"],
        [[dag, tijd] for dag, tijd in TRAINING_SCHEDULE.items()],
    ))
    lines.append("\n*5 trainingsdagen per week (CrossFit klassen bij CrossFit Hilversum).*")
    return "\n".join(lines)


def section_prs(wod_data: dict | None) -> str:
    lines = [_section("Persoonlijke Records — Barbell Lifts")]

    lifts = (wod_data or {}).get("barbell_lifts") or BARBELL_LIFTS_FALLBACK
    source = "live (uit Gist)" if (wod_data or {}).get("barbell_lifts") else "fallback (hardcoded)"
    lines.append(f"*Bron: {source}*\n")

    # Verzamel alle RM-kolommen
    all_rms: set[str] = set()
    for vals in lifts.values():
        all_rms.update(vals.keys())
    rm_cols = sorted(all_rms, key=lambda x: int(x.replace("RM", "")))

    headers = ["Oefening"] + rm_cols
    rows = []
    for lift, vals in sorted(lifts.items()):
        row = [lift]
        for rm in rm_cols:
            v = vals.get(rm)
            row.append(f"{v} kg" if v is not None else "—")
        rows.append(row)

    lines.append(_table(headers, rows))

    # Benchmark WODs
    benchmarks: list[dict] = (wod_data or {}).get("benchmark_workouts", [])
    if benchmarks:
        lines.append("\n### Benchmark WODs\n")
        bm_rows = []
        for bm in benchmarks:
            bm_rows.append([
                bm.get("name", "—"),
                bm.get("result", "—"),
                bm.get("scaling", "—"),
                bm.get("date", "—"),
            ])
        lines.append(_table(["WOD", "Resultaat", "Scaling", "Datum"], bm_rows))

    # SugarWOD personal records (geschrapt uit profiel)
    pr_list: list[dict] = (wod_data or {}).get("personal_records", [])
    if pr_list:
        lines.append("\n### SugarWOD Personal Records\n")
        pr_rows = [[pr.get("workout", "—"), pr.get("notes", "—"), pr.get("date", "—")] for pr in pr_list]
        lines.append(_table(["Workout", "Resultaat / Notities", "Datum"], pr_rows))

    return "\n".join(lines)


def section_body_composition(wod_data: dict | None) -> str:
    lines = [_section("Lichaamssamenstelling (Withings)")]

    withings = (wod_data or {}).get("withings_data", {})
    measurements: list[dict] = (withings or {}).get("measurements", [])

    if not measurements:
        lines.append("*Geen Withings-data beschikbaar.*")
        return "\n".join(lines)

    latest = measurements[0]
    lines.append(f"*Laatste meting: {latest.get('date', '?')}*\n")
    lines.append(_table(
        ["Meting", "Waarde"],
        [
            ["Gewicht", _fmt_kg(latest.get("weight_kg"))],
            ["Vetpercentage", _fmt_val(latest.get("fat_pct"), " %")],
            ["Spiermassa", _fmt_kg(latest.get("muscle_kg"))],
            ["Hydratatie", _fmt_kg(latest.get("hydration_kg"))],
            ["Botmassa", _fmt_kg(latest.get("bone_kg"))],
            ["Visceraal vet index", _fmt_val(latest.get("visceral_fat"))],
            ["Pulse Wave Velocity", _fmt_val(latest.get("pwv_ms"), " m/s")],
            ["Zenuwgezondheid (ANS)", _fmt_val(latest.get("nerve_health"), "/100")],
        ],
    ))

    # Trend (laatste 4 metingen)
    if len(measurements) > 1:
        lines.append("\n**Gewichtstrend (laatste metingen):**")
        for m in measurements[:6]:
            lines.append(f"- {m.get('date', '?')}: {_fmt_kg(m.get('weight_kg'))}  |  vet: {_fmt_val(m.get('fat_pct'), '%')}  |  spier: {_fmt_kg(m.get('muscle_kg'))}")

    return "\n".join(lines)


def section_health_metrics(wod_data: dict | None, health_input: dict | None, hi_history: list[dict]) -> str:
    lines = [_section("Gezondheidsdata & Trainingsbelasting")]

    intervals = (wod_data or {}).get("intervals_data", {})
    wellness_by_date: dict = (intervals or {}).get("wellness", {}).get("by_date", {})

    if not wellness_by_date:
        lines.append("*Geen intervals.icu wellness-data beschikbaar.*\n")
    else:
        # Laatste 14 dagen
        today = datetime.now(AMS).date()
        dates = sorted(wellness_by_date.keys(), reverse=True)[:14]

        lines.append("### Objectieve Metingen (intervals.icu / Garmin)\n")
        rows = []
        for d in dates:
            w = wellness_by_date[d]
            rows.append([
                d,
                _fmt_val(w.get("resting_hr"), " bpm"),
                _fmt_val(w.get("hrv"), " ms"),
                _fmt_val(w.get("sleep_hrs"), " u"),
                _fmt_val(w.get("sleep_score"), "/100"),
                _fmt_val(w.get("ctl"), ""),
                _fmt_val(w.get("atl"), ""),
                _fmt_val(w.get("tsb"), ""),
                _fmt_val(w.get("spo2"), " %"),
            ])
        lines.append(_table(
            ["Datum", "Rustpols", "HRV (RMSSD)", "Slaap", "Slaapscore", "CTL (fitness)", "ATL (vermoeidheid)", "TSB (vorm)", "SpO2"],
            rows,
        ))
        lines.append("\n*CTL = chronic training load (fitness), ATL = acute training load (vermoeidheid), TSB = CTL − ATL (hogere TSB = beter hersteld)*")

    # Subjectieve health input
    lines.append("\n### Subjectieve Herstelscores (health_input.json)\n")

    # Combineer today + history
    all_entries: list[dict] = []
    if health_input:
        all_entries.append(health_input)
    if hi_history:
        all_entries.extend(hi_history)
    all_entries = sorted(all_entries, key=lambda x: x.get("date", ""), reverse=True)[:14]

    if not all_entries:
        lines.append("*Geen subjectieve data beschikbaar.*")
    else:
        rows = []
        for e in all_entries:
            rows.append([
                e.get("date", "—"),
                _fmt_val(e.get("slaap"), "/10"),
                _fmt_val(e.get("energie"), "/10"),
                _fmt_val(e.get("spierpijn"), "/10"),
                _fmt_val(e.get("stress"), "/10"),
            ])
        lines.append(_table(["Datum", "Slaap", "Energie", "Spierpijn", "Stress"], rows))

    return "\n".join(lines)


def section_activities(wod_data: dict | None) -> str:
    lines = [_section("Recente Activiteiten (afgelopen 14 dagen)")]

    intervals = (wod_data or {}).get("intervals_data", {})
    acts_by_date: dict = (intervals or {}).get("activities", {}).get("by_date", {})

    strava = (wod_data or {}).get("strava_data", {})
    strava_by_date: dict = (strava or {}).get("activities_by_date", {})

    dates = sorted(set(list(acts_by_date.keys()) + list(strava_by_date.keys())), reverse=True)[:14]

    if not dates:
        lines.append("*Geen activiteitendata beschikbaar.*")
        return "\n".join(lines)

    rows = []
    for d in dates:
        day_acts = acts_by_date.get(d, []) + strava_by_date.get(d, [])
        for a in day_acts:
            rows.append([
                d,
                a.get("name", "—"),
                a.get("type", "—"),
                _fmt_val(a.get("duration_min"), " min"),
                _fmt_val(a.get("avg_hr"), " bpm"),
                _fmt_val(a.get("calories"), " kcal"),
                _fmt_val(a.get("training_load") or a.get("suffer_score"), ""),
            ])

    if not rows:
        lines.append("*Geen activiteiten gevonden.*")
        return "\n".join(lines)

    lines.append(_table(
        ["Datum", "Naam", "Type", "Duur", "Gem. HR", "Calorieën", "Training Load"],
        rows,
    ))
    return "\n".join(lines)


def section_wods(wod_data: dict | None, workout_log: dict | None) -> str:
    lines = [_section("CrossFit WODs (afgelopen 14 dagen)")]

    by_date: dict = (wod_data or {}).get("by_date", {})
    today = datetime.now(AMS).date()
    cutoff = (today - timedelta(days=14)).isoformat()

    recent_dates = sorted([d for d in by_date if d >= cutoff], reverse=True)

    if not recent_dates:
        lines.append("*Geen WOD-data voor de afgelopen 14 dagen.*")
        return "\n".join(lines)

    for d in recent_dates:
        wods = by_date[d]
        for w in wods:
            name = w.get("name", "Onbekend")
            desc = w.get("description", "")
            signed = "ja" if w.get("signed_up") else "nee"
            wod_type = w.get("wod_type", "")
            dur = w.get("duration_min")
            log_entry = (workout_log or {}).get(d, {})
            completed = "ja" if log_entry.get("checked") else "—"
            score = log_entry.get("reps") or log_entry.get("notes") or "—"

            lines.append(f"\n**{d} — {name}**")
            if wod_type:
                lines.append(f"Type: {wod_type}" + (f" | {dur} min" if dur else ""))
            if desc:
                lines.append(f"> {desc[:300]}")
            lines.append(f"Ingeschreven: {signed} | Voltooid: {completed} | Score: {score}")

    return "\n".join(lines)


def section_nutrition() -> str:
    lines = [_section("Voeding")]
    lines.append(f"**Ontbijt ({BREAKFAST['time']}):** {BREAKFAST['description']}\n")
    lines.append(f"**Diner:** rondom {DINNER_TIME}")
    lines.append(
        "\n*Gebruik bovenstaande tijden bij het plannen van pre/post-workout voeding in het fitnessplan.*"
    )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def generate(output_file: str = "fitness_context.md") -> None:
    gist_id = os.getenv("GIST_ID", "")
    token = os.getenv("GITHUB_TOKEN", "")

    wod_data: dict | None = None
    health_input: dict | None = None
    hi_history: list[dict] = []
    workout_log: dict | None = None
    if gist_id and token:
        print("[info] Gist-data ophalen...", file=sys.stderr)
        try:
            files = _load_gist(gist_id, token)
            wod_data = _parse_json(files.get("sugarwod_wod.json", ""), "sugarwod_wod.json")
            hi_raw = _parse_json(files.get("health_input.json", ""), "health_input.json")
            if isinstance(hi_raw, dict):
                if hi_raw.get("date"):
                    health_input = {
                        "date": hi_raw.get("date"),
                        "slaap": hi_raw.get("slaap"),
                        "energie": hi_raw.get("energie"),
                        "spierpijn": hi_raw.get("spierpijn"),
                        "stress": hi_raw.get("stress"),
                    }
                hi_history = hi_raw.get("history", [])
            wl_raw = _parse_json(files.get("workout_log.json", ""), "workout_log.json")
            if isinstance(wl_raw, dict):
                workout_log = {e["date"]: e for e in wl_raw.get("entries", []) if "date" in e}
            print("[info] Gist-data geladen.", file=sys.stderr)
        except Exception as exc:
            print(f"[waarschuwing] Gist ophalen mislukt: {exc}. Fallback naar hardcoded data.", file=sys.stderr)
    else:
        print("[info] GIST_ID of GITHUB_TOKEN niet ingesteld — alleen hardcoded data gebruikt.", file=sys.stderr)

    now_str = datetime.now(AMS).strftime("%Y-%m-%d %H:%M")
    fetched_at = (wod_data or {}).get("fetched_at", "onbekend")

    sections = [
        f"# Fitness Context — {ATHLETE_PROFILE['name']}\n",
        f"*Gegenereerd op: {now_str} (Amsterdam)*  \n"
        f"*Data bijgewerkt: {fetched_at}*\n",
        "---",
        section_profile(),
        section_schedule(),
        section_prs(wod_data),
        section_body_composition(wod_data),
        section_health_metrics(wod_data, health_input, hi_history),
        section_activities(wod_data),
        section_wods(wod_data, workout_log),
        section_nutrition(),
        "\n---",
        "\n*Dit document is automatisch gegenereerd door `generate_fitness_context.py`. "
        "Gebruik het als context bij het vragen aan Claude om een persoonlijk fitnessplan.*",
    ]

    markdown = "\n".join(sections)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"[info] Context opgeslagen in: {output_file}", file=sys.stderr)
    print(markdown)


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "fitness_context.md"
    generate(output)
