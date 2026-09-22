"""Recover final prose only from an exactly correlated, completed backend turn."""

import re

from .tool_bridge import ToolProtocolError
from .turn_anchor import normalize_text


def verified_final_source(projection: dict, snapshot: dict) -> str | None:
    """Keep original Markdown; never reconstruct executable data from the DOM."""
    user_id = snapshot.get("user_message_id")
    assistant_id = snapshot.get("assistant_message_id")
    if not user_id or not assistant_id:
        return None
    nodes = projection.get("nodes", {})
    users = [(key, node) for key, node in nodes.items() if node.get("id") == user_id]
    answers = [(key, node) for key, node in nodes.items() if node.get("id") == assistant_id]
    if len(users) != 1 or len(answers) != 1:
        return None
    user_key, user = users[0]
    answer_key, answer = answers[0]
    if (
        user.get("role") != "user"
        or not user.get("text")
        or normalize_text(user["text"]) != normalize_text(snapshot.get("user", ""))
        or answer.get("role") != "assistant"
        or answer.get("content_type") != "text"
        or answer.get("end_turn") is not True
        or projection.get("current_node") != answer_key
    ):
        return None
    # An exact user ID must be the nearest user ancestor of this final answer.
    # Reasoning/tool graph nodes can intervene; other branches/turns cannot.
    parent = answer.get("parent")
    seen = {answer_key}
    while parent != user_key:
        if parent in seen or parent not in nodes:
            return None
        seen.add(parent)
        node = nodes[parent]
        if node.get("role") == "user":
            return None
        parent = node.get("parent")
    text = answer.get("text")
    return text if isinstance(text, str) and text.strip() else None


def final_text_message(text: str, choice: str | dict) -> dict:
    """Prose is display-only. Broken tool envelopes must still fail closed."""
    if choice not in ("auto", "none"):
        raise ToolProtocolError("A final answer cannot satisfy a required tool choice")
    if not isinstance(text, str) or not text.strip():
        raise ToolProtocolError("No verified final text")
    # Do not disguise a rejected action batch as a successful final answer.
    # Mentioning the wrapper in ordinary prose (including a refusal) is fine.
    if re.search(r"</?web2api_response\b", text, re.IGNORECASE) or re.search(
        r'["\'](?:tool_calls|function_call)["\']\s*:', text
    ):
        raise ToolProtocolError("A rejected tool envelope cannot become a final answer")
    return {"role": "assistant", "content": text}
