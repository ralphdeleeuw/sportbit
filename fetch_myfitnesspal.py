#!/usr/bin/env python3
"""
MyFitnessPal data fetcher voor het SportBit CrossFit dashboard.

Haalt het voedingsdagboek op van MyFitnessPal via Playwright (headless
browser). MyFitnessPal heeft geen publieke API meer (gesloten in 2020),
en de python-myfitnesspal scraping-bibliotheek werkt niet meer door
JavaScript-gebaseerde auth op de MFP-website.

Deze fetcher draait als onderdeel van de fetch_sugarwod.yml workflow,
die al Playwright en Chromium installeert.

══════════════════════════════════════════════════════════════
SETUP
══════════════════════════════════════════════════════════════
1. Maak een MyFitnessPal account aan op https://www.myfitnesspal.com
2. Log je dagelijkse voeding in via de app of website
3. Voeg toe als GitHub Secrets (in de sportbit repo):
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

MFP_BASE = "https://www.myfitnesspal.com"


def _parse_num(text: str) -> float:
    """Parseer een getal uit een MFP-cel (verwijdert komma's, eenheden)."""
    if not text:
        return 0.0
    cleaned = text.strip().replace(",", "").replace("g", "").replace("mg", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_from_xhr(captured: list[dict]) -> dict | None:
    """
    Probeer voedingsdata te halen uit onderschepte XHR-responses.

    MFP's SPA roept interne API-endpoints aan wanneer de dagboekpagina laadt.
    We zoeken naar responses van api.myfitnesspal.com die macro-data bevatten.
    """
    for item in captured:
        url = item["url"]
        data = item["data"]

        if "api.myfitnesspal.com" not in url and "myfitnesspal.com/api" not in url:
            continue

        # Zoek naar een 'items' of 'diary' key met voedingsdata
        items = None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("items", "diary", "entries", "food_entries", "meals"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break

        if not items:
            continue

        # Controleer of het voedingsitems zijn (hebben nutritional_contents of macros)
        sample = items[0] if items else {}
        has_nutrition = (
            "nutritional_contents" in sample
            or "nutrition" in sample
            or "calories" in sample
            or "energy" in sample
        )
        if not has_nutrition:
            continue

        log.info("MFP XHR: voedingsdata gevonden in %s (%d items)", url, len(items))

        # Aggregeer totalen en bouw maaltijdstructuur op
        totals: dict[str, float] = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}
        meals: list[dict] = []

        for entry in items:
            nc = entry.get("nutritional_contents") or entry.get("nutrition") or entry
            kcal = float(nc.get("calories") or nc.get("energy", {}).get("value", 0) or 0)
            prot = float(nc.get("protein", 0) or 0)
            carbs = float(nc.get("carbohydrates", 0) or nc.get("carbs", 0) or 0)
            fat = float(nc.get("fat", 0) or 0)
            fiber = float(nc.get("fiber", 0) or nc.get("dietary_fiber", 0) or 0)

            totals["calories"] += kcal
            totals["protein_g"] += prot
            totals["carbs_g"] += carbs
            totals["fat_g"] += fat
            totals["fiber_g"] += fiber

            meal_name = entry.get("meal_name") or entry.get("meal") or "Overig"
            food_name = (
                (entry.get("food") or {}).get("description")
                or entry.get("food_name")
                or entry.get("name")
                or ""
            )

            # Voeg toe aan bestaande maaltijd of maak nieuwe aan
            existing = next((m for m in meals if m["name"] == meal_name), None)
            food_entry = {
                "food": food_name,
                "calories": int(kcal),
                "protein_g": prot,
                "carbs_g": carbs,
                "fat_g": fat,
            }
            if existing:
                existing["calories"] += int(kcal)
                existing["protein_g"] += prot
                existing["carbs_g"] += carbs
                existing["fat_g"] += fat
                existing["entries"].append(food_entry)
            else:
                meals.append({
                    "name": meal_name,
                    "calories": int(kcal),
                    "protein_g": prot,
                    "carbs_g": carbs,
                    "fat_g": fat,
                    "entries": [food_entry],
                })

        return {**totals, "calories": int(totals["calories"]), "meals": meals}

    return None


def _extract_from_dom(page) -> dict | None:
    """
    Scrapt voedingstotalen direct uit de MFP-dagboekpagina via JavaScript.

    Probeert meerdere strategieën omdat MFP hun HTML-structuur regelmatig
    wijzigt. Extraheert minimaal de dagelijkse totalen.
    """
    try:
        result = page.evaluate("""
        () => {
            function parseNum(text) {
                if (!text) return 0;
                const n = parseFloat(text.replace(/,/g, '').replace(/[^0-9.-]/g, ''));
                return isNaN(n) ? 0 : n;
            }

            // Zoek kolom-volgorde op basis van tabelkoppen
            let colCalories = 1, colCarbs = 2, colFat = 3, colProtein = 4, colFiber = -1;
            const headerCells = document.querySelectorAll('table thead th, .main-title-2 th');
            [...headerCells].forEach((th, i) => {
                const h = th.textContent.trim().toLowerCase();
                if (h.includes('calorie')) colCalories = i;
                else if (h.includes('carb')) colCarbs = i;
                else if (h.includes('fat')) colFat = i;
                else if (h.includes('protein') || h.includes('eiwit')) colProtein = i;
                else if (h.includes('fiber') || h.includes('fibre') || h.includes('vezel')) colFiber = i;
            });

            const out = {calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, meals: []};

            // Strategie 1: zoek "Your Daily Total" rij of "Totals" rij
            const allRows = [...document.querySelectorAll('tr')];
            const dailyTotalRow = allRows.find(tr => {
                const t = tr.textContent.toLowerCase();
                return t.includes('your daily total') || t.includes('dagelijks totaal');
            });
            const totalsRow = allRows.find(tr => {
                const cells = [...tr.querySelectorAll('td, th')];
                return cells.length > 1 && cells[0].textContent.trim().toLowerCase() === 'totals';
            });
            const targetRow = dailyTotalRow || totalsRow;
            if (targetRow) {
                const cells = [...targetRow.querySelectorAll('td, th')];
                if (cells.length > Math.max(colCalories, colProtein)) {
                    out.calories  = parseNum(cells[colCalories]?.textContent);
                    out.carbs_g   = parseNum(cells[colCarbs]?.textContent);
                    out.fat_g     = parseNum(cells[colFat]?.textContent);
                    out.protein_g = parseNum(cells[colProtein]?.textContent);
                    if (colFiber >= 0) out.fiber_g = parseNum(cells[colFiber]?.textContent);
                }
            }

            // Strategie 2: zoek per-maaltijd totaalrijen
            const mealNames = ['breakfast', 'lunch', 'dinner', 'snacks'];
            const mealRows = allRows.filter(tr => {
                const first = tr.querySelector('td.first, td:first-child, th:first-child');
                if (!first) return false;
                const t = first.textContent.trim().toLowerCase();
                return mealNames.includes(t) || tr.className.toLowerCase().includes('meal');
            });

            const meals = [];
            let currentMeal = null;
            for (const row of allRows) {
                const firstCell = row.querySelector('td:first-child, th:first-child');
                if (!firstCell) continue;
                const cellText = firstCell.textContent.trim();
                const cellLower = cellText.toLowerCase();

                // Maaltijdkop detecteren
                if (mealNames.includes(cellLower) || row.classList.contains('main-title-2')) {
                    currentMeal = {
                        name: cellText.charAt(0).toUpperCase() + cellText.slice(1),
                        calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0,
                        entries: []
                    };
                    meals.push(currentMeal);
                    continue;
                }

                // Maaltijdtotaalrij detecteren
                if (currentMeal && cellLower === 'totals') {
                    const cells = [...row.querySelectorAll('td, th')];
                    if (cells.length > Math.max(colCalories, colProtein)) {
                        currentMeal.calories  = parseNum(cells[colCalories]?.textContent);
                        currentMeal.carbs_g   = parseNum(cells[colCarbs]?.textContent);
                        currentMeal.fat_g     = parseNum(cells[colFat]?.textContent);
                        currentMeal.protein_g = parseNum(cells[colProtein]?.textContent);
                    }
                    continue;
                }

                // Voedingsrij: heeft numerieke waarden in de cellen
                if (currentMeal) {
                    const cells = [...row.querySelectorAll('td')];
                    if (cells.length > 1) {
                        const maybeCal = parseNum(cells[colCalories]?.textContent);
                        if (maybeCal > 0) {
                            currentMeal.entries.push({
                                food: cells[0].textContent.trim(),
                                calories: maybeCal,
                                protein_g: parseNum(cells[colProtein]?.textContent),
                                carbs_g:   parseNum(cells[colCarbs]?.textContent),
                                fat_g:     parseNum(cells[colFat]?.textContent),
                            });
                        }
                    }
                }
            }

            if (meals.length > 0) out.meals = meals;

            // Herbereken dagelijkse totalen uit maaltijden als strategie 1 geen data gaf
            if (out.calories === 0 && meals.length > 0) {
                for (const m of meals) {
                    out.calories  += m.calories;
                    out.protein_g += m.protein_g;
                    out.carbs_g   += m.carbs_g;
                    out.fat_g     += m.fat_g;
                }
            }

            return out;
        }
        """)

        if result and result.get("calories", 0) > 0:
            log.info("MFP DOM: dagelijkse totalen gevonden via DOM-scraping")
            return {
                "calories": int(result.get("calories", 0)),
                "protein_g": float(result.get("protein_g", 0)),
                "carbs_g": float(result.get("carbs_g", 0)),
                "fat_g": float(result.get("fat_g", 0)),
                "fiber_g": float(result.get("fiber_g", 0)),
                "meals": result.get("meals", []),
            }

    except Exception as exc:
        log.debug("MFP DOM extractie mislukt: %s", exc)

    return None


def fetch_myfitnesspal_data(days: int = 7) -> dict | None:
    """
    Haal MyFitnessPal voedingsdagboek op voor de afgelopen `days` dagen
    via Playwright (headless Chromium).

    Vereist playwright geïnstalleerd + Chromium via `playwright install chromium`.
    Retourneert None als credentials ontbreken, Playwright niet beschikbaar is,
    of als inloggen mislukt.
    """
    username = os.environ.get("MFP_USERNAME", "").strip()
    password = os.environ.get("MFP_PASSWORD", "").strip()

    if not username or not password:
        log.info(
            "MyFitnessPal: credentials ontbreken (MFP_USERNAME / MFP_PASSWORD)"
        )
        return None

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        log.warning(
            "MyFitnessPal: playwright niet geïnstalleerd — "
            "voeg 'playwright' toe aan pip install en draai 'playwright install chromium'"
        )
        return None

    today = datetime.now(timezone.utc).date()
    diary_by_date: dict[str, dict] = {}

    # XHR-responses worden opgeslagen per paginabezoek
    captured: list[dict] = []

    def _on_response(response) -> None:
        try:
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            if "myfitnesspal.com" not in response.url:
                return
            data = response.json()
            captured.append({"url": response.url, "data": data})
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("response", _on_response)

            # ── 1. Inloggen ───────────────────────────────────────────────────
            log.info("MyFitnessPal: navigeren naar inlogpagina")
            page.goto(
                f"{MFP_BASE}/account/login",
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            # Gebruikersnaamveld invullen
            user_input = page.locator(
                'input[name="username"], input[id="username"], '
                'input[id="email"], input[type="email"]'
            ).first
            user_input.click()
            user_input.type(username, delay=40)

            # Wachtwoordveld invullen
            pw_input = page.locator('input[type="password"]').first
            pw_input.click()
            pw_input.type(password, delay=40)

            # Formulier verzenden
            try:
                submit = page.locator(
                    'button[type="submit"], input[type="submit"]'
                ).first
                submit.click()
            except Exception:
                pw_input.press("Enter")

            # Wacht tot we van de loginpagina af zijn
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/account/login')",
                    timeout=20_000,
                )
                log.info("MyFitnessPal: succesvol ingelogd als %s", username)
            except Exception:
                log.warning(
                    "MyFitnessPal: inloggen mislukt — "
                    "controleer MFP_USERNAME / MFP_PASSWORD secrets"
                )
                browser.close()
                return None

            # ── 2. Dagboek per dag ophalen ────────────────────────────────────
            for i in range(days):
                date = today - timedelta(days=i)
                date_str = date.isoformat()
                captured.clear()

                page.goto(
                    f"{MFP_BASE}/food/diary?date={date_str}",
                    wait_until="networkidle",
                    timeout=30_000,
                )

                # Strategie 1: XHR-response van MFP-API
                day_data = _extract_from_xhr(captured)

                # Strategie 2: DOM-scraping
                if not day_data or day_data.get("calories", 0) == 0:
                    day_data = _extract_from_dom(page)

                if day_data:
                    diary_by_date[date_str] = day_data
                    log.info(
                        "MFP %s: %d kcal | %dg eiwit | %dg KH | %dg vet",
                        date_str,
                        day_data.get("calories", 0),
                        round(day_data.get("protein_g", 0)),
                        round(day_data.get("carbs_g", 0)),
                        round(day_data.get("fat_g", 0)),
                    )
                else:
                    log.debug("MFP %s: geen data gevonden (dag mogelijk niet gelogd)", date_str)

            browser.close()

    except Exception as exc:
        log.warning("MyFitnessPal: scraping mislukt: %s", exc)
        return None

    if not diary_by_date:
        log.warning("MyFitnessPal: geen dagboekdata opgehaald voor de afgelopen %d dagen", days)
        return None

    logged_days = sum(1 for d in diary_by_date.values() if d.get("calories", 0) > 0)
    log.info(
        "MyFitnessPal: %d dagen opgehaald, %d met gelogde calorieën",
        len(diary_by_date),
        logged_days,
    )

    return {
        "diary": {"by_date": diary_by_date},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
