"""Conservative history matching and adaptive account pacing for the local API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def message_hash(message):
    # Continue can represent an empty assistant content as null or ''.
    value = {
        k: message[k] for k in ("role", "content", "tool_calls", "tool_call_id") if k in message
    }
    value["content"] = value.get("content") or ""
    if (
        value.get("role") == "assistant"
        and isinstance(value["content"], str)
        and not value["content"].strip()
    ):
        # Continue's addSpaceToAnyEmptyMessages converts null/'' to ' '.
        value["content"] = ""
    calls = value.get("tool_calls") or []
    value["tool_calls"] = []
    for call in calls:
        fn = dict(call.get("function", {}))
        try:
            fn["arguments"] = json.loads(fn["arguments"])
        except (ValueError, TypeError, KeyError):
            pass
        value["tool_calls"].append({"id": call.get("id"), "function": fn})
    return digest(value)


class UncertainSendError(RuntimeError):
    pass


class AgentState:
    """Persist only hashes/identifiers/times, never project contents or credentials."""

    def __init__(self, path=None, interval=0.0):
        self.path = Path(path) if path else None
        self.interval = interval
        self.sessions = []
        self.uncertain = {}
        self.pending_frames = {}
        self.replies = {}
        self.next_send = 0
        self.cooldown_until = 0
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.sessions = data.get("sessions", [])
            self.uncertain = data.get("uncertain", {})
            self.pending_frames = data.get("pending_frames", {})
            # Pacing is a local throughput preference, not a rate-limit
            # penalty.  A previous version may have persisted a 30-second
            # deadline; cap it to the current interval so a speed upgrade takes
            # effect immediately.  Real rate limits live in cooldown_until.
            self.next_send = min(
                float(data.get("next_send", 0)),
                time.time() + max(0.0, float(self.interval)),
            )
            self.cooldown_until = data.get("cooldown_until", 0)

    def save(self):
        now = time.time()
        self.sessions = [s for s in self.sessions if now - s["time"] < 86400][-32:]
        self.uncertain = {k: v for k, v in self.uncertain.items() if now - v < 86400}
        self.pending_frames = {k: v for k, v in self.pending_frames.items() if k in self.uncertain}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = dict(
                sessions=self.sessions,
                uncertain=self.uncertain,
                pending_frames=self.pending_frames,
                next_send=self.next_send,
                cooldown_until=self.cooldown_until,
            )
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)

    def match(self, messages, scope):
        hashes = [message_hash(m) for m in messages]
        for entry in sorted(self.sessions, key=lambda s: len(s["hashes"]), reverse=True):
            prefix = entry["hashes"]
            if (
                time.time() - entry["time"] < 86400
                and entry["scope"] == scope
                and len(hashes) > len(prefix)
                and hashes[: len(prefix)] == prefix
            ):
                return entry["conversation"], len(prefix) - 1
        return None, 0

    def remember(self, messages, reply, scope, conversation):
        if not conversation:
            return
        self.sessions = [s for s in self.sessions if s["conversation"] != conversation]
        self.sessions.append(
            dict(
                scope=scope,
                conversation=conversation,
                hashes=[message_hash(m) for m in messages + [reply]],
                time=time.time(),
            )
        )
        self.save()

    def check(self, key=None):
        from .cdp_driver import RateLimitError

        if key in self.uncertain and time.time() - self.uncertain[key] < 86400:
            raise UncertainSendError(
                "Previous send has an uncertain outcome; automatic resubmission is blocked. Check the existing ChatGPT conversation before continuing."
            )
        if self.cooldown_until > time.time():
            raise RateLimitError(retry_after=math.ceil(self.cooldown_until - time.time()))

    async def reserve(self):
        self.check()
        wait_seconds = max(0, self.next_send - time.time())
        await asyncio.sleep(wait_seconds)
        self.check()
        self.next_send = time.time() + self.interval
        self.save()
        return wait_seconds

    def penalize(self, seconds):
        self.cooldown_until = max(self.cooldown_until, time.time() + max(180, seconds))
        self.save()

    def begin(self, key, *, nonce=None, prompt=None, conversation=None, repair_attempted=False):
        self.uncertain[key] = time.time()
        if nonce and prompt:
            from .turn_anchor import normalize_text

            previous_repair = self.pending_frames.get(key, {}).get("repair_attempted", False)
            self.pending_frames[key] = dict(
                nonce=nonce,
                prompt_hash=digest(normalize_text(prompt)),
                conversation=conversation,
                repair_attempted=repair_attempted or previous_repair,
            )
        self.save()

    def complete(self, key):
        self.uncertain.pop(key, None)
        self.pending_frames.pop(key, None)
        self.save()
