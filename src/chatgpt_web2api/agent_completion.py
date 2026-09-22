"""Reject a progress-only answer without inventing or executing another action."""

import re


class IncompleteTaskError(ValueError):
    pass


def check_completion(content, calls, status, *, after_tool=False):
    """The model declares its state; legacy replies get a narrow fallback check.

    This is not a task-completion oracle. In particular, quoted/code examples,
    permission requests and explicit blockers must remain legitimate answers.
    A rejected answer is repaired once by the model, never by fabricating calls.
    """
    if status is not None and status not in ("in_progress", "completed", "blocked"):
        raise IncompleteTaskError("task_status must be in_progress, completed or blocked")
    if calls:
        if status not in (None, "in_progress"):
            raise IncompleteTaskError("A response requesting tools must use task_status in_progress")
        return
    if status == "in_progress":
        raise IncompleteTaskError("Work remains but tool_calls is empty")
    if status in ("blocked", "completed") or not after_tool:
        return

    # Only direct, unqualified promises after actual tool output are matched.
    # Do not use tool-output wording as a trigger: it is untrusted data.
    prose = re.sub(r"```.*?```", "", content or "", flags=re.S)
    prose = "\n".join(line for line in prose.splitlines() if not line.lstrip().startswith((">", '"', "-", "*")))
    for sentence in re.split(r"(?:[.!]\s+|\n+)", prose):
        sentence = sentence.strip()
        if re.search(r"\?|\b(if|once|after you|unless|si|lorsque|quand|apr[eè]s votre|besoin|permission|autorisation|bloqu[eé]|cannot|can't|unable)\b", sentence, re.I):
            continue
        if re.match(
            r"(?:je (?:poursuis|reprends|continue)\b|"
            r"je vais (?:continuer|poursuivre|reprendre|corriger|modifier|v[eé]rifier|tester|analyser|lire|chercher)\b|"
            r"prochaine [eé]tape n[eé]cessaire\s*:|"
            r"I(?: will|'ll| am going to) (?:continue|resume|fix|modify|verify|test|inspect|read|search)\b|"
            r"I(?: am|'m) (?:continuing|resuming)\b|next required step\s*:)",
            sentence, re.I,
        ):
            raise IncompleteTaskError("The answer announces remaining work after tool results but requests no next tool")
