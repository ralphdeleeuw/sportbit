#!/usr/bin/env python3
"""
Intervals.icu data fetcher voor het SportBit CrossFit dashboard.

Haalt Garmin-data op via intervals.icu (wellness + activiteiten).
Intervals.icu synchroniseert automatisch met Garmin Connect.

══════════════════════════════════════════════════════════════
SETUP
══════════════════════════════════════════════════════════════
1. Maak een intervals.icu account aan op https://intervals.icu
2. Koppel Garmin via Settings → Connected Accounts → Garmin
3. Vind je Athlete ID: Settings → Profile (bovenaan, formaat "iXXXXX")
4. Maak een API key: Settings → API key → New key
5. Voeg toe als GitHub Secrets:
       INTERVALS_ATHLETE_ID  — bijv. "i12345"
       INTERVALS_API_KEY     — de gegenereerde API key

Vereiste secrets:
  INTERVALS_ATHLETE_ID  - intervals.icu athlete ID (bijv. "i12345")
  INTERVALS_API_KEY     - intervals.icu API key

Return formaat:
{
  "wellness": {
    "by_date": {
      "YYYY-MM-DD": {
        "resting_hr": int,       # rustpols (bpm)
        "hrv": float,            # RMSSD (ms)
        "sleep_hrs": float,      # slaap (uur)
        "sleep_score": int,      # slaapscore (0-100)
        "ctl": float,            # chronic training load (fitness)
        "atl": float,            # acute training load (vermoeidheid)
        "tsb": float,            # training stress balance (vorm = CTL - ATL)
        "weight_kg": float,      # gewicht in kg (als Garmin dit bijhoudt)
        "spo2": float,           # bloedzuurstof %
        "skin_temp_c": float,    # huidtemperatuur-afwijking (Fenix 8 Elevate V5, indien gesynct)
        "endurance_score": int,  # Garmin Endurance Score (Fenix 8, indien gesynct)
        "hill_score": int,       # Garmin Hill Score (Fenix 8, indien gesynct)
      }
    }
  },
  "activities": {
    "by_date": {
      "YYYY-MM-DD": [
        {
          "name": str,
          "type": str,
          "duration_min": int,
          "avg_hr": int,
          "max_hr": int,
          "calories": int,
          "training_load": float,
          "avg_watts": float,         # gem. vermogen — bij hardlopen running power (Fenix 8 vanaf pols)
          "stride_length_m": float,   # gem. staplengte (running dynamics, Fenix 8 zonder band)
          "ground_contact_ms": float, # grondcontacttijd (ms)
          "vert_oscillation_mm": float,  # verticale oscillatie (mm)
          "vert_ratio_pct": float,    # verticale ratio (%)
        }
      ]
    }
  },
  "fetched_at": "ISO8601"
}

NB: Fenix 8-specifieke velden (running power/dynamics, huidtemperatuur,
Endurance/Hill Score) worden alleen opgenomen als intervals.icu ze daadwerkelijk
synct vanuit Garmin Connect. Zet de omgevingsvariabele INTERVALS_DEBUG_KEYS=1 om
de ruwe API-keys te loggen en te zien welke velden binnenkomen.
"""

import logging
import os
from datetime import date, timedelta, timezone, datetime

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://intervals.icu/api/v1/athlete"
# Single-activity endpoint (detail + streams). Let op: dit is /activity/{id}
# (enkelvoud, zonder athlete-prefix). De /athlete/{id}/activities/{id}-variant
# negeert het id en geeft de volledige lijst terug → kapotte lap-fetch.
ACTIVITY_BASE = "https://intervals.icu/api/v1/activity"
DAYS_BACK = 30  # ophalen laatste 30 dagen wellness (nodig voor stabiele HRV basislijn)
ACTIVITY_DAYS_BACK = 28  # ophalen laatste 28 dagen activiteiten (nodig voor 7:28 ACWR)

