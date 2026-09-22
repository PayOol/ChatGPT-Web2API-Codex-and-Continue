"""Regression tests for Codex Computer Use calls relayed through exec.

These fixtures reproduce the failed WhatsApp task without controlling a real app.
"""

import json

import pytest

from chatgpt_web2api.tool_bridge import (
    TaskContinuationError,
    ToolBridge,
    ToolProtocolError,
)

EXEC = {
    "type": "function",
    "function": {
        "name": "exec",
        "description": "Run JavaScript with nested client tools.",
        "parameters": {
            "type": "object",
            "properties": {"input": {"type": "string"}},
            "required": ["input"],
            "additionalProperties": False,
        },
    },
}
WINDOW = '{app:"5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",id:68014}'
REHYDRATE = (
    "const w=await sky.get_window({id:68014,"
    "app:'5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App'});"
)


def frame(bridge, *, source=None, content=None):
    calls = [] if source is None else [{"name": "exec", "arguments": {"input": source}}]
    return (
        bridge.opening
        + json.dumps({"content": content, "tool_calls": calls})
        + "</web2api_response>"
    )


def bridge_after(source, result, *, image=False):
    content = [{"type": "text", "text": result}]
    if image:
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AA==", "detail": "auto"},
        })
    messages = [
        {"role": "user", "content": "Utilise Computer Use pour ouvrir WhatsApp."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_sky",
                "type": "function",
                "function": {
                    "name": "exec",
                    "arguments": json.dumps({"input": source}),
                },
            }],
        },
        {"role": "tool", "tool_call_id": "call_sky", "content": content},
    ]
    return ToolBridge.from_request({"model": "auto", "messages": messages, "tools": [EXEC]})


def initial_bridge():
    return ToolBridge.from_request({
        "model": "auto",
        "messages": [{"role": "user", "content": "Inspecte WhatsApp."}],
        "tools": [EXEC],
    })


def test_successful_sky_result_is_matched_to_its_exec_call():
    source = "const r=await sky.list_windows();nodeRepl.write(JSON.stringify(r));"
    bridge = bridge_after(source, '[{"app":"WhatsApp","id":68014}]')

    assert bridge._computer_use_verified is True
    prompt = bridge.prompt([], prior_messages=[])
    assert "persistent sky Computer Use are available" in prompt

    for repeated in (
        "nodeRepl.write(JSON.stringify(await sky.list_windows()));",
        "nodeRepl.write(JSON.stringify(Object.keys(sky)));",
    ):
        with pytest.raises(ToolProtocolError, match="already proves Computer Use"):
            bridge.parse(frame(bridge, source=repeated))


@pytest.mark.parametrize("source, message", [
    ("await sky.get_window(68014);", "get_window requires one object"),
    ("await sky.get_window_state({id:68014});", "requires {window: Window"),
    ("await sky.activate_window({app:'WhatsApp',id:68014});", "requires {window: Window"),
])
def test_real_failed_signatures_are_rejected_before_execution(source, message):
    bridge = initial_bridge()
    with pytest.raises(ToolProtocolError, match=message):
        bridge.parse(frame(bridge, source=source))


def test_invented_sky_method_is_rejected_before_execution():
    bridge = initial_bridge()
    source = (
        REHYDRATE
        + "const state=await sky.observe("
        "{window:w,include_screenshot:true,include_text:false});"
        "await nodeRepl.emitImage(state.screenshots[0].url);image(block);"
    )
    with pytest.raises(ToolProtocolError, match=r"Unsupported @oai/sky method\(s\): observe"):
        bridge.parse(frame(bridge, source=source))


def test_manually_reconstructed_window_is_rejected():
    bridge = initial_bridge()
    source = (
        f"globalThis.targetWindow={WINDOW};"
        "const state=await sky.get_window_state({window:globalThis.targetWindow,"
        "include_screenshot:false,include_text:true});"
        "nodeRepl.write(JSON.stringify(state.accessibility));"
    )
    with pytest.raises(ToolProtocolError, match="Do not reconstruct a Window"):
        bridge.parse(frame(bridge, source=source))

    rehydrated = (
        "globalThis.targetWindow=await sky.get_window({id:68014,"
        "app:'5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App'});"
        "const state=await sky.get_window_state({window:globalThis.targetWindow,"
        "include_screenshot:false,include_text:true});"
        "nodeRepl.write(JSON.stringify(state.accessibility));"
    )
    assert bridge.parse(frame(bridge, source=rehydrated))["tool_calls"]


