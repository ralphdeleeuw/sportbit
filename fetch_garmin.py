#!/usr/bin/env python3
"""
Garmin Connect data fetcher voor het SportBit CrossFit dashboard.

Ondersteunt twee authenticatiemethoden (in volgorde van voorkeur):

══════════════════════════════════════════════════════════════
METHODE 1 — garth OAuth2-tokens (voorkeur, ~12 maanden geldig)
══════════════════════════════════════════════════════════════
Vereist GitHub Secret: GARMIN_TOKENS

ONE-TIME TOKEN SETUP (run lokaal, eenmalig per ~12 maanden):

1. Install deps:
       pip install garth garminconnect

2. Authenticeer en sla tokens op:
       python3 -c "
       import garth, getpass
       garth.login('ralph.deleeuw@gmail.com', getpass.getpass('Garmin wachtwoord: '))
       garth.save('garth_tokens')
       print('Tokens opgeslagen in ./garth_tokens/')
       "
   Keur MFA goed in de Garmin Connect app als gevraagd.

3. Exporteer tokens als base64:
       tar czf - garth_tokens | base64 -w0 > garth_tokens.b64
       # op macOS: tar czf - garth_tokens | base64 > garth_tokens.b64

4. Voeg toe als GitHub Secret:
       Repo → Settings → Secrets and variables → Actions → New secret
       Name : GARMIN_TOKENS
       Value: <plak hier de base64-string>

5. Verwijder lokale bestanden:
       rm -rf garth_tokens garth_tokens.b64

══════════════════════════════════════════════════════════════
METHODE 2 — browser SESSIONID (noodoplossing, weken/maanden geldig)
══════════════════════════════════════════════════════════════
Vereist GitHub Secret: GARMIN_SESSION_ID

Gebruik dit als GARMIN_TOKENS verlopen is én de OAuth2-login
tijdelijk geblokkeerd is (429 rate-limit).

Hoe de SESSIONID ophalen:
1. Log in op https://connect.garmin.com in Chrome/Firefox
2. Open DevTools → Application → Cookies → connect.garmin.com
3. Kopieer de waarde van het cookie "SESSIONID"
4. Voeg toe als GitHub Secret:
       Name : GARMIN_SESSION_ID
       Value: <SESSIONID-waarde>

Opmerking: methode 2 werkt NIET als het browsertabblad en alle
sessies uitgelogd zijn. De SESSIONID blijft geldig zolang je
ingelogd blijft op connect.garmin.com.
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
from datetime import date, timedelta, timezone
from datetime import datetime as dt
from typing import Any

log = logging.getLogger(__name__)


def _restore_garth_tokens(tokens_b64: str, target_dir: str) -> bool:
    """Decode the base64 tarball and extract garth tokens to target_dir."""
    try:
        tar_data = base64.b64decode(tokens_b64)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
            f.write(tar_data)
            tmp_path = f.name
        result = subprocess.run(
            ["tar", "xzf", tmp_path, "--strip-components=1", "-C", target_dir],
            capture_output=True,
        )
        os.unlink(tmp_path)
        return result.returncode == 0
    except Exception as exc:
        log.warning("Failed to restore garth tokens: %s", exc)
        return False


def _parse_activity(raw: dict) -> dict:
    """Parse a raw Garmin activity dict into a clean summary."""
    start_local = raw.get("startTimeLocal", "")
    # startTimeLocal format: "2026-03-22 20:05:00"
    activity_date = start_local[:10] if start_local else None

    duration_s = raw.get("duration") or raw.get("elapsedDuration") or 0
    duration_min = round(duration_s / 60) if duration_s else None

    avg_hr = raw.get("averageHR")
    max_hr = raw.get("maxHR")
    calories = raw.get("calories") or raw.get("activeKilocalories")
    aerobic_te = raw.get("aerobicTrainingEffect")
    anaerobic_te = raw.get("anaerobicTrainingEffect")

    # HR zones: seconds spent in each zone
    zones: dict[str, Any] = {}
    for i in range(1, 6):
        key = f"hrTimeInZone_{i}"
        val = raw.get(key)
        if val is not None:
            zones[f"zone{i}_min"] = round(val / 60)

    activity_type = raw.get("activityType", {})
    type_key = activity_type.get("typeKey", "") if isinstance(activity_type, dict) else ""

    return {
        "date": activity_date,
        "start_time": start_local,
        "activity_id": raw.get("activityId"),
        "name": raw.get("activityName", ""),
        "type": type_key,
        "duration_min": duration_min,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "calories": calories,
        "aerobic_te": aerobic_te,
        "anaerobic_te": anaerobic_te,
        "hr_zones": zones if zones else None,
    }


def fetch_recent_activities(garmin, days: int = 14) -> dict[str, list[dict]]:
    """
    Fetch recent Garmin activities for the past `days` days.

    Returns a dict keyed by date string (YYYY-MM-DD), each value a list of
    activity summaries for that day (avg/max HR, duration, training effect,
    HR zones, calories).
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        activities_raw = garmin.get_activities_by_date(
            start_date.isoformat(), end_date.isoformat()
        )
    except Exception as exc:
        log.warning("Activiteiten ophalen mislukt: %s", exc)
        return {}

    by_date: dict[str, list[dict]] = {}
    for raw in (activities_raw or []):
        parsed = _parse_activity(raw)
        d = parsed.get("date")
        if d:
            by_date.setdefault(d, []).append(parsed)
            log.info(
                "Activiteit %s: %s, gem.HR %s, max.HR %s, TE %.1f/%.1f",
                d,
                parsed["name"],
                parsed["avg_hr"],
                parsed["max_hr"],
                parsed["aerobic_te"] or 0,
                parsed["anaerobic_te"] or 0,
            )

    log.info("Totaal %d activiteiten opgehaald over afgelopen %d dagen", len(activities_raw or []), days)
    return by_date


