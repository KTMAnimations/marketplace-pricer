from __future__ import annotations

import requests

from marketplace_pricer.alerts.base import AlertMessage


class DiscordWebhookAlert:
    name = "discord"

    def __init__(self, webhook_url: str):
        self._url = webhook_url

    def send(self, message: AlertMessage) -> None:
        resp = requests.post(
            self._url,
            json={"content": message.render_text()},
            timeout=20,
        )
        resp.raise_for_status()

