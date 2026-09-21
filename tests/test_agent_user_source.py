import json
from unittest.mock import AsyncMock

import pytest

from chatgpt_web2api.cdp_driver import CDPDriver


@pytest.mark.asyncio
async def test_rendered_user_source_is_exactly_resolved_by_id_and_cached():
    driver = CDPDriver()
    snapshot = dict(conversation="chat1", user_message_id="user1", user_rendered=True,
                    completed=True, paired=True, generating=False, user="run code")
    driver._js_strict = AsyncMock(return_value=json.dumps(snapshot))
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock(return_value={
        "nodes": {"wrong": {"id": "old", "role": "user", "text": "wrong task"},
                  "right": {"id": "user1", "role": "user", "text": "run `code`"}}})
    assert (await driver.read_agent_exchange())["user"] == "run `code`"
    assert (await driver.read_agent_exchange())["user"] == "run `code`"
    driver._backend_client._fetch_recent_conversation_projection.assert_awaited_once_with("chat1")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [dict(generating=True), dict(completed=False), dict(paired=False),
                                   dict(user_message_id=None), dict(user_rendered=False)])
async def test_unfinished_or_unidentified_turn_never_fetches_user_source(change):
    driver = CDPDriver()
    snapshot = dict(conversation="chat1", user_message_id="user1", user_rendered=True,
                    completed=True, paired=True, generating=False, user="run code")
    driver._js_strict = AsyncMock(return_value=json.dumps({**snapshot, **change}))
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock()
    assert (await driver.read_agent_exchange())["user"] == "run code"
    driver._backend_client._fetch_recent_conversation_projection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("nodes", [{}, {"n": {"id": "other", "role": "user", "text": "wrong"}},
                                 {"n": {"id": "user1", "role": "assistant", "text": "wrong"}}])
async def test_missing_or_wrong_user_id_does_not_replace_rendered_text(nodes):
    driver = CDPDriver()
    driver._js_strict = AsyncMock(return_value=json.dumps(dict(
        conversation="chat1", user_message_id="user1", user_rendered=True,
        completed=True, paired=True, generating=False, user="run code")))
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock(return_value={"nodes": nodes})
    assert (await driver.read_agent_exchange())["user"] == "run code"
