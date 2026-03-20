#!/usr/bin/env python3
"""
SugarWOD WOD Fetcher for CrossFit Hilversum

Fetches workout data from SugarWOD's public RSS feed and stores it in a GitHub Gist
for display in the SportBit dashboard.

The gym must have public workout publishing enabled in SugarWOD settings.

Usage:
    python3 fetch_sugarwod.py

Environment variables:
    SUGARWOD_GYM_ID  - SugarWOD affiliate/gym ID (required)
    GIST_ID          - GitHub Gist ID for storing WOD data
    GITHUB_TOKEN     - GitHub personal access token with gist scope
"""

import json
import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

SUGARWOD_BASE = "https://www.sugarwod.com/public/api/v1/affiliates"
GIST_FILENAME = "sugarwod_wod.json"
DAYS_AHEAD = 7
AMS = ZoneInfo("Europe/Amsterdam")

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sugarwod")


# ──────────────────────────────────────────────────────────────
# SugarWOD fetching
# ──────────────────────────────────────────────────────────────

def fetch_wod_rss(gym_id: str, days: int = DAYS_AHEAD) -> list:
    """Fetch WOD data from SugarWOD public RSS endpoint."""
    tracks = urllib.parse.quote('["workout-of-the-day"]')
    url = f"{SUGARWOD_BASE}/{gym_id}/workouts/days/{days}/rss?tracks={tracks}"
    log.info("Fetching WOD RSS from: %s", url)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return parse_rss(resp.text)


def parse_rss(rss_text: str) -> list:
    """Parse SugarWOD RSS XML and return list of workout dicts."""
    root = ET.fromstring(rss_text)
    channel = root.find("channel")
    if channel is None:
        log.warning("No <channel> element found in RSS response")
        return []

    workouts = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()

        date_str = None
        if pub_date:
            # Try common RSS date formats
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
                try:
                    dt = datetime.strptime(pub_date, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    date_str = dt.astimezone(AMS).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

        workouts.append({
            "title": title,
            "description": description,
            "date": date_str,
            "link": link,
        })

    log.info("Parsed %d workout(s) from RSS", len(workouts))
    return workouts


# ──────────────────────────────────────────────────────────────
# Gist storage
# ──────────────────────────────────────────────────────────────

def save_to_gist(gist_id: str, token: str, wod_data: dict) -> None:
    """Save WOD data as a new file in an existing GitHub Gist."""
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(wod_data, ensure_ascii=False, indent=2)
            }
        }
    }
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        json=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    log.info("WOD data saved to Gist %s as '%s'", gist_id, GIST_FILENAME)


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main() -> int:
    gym_id = os.environ.get("SUGARWOD_GYM_ID", "").strip()
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    if not gym_id:
        log.error("SUGARWOD_GYM_ID environment variable is required")
        log.error(
            "Find your gym ID in the SugarWOD public whiteboard URL or contact your gym."
        )
        return 1

    try:
        workouts = fetch_wod_rss(gym_id)
    except requests.HTTPError as exc:
        log.error("Failed to fetch WOD data: %s", exc)
        if exc.response is not None and exc.response.status_code == 404:
            log.error(
                "Gym ID '%s' not found, or public publishing is not enabled. "
                "Ask your gym to enable 'Publish workouts publicly' in SugarWOD settings.",
                gym_id,
            )
        return 1
    except Exception as exc:
        log.error("Unexpected error fetching WOD: %s", exc)
        return 1

    wod_data = {
        "workouts": workouts,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "gym_id": gym_id,
    }

    if gist_id and token:
        try:
            save_to_gist(gist_id, token, wod_data)
        except requests.HTTPError as exc:
            log.error("Failed to save WOD to Gist: %s", exc)
            return 1
    else:
        log.warning("GIST_ID or GITHUB_TOKEN not set — printing to stdout")
        print(json.dumps(wod_data, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
