#!/usr/bin/env python3
"""
MyFitnessPal data fetcher voor het SportBit CrossFit dashboard.

Haalt het voedingsdagboek op van MyFitnessPal voor de afgelopen N dagen.
Gebruikt de `myfitnesspal` Python-bibliotheek (coddingtonbear) die de
MFP-website scrapt op basis van gebruikersnaam en wachtwoord.

MyFitnessPal heeft geen officiële publieke API meer (gesloten in 2020).

══════════════════════════════════════════════════════════════
SETUP
══════════════════════════════════════════════════════════════
1. Maak een MyFitnessPal account aan op https://www.myfitnesspal.com
2. Log je dagelijkse voeding in via de app of website
3. Zorg dat het dagboek zichtbaar is (Privacy → Diary → "Everyone" of alleen jezelf)
4. Voeg toe als GitHub Secrets:
       MFP_USERNAME  — jouw MyFitnessPal gebruikersnaam
       MFP_PASSWORD  — jouw MyFitnessPal wachtwoord

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  MFP_USERNAME  - MyFitnessPal gebruikersnaam
  MFP_PASSWORD  - MyFitnessPal wachtwoord

Return formaat:
{
  "diary": {
    "by_date": {
      "YYYY-MM-DD": {
        "calories": int,
        "protein_g": float,
        "carbs_g": float,
        "fat_g": float,
        "fiber_g": float,
        "meals": [
          {
            "name": str,          # "Breakfast", "Lunch", "Dinner", "Snacks"
            "calories": int,
            "protein_g": float,
            "carbs_g": float,
            "fat_g": float,
            "entries": [
              {
                "food": str,
                "calories": int,
                "protein_g": float,
                "carbs_g": float,
                "fat_g": float,
              }
            ]
          }
        ]
      }
    }
  },
  "fetched_at": "ISO8601"
}
"""

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def fetch_myfitnesspal_data(days: int = 7) -> dict | None:
    """
    Haal MyFitnessPal voedingsdagboek op voor de afgelopen `days` dagen.

    Retourneert None als de secrets niet geconfigureerd zijn of bij een fout.
    """
    username = os.environ.get("MFP_USERNAME", "").strip()
    password = os.environ.get("MFP_PASSWORD", "").strip()

    if not username or not password:
        log.info(
            "MyFitnessPal: geen credentials geconfigureerd "
            "(MFP_USERNAME / MFP_PASSWORD)"
        )
        return None

    try:
        import myfitnesspal  # noqa: PLC0415
    except ImportError:
        log.warning(
            "MyFitnessPal: pakket 'myfitnesspal' niet geïnstalleerd — "
            "voeg 'myfitnesspal' toe aan requirements.txt en pip install"
        )
        return None

    try:
        client = myfitnesspal.Client(username, password=password)
        log.info("MyFitnessPal: ingelogd als %s", username)
    except Exception as exc:
        log.warning("MyFitnessPal: inloggen mislukt: %s", exc)
        return None

    today = datetime.now(timezone.utc).date()
    diary_by_date: dict[str, dict] = {}

    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.isoformat()
        try:
            day = client.get_date(date.year, date.month, date.day)
        except Exception as exc:
            log.debug("MyFitnessPal: dag %s ophalen mislukt: %s", date_str, exc)
            continue

        totals = day.totals or {}

        meals = []
        for meal in day.meals:
            meal_entries = []
            for entry in meal.entries:
                nutrients = entry.nutrition_information or {}
                meal_entries.append({
                    "food": entry.name or "",
                    "calories": int(nutrients.get("calories", 0) or 0),
                    "protein_g": float(nutrients.get("protein", 0) or 0),
                    "carbs_g": float(nutrients.get("carbohydrates", 0) or 0),
                    "fat_g": float(nutrients.get("fat", 0) or 0),
                })
            meal_totals = meal.totals or {}
            meals.append({
                "name": meal.name or "",
                "calories": int(meal_totals.get("calories", 0) or 0),
                "protein_g": float(meal_totals.get("protein", 0) or 0),
                "carbs_g": float(meal_totals.get("carbohydrates", 0) or 0),
                "fat_g": float(meal_totals.get("fat", 0) or 0),
                "entries": meal_entries,
            })

        diary_by_date[date_str] = {
            "calories": int(totals.get("calories", 0) or 0),
            "protein_g": float(totals.get("protein", 0) or 0),
            "carbs_g": float(totals.get("carbohydrates", 0) or 0),
            "fat_g": float(totals.get("fat", 0) or 0),
            "fiber_g": float(totals.get("fiber", 0) or 0),
            "meals": meals,
        }

    if not diary_by_date:
        log.warning("MyFitnessPal: geen dagboekdata opgehaald voor de afgelopen %d dagen", days)
        return None

    logged_days = sum(1 for d in diary_by_date.values() if d["calories"] > 0)
    log.info(
        "MyFitnessPal: %d dagen opgehaald, %d met gelogde calorieën",
        len(diary_by_date), logged_days,
    )

    return {
        "diary": {"by_date": diary_by_date},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
