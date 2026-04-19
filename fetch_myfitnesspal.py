#!/usr/bin/env python3
"""
MyFitnessPal data fetcher voor het SportBit CrossFit dashboard.

Haalt het voedingsdagboek op via directe HTTP-requests met sessie-cookies.
Geen login-flow nodig: MFP blokkeert geautomatiseerd inloggen via Cloudflare.

Cookies haal je op via DevTools → Application → Cookies → myfitnesspal.com
en sla je op als GitHub Secrets. Ze zijn doorgaans maanden geldig.

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  MFP_USERNAME       - MyFitnessPal gebruikersnaam (voor de diary URL)
  MFP_SESSION_TOKEN  - Waarde van cookie '__Secure-next-auth.session-token'
  MFP_CF_CLEARANCE   - Waarde van cookie 'cf_clearance'
  MFP_REMEMBER_ME    - Waarde van cookie 'remember_me'

Cookies vernieuwen: log in via browser, kopieer nieuwe waarden, update secrets.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MFP_BASE = "https://www.myfitnesspal.com"


def _build_session() -> requests.Session | None:
    """Bouw een authenticated requests.Session met MFP sessie-cookies."""
    session_token = os.environ.get("MFP_SESSION_TOKEN", "").strip()
    cf_clearance = os.environ.get("MFP_CF_CLEARANCE", "").strip()
    remember_me = os.environ.get("MFP_REMEMBER_ME", "").strip()

    if not session_token:
        log.info("MyFitnessPal: MFP_SESSION_TOKEN niet geconfigureerd")
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    session.cookies.set(
        "__Secure-next-auth.session-token", session_token,
        domain="www.myfitnesspal.com",
    )
    if cf_clearance:
        session.cookies.set("cf_clearance", cf_clearance, domain=".myfitnesspal.com")
    if remember_me:
        session.cookies.set(
            "remember_me", unquote(remember_me),
            domain="www.myfitnesspal.com",
        )

    return session


def _extract_next_data(soup: BeautifulSoup) -> dict | None:
    """Extraheer Next.js __NEXT_DATA__ JSON uit de pagina."""
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError:
        return None


def _parse_nextjs_diary(next_data: dict) -> dict | None:
    """Extraheer dagboekdata uit Next.js pageProps."""
    page_props = next_data.get("props", {}).get("pageProps", {})

    # Zoek de diary-data op verschillende mogelijke locaties
    diary = (
        page_props.get("diary")
        or page_props.get("diaryData")
        or page_props.get("foodDiary")
        or page_props.get("food_diary")
    )
    if not diary:
        return None

    totals = diary.get("totals") or diary.get("daily_totals") or {}
    meals_raw = diary.get("meals") or []

    meals = []
    for meal in meals_raw:
        entries = []
        for entry in meal.get("food_entries") or meal.get("entries") or []:
            nc = entry.get("nutritional_contents") or entry.get("nutrition") or {}
            entries.append({
                "food": (
                    (entry.get("food") or {}).get("description")
                    or entry.get("name", "")
                ),
                "calories": int(nc.get("calories", 0) or 0),
                "protein_g": float(nc.get("protein", 0) or 0),
                "carbs_g": float(nc.get("carbohydrates", 0) or 0),
                "fat_g": float(nc.get("fat", 0) or 0),
            })
        mt = meal.get("totals") or {}
        meals.append({
            "name": meal.get("name", ""),
            "calories": int(mt.get("calories", 0) or 0),
            "protein_g": float(mt.get("protein", 0) or 0),
            "carbs_g": float(mt.get("carbohydrates", 0) or 0),
            "fat_g": float(mt.get("fat", 0) or 0),
            "entries": entries,
        })

    return {
        "calories": int(totals.get("calories", 0) or 0),
        "protein_g": float(totals.get("protein", 0) or 0),
        "carbs_g": float(totals.get("carbohydrates", 0) or 0),
        "fat_g": float(totals.get("fat", 0) or 0),
        "fiber_g": float(totals.get("fiber", 0) or 0),
        "meals": meals,
    }


def _parse_html_diary(soup: BeautifulSoup) -> dict | None:
    """Parse de oude MFP XHTML diary. Kolommen: 0=label, 1=cal, 2=carbs, 3=fat, 4=protein, 5=sodium, 6=sugar."""
    def num(text: str) -> float:
        if not text or text.strip() in ("-", "—"):
            return 0.0
        cleaned = "".join(c for c in text.strip().replace(",", "") if c.isdigit() or c == ".")
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    def cell_num(td) -> float:
        """Lees waarde uit <td>, gebruik <span class="macro-value"> als aanwezig."""
        span = td.find("span", class_="macro-value")
        return num(span.get_text(strip=True) if span else td.get_text(strip=True))

    # Kolommen: 0=label, 1=calories, 2=carbs, 3=fat, 4=protein, 5=fiber, 6=sugar
    COL = {"cal": 1, "carbs": 2, "fat": 3, "protein": 4, "fiber": 5, "sugar": 6}

    MEAL_NAMES = {"breakfast", "lunch", "dinner", "snacks",
                  "ontbijt", "diner", "tussendoor"}

    meals: list[dict] = []
    current: dict | None = None
    daily: dict = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0,
                   "fat_g": 0.0, "fiber_g": 0.0, "sugar_g": 0.0}
    goal: dict = {}
    found_daily = False

    for row in soup.find_all("tr"):
        cs = row.find_all(["td", "th"])
        if not cs:
            continue
        first = cs[0].get_text(strip=True)
        fl = first.lower()
        row_classes = " ".join(row.get("class", []))

        # Goal-rij apart parsen
        if any(k in fl for k in ("goal", "doel")) and "total" in row_classes:
            if len(cs) > COL["protein"]:
                goal = {
                    "calories": int(cell_num(cs[COL["cal"]])),
                    "protein_g": cell_num(cs[COL["protein"]]),
                    "carbs_g": cell_num(cs[COL["carbs"]]),
                    "fat_g": cell_num(cs[COL["fat"]]),
                    "fiber_g": cell_num(cs[COL["fiber"]]) if len(cs) > COL["fiber"] else 0.0,
                    "sugar_g": cell_num(cs[COL["sugar"]]) if len(cs) > COL["sugar"] else 0.0,
                }
            continue

        # Sla remaining-rijen over
        if any(k in fl for k in ("remaining", "resterend")):
            continue

        if fl in MEAL_NAMES:
            current = {"name": first, "calories": 0, "protein_g": 0.0,
                       "carbs_g": 0.0, "fat_g": 0.0, "entries": [],
                       "_totals_set": False}
            meals.append(current)

        elif fl == "totals" and "total" in row_classes:
            if len(cs) <= COL["protein"]:
                continue
            cal = int(cell_num(cs[COL["cal"]]))
            carbs = cell_num(cs[COL["carbs"]])
            fat = cell_num(cs[COL["fat"]])
            protein = cell_num(cs[COL["protein"]])
            fiber = cell_num(cs[COL["fiber"]]) if len(cs) > COL["fiber"] else 0.0
            sugar = cell_num(cs[COL["sugar"]]) if len(cs) > COL["sugar"] else 0.0

            if current and not current["_totals_set"]:
                current.update({"calories": cal, "carbs_g": carbs,
                                 "fat_g": fat, "protein_g": protein})
                current["_totals_set"] = True
            elif not found_daily:
                daily.update({"calories": cal, "carbs_g": carbs, "fat_g": fat,
                               "protein_g": protein, "fiber_g": fiber, "sugar_g": sugar})
                found_daily = True

        elif current:
            if len(cs) <= COL["cal"]:
                continue
            cal = int(cell_num(cs[COL["cal"]]))
            if cal > 0:
                current["entries"].append({
                    "food": first,
                    "calories": cal,
                    "protein_g": cell_num(cs[COL["protein"]]) if len(cs) > COL["protein"] else 0.0,
                    "carbs_g": cell_num(cs[COL["carbs"]]) if len(cs) > COL["carbs"] else 0.0,
                    "fat_g": cell_num(cs[COL["fat"]]) if len(cs) > COL["fat"] else 0.0,
                })

    # Verwijder interne vlag vóór return
    for m in meals:
        m.pop("_totals_set", None)

    if not found_daily and meals:
        for m in meals:
            daily["calories"] += m["calories"]
            daily["protein_g"] += m["protein_g"]
            daily["carbs_g"] += m["carbs_g"]
            daily["fat_g"] += m["fat_g"]

    if daily["calories"] == 0 and not meals:
        return None

    result = {**daily, "meals": meals}
    if goal:
        result["goal"] = goal
    return result


def _extract_water(soup: BeautifulSoup) -> float | None:
    """Extraheer water-intake (cups of ml) uit de MFP XHTML diary."""
    # Patroon 1: <span id="total-water-count">5</span>
    el = soup.find(id="total-water-count")
    if el:
        try:
            return float(el.get_text(strip=True))
        except ValueError:
            pass

    # Patroon 2: input met name/class water
    for inp in soup.find_all("input"):
        name = inp.get("name", "") + inp.get("id", "") + inp.get("class", [""])[0]
        if "water" in name.lower():
            try:
                return float(inp.get("value", "") or "")
            except ValueError:
                pass

    # Patroon 3: zoek in tekst van alle elementen met 'water' in id/class
    for el in soup.find_all(True, {"id": lambda x: x and "water" in x.lower()}):
        t = el.get_text(strip=True)
        digits = "".join(c for c in t if c.isdigit() or c == ".")
        if digits:
            try:
                return float(digits)
            except ValueError:
                pass

    return None


def fetch_myfitnesspal_data(days: int = 7) -> dict | None:
    """
    Haal MyFitnessPal voedingsdagboek op voor de afgelopen `days` dagen
    via directe HTTP-requests met sessie-cookies.

    Retourneert None als credentials ontbreken of bij een fout.
    """
    session = _build_session()
    if not session:
        return None

    username = os.environ.get("MFP_USERNAME", "").strip()

    # Probe: altijd eerst /food/diary zonder gebruikersnaam proberen.
    # MFP stuurt geauthenticeerde gebruikers door naar /food/diary/{username}.
    # Zo ontdekken we de juiste URL zonder MFP_USERNAME te hoeven weten.
    diary_base = f"{MFP_BASE}/food/diary"
    try:
        probe = session.get(diary_base, timeout=30, allow_redirects=True)
        log.info("MFP probe: status=%d url=%s", probe.status_code, probe.url)
        if probe.status_code == 200 and "/food/diary" in probe.url:
            diary_base = probe.url.split("?")[0]
            log.info("MFP: diary base URL vastgesteld op %s", diary_base)
        elif probe.status_code == 404 and username:
            # Fallback: probeer met expliciete gebruikersnaam
            diary_base = f"{MFP_BASE}/food/diary/{username}"
            log.info("MFP: /food/diary gaf 404, fallback naar username URL")
        else:
            log.warning("MFP probe onverwacht resultaat: status=%d url=%s — pagina snippet: %.300s",
                        probe.status_code, probe.url, probe.text)
    except Exception as exc:
        log.warning("MFP probe mislukt: %s", exc)
        if username:
            diary_base = f"{MFP_BASE}/food/diary/{username}"

    today = datetime.now(timezone.utc).date()
    diary_by_date: dict[str, dict] = {}

    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.isoformat()

        try:
            resp = session.get(
                f"{diary_base}?date={date_str}",
                timeout=30,
            )
        except Exception as exc:
            log.warning("MFP %s: request mislukt: %s", date_str, exc)
            continue

        if resp.status_code in (401, 403):
            log.warning(
                "MyFitnessPal: niet geautoriseerd (HTTP %d) — "
                "cookies zijn verlopen, voeg nieuwe waarden toe als GitHub Secrets",
                resp.status_code,
            )
            break

        if resp.status_code != 200:
            log.warning("MFP %s: HTTP %d (final URL: %s)", date_str, resp.status_code, resp.url)
            continue

        # Detecteer redirect naar loginpagina (cookies verlopen / geweigerd)
        if "/food/diary" not in resp.url:
            log.warning(
                "MyFitnessPal: omgeleid naar %s — cookies werken niet of zijn verlopen",
                resp.url,
            )
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Strategie 1: Next.js __NEXT_DATA__ JSON
        next_data = _extract_next_data(soup)
        if i == 0:
            if next_data:
                page_props_keys = list(next_data.get("props", {}).get("pageProps", {}).keys())
                log.debug("MFP __NEXT_DATA__ pageProps keys: %s", page_props_keys[:15])

        day_data = _parse_nextjs_diary(next_data) if next_data else None

        # Strategie 2: HTML-tabel fallback
        if not day_data or day_data.get("calories", 0) == 0:
            day_data = _parse_html_diary(soup)

        if day_data:
            water = _extract_water(soup)
            if water is not None:
                day_data["water_cups"] = water

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
            log.debug("MFP %s: geen data (dag niet gelogd?)", date_str)

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
