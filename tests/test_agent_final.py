import copy
from unittest.mock import AsyncMock

import pytest

from chatgpt_web2api.agent_final import final_text_message, verified_final_source
from chatgpt_web2api.cdp_driver import CDPDriver
from chatgpt_web2api.tool_bridge import ToolProtocolError

PROSE = (
    "Je ne peux pas fournir ce format de wrapper `web2api_response`.\n\n"
    "Le dernier état confirmé est que la cartographie du dépôt a été récupérée."
)
SNAPSHOT = dict(
    conversation="chat", user_message_id="user-id", assistant_message_id="answer-id",
    user="Exact repair prompt", assistant="Rendered prose", literal=False, unsafe_markup=True,
    completed=True, paired=True, generating=False,
)
PROJECTION = {
    "current_node": "answer",
    "nodes": {
        "user": dict(id="user-id", role="user", text=SNAPSHOT["user"], parent="old"),
        "recap": dict(id="recap-id", role="assistant", content_type="reasoning_recap", parent="user"),
        "answer": dict(id="answer-id", role="assistant", content_type="text", end_turn=True,
                       parent="recap", text=PROSE),
    },
}


def test_final_source_retains_original_markdown_and_selects_exact_ids():
    assert verified_final_source(PROJECTION, SNAPSHOT) == PROSE
    assert final_text_message(PROSE, "auto") == {"role": "assistant", "content": PROSE}


@pytest.mark.parametrize("change", [
    {"user_message_id": "other"}, {"assistant_message_id": "other"}, {"user": "Different task"},
    {"user_message_id": None}, {"assistant_message_id": None},
])
def test_different_prompt_or_missing_exact_ids_cannot_recover(change):
    assert verified_final_source(PROJECTION, {**SNAPSHOT, **change}) is None


@pytest.mark.parametrize("change", [
    {"role": "tool"}, {"content_type": "reasoning_recap"}, {"end_turn": False},
    {"parent": "missing"}, {"parent": "answer"}, {"text": ""}, {"text": None},
])
def test_nonfinal_or_unrelated_nodes_cannot_recover(change):
    projection = copy.deepcopy(PROJECTION)
    projection["nodes"]["answer"].update(change)
    assert verified_final_source(projection, SNAPSHOT) is None


def test_other_branch_and_intervening_user_cannot_recover():
    projection = copy.deepcopy(PROJECTION)
    projection["current_node"] = "another-branch"
    assert verified_final_source(projection, SNAPSHOT) is None
    projection["current_node"] = "answer"
    projection["nodes"]["recap"]["role"] = "user"
    assert verified_final_source(projection, SNAPSHOT) is None


def test_duplicate_ids_cannot_recover():
    for key in ("user", "answer"):
        projection = copy.deepcopy(PROJECTION)
        projection["nodes"]["duplicate"] = projection["nodes"][key]
        assert verified_final_source(projection, SNAPSHOT) is None


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": "read"}}])
def test_prose_does_not_satisfy_required_calls(choice):
    with pytest.raises(ToolProtocolError):
        final_text_message(PROSE, choice)


@pytest.mark.parametrize("text", [
    '<web2api_response nonce="wrong">{"content":"text","tool_calls":[]}</web2api_response>',
    '```json\n{"content":null,"tool_calls":[{"name":"shell"}]}\n```',
    'Result {"function_call": {"name":"shell"}}',
    "", "  ",
])
def test_broken_tool_frames_never_become_successful_final_answers(text):
    with pytest.raises(ToolProtocolError):
        final_text_message(text, "auto")


@pytest.mark.asyncio
async def test_driver_reads_source_and_rechecks_visible_exchange_without_sending():
    driver = CDPDriver()
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock(return_value=PROJECTION)
    driver.read_agent_exchange = AsyncMock(return_value=SNAPSHOT)
    assert await driver.read_agent_final_text(SNAPSHOT) == PROSE
    driver._backend_client._fetch_recent_conversation_projection.assert_awaited_once_with("chat")
    driver.read_agent_exchange.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"conversation": "elsewhere"}, {"user_message_id": "another-user"},
    {"assistant_message_id": "another-answer"}, {"user": "changed prompt"},
    {"assistant": "changed reply"}, {"completed": False}, {"paired": False}, {"generating": True},
])
async def test_driver_rejects_browser_change_during_backend_fetch(change):
    driver = CDPDriver()
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock(return_value=PROJECTION)
    driver.read_agent_exchange = AsyncMock(return_value={**SNAPSHOT, **change})
    assert await driver.read_agent_final_text(SNAPSHOT) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"completed": False}, {"paired": False}, {"generating": True},
    {"conversation": ""}, {"user_message_id": None}, {"assistant_message_id": None},
])
async def test_driver_never_fetches_unfinished_or_unidentified_exchange(change):
    driver = CDPDriver()
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock()
    assert await driver.read_agent_final_text({**SNAPSHOT, **change}) is None
    driver._backend_client._fetch_recent_conversation_projection.assert_not_awaited()
