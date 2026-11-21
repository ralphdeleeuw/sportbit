"""Detecteer nieuwe persoonlijke records (SugarWOD) en stuur een pushmelding.

Vergelijkt de PR-lijst van de vorige run (uit de Gist) met de zojuist gescrapete
lijst. Een PR is "nieuw" als de combinatie workout + resultaat nog niet bestond.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Bij meer nieuwe PR's dan dit is de vorige scrape vermoedelijk (deels) mislukt:
# dan één samenvattende melding in plaats van een stortvloed.
MAX_INDIVIDUAL_ALERTS = 3


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def find_new_prs(old: list[dict], new: list[dict]) -> list[dict]:
    """Geef de PR's uit `new` die niet in `old` stonden, met het vorige resultaat erbij."""
    if not old:
        # Eerste run of vorige scrape leeg: geen basis om te vergelijken.
        return []
    seen = {(_norm(p.get("workout", "")), _norm(p.get("result", ""))) for p in old}
    previous = {}
    for p in old:
        previous.setdefault(_norm(p.get("workout", "")), p.get("result", ""))
    out = []
    for p in new:
        key = (_norm(p.get("workout", "")), _norm(p.get("result", "")))
        if not key[0] or not key[1] or key in seen:
            continue
        out.append({**p, "previous_result": previous.get(key[0], "")})
    return out


def notify_new_prs(old: list[dict], new: list[dict]) -> int:
    """Stuur pushmeldingen voor nieuwe PR's. Geeft het aantal nieuwe PR's terug."""
    fresh = find_new_prs(old, new)
    if not fresh:
        return 0
    try:
        from notify import send_notification  # noqa: PLC0415 — pywebpush optioneel
    except Exception as e:  # noqa: BLE001
        log.warning("PR-melding overgeslagen (notify niet beschikbaar): %s", e)
        return len(fresh)

    if len(fresh) > MAX_INDIVIDUAL_ALERTS:
        names = ", ".join(p.get("workout", "?") for p in fresh[:5])
        send_notification("🏆 Nieuwe PR's", f"{len(fresh)} nieuwe records: {names}{'…' if len(fresh) > 5 else ''}")
        return len(fresh)

    for p in fresh:
        prev = p.get("previous_result")
        body = p.get("result", "")
        if prev:
            body += f" (vorige: {prev})"
        send_notification(f"🏆 Nieuw PR: {p.get('workout', '?')}", body)
        log.info("Nieuw PR gemeld: %s — %s", p.get("workout"), body)
    return len(fresh)
