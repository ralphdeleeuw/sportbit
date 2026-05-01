"""Gedeelde Web Push notificatiefunctie (vervangt Pushover)."""
import json
import logging
import os

import requests
from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)


def send_notification(title: str, body: str, url: str = "/sportbit/") -> bool:
    """Stuur een Web Push notificatie via de opgeslagen push-subscription in de Gist."""
    gist_id = os.environ.get("GIST_ID")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GIST_TOKEN")
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    claims_email = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:sportbit@example.com")

    if not all([gist_id, token, private_key]):
        log.warning("GIST_ID, GITHUB_TOKEN of VAPID_PRIVATE_KEY niet ingesteld; notificatie overgeslagen.")
        return False

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        sub_file = resp.json().get("files", {}).get("push_subscription.json")
        if not sub_file or not sub_file.get("content"):
            log.info("Geen push_subscription.json gevonden in Gist; notificatie overgeslagen.")
            return False
        subscription = json.loads(sub_file["content"])
    except Exception as e:
        log.error("Kan push subscription niet lezen uit Gist: %s", e)
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=private_key,
            vapid_claims={"sub": claims_email},
        )
        log.info("Web Push notificatie verstuurd: %s", title)
        return True
    except WebPushException as e:
        log.error("Web Push mislukt: %s", e)
        return False
