"""Request-local, bounded observations. Never model thoughts or tool results."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

current: ContextVar[Progress | None] = ContextVar("web2api_progress", default=None)


class Progress:
    def __init__(self):
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self.last = "Connexion à la passerelle établie."
        self.seen: set[str] = set()

    def publish(self, message: str):
        self.last = message
        if message in self.seen or len(self.seen) >= 32:
            return
        self.seen.add(message)
        self.queue.put_nowait(message)


def report(message: str):
    sink = current.get()
    if sink is not None:
        sink.publish(message)
