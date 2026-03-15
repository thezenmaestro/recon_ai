"""Microsoft Teams notifications via Incoming Webhook (Adaptive Card)."""
from __future__ import annotations

import json

import requests


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
        "themeColor": "C0392B",     # Red header
        "summary": "Reconciliation Alert",
        "sections": [{
            "activityTitle": "**Trade Reconciliation Alert**",
            "activitySubtitle": "Automated nightly run",
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
