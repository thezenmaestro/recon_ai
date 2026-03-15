"""Microsoft Teams notifications via Incoming Webhook (Adaptive Card)."""
from __future__ import annotations

import json
import os

import requests
import yaml

_ROUTING_PATH = os.path.join(os.path.dirname(__file__), "../../config/alert_routing.yaml")
with open(_ROUTING_PATH) as _f:
    _ROUTING = yaml.safe_load(_f)

_TEAMS_FMT = _ROUTING.get("notification_formatting", {}).get("teams", {})


def send_teams(webhook_url: str, message: str) -> None:
    """
    Post a message to a Microsoft Teams channel via Incoming Webhook.

    Args:
        webhook_url: Full Teams webhook URL from alert_routing.yaml
        message: Plain text message (will be rendered in a Teams card)
    """
    if not webhook_url or webhook_url.startswith("https://yourfirm"):
        print("[Teams] Webhook URL not configured. Skipping alert.")
        return

    # Teams uses Adaptive Cards — format as a simple MessageCard
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": _TEAMS_FMT.get("theme_color", "C0392B"),
        "summary": "Reconciliation Alert",
        "sections": [{
            "activityTitle": _TEAMS_FMT.get("card_title", "**Trade Reconciliation Alert**"),
            "activitySubtitle": _TEAMS_FMT.get("card_subtitle", "Automated nightly run"),
            "text": message.replace("\n", "<br>"),
        }],
    }

    response = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    if response.status_code not in (200, 204):
        print(f"[Teams] Failed to send alert. Status: {response.status_code} | {response.text}")
    else:
        print("[Teams] Alert sent.")
