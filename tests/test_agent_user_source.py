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


@pytest.mark.asyncio
async def test_actual_projection_retains_user_multimodal_text_for_completion():
    import shutil
    import subprocess

    from chatgpt_web2api.backend_projection import CONVERSATION_PROJECTION_JS

    node = shutil.which("node")
    if not node:
        pytest.skip("Node required to execute production projection JS")
    source = 'Inspect `image` with nonce exact_request_123'
    mapping = {"user1": {"message": {"id": "user1", "author": {"role": "user"},
        "content": {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "SECRET_ASSET"}, source]}}},
        "assistant1": {"message": {"id": "assistant1", "author": {"role": "assistant"},
            "content": {"content_type": "multimodal_text", "parts": ["DO_NOT_PROJECT_ASSISTANT_ASSETS"]}}}}
    script = (
        "const [code,mapping]=JSON.parse(process.argv[1]);"
        "const __D={conv_id:'chat1',token:'fake',limit:50};"
        "const fetch=async()=>({ok:true,json:async()=>({mapping,current_node:'assistant1'})});"
        "Promise.resolve(eval(code)).then(console.log);"
    )
    raw = subprocess.check_output([node, "-e", script, json.dumps([CONVERSATION_PROJECTION_JS, mapping])], text=True)
    projection = json.loads(raw)
    assert projection["nodes"]["user1"]["text"] == source
    assert projection["nodes"]["assistant1"]["text"] == ""
    assert "SECRET_ASSET" not in raw
    driver = CDPDriver()
    driver._js_strict = AsyncMock(return_value=json.dumps(dict(
        conversation="chat1", user_message_id="user1", user_rendered=True,
        completed=True, paired=True, generating=False, user="Inspect image")))
    driver._backend_client._fetch_recent_conversation_projection = AsyncMock(return_value=projection)
    assert (await driver.read_agent_exchange())["user"] == source
