"""Gedeelde helpers voor GitHub Gist lezen en schrijven."""
from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)
_GIST_API = "https://api.github.com/gists/{gist_id}"
_HEADERS = {"Accept": "application/json"}


def load_gist(gist_id: str, token: str, timeout: int = 20) -> dict[str, str]:
    """Laad alle bestanden uit een Gist. Retourneert {bestandsnaam: inhoud}."""
    resp = requests.get(
        _GIST_API.format(gist_id=gist_id),
        headers={**_HEADERS, "Authorization": f"token {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return {
        name: meta.get("content", "")
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
