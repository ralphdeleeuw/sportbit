#!/usr/bin/env python3
"""
Withings smart scale data fetcher voor het SportBit CrossFit dashboard.

Haalt lichaamssamenstelling op (gewicht, vetpercentage, spiermassa, etc.)
via de Withings Public API. Retourneert None als secrets niet zijn ingesteld.

Token-rotatie: Withings geeft bij elke token-uitwisseling een nieuwe refresh
token terug. Deze wordt automatisch opgeslagen in de Gist (withings_token.json)
zodat de volgende run de meest recente token gebruikt.

══════════════════════════════════════════════════════════════
EENMALIGE SETUP — Withings OAuth2 refresh token ophalen
══════════════════════════════════════════════════════════════

1. Maak een Withings developer account aan:
   https://developer.withings.com/

2. Maak een nieuwe applicatie aan:
   - Kies "Public API Integration"
   - Callback URI: http://localhost/callback
   Noteer: Client ID en Consumer Secret

3. Genereer de autorisatie URL en open in browser
   (vervang CLIENT_ID door jouw ID):
   https://account.withings.com/oauth2_user/authorize2?response_type=code&client_id=CLIENT_ID&scope=user.metrics&redirect_uri=http://localhost/callback&state=sportbit

   Na autoriseren word je doorgestuurd naar:
   http://localhost/callback?code=XXXXX&state=sportbit
   Kopieer de code-waarde (XXXXX).

4. Wissel de code in voor tokens
   (vervang CLIENT_ID, CLIENT_SECRET en CODE):
   curl -X POST "https://wbsapi.withings.net/v2/oauth2?action=requesttoken" \
     -d "grant_type=authorization_code" \
     -d "client_id=CLIENT_ID" \
     -d "client_secret=CLIENT_SECRET" \
     -d "code=CODE" \
     -d "redirect_uri=http://localhost/callback"

   Noteer refresh_token uit het antwoord.

5. Voeg toe als GitHub Secrets:
   Repo → Settings → Secrets and variables → Actions
   WITHINGS_CLIENT_ID     = jouw Client ID
   WITHINGS_CLIENT_SECRET = jouw Consumer Secret
   WITHINGS_REFRESH_TOKEN = refresh_token uit stap 4

══════════════════════════════════════════════════════════════
VEREISTE GITHUB SECRETS
══════════════════════════════════════════════════════════════
  WITHINGS_CLIENT_ID      - Withings app Client ID
  WITHINGS_CLIENT_SECRET  - Withings app Consumer Secret
  WITHINGS_REFRESH_TOKEN  - OAuth2 refresh token (initieel; wordt daarna
                            automatisch geroteerd via de Gist)
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

WITHINGS_API = "https://wbsapi.withings.net"
_GIST_TOKEN_FILENAME = "withings_token.json"

# Withings measure types (meastype)
_MEASTYPE_WEIGHT = 1          # kg
_MEASTYPE_FAT_RATIO = 6       # %
_MEASTYPE_MUSCLE_MASS = 76    # kg
_MEASTYPE_HYDRATION = 77      # kg (niet %)
_MEASTYPE_BONE_MASS = 88      # kg
# Body Scan extra meetwaarden
_MEASTYPE_PWV = 91            # Pulse Wave Velocity m/s (vaatgezondheid)
_MEASTYPE_NERVE_HEALTH = 155  # Nerve Health Score 0–100 (zenuwgezondheid)
_MEASTYPE_VISCERAL_FAT = 174  # Visceraal vet index


def _load_refresh_token_from_gist(gist_id: str, token: str) -> str | None:
    """Haal de meest recente (geroteerde) refresh token op uit de Gist."""
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("files", {}).get(_GIST_TOKEN_FILENAME, {}).get("content", "")
        if raw:
            return json.loads(raw).get("refresh_token")
    except Exception as exc:
        log.debug("Withings token uit Gist laden mislukt: %s", exc)
    return None


def _save_refresh_token_to_gist(gist_id: str, token: str, refresh_token: str) -> None:
    """Sla de nieuwe (geroteerde) refresh token op in de Gist voor de volgende run."""
    try:
        payload = {
            "files": {
                _GIST_TOKEN_FILENAME: {
                    "content": json.dumps(
                        {"refresh_token": refresh_token, "updated_at": datetime.now(timezone.utc).isoformat()},
                        indent=2,
                    )
                }
            }
        }
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            json=payload,
            headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Withings refresh token opgeslagen in Gist (token-rotatie)")
    except Exception as exc:
        log.warning("Withings refresh token opslaan in Gist mislukt: %s", exc)


def _refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> tuple[str, str] | None:
    """Wissel een Withings refresh token in voor een nieuw access token.

    Retourneert (access_token, new_refresh_token) of None bij fout.
    Withings roteert de refresh token bij elke uitwisseling.
    """
    try:
        resp = requests.post(
            f"{WITHINGS_API}/v2/oauth2",
            params={"action": "requesttoken"},
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != 0:
            log.warning("Withings token refresh mislukt: status=%s", body.get("status"))
            return None
        b = body["body"]
        return b["access_token"], b.get("refresh_token", "")
    except Exception as exc:
        log.warning("Withings token refresh fout: %s", exc)
        return None


def fetch_withings_data(max_measurements: int = 30) -> dict | None:
    """Haalt lichaamssamenstelling op van een Withings smart scale.

    Vereist WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET en
    WITHINGS_REFRESH_TOKEN als omgevingsvariabelen.
    Retourneert None als secrets niet zijn ingesteld — geen fout.

    Token-rotatie: de nieuwe refresh token wordt automatisch opgeslagen
    in de Gist zodat toekomstige runs de meest recente token gebruiken.
    """
    client_id = os.environ.get("WITHINGS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("WITHINGS_CLIENT_SECRET", "").strip()
    refresh_token_env = os.environ.get("WITHINGS_REFRESH_TOKEN", "").strip()
    gist_id = os.environ.get("GIST_ID", "").strip()
    gist_token = os.environ.get("GITHUB_TOKEN", "").strip()

    if not client_id or not client_secret or not refresh_token_env:
        log.info("Withings secrets niet ingesteld — Withings data overgeslagen")
        return None

    # Gebruik de Gist-opgeslagen token als die beschikbaar is (meest recent na rotatie).
    # Val terug op de GitHub Secret als de Gist geen token heeft.
    refresh_token = refresh_token_env
    if gist_id and gist_token:
        saved = _load_refresh_token_from_gist(gist_id, gist_token)
        if saved:
            log.debug("Withings: geroteerde refresh token geladen uit Gist")
            refresh_token = saved

    # ── 1. Access token ophalen (en nieuwe refresh token ontvangen) ──────
    result = _refresh_access_token(client_id, client_secret, refresh_token)
    if not result:
        # Fallback: probeer alsnog de originele env-var token als die verschilt
        if refresh_token != refresh_token_env:
            log.info("Withings: Gist-token mislukt, probeer GitHub Secret refresh token...")
            result = _refresh_access_token(client_id, client_secret, refresh_token_env)
        if not result:
            return None

    access_token, new_refresh_token = result

    # Sla de nieuwe (geroteerde) refresh token op in de Gist
    if new_refresh_token and gist_id and gist_token:
        _save_refresh_token_to_gist(gist_id, gist_token, new_refresh_token)

    # ── 2. Metingen ophalen ───────────────────────────────────────────────
    try:
        resp = requests.post(
            f"{WITHINGS_API}/measure",
            headers={"Authorization": f"Bearer {access_token}"},
            data={
                "action": "getmeas",
                "meastypes": ",".join(str(t) for t in [
                    _MEASTYPE_WEIGHT,
                    _MEASTYPE_FAT_RATIO,
                    _MEASTYPE_MUSCLE_MASS,
                    _MEASTYPE_HYDRATION,
                    _MEASTYPE_BONE_MASS,
                    _MEASTYPE_PWV,
                    _MEASTYPE_NERVE_HEALTH,
                    _MEASTYPE_VISCERAL_FAT,
                ]),
                "category": 1,  # echte metingen (geen doelstellingen)
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != 0:
            log.warning("Withings getmeas mislukt: status=%s", body.get("status"))
            return None
    except Exception as exc:
        log.warning("Withings getmeas fout: %s", exc)
        return None

    # ── 3. Verwerk metingen — samenvoegen per dag ────────────────────────
    # Withings levert elke meting-sessie (weging, Body Scan, etc.) als
    # aparte measuregrp. We voegen alle sessies van dezelfde dag samen zodat
    # PWV en zenuwgezondheid (Body Scan) gecombineerd worden met de weging.
    measuregrps = body.get("body", {}).get("measuregrps", [])
    by_date: dict[str, dict] = {}

    for grp in sorted(measuregrps, key=lambda g: g.get("date", 0), reverse=True):
        date_str = datetime.fromtimestamp(grp["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        if date_str not in by_date:
            by_date[date_str] = {"date": date_str}
        entry = by_date[date_str]
        for m in grp.get("measures", []):
            # Withings stores value as integer + unit exponent: actual = value * 10^unit
            actual = m["value"] * (10 ** m["unit"])
            mtype = m["type"]
            # Eerste (meest recente sessie van die dag) waarde wint
            if mtype == _MEASTYPE_WEIGHT and "weight_kg" not in entry:
                entry["weight_kg"] = round(actual, 2)
            elif mtype == _MEASTYPE_FAT_RATIO and "fat_pct" not in entry:
                entry["fat_pct"] = round(actual, 1)
            elif mtype == _MEASTYPE_MUSCLE_MASS and "muscle_kg" not in entry:
                entry["muscle_kg"] = round(actual, 1)
            elif mtype == _MEASTYPE_HYDRATION and "hydration_kg" not in entry:
                entry["hydration_kg"] = round(actual, 1)
            elif mtype == _MEASTYPE_BONE_MASS and "bone_kg" not in entry:
                entry["bone_kg"] = round(actual, 2)
            elif mtype == _MEASTYPE_PWV and "pwv_ms" not in entry:
                entry["pwv_ms"] = round(actual, 1)
            elif mtype == _MEASTYPE_NERVE_HEALTH and "nerve_health" not in entry:
                entry["nerve_health"] = round(actual, 0)
            elif mtype == _MEASTYPE_VISCERAL_FAT and "visceral_fat" not in entry:
                entry["visceral_fat"] = round(actual, 1)

    # Sorteer op datum (nieuwste eerst), maximaal max_measurements dagen
    measurements = sorted(by_date.values(), key=lambda x: x["date"], reverse=True)[:max_measurements]

    log.info("Withings: %d metingen opgehaald", len(measurements))
    return {
        "measurements": measurements,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
