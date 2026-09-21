"""Long silent reasoning, explicit deadlines and cancellation without resends."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from chatgpt_web2api import completion_detector as module
from chatgpt_web2api.cdp_driver import CDPJSError, GenerationStuckError, RateLimitError
from chatgpt_web2api.completion_detector import CompletionDetector, DetectorBudgets
from chatgpt_web2api.config import ChatGPTConfig, Config
from chatgpt_web2api.tool_bridge import ToolProtocolError
from chatgpt_web2api.turn_anchor import TurnAnchor, TurnEndResult


def simulated_detector(monkeypatch, *, appear_after=0, finish_after=21600, partial=False):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))

    async def sleep(seconds):
        clock.now += 3600  # One hour per poll; no real wait or loop-clock changes.

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(sleep=sleep))
    driver = MagicMock()
    driver._current_conv_id = "test-conversation"
    driver._fetch_end_turn_for_turn = AsyncMock(return_value=TurnEndResult(status="not_ready"))
    marker = '<web2api_response nonce="test">'
    frame = marker + '{"content":"Finished","tool_calls":[]}</web2api_response>'

    async def observe(expression):
        if "getBoundingClientRect" in expression:
            ready = clock.now >= finish_after
            text = frame if ready else (marker + '{"content":' if partial else "")
            return json.dumps(
                {
                    "text": text,
                    "md_text": text,
                    "agent_text": text,
                    "has_action": ready,
                    "is_thinking": not ready,
                    "is_generating": not ready,
                }
            )
        if "[role=dialog],[role=alert]" in expression:
            return '{"text":""}'
        if "web2apiAgentText(last).text" in expression:
            return marker if clock.now >= appear_after else "old answer"
        return "3"  # Virtualization: assistant count NEVER increases.

    driver._js_strict = observe

    def validate(text):
        if text != frame:
            raise ValueError("Incomplete")
        return frame

    return (
        CompletionDetector(driver),
        driver,
        clock,
        dict(
            initial_count=3,
            timeout=0,
            turn_anchor=TurnAnchor(sent_text="hi", mode="fresh_chat"),
            budgets=DetectorBudgets.from_config(ChatGPTConfig(), "auto"),
            response_marker=marker,
            response_validator=validate,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("appear_after,partial", [(21600, False), (0, False), (0, True)])
async def test_six_hours_without_dom_progress_then_complete(monkeypatch, appear_after, partial):
    detector, driver, clock, kwargs = simulated_detector(
        monkeypatch, appear_after=appear_after, finish_after=28800, partial=partial
    )
    async for _ in detector.stream_until_complete(**kwargs):
        pass
    assert clock.now >= 28800
    assert '"content":"Finished"' in detector.validated_dom_text
    driver._fetch_end_turn_for_turn.assert_not_awaited()  # Agent nonce only, no API polling.


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [1, 2])
async def test_explicit_deadline_still_raises_and_never_returns_partial(monkeypatch, phase):
    detector, _, clock, kwargs = simulated_detector(
        monkeypatch, appear_after=10000 if phase == 1 else 0
    )
    kwargs["timeout"] = 7200
    with pytest.raises(GenerationStuckError, match=f"phase_{phase}"):
        async for _ in detector.stream_until_complete(**kwargs):
            pass
    assert clock.now == 7200
    assert detector.validated_dom_text == ""


@pytest.mark.asyncio
async def test_deadline_is_shared_between_appear_and_stream(monkeypatch):
    detector, _, clock, kwargs = simulated_detector(monkeypatch, appear_after=3600)
    kwargs["timeout"] = 7200
    with pytest.raises(GenerationStuckError, match="phase_2"):
        async for _ in detector.stream_until_complete(**kwargs):
            pass
    assert clock.now == 7200


@pytest.mark.asyncio
async def test_rate_limit_still_fails_immediately(monkeypatch):
    detector, driver, clock, kwargs = simulated_detector(monkeypatch)
    driver._js_strict = AsyncMock(return_value='{"text":"Too many requests"}')
    with pytest.raises(RateLimitError):
        async for _ in detector.stream_until_complete(**kwargs):
            pass
    assert clock.now == 0


@pytest.mark.asyncio
async def test_unreadable_browser_does_not_wait_forever(monkeypatch):
    detector, driver, _, kwargs = simulated_detector(monkeypatch)
    driver._js_strict = AsyncMock(side_effect=CDPJSError("Browser observation failed"))
    with pytest.raises(CDPJSError):
        async for _ in detector.stream_until_complete(**kwargs):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", [None, "user", "conversation", "paired", "generating", "completed"]
)
async def test_finished_plain_answer_is_repaired_only_for_the_exact_sent_turn(
    monkeypatch, mismatch
):
    detector, driver, clock, kwargs = simulated_detector(monkeypatch, appear_after=100000)
    kwargs["timeout"] = 7200
    kwargs["turn_anchor"] = TurnAnchor(
        sent_text="hi", mode="existing_conversation", conversation_id_at_capture="test-conversation"
    )
    snapshot = dict(
        user="hi",
        assistant="old answer",
        paired=True,
        completed=True,
        generating=False,
        conversation="test-conversation",
    )
    changes = dict(
        user="other prompt",
        conversation="other chat",
        paired=False,
        generating=True,
        completed=False,
    )
    if mismatch:
        snapshot[mismatch] = changes[mismatch]
    driver.read_agent_exchange = AsyncMock(return_value=snapshot)
    with pytest.raises(ToolProtocolError if mismatch is None else GenerationStuckError):
        async for _ in detector.stream_until_complete(**kwargs):
            pass
    assert clock.now == (3600 if mismatch is None else 7200)
    driver._fetch_end_turn_for_turn.assert_not_awaited()


def test_all_default_models_allow_unlimited_generation():
    cfg = Config()
    assert cfg.server.request_timeout == 0
    for model in ["auto", "gpt-5-5-thinking", "unknown"]:
        assert DetectorBudgets.from_config(cfg.chatgpt, model) == DetectorBudgets(0, 0, 0)


def test_continue_long_wait_transport():
    test = Path(__file__).parent / "integration/test_continue_long_wait.cjs"
    result = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
