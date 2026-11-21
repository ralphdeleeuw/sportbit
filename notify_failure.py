"""Stuur een pushmelding als een GitHub Actions workflow mislukt.

Wordt aangeroepen vanuit de laatste stap van elke workflow (`if: failure()`).
Om spam te voorkomen bij een bron die structureel faalt (bv. Garmin-login die elke
4 uur misgaat) wordt per workflow hooguit één melding per 12 uur verstuurd. De
laatste mislukking per workflow staat in `workflow_status.json` in de Gist, zodat de
PWA die ook kan tonen.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from gist_utils import load_gist, patch_gist
from notify import send_notification

log = logging.getLogger(__name__)
STATUS_FILE = "workflow_status.json"
DEDUPE_HOURS = 12


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    workflow = os.environ.get("GITHUB_WORKFLOW", "onbekende workflow")
    run_url = "{}/{}/actions/runs/{}".format(
        os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_RUN_ID", ""),
    )
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GIST_TOKEN") or "").strip()
    now = datetime.now(timezone.utc)

    status: dict = {}
    if gist_id and token:
        try:
            raw = load_gist(gist_id, token).get(STATUS_FILE) or "{}"
            status = json.loads(raw)
        except Exception as e:  # noqa: BLE001 — melding mag nooit zelf crashen
            log.warning("Kon %s niet lezen: %s", STATUS_FILE, e)

    entry = status.get(workflow, {})
    last_notified = entry.get("last_notified")
    recently = False
    if last_notified:
        try:
            recently = now - datetime.fromisoformat(last_notified) < timedelta(hours=DEDUPE_HOURS)
        except ValueError:
            pass

    entry["last_failure"] = now.isoformat()
    entry["run_url"] = run_url
    entry["fail_count"] = int(entry.get("fail_count", 0)) + 1

    if recently:
        log.info("Melding voor '%s' overgeslagen — al gemeld binnen %du.", workflow, DEDUPE_HOURS)
    elif send_notification("❌ Workflow mislukt", f"{workflow} is mislukt. Tik om de log te openen.", run_url):
        entry["last_notified"] = now.isoformat()

    status[workflow] = entry
    if gist_id and token:
        try:
            patch_gist(gist_id, token, {STATUS_FILE: json.dumps(status, indent=2, ensure_ascii=False)})
        except Exception as e:  # noqa: BLE001
            log.warning("Kon %s niet bijwerken: %s", STATUS_FILE, e)


if __name__ == "__main__":
    main()