# ── Methode 2: web-session (SESSIONID) ───────────────────────────────────────

_GARMIN_WEB_BASE = "https://connect.garmin.com/modern/proxy"
_GARMIN_WEB_HEADERS = {
    "NK": "NT",  # Garmin CSRF-bypass header (vereist voor proxy-endpoints)
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _refresh_jwt_from_session(session_id: str, sso_session: str = "") -> str | None:
    """
    Gebruik de SESSIONID-cookie (en optioneel de SSO 'session'-cookie) om
    een verse JWT_WEB te krijgen van connect.garmin.com.

    - SESSIONID  → connect.garmin.com app-sessie (base64-encoded UUID)
    - sso_session → sso.garmin.com Fe26.2-sessie (optioneel, geeft meer kans
                    op succes als de SESSIONID net verlopen is)
    """
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        log.warning("requests niet geïnstalleerd — web-session methode niet beschikbaar")
        return None

    s = requests.Session()
    s.cookies.set("SESSIONID", session_id, domain="connect.garmin.com")
    if sso_session:
        s.cookies.set("session", sso_session, domain="sso.garmin.com")
    try:
        s.get(
            "https://connect.garmin.com/modern/",
            headers={"User-Agent": _GARMIN_WEB_HEADERS["User-Agent"]},
            timeout=15,
            allow_redirects=True,
        )
        jwt = s.cookies.get("JWT_WEB")
        if jwt:
            log.info("JWT_WEB succesvol vernieuwd via SESSIONID")
        else:
            log.warning("SESSIONID geldig maar geen JWT_WEB ontvangen — sessie mogelijk verlopen")
        return jwt
    except Exception as exc:
        log.warning("JWT refresh via SESSIONID mislukt: %s", exc)
        return None


def _web_get(jwt: str, path: str, params: dict | None = None) -> dict | list | None:
    """GET-verzoek naar de Garmin Connect web-proxy API."""
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        return None

    url = f"{_GARMIN_WEB_BASE}/{path}"
    headers = {**_GARMIN_WEB_HEADERS, "Authorization": f"Bearer {jwt}"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Garmin web-API fout [%s]: %s", path, exc)
        return None


def _get_web_user_id(jwt: str) -> str | None:
    """Haal de Garmin gebruikers-ID op via het sociaal-profiel endpoint."""
    profile = _web_get(jwt, "userprofile-service/socialProfile")
    if isinstance(profile, dict):
        return str(profile.get("profileId") or profile.get("userId") or "")
    return None


def _fetch_metrics_web(jwt: str, user_id: str, query_date: date) -> dict | None:
    """
    Haal alle herstelmetrieken op via de Garmin Connect web-API
    (zelfde data als _fetch_metrics maar via JWT_WEB i.p.v. OAuth2).
    """
    date_str = query_date.isoformat()
    result: dict = {
        "date": date_str,
        "hrv": None,
        "sleep": None,
        "body_battery": None,
        "stress_avg": None,
        "resting_hr": None,
        "fetched_at": dt.now(timezone.utc).isoformat(),
    }
    has_any_data = False

    # ── HRV ──────────────────────────────────────────────────────────────
    hrv_raw = _web_get(jwt, f"wellness-service/wellness/hrv/{date_str}")
    if hrv_raw and isinstance(hrv_raw, dict):
        summary = hrv_raw.get("hrvSummary", hrv_raw)
        last_night = summary.get("lastNight")
        weekly_avg = summary.get("weeklyAvg")
        if last_night or weekly_avg:
            result["hrv"] = {
                "lastNight": last_night,
                "weeklyAvg": weekly_avg,
                "status": summary.get("status", "NONE"),
            }
            has_any_data = True
            log.info("HRV: %sms (weekgemiddelde: %s)", last_night, weekly_avg)

    # ── Slaap ─────────────────────────────────────────────────────────────
    sleep_raw = _web_get(jwt, f"sleep-service/sleep/{date_str}")
    if sleep_raw and isinstance(sleep_raw, dict):
        daily = sleep_raw.get("dailySleepDTO", {})
        scores = sleep_raw.get("sleepScores", {})
        score_value = None
        if isinstance(scores, dict):
            score_value = (
                scores.get("overall", {}).get("value")
                or scores.get("totalDuration", {}).get("value")
            )
        if score_value is None:
            score_value = daily.get("sleepScoreValue")
        total_s = daily.get("sleepTimeSeconds", 0) or 0
        if total_s > 0 or score_value is not None:
            result["sleep"] = {
                "score": score_value,
                "duration_hours": round(total_s / 3600, 1) if total_s else None,
                "deep_minutes": round((daily.get("deepSleepSeconds") or 0) / 60) or None,
                "rem_minutes": round((daily.get("remSleepSeconds") or 0) / 60) or None,
                "light_minutes": round((daily.get("lightSleepSeconds") or 0) / 60) or None,
                "awake_minutes": round((daily.get("awakeSleepSeconds") or 0) / 60) or None,
            }
            has_any_data = True
            log.info("Slaap: %.1fu (score: %s)", total_s / 3600, score_value)

    # ── Body Battery ──────────────────────────────────────────────────────
    bb_raw = _web_get(
        jwt,
        "wellness-service/wellness/bodyBattery/events",
        params={"startDate": date_str, "endDate": date_str},
    )
    if bb_raw and isinstance(bb_raw, list) and bb_raw:
        day = bb_raw[0]
        charged = day.get("charged")
        readings = day.get("bodyBatteryValuesArray", [])
        end_value = readings[-1][1] if readings else None
        if charged is not None or end_value is not None:
            result["body_battery"] = {
                "charged": charged,
                "drained": day.get("drained"),
                "end_value": end_value,
            }
            has_any_data = True
            log.info("Body Battery: opgeladen %s, huidig %s", charged, end_value)

    # ── Stress ────────────────────────────────────────────────────────────
    stress_raw = _web_get(jwt, f"wellness-service/wellness/dailyStress/{date_str}")
    if stress_raw and isinstance(stress_raw, dict):
        avg = stress_raw.get("avgStressLevel") or stress_raw.get("overallStressLevel")
        if avg is not None and avg >= 0:
            result["stress_avg"] = avg
            has_any_data = True
            log.info("Gemiddelde stress: %s/100", avg)

    # ── Rustpols (dagelijkse samenvatting) ────────────────────────────────
    stats_raw = _web_get(
        jwt,
        f"usersummary-service/usersummary/daily/{user_id}",
        params={"calendarDate": date_str},
    )
    if stats_raw and isinstance(stats_raw, dict):
        rhr = stats_raw.get("restingHeartRate")
        if rhr:
            result["resting_hr"] = rhr
            has_any_data = True
            log.info("Rustpols: %s bpm", rhr)

    return result if has_any_data else None


def _fetch_activities_web(jwt: str, days: int = 14) -> dict[str, list[dict]]:
    """Haal recente activiteiten op via de Garmin Connect web-API."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    raw = _web_get(
        jwt,
        "activitylist-service/activities/search/activities",
        params={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "limit": 40,
        },
    )
    by_date: dict[str, list[dict]] = {}
    for activity in raw or []:
        parsed = _parse_activity(activity)
        d = parsed.get("date")
        if d:
            by_date.setdefault(d, []).append(parsed)
    log.info("Web-API: %d activiteiten opgehaald over afgelopen %d dagen", len(raw or []), days)
    return by_date


def _fetch_garmin_via_web_session(target_date: date) -> dict | None:
    """
    Alternatieve Garmin-fetch via browser SESSIONID (geen garth/OAuth2 nodig).

    Gebruik dit als GARMIN_TOKENS verlopen is. Sla de SESSIONID-cookie van
    connect.garmin.com op als GitHub Secret 'GARMIN_SESSION_ID'.
    """
    session_id = os.environ.get("GARMIN_SESSION_ID", "").strip()
    if not session_id:
        return None

    sso_session = os.environ.get("GARMIN_SSO_SESSION", "").strip()
    log.info("GARMIN_TOKENS niet beschikbaar — probeer GARMIN_SESSION_ID...")
    jwt = _refresh_jwt_from_session(session_id, sso_session)
    if not jwt:
        log.warning("Kon geen JWT_WEB verkrijgen via SESSIONID — web-session methode mislukt")
        return None

    user_id = _get_web_user_id(jwt) or ""
    if not user_id:
        log.warning("Kon gebruikers-ID niet ophalen — rustpols-data mogelijk niet beschikbaar")

    activities_by_date = _fetch_activities_web(jwt, days=14)

    for delta in (0, 1):
        query_date = target_date - timedelta(days=delta)
        data = _fetch_metrics_web(jwt, user_id, query_date)
        if data is not None:
            if delta > 0:
                log.info(
                    "Web-session: data voor %s niet beschikbaar, valt terug op %s",
                    target_date,
                    query_date,
                )
            data["activities_by_date"] = activities_by_date
            log.info("Garmin data succesvol opgehaald via web-session methode")
            return data

    log.warning("Web-session: geen data beschikbaar voor %s of eerder", target_date)
    return None


# ── Hoofdfunctie ──────────────────────────────────────────────────────────────


def fetch_garmin_data(target_date: date | None = None) -> dict | None:
    """
    Fetch recovery metrics from Garmin Connect for the given date.

    Returns a dict with HRV, sleep, body battery, stress, resting HR and
    recent activities (keyed by date), or None if GARMIN_TOKENS is not configured.

    Falls back to the previous day if today's data is not yet synced to
    Garmin Connect (Fenix 6 watches sync in batches).
    """
    tokens_b64 = os.environ.get("GARMIN_TOKENS", "").strip()
    if not tokens_b64:
        log.info("GARMIN_TOKENS not set — probeer web-session methode")
        if target_date is None:
            target_date = date.today()
        return _fetch_garmin_via_web_session(target_date)

    try:
        import garth  # noqa: PLC0415
        from garminconnect import Garmin  # noqa: PLC0415
    except ImportError:
        log.warning("garth/garminconnect not installed — skipping Garmin fetch")
        return None

    if target_date is None:
        target_date = date.today()

    # Restore tokens to a temp directory
    with tempfile.TemporaryDirectory() as token_dir:
        if not _restore_garth_tokens(tokens_b64, token_dir):
            log.warning("Could not restore garth tokens — skipping Garmin fetch")
            return None

        try:
            garth.resume(token_dir)
            garmin = Garmin()
            garmin.login()
            log.info("Garmin Connect authenticatie geslaagd via opgeslagen tokens")
        except Exception as exc:
            log.warning("Garmin login mislukt: %s — probeer web-session methode als fallback", exc)
            return _fetch_garmin_via_web_session(target_date)

        # Fetch recent activities (last 14 days) for WOD matching
        activities_by_date = fetch_recent_activities(garmin, days=14)

        # Try today, fall back to yesterday if data is incomplete
        for delta in (0, 1):
            query_date = target_date - timedelta(days=delta)
            data = _fetch_metrics(garmin, query_date)
            if data is not None:
                if delta > 0:
                    log.info(
                        "Garmin data voor %s niet beschikbaar, valt terug op %s",
                        target_date,
                        query_date,
                    )
                data["activities_by_date"] = activities_by_date
                return data

    log.warning("Geen Garmin data beschikbaar voor %s of %s", target_date, target_date - timedelta(days=1))
    return None


def _fetch_metrics(garmin, query_date: date) -> dict | None:
    """
    Fetch all metrics for one date. Returns None if the data looks empty/incomplete.
    """
    date_str = query_date.isoformat()
    result: dict = {
        "date": date_str,
        "hrv": None,
        "sleep": None,
        "body_battery": None,
        "stress_avg": None,
        "resting_hr": None,
        "fetched_at": dt.now(timezone.utc).isoformat(),
    }

    has_any_data = False

    # ── HRV ──────────────────────────────────────────────────────────────
    try:
        hrv_raw = garmin.get_hrv_data(date_str)
        if hrv_raw:
            # garminconnect returns dict with 'hrvSummary' key
            summary = hrv_raw.get("hrvSummary", hrv_raw)
            last_night = summary.get("lastNight")
            weekly_avg = summary.get("weeklyAvg")
            status = summary.get("status", "NONE")
            if last_night or weekly_avg:
                result["hrv"] = {
                    "lastNight": last_night,
                    "weeklyAvg": weekly_avg,
                    "status": status,
                }
                has_any_data = True
                log.info("HRV: %sms (status: %s, weekgemiddelde: %s)", last_night, status, weekly_avg)
    except Exception as exc:
        log.warning("HRV ophalen mislukt: %s", exc)

    # ── Slaap ─────────────────────────────────────────────────────────────
    try:
        sleep_raw = garmin.get_sleep_data(date_str)
        if sleep_raw:
            daily = sleep_raw.get("dailySleepDTO", {})
            score_value = None
            # Sleep score can be nested under sleepScores
            scores = sleep_raw.get("sleepScores", {})
            if isinstance(scores, dict):
                score_value = scores.get("overall", {}).get("value") or scores.get("totalDuration", {}).get("value")
            if score_value is None:
                score_value = daily.get("sleepScoreValue")

            total_seconds = daily.get("sleepTimeSeconds", 0) or 0
            deep_seconds = daily.get("deepSleepSeconds", 0) or 0
            rem_seconds = daily.get("remSleepSeconds", 0) or 0
            light_seconds = daily.get("lightSleepSeconds", 0) or 0
            awake_seconds = daily.get("awakeSleepSeconds", 0) or 0

            if total_seconds > 0 or score_value is not None:
                result["sleep"] = {
                    "score": score_value,
                    "duration_hours": round(total_seconds / 3600, 1) if total_seconds else None,
                    "deep_minutes": round(deep_seconds / 60) if deep_seconds else None,
                    "rem_minutes": round(rem_seconds / 60) if rem_seconds else None,
                    "light_minutes": round(light_seconds / 60) if light_seconds else None,
                    "awake_minutes": round(awake_seconds / 60) if awake_seconds else None,
                }
                has_any_data = True
                log.info(
                    "Slaap: %.1fu (score: %s, diep: %sm, REM: %sm)",
                    total_seconds / 3600,
                    score_value,
                    round(deep_seconds / 60),
                    round(rem_seconds / 60),
                )
    except Exception as exc:
        log.warning("Slaapdata ophalen mislukt: %s", exc)

    # ── Body Battery ──────────────────────────────────────────────────────
    try:
        bb_raw = garmin.get_body_battery(date_str, date_str)
        if bb_raw and isinstance(bb_raw, list) and len(bb_raw) > 0:
            day_data = bb_raw[0]
            charged = day_data.get("charged")
            drained = day_data.get("drained")
            # End-of-day value from body battery readings
            readings = day_data.get("bodyBatteryValuesArray", [])
            end_value = readings[-1][1] if readings else None
            if charged is not None or end_value is not None:
                result["body_battery"] = {
                    "charged": charged,
                    "drained": drained,
                    "end_value": end_value,
                }
                has_any_data = True
                log.info("Body Battery: opgeladen %s, huidig %s", charged, end_value)
    except Exception as exc:
        log.warning("Body Battery ophalen mislukt: %s", exc)

    # ── Stress ────────────────────────────────────────────────────────────
    try:
        stress_raw = garmin.get_stress_data(date_str)
        if stress_raw:
            avg = stress_raw.get("avgStressLevel") or stress_raw.get("overallStressLevel")
            if avg is not None and avg >= 0:
                result["stress_avg"] = avg
                has_any_data = True
                log.info("Gemiddelde stress: %s/100", avg)
    except Exception as exc:
        log.warning("Stressdata ophalen mislukt: %s", exc)

    # ── Daily stats (resting HR, steps) ───────────────────────────────────
    try:
        stats_raw = garmin.get_stats(date_str)
        if stats_raw:
            rhr = stats_raw.get("restingHeartRate")
            if rhr:
                result["resting_hr"] = rhr
                has_any_data = True
                log.info("Rustpols: %s bpm", rhr)
    except Exception as exc:
        log.warning("Dagelijkse stats ophalen mislukt: %s", exc)

    return result if has_any_data else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from datetime import date as date_cls
    data = fetch_garmin_data(date_cls.today())
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("Geen Garmin data beschikbaar (GARMIN_TOKENS niet ingesteld of fetch mislukt)")