# Discovery-modus: log de ruwe keys van het eerste wellness-record en de eerste run.
# Handig om vast te stellen welke nieuwe Fenix 8-velden intervals.icu daadwerkelijk
# levert (running power/dynamics, huidtemperatuur, Endurance/Hill Score).
DEBUG_KEYS = os.environ.get("INTERVALS_DEBUG_KEYS", "").strip() in ("1", "true", "yes")


def _auth(api_key: str) -> tuple[str, str]:
    """HTTP Basic Auth tuple voor intervals.icu: username='API_KEY', password=api_key."""
    return ("API_KEY", api_key)


# Running-dynamics velden → (kandidaat-keys in intervals.icu, afronding).
# intervals.icu hanteert geen vaste veldnamen; we proberen meerdere varianten.
_RUN_DYNAMICS = {
    "stride_length_m":     (("average_stride", "avg_stride", "stride_length"), 2),
    "ground_contact_ms":   (("average_ground_contact_time", "ground_contact_time", "avg_gct"), 1),
    "vert_oscillation_mm": (("average_vertical_oscillation", "vertical_oscillation", "avg_vert_osc"), 1),
    "vert_ratio_pct":      (("average_vertical_ratio", "vertical_ratio", "avg_vert_ratio"), 1),
}


def _extract_run_dynamics(source: dict) -> dict:
    """Haal beschikbare running-dynamics velden uit een activity- of detail-dict."""
    found: dict = {}
    for out_key, (candidates, ndigits) in _RUN_DYNAMICS.items():
        val = next((source.get(k) for k in candidates if source.get(k) is not None), None)
        if val is not None and val > 0:
            found[out_key] = round(float(val), ndigits)
    return found


