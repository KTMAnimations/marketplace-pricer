from __future__ import annotations

import requests

from marketplace_pricer.alerts.base import AlertMessage


class TelegramBotAlert:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send(self, message: AlertMessage) -> None:
        resp = requests.post(
            f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
            data={
                "chat_id": self._chat_id,
                "text": message.render_text(),
                "disable_web_page_preview": "true",
            },
            timeout=20,
        )
        resp.raise_for_status()