def test_accessibility_observation_is_small_text_only():
    bridge = initial_bridge()
    valid = (
        REHYDRATE
        + "const state=await sky.get_window_state({window:w,include_screenshot:false,"
        "include_text:true});nodeRepl.write(JSON.stringify(state.accessibility));"
    )
    assert bridge.parse(frame(bridge, source=valid))["tool_calls"]

    invalid = (
        REHYDRATE
        + "const state=await sky.get_window_state({window:w,include_text:true});"
        "nodeRepl.write(JSON.stringify(state));"
    )
    with pytest.raises(ToolProtocolError, match="accessibility observation"):
        bridge.parse(frame(bridge, source=invalid))


def test_screenshot_must_be_forwarded_as_an_image_block():
    bridge = initial_bridge()
    invalid = (
        REHYDRATE
        + "const state=await sky.get_window_state({window:w,include_screenshot:true,"
        "include_text:false});nodeRepl.write(JSON.stringify(state));"
    )
    with pytest.raises(ToolProtocolError, match="must call nodeRepl.emitImage"):
        bridge.parse(frame(bridge, source=invalid))

    valid = (
        "const result=await tools.mcp__node_repl__js({code:"
        f"'{REHYDRATE}const state=await sky.get_window_state("
        "{window:w,include_screenshot:true,include_text:false});"
        "await nodeRepl.emitImage(state.screenshots[0].url)'});"
        "for(const block of result.content??[]){"
        "if(block.type==='image')image(block);else if(block.type==='text')text(block.text);}"
    )
    assert bridge.parse(frame(bridge, source=valid))["tool_calls"]


def test_one_input_requires_a_refresh_and_multiple_inputs_are_rejected():
    bridge = initial_bridge()
    valid = (
        REHYDRATE
        + "await sky.click({window:w,x:120,y:250});"
        "const state=await sky.get_window_state({window:w,include_screenshot:false,"
        "include_text:true});nodeRepl.write(JSON.stringify(state.accessibility));"
    )
    assert bridge.parse(frame(bridge, source=valid))["tool_calls"]

    no_refresh = REHYDRATE + "await sky.click({window:w,x:120,y:250});"
    with pytest.raises(ToolProtocolError, match="refresh WindowState"):
        bridge.parse(frame(bridge, source=no_refresh))

    batched = (
        REHYDRATE
        + "await sky.click({window:w,x:120,y:250});"
        "await sky.type_text({window:w,text:'Bonjour'});"
        "await sky.get_window_state({window:w,include_screenshot:false,include_text:true});"
    )
    with pytest.raises(ToolProtocolError, match="one state-derived input"):
        bridge.parse(frame(bridge, source=batched))


def test_successful_observation_blocks_false_capability_denial():
    source = (
        REHYDRATE
        + "const state=await sky.get_window_state("
        "{window:w,include_screenshot:true,include_text:false});"
        "await nodeRepl.emitImage(state.screenshots[0].url);image(block);"
    )
    bridge = bridge_after(source, '{"isError":false,"status":"Script completed"}', image=True)
    assert bridge._computer_use_verified is True
    assert bridge._computer_use_observed is True

    with pytest.raises(TaskContinuationError, match="prove Computer Use is available"):
        bridge.parse(frame(
            bridge,
            content=(
                "Je ne peux pas exécuter l'appel externe exec demandé ni contrôler WhatsApp "
                "depuis cet environnement."
            ),
        ))

    blocker = "Le bureau Windows est verrouillé et l'outil demande de déverrouiller la session."
    assert bridge.parse(frame(bridge, content=blocker))["content"] == blocker
