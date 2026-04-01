#!/usr/bin/env python3
"""
Environmental data fetcher voor het SportBit CrossFit dashboard.

Haalt weersdata op van Open-Meteo (geen API key nodig) en luchtkwaliteitsdata
van WAQI (gratis token vereist) voor Hilversum, Nederland.

══════════════════════════════════════════════════════════════
SETUP
══════════════════════════════════════════════════════════════

Open-Meteo: Geen setup nodig — volledig gratis en zonder registratie.
            Documentatie: https://open-meteo.com/en/docs

WAQI (luchtkwaliteit):
1. Ga naar https://aqicn.org/api/
2. Vraag een gratis API token aan (geen creditcard nodig)
3. Voeg toe als GitHub Secret:
   Repo → Settings → Secrets and variables → Actions
   WAQI_API_TOKEN = jouw token

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  WAQI_API_TOKEN  - WAQI luchtkwaliteit API token (optioneel)
                    Zonder token wordt AQI overgeslagen.
"""

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

AMS = ZoneInfo("Europe/Amsterdam")

# Hilversum, Nederland
HILVERSUM_LAT = 52.2318
HILVERSUM_LON = 5.1880

# WMO weather code → Nederlandse omschrijving
_WEATHER_CODES: dict[int, str] = {
    0: "Helder",
    1: "Overwegend helder",
    2: "Gedeeltelijk bewolkt",
    3: "Bewolkt",
    45: "Mist",
    48: "Rijpmist",
    51: "Lichte motregen",
    53: "Motregen",
    55: "Dichte motregen",
    61: "Lichte regen",
    63: "Regen",
    65: "Zware regen",
    71: "Lichte sneeuw",
    73: "Sneeuw",
    75: "Zware sneeuw",
    77: "Sneeuwkorrels",
    80: "Lichte regenbuien",
    81: "Regenbuien",
    82: "Zware regenbuien",
    85: "Sneeuwbuien",
    86: "Zware sneeuwbuien",
    95: "Onweer",
    96: "Onweer met hagel",
    99: "Zwaar onweer met hagel",
}


def _weather_desc(code: int) -> str:
    return _WEATHER_CODES.get(code, f"Code {code}")


def _aqi_category(aqi: int) -> str:
    if aqi <= 50:
        return "Goed"
    elif aqi <= 100:
        return "Matig"
    elif aqi <= 150:
        return "Ongezond voor gevoelige groepen"
    elif aqi <= 200:
        return "Ongezond"
    else:
        return "Zeer ongezond"


def fetch_environmental_data(
    training_times: dict[str, str] | None = None,
) -> dict | None:
    """Haalt weersdata en luchtkwaliteit op voor Hilversum.

    Args:
        training_times: optioneel dict van {date_str: "HH:MM"} voor welke
                        trainingsdata (datum + tijd) specifiek opgezocht
                        moet worden in de uursvoorspelling.

    Returns:
        dict met 'training_conditions', 'aqi' en 'fetched_at', of None bij fout.
    """
    # ── 1. Weersdata van Open-Meteo (geen API key nodig) ─────────────────
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": HILVERSUM_LAT,
                "longitude": HILVERSUM_LON,
                "hourly": ",".join([
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "wind_speed_10m",
                    "weather_code",
                ]),
                "timezone": "Europe/Amsterdam",
                "forecast_days": 7,
            },
            timeout=15,
        )
        resp.raise_for_status()
        weather_raw = resp.json()
        hourly_count = len(weather_raw.get("hourly", {}).get("time", []))
        log.info("Open-Meteo: weersdata opgehaald voor %d uur", hourly_count)
    except Exception as exc:
        log.warning("Open-Meteo fetch mislukt: %s", exc)
        return None

    hourly = weather_raw.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    feels = hourly.get("apparent_temperature", [])
    humids = hourly.get("relative_humidity_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    codes = hourly.get("weather_code", [])

    # Build lookup: "YYYY-MM-DDTHH:00" → list index
    time_index = {t: i for i, t in enumerate(times)}

    # ── 2. Extract trainingsomstandigheden per datum ──────────────────────
    training_conditions: dict[str, dict] = {}
    if training_times:
        for date_str, time_str in training_times.items():
            hour = time_str[:2]  # "20:00" → "20"
            key = f"{date_str}T{hour}:00"
            idx = time_index.get(key)
            if idx is not None:
                wcode = int(codes[idx]) if codes[idx] is not None else 0
                training_conditions[date_str] = {
                    "training_time": time_str,
                    "temp_c": temps[idx],
                    "feels_like_c": feels[idx],
                    "humidity_pct": humids[idx],
                    "wind_kmh": winds[idx],
                    "weather_code": wcode,
                    "weather_desc": _weather_desc(wcode),
                }
                log.info(
                    "Weersdata %s %s: %.1f°C, %s",
                    date_str, time_str, temps[idx], _weather_desc(wcode),
                )
            else:
                log.info("Geen weersdata beschikbaar voor %s %s", date_str, time_str)

    # ── 3. AQI van WAQI (optioneel — skip als token ontbreekt) ───────────
    aqi_data: dict | None = None
    waqi_token = os.environ.get("WAQI_API_TOKEN", "").strip()
    if waqi_token:
        try:
            resp = requests.get(
                f"https://api.waqi.info/feed/Hilversum/?token={waqi_token}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ok":
                d = data["data"]
                aqi_val = int(d.get("aqi") or 0)
                iaqi = d.get("iaqi", {})
                aqi_data = {
                    "value": aqi_val,
                    "pm25": iaqi.get("pm25", {}).get("v"),
                    "pm10": iaqi.get("pm10", {}).get("v"),
                    "dominant_pol": d.get("dominentpol", ""),
                    "category": _aqi_category(aqi_val),
                }
                log.info("WAQI: AQI=%d (%s)", aqi_val, aqi_data["category"])
            else:
                log.warning("WAQI: onverwacht antwoord: %s", data.get("status"))
        except Exception as exc:
            log.warning("WAQI fetch mislukt: %s", exc)
    else:
        log.info("WAQI_API_TOKEN niet ingesteld — luchtkwaliteit overgeslagen")

    return {
        "training_conditions": training_conditions,
        "aqi": aqi_data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