def fetch_intervals_data() -> dict | None:
    """
    Haal wellness en activiteiten op van intervals.icu.
    Retourneert None als secrets ontbreken of API niet bereikbaar is.
    """
    athlete_id = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key = os.environ.get("INTERVALS_API_KEY", "").strip()

    if not athlete_id or not api_key:
        log.info("INTERVALS_ATHLETE_ID of INTERVALS_API_KEY niet ingesteld — intervals.icu overgeslagen")
        return None

    today = date.today()
    oldest_wellness = (today - timedelta(days=DAYS_BACK)).isoformat()
    oldest_activities = (today - timedelta(days=ACTIVITY_DAYS_BACK)).isoformat()
    newest = today.isoformat()

    auth = _auth(api_key)
    session = requests.Session()
    session.auth = auth
    session.headers.update({"Accept": "application/json"})

    result: dict = {
        "wellness": {"by_date": {}},
        "activities": {"by_date": {}},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── 1. Wellness (rustpols, HRV, slaap, CTL/ATL/TSB) ─────────────────
    try:
        url = f"{BASE_URL}/{athlete_id}/wellness"
        resp = session.get(url, params={"oldest": oldest_wellness, "newest": newest}, timeout=20)
        resp.raise_for_status()
        wellness_list = resp.json()
        log.info("Intervals.icu wellness: %d records ontvangen", len(wellness_list))

        if DEBUG_KEYS and wellness_list:
            # Log de keys van het meest recente record met data (laatste in de lijst)
            for w in reversed(wellness_list):
                if any(v is not None for v in w.values()):
                    log.info("[DEBUG] wellness keys (%s): %s", w.get("id"), sorted(w.keys()))
                    break

        for w in wellness_list:
            day = w.get("id")  # datum als "YYYY-MM-DD"
            if not day:
                continue

            entry: dict = {}

            rhr = w.get("restingHR")
            if rhr is not None and rhr > 0:
                entry["resting_hr"] = int(rhr)

            # HRV: intervals.icu slaat RMSSD op als 'rmssd' of 'hrv'
            hrv = w.get("rmssd") or w.get("hrv")
            if hrv is not None and hrv > 0:
                entry["hrv"] = round(float(hrv), 1)

            # HRV SDNN (aanvullende HRV-maat naast rMSSD)
            hrv_sdnn = w.get("hrvSDNN")
            if hrv_sdnn is not None and hrv_sdnn > 0:
                entry["hrv_sdnn"] = round(float(hrv_sdnn), 1)

            sleep_secs = w.get("sleepSecs")
            if sleep_secs is not None and sleep_secs > 0:
                entry["sleep_hrs"] = round(sleep_secs / 3600, 2)

            sleep_score = w.get("sleepScore")
            if sleep_score is not None:
                entry["sleep_score"] = int(sleep_score)

            # Gemiddelde slaap-HR (bpm)
            sleep_hr = w.get("avgSleepingHR")
            if sleep_hr is not None and sleep_hr > 0:
                entry["avg_sleeping_hr"] = round(float(sleep_hr), 1)

            # Slaapkwaliteit (1–5 score)
            sleep_quality = w.get("sleepQuality")
            if sleep_quality is not None:
                entry["sleep_quality"] = int(sleep_quality)

            ctl = w.get("ctl")
            if ctl is not None:
                entry["ctl"] = round(float(ctl), 1)

            atl = w.get("atl")
            if atl is not None:
                entry["atl"] = round(float(atl), 1)

            # TSB: intervals.icu retourneert dit niet altijd — fallback: ctl - atl
            tsb = w.get("tsb")
            if tsb is None and ctl is not None and atl is not None:
                tsb = float(ctl) - float(atl)
            if tsb is not None:
                entry["tsb"] = round(float(tsb), 1)

            weight = w.get("weight")
            if weight is not None and weight > 0:
                entry["weight_kg"] = round(float(weight), 1)

            # SpO₂: intervals.icu gebruikt 'spO2' (camelCase) of 'spo2' (lowercase)
            spo2 = w.get("spO2") if w.get("spO2") is not None else w.get("spo2")
            if spo2 is not None and spo2 > 0:
                entry["spo2"] = round(float(spo2), 1)

            steps = w.get("steps")
            if steps is not None and steps > 0:
                entry["steps"] = int(steps)

            vo2max = w.get("vo2max")
            if vo2max is not None and vo2max > 0:
                entry["vo2max"] = round(float(vo2max), 1)

            # Gereedheid (readiness score, bijv. van Garmin Body Battery)
            readiness = w.get("readiness")
            if readiness is not None and readiness > 0:
                entry["readiness"] = int(readiness)

            # Ademhalingsfrequentie (ademhalingen/min, uit Garmin slaapdata)
            resp = w.get("respiration")
            if resp is not None and resp > 0:
                entry["respiration"] = round(float(resp), 1)

            # Bloeddruk (systolisch / diastolisch, mmHg)
            systolic = w.get("systolic")
            if systolic is not None and systolic > 0:
                entry["bp_systolic"] = int(systolic)
            diastolic = w.get("diastolic")
            if diastolic is not None and diastolic > 0:
                entry["bp_diastolic"] = int(diastolic)

            # Vetpercentage (%)
            body_fat = w.get("bodyFat")
            if body_fat is not None and body_fat > 0:
                entry["body_fat_pct"] = round(float(body_fat), 1)

            # Subjectieve metrics (schaal 1-4 in intervals.icu; 1=laag/best voor mood/motivatie)
            for field in ("soreness", "fatigue", "stress", "mood", "motivation"):
                val = w.get(field)
                if val is not None:
                    entry[field] = int(val)

            # ── Fenix 8-specifieke wellness ─────────────────────────────────
            # LET OP: uit discovery (INTERVALS_DEBUG_KEYS) blijkt dat intervals.icu
            # de Garmin huidtemperatuur, Endurance Score en Hill Score NIET synct.
            # Onderstaande extractie is defensief en future-proof: ze vult alleen
            # iets als intervals.icu deze velden ooit gaat aanbieden. Voor nu blijven
            # ze leeg (en worden ze in de UI weggelaten). Wil je deze data tóch,
            # dan moet die via de directe Garmin Connect-fetch (fetch_garmin.py) komen.
            skin_temp = next(
                (w.get(k) for k in ("skinTemp", "skin_temp", "bodyTemp", "temperature")
                 if w.get(k) is not None),
                None,
            )
            if skin_temp is not None:
                entry["skin_temp_c"] = round(float(skin_temp), 2)

            endurance = w.get("enduranceScore") or w.get("endurance_score")
            if endurance is not None and endurance > 0:
                entry["endurance_score"] = int(endurance)
            hill = w.get("hillScore") or w.get("hill_score")
            if hill is not None and hill > 0:
                entry["hill_score"] = int(hill)

            if entry:
                result["wellness"]["by_date"][day] = entry

    except Exception as exc:
        log.warning("Intervals.icu wellness fetch mislukt: %s", exc)

    # ── 2. Activiteiten (CrossFit + andere Garmin-trainingen) ────────────
    try:
        url = f"{BASE_URL}/{athlete_id}/activities"
        resp = session.get(
            url,
            params={"oldest": oldest_activities, "newest": newest},
            timeout=20,
        )
        resp.raise_for_status()
        activities_list = resp.json()
        log.info("Intervals.icu activiteiten: %d records ontvangen", len(activities_list))

        if DEBUG_KEYS:
            run_types_dbg = {"run", "running", "trailrun", "treadmill"}
            sample_run = next(
                (a for a in activities_list
                 if any(rt in (a.get("type") or "").lower() for rt in run_types_dbg)),
                None,
            )
            if sample_run:
                log.info("[DEBUG] run activity keys (%s): %s",
                         sample_run.get("name"), sorted(sample_run.keys()))

        for act in activities_list:
            # Datum uit start_date_local (formaat: "YYYY-MM-DDTHH:MM:SS")
            start = act.get("start_date_local") or act.get("start_date") or ""
            day = start[:10] if start else ""
            if not day:
                continue

            entry: dict = {}

            start_time = start[11:16] if len(start) > 10 else ""
            if start_time:
                entry["start_time"] = start_time

            name = act.get("name", "")
            if name:
                entry["name"] = name

            act_type = act.get("type") or act.get("sport_type", "")
            if act_type:
                entry["type"] = act_type

            # Duur in minuten
            moving = act.get("moving_time") or act.get("elapsed_time") or 0
            if moving > 0:
                entry["duration_min"] = round(moving / 60)

            avg_hr = act.get("average_heartrate")
            if avg_hr is not None and avg_hr > 0:
                entry["avg_hr"] = int(avg_hr)

            max_hr = act.get("max_heartrate")
            if max_hr is not None and max_hr > 0:
                entry["max_hr"] = int(max_hr)

            cals = act.get("calories")
            if cals is not None and cals > 0:
                entry["calories"] = int(cals)

            # Training load: intervals.icu eigen berekening heeft hogere prioriteit
            tl = act.get("icu_training_load") or act.get("training_load")
            if tl is not None:
                entry["training_load"] = round(float(tl), 1)

            # Afstand (meters → opslaan als meters, weergave in km)
            dist = act.get("distance")
            if dist is not None and dist > 0:
                entry["distance_m"] = round(float(dist))

            # Hoogtemeters
            elev = act.get("total_elevation_gain")
            if elev is not None and elev > 0:
                entry["elevation_m"] = round(float(elev))

            # Gemiddeld vermogen (watt). Bij hardlopen is dit running power; de
            # Fenix 8 meet dit vanaf de pols. intervals.icu levert het als
            # 'icu_average_watts' (runs hebben geen 'average_watts').
            watts = act.get("average_watts") or act.get("icu_average_watts")
            if watts is not None and watts > 0:
                entry["avg_watts"] = round(float(watts))

            # Gemiddelde snelheid (m/s → opslaan, weergave als km/u of tempo)
            speed = act.get("average_speed")
            if speed is not None and speed > 0:
                entry["avg_speed_ms"] = round(float(speed), 2)

            # Perceived exertion (RPE 1-10)
            rpe = act.get("perceived_exertion")
            if rpe is not None:
                entry["rpe"] = round(float(rpe), 1)

            # Cadans (stappen/min voor hardlopen, omw/min voor fietsen)
            cadence = act.get("average_cadence")
            if cadence is not None and cadence > 0:
                entry["avg_cadence"] = round(float(cadence), 1)

            # ── Running dynamics (Fenix 8 meet deze vanaf de pols, zonder band) ──
            # Probeer op activity-niveau; ontbrekende velden worden later via de
            # detail/stream fetch aangevuld (zie laps-sectie).
            entry.update(_extract_run_dynamics(act))

            # TRIMP (traditionele trainingsbelasting op basis van HR)
            trimp = act.get("trimp")
            if trimp is not None and trimp > 0:
                entry["trimp"] = round(float(trimp), 1)

            # HR-zone verdeling: seconden per zone [Z1, Z2, Z3, Z4, Z5]
            hr_zones = act.get("icu_hr_zone_times")
            if hr_zones and isinstance(hr_zones, list) and any(v for v in hr_zones if v):
                entry["hr_zone_times"] = [int(v or 0) for v in hr_zones]

            # Temperatuur tijdens activiteit
            temp = act.get("average_temp")
            if temp is not None:
                entry["avg_temp_c"] = round(float(temp), 1)

            # Indoor / trainer vlaggen
            if act.get("indoor") or act.get("trainer"):
                entry["indoor"] = True

            # Wedstrijd vlag
            if act.get("race"):
                entry["race"] = True

            # Sla intervals.icu activity ID op voor lap-fetch
            act_id = act.get("id")
            if act_id:
                entry["intervals_id"] = act_id

            result["activities"]["by_date"].setdefault(day, []).append(entry)

    except Exception as exc:
        log.warning("Intervals.icu activiteiten fetch mislukt: %s", exc)

    # ── 3. HRV adaptatie trend (recente 15 dagen vs. vorige 15 dagen) ───────
    hrv_dates = sorted(
        d for d in result["wellness"]["by_date"]
        if result["wellness"]["by_date"][d].get("hrv") is not None
    )
    if len(hrv_dates) >= 10:
        mid = len(hrv_dates) // 2
        recent_vals = [result["wellness"]["by_date"][d]["hrv"] for d in hrv_dates[mid:]]
        prev_vals   = [result["wellness"]["by_date"][d]["hrv"] for d in hrv_dates[:mid]]
        recent_avg  = sum(recent_vals) / len(recent_vals)
        prev_avg    = sum(prev_vals) / len(prev_vals)
        delta       = round(recent_avg - prev_avg, 1)
        result["hrv_trend"] = {
            "delta_ms":   delta,
            "direction":  "up" if delta > 0.5 else "down" if delta < -0.5 else "stable",
            "recent_avg": round(recent_avg, 1),
            "prev_avg":   round(prev_avg, 1),
            "days_used":  len(hrv_dates),
        }
        log.info("HRV trend: %+.1f ms (%s) — recent avg %.1f ms, prev avg %.1f ms",
                 delta, result["hrv_trend"]["direction"], recent_avg, prev_avg)

    # ── 4. Laps ophalen voor recente hardloopactiviteiten ────────────────
    try:
        run_types = {"run", "running", "trailrun", "treadmill"}
        run_acts = [
            (day, act)
            for day, acts in result["activities"]["by_date"].items()
            for act in acts
            if any(rt in (act.get("type") or "").lower() for rt in run_types)
            and act.get("intervals_id")
        ]
        # Beperk tot laatste 14 dagen en max 10 runs om API-calls te beperken
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        run_acts = [(d, a) for d, a in run_acts if d >= cutoff][:10]

        for day, act in run_acts:
            act_id = act["intervals_id"]
            try:
                resp = session.get(
                    f"{ACTIVITY_BASE}/{act_id}",
                    timeout=20,
                )
                if not resp.ok:
                    continue
                detail = resp.json()
                if not isinstance(detail, dict):
                    log.warning("Onverwacht activity-detail formaat voor %s (%s)", act_id, type(detail).__name__)
                    continue

                if DEBUG_KEYS:
                    log.info("[DEBUG] activity detail keys (%s): %s", act_id, sorted(detail.keys()))
                    log.info("[DEBUG] stream_types (%s): %s", act_id, detail.get("stream_types"))

                # Running dynamics aanvullen vanuit activity-detail (heeft soms meer
                # velden dan de lijst-respons). Bestaande waarden niet overschrijven.
                for k, v in _extract_run_dynamics(detail).items():
                    act.setdefault(k, v)

                # Stream-fallback: GCT / verticale oscillatie / ratio staan niet op
                # activity-niveau, alleen in de streams. Haal ze op en middel ze.
                if not all(k in act for k in _RUN_DYNAMICS):
                    try:
                        s_resp = session.get(
                            f"{ACTIVITY_BASE}/{act_id}/streams",
                            params={"types": "ground_contact_time,vertical_oscillation,"
                                             "vertical_ratio,stride,watts"},
                            timeout=20,
                        )
                        if s_resp.ok:
                            streams = s_resp.json() or []
                            # intervals.icu geeft een lijst van {type, data:[...]}
                            by_type = {s.get("type"): s.get("data") or [] for s in streams
                                       if isinstance(s, dict)}
                            stream_map = {
                                "stride_length_m":     ("stride", 2),
                                "ground_contact_ms":   ("ground_contact_time", 1),
                                "vert_oscillation_mm": ("vertical_oscillation", 1),
                                "vert_ratio_pct":      ("vertical_ratio", 1),
                            }
                            for out_key, (stype, ndigits) in stream_map.items():
                                vals = [v for v in by_type.get(stype, []) if isinstance(v, (int, float)) and v > 0]
                                if vals:
                                    act.setdefault(out_key, round(sum(vals) / len(vals), ndigits))
                            # Running power uit watts-stream als activity-niveau ontbreekt
                            if not act.get("avg_watts"):
                                w_vals = [v for v in by_type.get("watts", []) if isinstance(v, (int, float)) and v > 0]
                                if w_vals:
                                    act["avg_watts"] = round(sum(w_vals) / len(w_vals))
                    except Exception as exc:
                        log.warning("Streams fetch mislukt voor activiteit %s: %s", act_id, exc)

                laps_raw = detail.get("laps") or []
                laps = []
                for lap in laps_raw:
                    lap_entry: dict = {}
                    lap_dist = lap.get("distance")
                    if lap_dist and lap_dist > 0:
                        lap_entry["distance_m"] = round(float(lap_dist))
                    lap_time = lap.get("elapsed_time") or lap.get("moving_time")
                    if lap_time and lap_time > 0:
                        lap_entry["duration_s"] = int(lap_time)
                        if lap_dist and lap_dist > 0:
                            pace_spm = lap_time / (float(lap_dist) / 1000) / 60
                            lap_entry["pace_per_km"] = f"{int(pace_spm)}:{int((pace_spm % 1) * 60):02d}"
                    lap_hr = lap.get("average_heartrate")
                    if lap_hr and lap_hr > 0:
                        lap_entry["avg_hr"] = int(lap_hr)
                    lap_cadence = lap.get("average_cadence")
                    if lap_cadence and lap_cadence > 0:
                        lap_entry["avg_cadence"] = round(float(lap_cadence), 1)
                    if lap_entry:
                        laps.append(lap_entry)
                if laps:
                    act["laps"] = laps
                    log.info("Laps opgehaald voor activiteit %s (%s): %d laps", act_id, day, len(laps))
            except Exception as exc:
                log.warning("Laps fetch mislukt voor activiteit %s: %s", act_id, exc)
    except Exception as exc:
        log.warning("Laps fetch loop mislukt: %s", exc)

    # Retourneer None als er helemaal niets opgehaald is
    if not result["wellness"]["by_date"] and not result["activities"]["by_date"]:
        log.info("Geen intervals.icu data ontvangen")
        return None

    return result


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = fetch_intervals_data()
    if data:
        n_w = len(data["wellness"]["by_date"])
        n_a = sum(len(v) for v in data["activities"]["by_date"].values())
        print(f"Wellness: {n_w} dagen, Activiteiten: {n_a}")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("Geen data beschikbaar (INTERVALS_ATHLETE_ID / INTERVALS_API_KEY niet ingesteld of fetch mislukt)")
