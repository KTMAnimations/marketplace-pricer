from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AlertMessage:
    title: str
    body: str

    def render_text(self) -> str:
        if not self.title:
            return self.body
        if not self.body:
            return self.title
        return f"{self.title}\n{self.body}"


class AlertChannel(Protocol):
    name: str

    def send(self, message: AlertMessage) -> None:
        ...

