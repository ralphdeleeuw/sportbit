"""Gedeelde helpers voor GitHub Gist lezen en schrijven."""
from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)
_GIST_API = "https://api.github.com/gists/{gist_id}"
_HEADERS = {"Accept": "application/json"}


def file_content(meta: dict, token: str = "", timeout: int = 20) -> str:
    """Geef de volledige inhoud van één bestand uit een Gist-API-respons.

    GitHub kapt bestanden boven ~1 MB af: `truncated` staat dan op true en
    `content` is onvolledig of afwezig. Zonder deze fallback lijkt zo'n bestand
    leeg of stukgelopen, waarna aanroepers hun cache overschrijven met niets.
    Haal de volledige inhoud in dat geval op via raw_url.
    """
    content = meta.get("content") or ""
    if content and not meta.get("truncated"):
        return content
    raw_url = meta.get("raw_url")
    if not raw_url:
        return content
    try:
        resp = requests.get(
            raw_url,
            headers={"Authorization": f"token {token}"} if token else {},
            timeout=timeout,
        )
        resp.raise_for_status()
        log.info("Gist-bestand %s volledig opgehaald via raw_url (%d bytes)",
                 meta.get("filename", "?"), len(resp.text))
        return resp.text
    except requests.RequestException as exc:
        log.warning("Gist-bestand %s kon niet via raw_url geladen worden: %s",
                    meta.get("filename", "?"), exc)
        return content


def load_gist(gist_id: str, token: str, timeout: int = 20) -> dict[str, str]:
    """Laad alle bestanden uit een Gist. Retourneert {bestandsnaam: inhoud}."""
    resp = requests.get(
        _GIST_API.format(gist_id=gist_id),
        headers={**_HEADERS, "Authorization": f"token {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return {
        name: file_content(meta, token, timeout)
        for name, meta in resp.json().get("files", {}).items()
    }


def patch_gist(gist_id: str, token: str, files: dict[str, str | None], timeout: int = 20) -> None:
    """Patch een of meer bestanden in een Gist.

    Geef None als inhoud om een bestand te verwijderen.
    """
    payload: dict = {}
    for name, content in files.items():
        payload[name] = {"content": content} if content is not None else None
    resp = requests.patch(
        _GIST_API.format(gist_id=gist_id),
        headers={**_HEADERS, "Authorization": f"token {token}"},
        json={"files": payload},
        timeout=timeout,
    )
    resp.raise_for_status()
