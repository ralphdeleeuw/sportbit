#!/usr/bin/env python3
"""
Withings smart scale data fetcher voor het SportBit CrossFit dashboard.

Haalt lichaamssamenstelling op (gewicht, vetpercentage, spiermassa, etc.)
via de Withings Public API. Retourneert None als secrets niet zijn ingesteld.

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
  WITHINGS_REFRESH_TOKEN  - OAuth2 refresh token (langlevend)
"""

import logging
import os
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

WITHINGS_API = "https://wbsapi.withings.net"

# Withings measure types (meastype)
_MEASTYPE_WEIGHT = 1        # kg
_MEASTYPE_FAT_RATIO = 6     # %
_MEASTYPE_MUSCLE_MASS = 76  # kg
_MEASTYPE_HYDRATION = 77    # %
_MEASTYPE_BONE_MASS = 88    # kg


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str | None:
    """Wissel een Withings refresh token in voor een nieuw access token."""
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
        return body["body"]["access_token"]
    except Exception as exc:
        log.warning("Withings token refresh fout: %s", exc)
        return None


def fetch_withings_data(max_measurements: int = 30) -> dict | None:
    """Haalt lichaamssamenstelling op van een Withings smart scale.

    Vereist WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET en
    WITHINGS_REFRESH_TOKEN als omgevingsvariabelen.
    Retourneert None als secrets niet zijn ingesteld — geen fout.
    """
    client_id = os.environ.get("WITHINGS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("WITHINGS_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("WITHINGS_REFRESH_TOKEN", "").strip()

    if not client_id or not client_secret or not refresh_token:
        log.info("Withings secrets niet ingesteld — Withings data overgeslagen")
        return None

    # ── 1. Access token ophalen ───────────────────────────────────────────
    access_token = _refresh_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        return None

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

    # ── 3. Verwerk metingen per groep (datum + tijdstip) ─────────────────
    measuregrps = body.get("body", {}).get("measuregrps", [])
    measurements: list[dict] = []

    for grp in sorted(measuregrps, key=lambda g: g.get("date", 0), reverse=True)[:max_measurements]:
        date_str = datetime.fromtimestamp(grp["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        values: dict = {}
        for m in grp.get("measures", []):
            # Withings stores value as integer + unit exponent: actual = value * 10^unit
            actual = m["value"] * (10 ** m["unit"])
            mtype = m["type"]
            if mtype == _MEASTYPE_WEIGHT:
                values["weight_kg"] = round(actual, 2)
            elif mtype == _MEASTYPE_FAT_RATIO:
                values["fat_pct"] = round(actual, 1)
            elif mtype == _MEASTYPE_MUSCLE_MASS:
                values["muscle_kg"] = round(actual, 1)
            elif mtype == _MEASTYPE_HYDRATION:
                values["hydration_pct"] = round(actual, 1)
            elif mtype == _MEASTYPE_BONE_MASS:
                values["bone_kg"] = round(actual, 2)
        if values:
            values["date"] = date_str
            measurements.append(values)

    log.info("Withings: %d metingen opgehaald", len(measurements))
    return {
        "measurements": measurements,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
