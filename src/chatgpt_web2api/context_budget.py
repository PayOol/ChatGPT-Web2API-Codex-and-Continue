"""Bound serialized tool output without altering instructions or call IDs.

This is deterministic excerpting, not an LLM summary. Missing output is always
labelled; it must never be interpreted as evidence of success or absence.
"""

from __future__ import annotations

import copy
import json
import re

_DIAGNOSTIC = re.compile(
    r"error|exception|traceback|failed|failure|fatal|erreur|introuvable|"
    r"fullyqualifiederrorid|categoryinfo|exit.?code|access.?denied|permission.?denied",
    re.I,
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _excerpt(text: str, limit: int, diagnostics: list[str]) -> str:
    if len(text) <= limit:
        return text
    notice = (
        f"\n[web2api: OUTPUT ABBREVIATED; original={len(text)} characters. "
        "Middle omitted; excerpts below are incomplete, not a full execution result.]\n"
    )
    remaining = max(0, limit - len(notice) - 80)
    head_size = remaining // 2
    diagnostic_size = remaining // 5
    tail_size = remaining - head_size - diagnostic_size
    selected = "\n".join(diagnostics)[:diagnostic_size]
    return (
        text[:head_size]
        + notice
        + "[diagnostic excerpts]\n"
        + selected
        + "\n[tail of original output]\n"
        + (text[-tail_size:] if tail_size else "")
    )


def fit_tool_outputs(messages: list[dict], max_json_chars: int) -> tuple[list[dict], dict]:
    """Keep every message/call/result; shorten only tool-role text if necessary.

    A 16K per-text ceiling limits large results. A shared ceiling is reduced
    further if many results overflow the aggregate JSON budget. Count escaped
    JSON, not just raw text, so backslashes/control characters remain bounded.
    Non-tool content, tool arguments, result IDs and non-text blocks are never
    discarded. Return copies; matching and persistence use the original input.
    """
    original_size = len(_json(messages))
    stats = dict(original_chars=original_size, sent_chars=original_size, shortened_outputs=0)
    if original_size <= max_json_chars:
        return messages, stats

    slots = []
    for i, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, str):
            slots.append((i, None, content))
        elif isinstance(content, list):
            for j, block in enumerate(content):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    slots.append((i, j, block["text"]))

    prepared = []
    for i, j, text in slots:
        # Keep distinct diagnostic lines in original order, with a bounded
        # sample from both ends. Repetitive terminal failures cannot fill it.
        lines = []
        seen = set()
        for line in text.splitlines():
            if _DIAGNOSTIC.search(line) and line not in seen:
                seen.add(line)
                lines.append(line[:600])
        prepared.append((i, j, text, lines[:12] + lines[-12:] if len(lines) > 24 else lines))

    def render(limit):
        result = copy.deepcopy(messages)
        shortened = 0
        for i, j, text, diagnostics in prepared:
            value = _excerpt(text, limit, diagnostics)
            if value != text:
                shortened += 1
                if j is None:
                    result[i]["content"] = value
                else:
                    result[i]["content"][j]["text"] = value
        return result, len(_json(result)), shortened

    result, size, shortened = render(16384)
    if size > max_json_chars:
        result, size, shortened = render(512)
        if size > max_json_chars:
            raise ValueError(
                "Agent instructions, call metadata or non-text context exceed the available budget even after tool-output excerpting; compact the conversation."
            )
        lo, hi = 512, 16384
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            candidate, candidate_size, count = render(mid)
            if candidate_size <= max_json_chars:
                result, size, shortened = candidate, candidate_size, count
                lo = mid
            else:
                hi = mid
    stats.update(sent_chars=size, shortened_outputs=shortened)
    return result, stats
