from __future__ import annotations

from marketplace_pricer.alerts.base import AlertChannel, AlertMessage


class ConsoleAlert:
    name = "console"

    def send(self, message: AlertMessage) -> None:
        print("\n" + message.render_text() + "\n")

