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
    """HTML-fallback: parse de MFP diary tabel met BeautifulSoup."""
    def num(text: str) -> float:
        if not text:
            return 0.0
        cleaned = "".join(c for c in text.strip().replace(",", "") if c.isdigit() or c == ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    # Bepaal kolomvolgorde uit de tabelkoppen
    col = {"cal": 1, "carbs": 2, "fat": 3, "protein": 4, "fiber": -1}
    for th in soup.find_all("th"):
        h = th.get_text(strip=True).lower()
        idx = th.parent.find_all("th").index(th)
        if "calorie" in h:
            col["cal"] = idx
        elif "carb" in h:
            col["carbs"] = idx
        elif "fat" in h or "vet" in h:
            col["fat"] = idx
        elif "protein" in h or "eiwit" in h:
            col["protein"] = idx
        elif "fiber" in h or "fibre" in h or "vezel" in h:
            col["fiber"] = idx

    MEAL_NAMES = {"breakfast", "lunch", "dinner", "snacks",
                  "ontbijt", "diner", "tussendoor"}

    meals: list[dict] = []
    current: dict | None = None
    daily: dict = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0,
                   "fat_g": 0.0, "fiber_g": 0.0}
    found_daily = False

    def cells(row) -> list:
        return row.find_all(["td", "th"])

    for row in soup.find_all("tr"):
        cs = cells(row)
        if not cs:
            continue
        first = cs[0].get_text(strip=True)
        fl = first.lower()

        if fl in MEAL_NAMES:
            current = {"name": first, "calories": 0, "protein_g": 0.0,
                       "carbs_g": 0.0, "fat_g": 0.0, "entries": []}
            meals.append(current)

        elif "daily total" in fl or "dagelijks totaal" in fl:
            if len(cs) > max(col["cal"], col["protein"]):
                daily["calories"] = int(num(cs[col["cal"]].get_text()))
                daily["carbs_g"] = num(cs[col["carbs"]].get_text())
                daily["fat_g"] = num(cs[col["fat"]].get_text())
                daily["protein_g"] = num(cs[col["protein"]].get_text())
                if col["fiber"] >= 0 and len(cs) > col["fiber"]:
                    daily["fiber_g"] = num(cs[col["fiber"]].get_text())
                found_daily = True

        elif fl == "totals" and current:
            if len(cs) > max(col["cal"], col["protein"]):
                current["calories"] = int(num(cs[col["cal"]].get_text()))
                current["protein_g"] = num(cs[col["protein"]].get_text())
                current["carbs_g"] = num(cs[col["carbs"]].get_text())
                current["fat_g"] = num(cs[col["fat"]].get_text())

        elif current and len(cs) > 1:
            c = int(num(cs[col["cal"]].get_text())) if len(cs) > col["cal"] else 0
            if c > 0:
                current["entries"].append({
                    "food": first,
                    "calories": c,
                    "protein_g": num(cs[col["protein"]].get_text()) if len(cs) > col["protein"] else 0.0,
                    "carbs_g": num(cs[col["carbs"]].get_text()) if len(cs) > col["carbs"] else 0.0,
                    "fat_g": num(cs[col["fat"]].get_text()) if len(cs) > col["fat"] else 0.0,
                })

    if not found_daily and meals:
        for m in meals:
            daily["calories"] += m["calories"]
            daily["protein_g"] += m["protein_g"]
            daily["carbs_g"] += m["carbs_g"]
            daily["fat_g"] += m["fat_g"]

    if daily["calories"] == 0 and not meals:
        return None

    return {**daily, "meals": meals}


def fetch_myfitnesspal_data(days: int = 7) -> dict | None:
    """
    Haal MyFitnessPal voedingsdagboek op voor de afgelopen `days` dagen
    via directe HTTP-requests met sessie-cookies.

    Retourneert None als credentials ontbreken of bij een fout.
    """
    session = _build_session()
    if not session:
        return None

    # Bepaal de diary-URL: probeer eerst zonder gebruikersnaam (werkt op sessiecookie),
    # val terug op MFP_USERNAME als dat ingesteld is.
    username = os.environ.get("MFP_USERNAME", "").strip()
    diary_base = f"{MFP_BASE}/food/diary/{username}" if username else f"{MFP_BASE}/food/diary"

    # Eerste request: check authenticatie en ontdek de echte diary-URL
    try:
        probe = session.get(f"{diary_base}", timeout=30, allow_redirects=True)
        log.warning("MFP probe: status=%d url=%s", probe.status_code, probe.url)
        # Als MFP omleidt naar /food/diary/{username}, gebruik die URL voortaan
        if "/food/diary/" in probe.url and probe.status_code == 200:
            diary_base = probe.url.split("?")[0]
            log.warning("MFP: diary base URL vastgesteld op %s", diary_base)
    except Exception as exc:
        log.warning("MFP probe mislukt: %s", exc)

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
                log.warning("MFP __NEXT_DATA__ pageProps keys: %s", page_props_keys[:15])
            else:
                log.warning("MFP dag 0: geen __NEXT_DATA__ gevonden (pagina snippet: %s)", resp.text[:300])

        day_data = _parse_nextjs_diary(next_data) if next_data else None

        # Strategie 2: HTML-tabel fallback
        if not day_data or day_data.get("calories", 0) == 0:
            day_data = _parse_html_diary(soup)

        if day_data:
            diary_by_date[date_str] = day_data
            log.warning(
                "MFP %s: %d kcal | %dg eiwit | %dg KH | %dg vet",
                date_str,
                day_data.get("calories", 0),
                round(day_data.get("protein_g", 0)),
                round(day_data.get("carbs_g", 0)),
                round(day_data.get("fat_g", 0)),
            )
        else:
            log.warning("MFP %s: geen data gevonden (dag niet gelogd of formaat onbekend)", date_str)

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
