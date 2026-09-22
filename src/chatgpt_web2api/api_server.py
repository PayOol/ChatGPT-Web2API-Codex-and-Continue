"""OpenAI-compatible API server.

Endpoints:
  POST /v1/chat/completions  — chat (streaming + non-streaming)
  GET  /v1/models            — model catalog
  GET  /v1/projects          — ChatGPT projects
  GET  /health               — health + Chrome status
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import suppress
from pathlib import Path

from aiohttp import web

from .agent_sessions import AgentState, UncertainSendError, digest
from .breakers import BreakerKind, BreakerRegistry, CircuitOpenError
from .cdp_driver import (
    AuthExpiredError,
    CDPDriver,
    GenerationStuckError,
    RateLimitError,
    SendReadinessError,
    is_rate_limited_text,
)
from .config import Config
from .cross_process_lock import LockAcquisitionError
from .lock_resolver import MutationLock, OwnedTabRequiredError, resolve_mutation_lock
from .progress import report
from .tool_bridge import ToolBridge, ToolProtocolError, ToolRequestError
from .vision_bridge import ImageUploadError, images_for_turn, normalize_images

logger = logging.getLogger(__name__)


class PendingFormatRepair(ToolProtocolError):
    """The exact pending turn finished but needs its one format-only repair."""

    def __init__(self, error, nonce, conversation):
        super().__init__(str(error))
        self.nonce = nonce
        self.conversation = conversation


# Model mapping: user-facing names → ChatGPT web slugs
MODEL_MAP = {
    "gpt-5.5": "gpt-5-5",
    "gpt-5.5-thinking": "gpt-5-5-thinking",
    "gpt-5.3": "gpt-5-3",
    "gpt-5.2": "gpt-5-2",
    "gpt-5.1": "gpt-5-1",
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
    "gpt-5.3-mini": "gpt-5-3-mini",
    "auto": "auto",
    # Legacy aliases
    "gpt-4o": "auto",
    "gpt-4": "gpt-5",
    "gpt-3.5-turbo": "gpt-5-mini",
}


class APIServer:
    """OpenAI-compatible API backed by CDP automation."""

    def __init__(
        self, config: Config, driver: CDPDriver, breakers: BreakerRegistry | None = None
    ) -> None:
        self._config = config
        self._driver = driver
        self._cdp_port = config.chrome.cdp_port
        self._parallel_tabs = config.chatgpt.parallel_tabs
        self._request_count = 0
        self._active_requests = 0
        # Health telemetry (event-derived, not polled). These are the only
        # fields that make sense to cache: they mark WHEN something happened,
        # not whether something is alive right now (that's computed live in
        # _handle_health). Without last_successful_send_at, a zombie process
        # that never connected (cdp_connected=false, requests_served=0) looks
        # identical to a freshly-started healthy one — both report "waiting".
        self._started_at = time.time()
        self._last_error: str | None = None
        self._last_successful_send_at: float | None = None
        # Non-rate-limit breaker registry (Phase 4). Injected by Service so the
        # REST process shares one registry across Chrome + driver + server.
        # Default-constructed for back-compat with tests that don't pass one.
        self._breakers = breakers or BreakerRegistry()
        # Track last conversation for multi-turn continuity
        self._last_conv_id: str | None = None
        self._last_project_id: str | None = None
        self._agent_state = AgentState(
            Path(os.environ.get("W2A_STATE_DIR", str(Path.home() / ".chatgpt-web2api")))
            / "agent-state.json"
            if isinstance(driver, CDPDriver)
            else None,
            interval=config.chatgpt.agent_request_interval_seconds,
        )

        # Four 12 MiB images can exceed 64 MiB after base64 + JSON encoding.
        self.app = web.Application(client_max_size=70 * 1024 * 1024)
        self.app.router.add_post("/v1/chat/completions", self._handle_chat)
        self.app.router.add_post("/chat/completions", self._handle_chat)
        self.app.router.add_get("/v1/models", self._handle_models)
        self.app.router.add_get("/v1/projects", self._handle_projects)
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_get("/", self._handle_health)
        self.app.router.add_post("/codex/v1/chat/completions", self._handle_codex_chat)
        self.app.router.add_post("/codex/v1/responses", self._handle_codex_responses)
        self.app.router.add_get("/codex/v1/models", self._handle_codex_models)

    async def _handle_codex_chat(self, request):
        from .codex_transport import chat

        return await chat(self, request)

    async def _handle_codex_responses(self, request):
        from .codex_transport import responses

        return await responses(self, request)

    async def _handle_codex_models(self, request):
        from .codex_transport import models

        return await models(self, request)

    # ── Auth ──────────────────────────────────────────────────

    def _check_auth(self, request: web.Request) -> web.Response | None:
        """Check API key if configured. Returns error response or None."""
        keys = self._config.server.api_keys
        if not keys:
            return None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:]
        else:
            key = request.query.get("key", "")
        if key not in keys:
            return web.json_response(
                {"error": {"message": "Invalid API key", "type": "auth_error"}},
                status=401,
            )
        return None

    # ── Handlers ──────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Honest health endpoint — observes current reality, not a stale mirror.

        The old version returned ``"waiting"`` when CDP was disconnected, which
        is indistinguishable from "freshly started, connecting now" — a zombie
        process (HTTP listener up, CDP never connected) reported the same
        status as a healthy one. This version distinguishes four states:

        - ``starting``: listener up, driver not yet connected, never served
        - ``healthy``: Chrome alive AND driver connected
        - ``degraded``: Chrome alive but driver disconnected (zombie/recovering)
        - ``broken``: Chrome itself unreachable

        Live fields (chrome_running, driver_connected) are computed fresh on
        each call — /health is infrequent (supervisor poll), and cached state
        would lag reality. Event-derived fields (started_at, last_error,
        last_successful_send_at, requests_served) are tracked on the instance.
        """
        import urllib.request

        driver_connected = bool(self._driver.is_connected)

        # Chrome liveness: cheap HTTP GET to /json/version. If Chrome is dead,
        # this fails fast (connection refused). Run synchronously — /health is
        # infrequent and the call is sub-millisecond on loopback.
        chrome_running = False
        try:
            loop = asyncio.get_event_loop()

            def _probe():
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{self._cdp_port}/json/version", timeout=2
                    ) as r:
                        return r.status == 200
                except Exception:
                    return False

            chrome_running = await loop.run_in_executor(None, _probe)
        except Exception:
            chrome_running = False

        # Status logic — zombie case (Chrome up, driver dead) is "degraded",
        # never "ok"/"waiting". The old "waiting" non-answer is gone.
        if not chrome_running:
            status = "broken"
        elif not driver_connected:
            status = "degraded"
        elif self._last_successful_send_at is None and self._request_count == 0:
            status = "starting"
        else:
            status = "healthy"

        # An open breaker can only DOWNGRADE starting|healthy -> degraded. It
        # must never override "broken" (Chrome down is a harder failure than a
        # tripped circuit) and never force "broken" — auth_required is serious,
        # but "broken" invites a destructive supervisor restart, while
        # "degraded" correctly signals "up but refusing some/all traffic". A
        # disconnect-degraded stays degraded (not worse).
        if status in ("starting", "healthy") and self._breakers.first_open() is not None:
            status = "degraded"

        # Current-state summary, distinct from the historical/latching last_error.
        open_kinds = [k.value for k in BreakerKind if self._breakers.is_open(k)]

        return web.json_response(
            {
                "status": status,
                "chrome_running": chrome_running,
                "cdp_connected": driver_connected,
                "driver_connected": driver_connected,
                "requests_served": self._request_count,
                "active_requests": self._active_requests,
                "request_timeout_seconds": self._config.server.request_timeout,
                "agent_request_interval_seconds": self._agent_state.interval,
                "tool_calling": "text-bridge-v1",
                "image_inputs": True,
                "started_at": self._started_at,
                "last_successful_send_at": self._last_successful_send_at,
                "last_error": self._last_error,
                "open_breakers": open_kinds,
                "breakers": self._breakers.snapshot(),
            }
        )

    async def _handle_models(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err
        try:
            raw = await self._driver.get_models()
        except Exception:
            raw = []

        models = []
        for m in raw:
            slug = m.get("slug", "")
            models.append(
                {
                    "id": slug,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "chatgpt-web",
                }
            )

        if not models:
            for slug in ["auto", "gpt-5-5", "gpt-5-mini"]:
                models.append(
                    {
                        "id": slug,
                        "object": "model",
                        "created": 1700000000,
                        "owned_by": "chatgpt-web",
                    }
                )

        return web.json_response({"object": "list", "data": models})

    async def _handle_projects(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err
        try:
            projects = await self._driver.get_projects()
        except Exception as e:
            logger.error("Failed to get projects: %s", e)
            projects = []
        return web.json_response({"object": "list", "data": projects})

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """Cancel observation when the caller disconnects, even before headers.

        Agent frames stay buffered until validated, preserving genuine HTTP
        errors and preventing partial tool execution. No generation deadline
        is needed to release the browser lock when Continue cancels a request.
        The pending nonce remains recoverable; cancellation never resends.
        """
        task = asyncio.create_task(self._handle_chat_response(request))
        self._active_requests += 1
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=1.0)
                if done:
                    return task.result()
                transport = request.transport
                if transport is None or transport.is_closing():
                    raise asyncio.CancelledError("Chat client disconnected")
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            self._active_requests -= 1

    async def _handle_chat_response(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err

        self._request_count += 1

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
                status=400,
            )

        if not isinstance(body, dict):
            return self._error_response(ToolRequestError("Request body must be an object"))
        try:
            tool_bridge = ToolBridge.from_request(body)
        except ToolRequestError as exc:
            return self._error_response(exc)

        try:
            messages, user_images = normalize_images(body.get("messages", []))
        except (ValueError, OSError) as exc:
            return self._error_response(ToolRequestError(str(exc)))
        if user_images and tool_bridge is None:
            tool_bridge = ToolBridge([], choice="none")
        if not messages:
            return web.json_response(
                {"error": {"message": "No messages provided", "type": "invalid_request_error"}},
                status=400,
            )

        model = body.get("model", self._config.chatgpt.default_model)
        stream = body.get("stream", False)
        project_id = (
            body.get("project_id")
            or body.get("gizmo_id")
            or (body.get("metadata", {}) or {}).get("project_id")
            or self._config.chatgpt.default_project_id
        )
        conversation_id = body.get("conversation_id")

        # Build conversation text from all messages
        # Includes prior assistant context for stateless clients (OpenAI SDK)
        system_parts = []
        conversation_lines = []
        user_msg_count = 0
        MAX_HISTORY_TURNS = 10  # Cap to avoid textarea overflow

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") if isinstance(p, dict) else str(p) for p in content
                )
            else:
                content = str(content)

            if role == "system":
                system_parts.append(content)
            elif role == "user":
                conversation_lines.append(f"[User]\n{content}")
                user_msg_count += 1
            elif role == "assistant":
                conversation_lines.append(f"[Assistant]\n{content}")

        # Trim to last N turns if too many messages
        if len(conversation_lines) > MAX_HISTORY_TURNS * 2:
            conversation_lines = conversation_lines[-(MAX_HISTORY_TURNS * 2) :]

        # Verify at least one user message exists
        if user_msg_count == 0:
            return web.json_response(
                {"error": {"message": "No user message", "type": "invalid_request_error"}},
                status=400,
            )

        # Compose final text
        prefix = ""
        if system_parts:
            prefix = "[System Instructions]\n" + "\n".join(system_parts) + "\n\n"
        full_text = prefix + "\n".join(conversation_lines)
        # Generate the Agent prompt after matching its already-sent history.
        # A continuation sends only the new turns, not the whole repository again.
        request_key = digest({k: v for k, v in body.items() if k != "stream"})
        scope = digest(
            [
                model,
                project_id,
                conversation_id,
                body.get("tools"),
                body.get("tool_choice"),
                body.get("parallel_tool_calls"),
            ]
        )

        model_slug = MODEL_MAP.get(model, model)
        timeout = self._config.server.request_timeout

        logger.info(
            "Request #%d: model=%s->%s conv=%s project=%s stream=%s msg=%.60s",
            self._request_count,
            model,
            model_slug,
            conversation_id,
            project_id,
            stream,
            full_text,
        )

        # Serialize — cross-process lock so MCP + REST don't corrupt each other
        try:
            # Circuit-open fail-fast (Phase 4 PR2): refuse before touching Chrome
            # if a breaker is open. Placed inside the try so it flows through
            # the except below → _error_response + _last_error, consistent with
            # every other failure path. Checked before acquiring the lock so a
            # process that already knows it will refuse doesn't block on the
            # browser lock. If AUTH_EXPIRED is open, probes auth recovery first
            # (the user may have logged back in).
            await self._check_circuit_or_recover()

            # PR4/5: per-target lock in parallel mode (port-wide otherwise).
            # Resolver raises OwnedTabRequiredError (→ 503) if parallel mode
            # has no owned target rather than silently degrading to the port
            # lock (split-brain guard). When parallel mode is OFF, skip the
            # resolver entirely and use the cached port — preserves the exact
            # legacy path (the resolver would read driver.port, which is the
            # same value but needlessly couples the legacy path to the driver).
            if self._parallel_tabs:
                _port, _key = resolve_mutation_lock(self._driver, True)
            else:
                _port, _key = self._cdp_port, None
            report("Attente du navigateur disponible.")
            async with MutationLock(_port, _key):
                # Drift guard (parallel mode only): if the owned target changed
                # while we waited for the lock, the key we hold no longer names
                # the active tab. Fail retryably instead of mutating under a
                # stale key.
                if self._parallel_tabs:
                    _, _current_key = resolve_mutation_lock(self._driver, True)
                    if _current_key != _key:
                        raise OwnedTabRequiredError(
                            "owned target changed while waiting for mutation lock"
                        )
                # Second circuit-open check, now that we hold the lock. A
                # concurrent request may have tripped a breaker while we were
                # waiting. Without this, we'd drive Chrome despite the process
                # already knowing the circuit is open.
                await self._check_circuit_or_recover()

                cached = self._agent_state.replies.get(request_key) if tool_bridge else None
                if cached is not None:
                    return await self._render_agent_reply(
                        request, model_slug, cached[0], cached[1], stream
                    )
                reuse_id, offset = (
                    self._agent_state.match(messages, scope) if tool_bridge else (None, 0)
                )
                try:
                    image_paths = (
                        images_for_turn(messages, user_images, offset) if tool_bridge else []
                    )
                except (ValueError, OSError) as exc:
                    raise ToolRequestError(str(exc)) from exc
                if tool_bridge:
                    full_text = tool_bridge.prompt(messages[offset:], prior_messages=messages[:offset])
                    if image_paths:
                        full_text = (
                            f"This request includes {len(image_paths)} actual attached image(s). "
                            "Inspect their pixels when relevant. Registered image references and user-image markers "
                            "in the serialized history identify their source. Do not infer image contents from filenames.\n"
                            + full_text
                        )
                    if reuse_id:
                        full_text = (
                            "Continue in this same conversation. Earlier project context remains available. "
                            "The following serialized turns provide the authoritative call IDs and new results.\n"
                            + full_text
                        )
                    if request_key in self._agent_state.uncertain:
                        try:
                            recovered = await self._recover_agent_reply(
                                tool_bridge, full_text, request_key, reuse_id
                            )
                        except PendingFormatRepair as exc:
                            # Continue the already-completed chat. Never resend
                            # the original request or any tool result here.
                            tool_bridge.nonce = exc.nonce
                            self._driver._current_conv_id = exc.conversation
                            await self._agent_state.reserve()
                            return await self._agent_response(
                                request,
                                model_slug,
                                full_text,
                                timeout,
                                tool_bridge,
                                stream,
                                messages,
                                scope,
                                request_key,
                                repair_error=exc,
                            )
                        if recovered:
                            message, conv_id = recovered
                            self._remember_agent_reply(
                                request_key, messages, message, scope, conv_id
                            )
                            return await self._render_agent_reply(
                                request, model_slug, message, conv_id, stream
                            )
                self._agent_state.check(request_key)
                if isinstance(self._driver, CDPDriver):
                    await self._driver._dom.check_rate_limit()
                # Applies to Agent, title generation and apply calls alike.
                pacing_wait = max(0.0, self._agent_state.next_send - time.time())
                if pacing_wait >= 0.05:
                    report(f"Préparation de l'envoi ; délai restant {pacing_wait:.1f} s.")
                waited = await self._agent_state.reserve()
                if waited >= 0.05:
                    logger.info("Agent pacing waited %.3fs before browser send", waited)

                # Select model if specified (non-fatal on failure)
                if model_slug and model_slug != "auto":
                    selected = await self._driver.select_model(model_slug)
                    if not selected:
                        logger.warning(
                            "Could not select model '%s', proceeding with active model",
                            model_slug,
                        )

                # Decide: continue existing conversation or start fresh?
                if reuse_id:
                    if self._driver._current_conv_id != reuse_id:
                        await self._driver.navigate_conversation(reuse_id)
                    logger.info(
                        "Agent conversation reused: %s; incremental messages=%d",
                        reuse_id,
                        len(messages) - offset,
                    )
                elif conversation_id:
                    # Explicit conversation_id from client — navigate to it
                    await self._driver.navigate_conversation(conversation_id)
                else:
                    # No matching Agent history: keep unrelated tasks isolated.
                    await self._driver.navigate_new_chat(gizmo_id=project_id)
                    self._last_project_id = project_id

                if tool_bridge is not None:
                    return await self._agent_response(
                        request,
                        model_slug,
                        full_text,
                        timeout,
                        tool_bridge,
                        stream,
                        messages,
                        scope,
                        request_key,
                        image_paths=image_paths,
                    )
                self._agent_state.begin(request_key)
                self._agent_state.next_send = time.time() + self._agent_state.interval
                self._agent_state.save()
                previous_success = self._last_successful_send_at
                if stream:
                    result = await self._stream_response(request, model_slug, full_text, timeout)
                else:
                    result = await self._full_response(request, model_slug, full_text, timeout)
                if self._last_successful_send_at != previous_success:
                    self._agent_state.complete(request_key)
                return result

        except Exception as e:
            if isinstance(e, RateLimitError):
                if self._agent_state.cooldown_until <= time.time():
                    self._agent_state.penalize(e.retry_after)
                    try:
                        await self._driver.dismiss_rate_limit()
                    except Exception:
                        pass
                e = RateLimitError(
                    retry_after=max(1, int(self._agent_state.cooldown_until - time.time()) + 1)
                )
            logger.error("Chat error: %s", e, exc_info=True)
            self._last_error = f"{type(e).__name__}: {e}"
            return self._error_response(e)

    async def _check_circuit_or_recover(self) -> None:
        """Fail-fast if a breaker is open, with one exception: if AUTH_EXPIRED
        is the open breaker, probe auth recovery first (the user may have logged
        back in via the browser since the trip). If recovery succeeds the breaker
        is reset and the request proceeds; if it fails, or if a non-auth breaker
        is open, raise CircuitOpenError.

        Called at each fail-fast checkpoint (pre-lock, post-lock, streaming
        pre-prepare). Does NOT drive a chat send — recovery is a lightweight
        ``/api/auth/session`` token fetch via ``driver.recover_auth()``.
        """
        open_kind = self._breakers.first_open()
        if open_kind is None:
            return
        if open_kind is BreakerKind.AUTH_EXPIRED:
            if await self._driver.recover_auth():
                # Auth restored — re-check in case another breaker is also open.
                open_kind = self._breakers.first_open()
                if open_kind is None:
                    return
        raise CircuitOpenError(open_kind)

    # ── Error mapping ─────────────────────────────────────────

    def _error_response(self, exc: Exception) -> web.Response:
        """Map a driver exception to an OpenAI-shaped error response.

        - RateLimitError → HTTP 429 with the canonical OpenAI
          ``rate_limit_exceeded`` type/code and a ``Retry-After`` header, so any
          OpenAI-aware agent framework (SDK, LangChain, LlamaIndex) automatically
          backs off and retries with zero client integration.
        - AuthExpiredError → HTTP 401 ``invalid_api_key`` — the ChatGPT session
          expired; previously this surfaced as silent empty data or a generic
          timeout.
        - GenerationStuckError → HTTP 504 ``generation_stuck`` — the generation
          stalled (no DOM progress within the stall window); the phase is in the
          message for diagnosis.
        - Everything else stays a 500 ``server_error`` (a real failure, not
          retriable).
        """
        if isinstance(exc, ToolRequestError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_request_error",
                        "code": "invalid_tool_request",
                    }
                },
                status=400,
            )
        if isinstance(exc, ToolProtocolError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "server_error",
                        "code": "invalid_tool_response",
                    }
                },
                status=422,
                headers={"x-should-retry": "false"},
            )
        if isinstance(exc, ImageUploadError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_request_error",
                        "code": "image_upload_failed_before_send",
                    }
                },
                status=422,
                headers={"x-should-retry": "false"},
            )
        if isinstance(exc, (UncertainSendError, SendReadinessError, TimeoutError)):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_request_error",
                        "code": "send_outcome_uncertain",
                    }
                },
                status=422,
                headers={"x-should-retry": "false"},
            )
        if isinstance(exc, RateLimitError):
            retry_after = str(int(exc.retry_after))
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "rate_limit_exceeded",
                        "param": None,
                        "code": "rate_limit_exceeded",
                    }
                },
                status=429,
                headers={"Retry-After": retry_after, "x-should-retry": "false"},
            )
        if isinstance(exc, AuthExpiredError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_api_key",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
                status=401,
            )
        if isinstance(exc, GenerationStuckError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "server_error",
                        "param": None,
                        "code": "generation_stuck",
                    }
                },
                status=504,
                headers={"x-should-retry": "false"},
            )
        if isinstance(exc, LockAcquisitionError):
            return web.json_response(
                {
                    "error": {
                        "message": str(exc),
                        "type": "server_error",
                        "param": None,
                        "code": "lock_timeout",
                    }
                },
                status=503,
            )
        if isinstance(exc, CircuitOpenError):
            return web.json_response(
                {
                    "error": {
                        "message": (
                            f"Circuit open for {exc.kind.value} — cooling down. Retry later."
                        ),
                        "type": "server_error",
                        "param": None,
                        "code": "circuit_open",
                    }
                },
                status=503,
            )
        if isinstance(exc, OwnedTabRequiredError):
            return web.json_response(
                {
                    "error": {
                        "message": f"{exc}. Retry later.",
                        "type": "server_error",
                        "param": None,
                        "code": "owned_tab_required",
                    }
                },
                status=503,
            )
        return web.json_response(
            {"error": {"message": str(exc), "type": "server_error"}},
            status=500,
        )

    # ── Response formatters ───────────────────────────────────

    async def _recover_agent_reply(self, bridge, expected_prompt, key, expected_conversation):
        """Recover only an exact, completed pending exchange; never send here."""
        from .turn_anchor import normalize_text

        original_nonce = bridge.nonce
        try:
            info = self._agent_state.pending_frames.get(key)
            expected_conversation = (info or {}).get("conversation") or expected_conversation
            snapshot = await self._driver.read_agent_exchange()
            if (
                expected_conversation
                and snapshot.get("conversation") != expected_conversation
                and not snapshot.get("generating")
            ):
                # A service restart can create an empty owned tab. Reopen only
                # the exact chat recorded for this pending request, once.
                self._agent_state.check()
                await self._driver.navigate_conversation(expected_conversation)
                snapshot = await self._driver.read_agent_exchange()
            if (
                not snapshot.get("paired")
                or snapshot.get("generating")
                or not snapshot.get("conversation")
            ):
                return None
            if info:
                nonce = info["nonce"]
                expected_hash = info["prompt_hash"]
                expected_conversation = info.get("conversation") or expected_conversation
            else:
                # Backward-compatible recovery for a pending request recorded
                # before nonce/hash metadata existed. Require the WHOLE prompt.
                found = re.search(
                    r'<web2api_response nonce="([a-f0-9]{32})">', snapshot.get("user", "")
                )
                if not found:
                    return None
                nonce = found.group(1)
                expected_hash = digest(
                    normalize_text(expected_prompt.replace(original_nonce, nonce))
                )
            if expected_conversation and snapshot["conversation"] != expected_conversation:
                return None
            if digest(normalize_text(snapshot.get("user", ""))) != expected_hash:
                return None
            bridge.nonce = nonce
            try:
                if snapshot.get("unsafe_markup") or not snapshot.get("literal", True):
                    raise ToolProtocolError(
                        "The completed answer must use one literal fenced JSON response"
                    )
                message = bridge.parse(bridge.validated_frame(snapshot.get("assistant", "")))
            except ToolProtocolError as exc:
                if not snapshot.get("completed"):
                    return None
                if (info or {}).get("repair_attempted"):
                    if snapshot.get("literal") and not snapshot.get("unsafe_markup"):
                        try:
                            message = bridge.parse_verified_final(snapshot.get("assistant", ""))
                        except ToolProtocolError:
                            pass
                        else:
                            logger.info("Recovered final text from the exact completed repair; no tool call accepted")
                            return message, snapshot["conversation"]
                    if bridge.choice in ("auto", "none") and not snapshot.get("literal"):
                        from .agent_final import final_text_message

                        read_final = getattr(self._driver, "read_agent_final_text", None)
                        source = await read_final(snapshot) if read_final else None
                        if source is not None:
                            message = final_text_message(source, bridge.choice)
                            logger.info(
                                "Recovered verified final prose after format repair; no tool call accepted"
                            )
                            return message, snapshot["conversation"]
                    raise ToolProtocolError(
                        "ChatGPT's answer is still invalid after one format repair; "
                        "no tool from this rejected response was executed"
                    ) from exc
                raise PendingFormatRepair(exc, nonce, snapshot["conversation"]) from exc
            logger.info(
                "Recovered completed Agent response from existing conversation without sending: %s",
                snapshot["conversation"],
            )
            return message, snapshot["conversation"]
        except ToolProtocolError:
            raise
        except Exception as exc:
            logger.warning(
                "Pending Agent response not recoverable (%s); resubmission remains blocked",
                type(exc).__name__,
            )
            return None
        finally:
            bridge.nonce = original_nonce

    def _remember_agent_reply(self, key, messages, message, scope, conv_id):
        self._agent_state.remember(messages, message, scope, conv_id)
        self._agent_state.complete(key)
        self._agent_state.replies[key] = (message, conv_id)
        if len(self._agent_state.replies) > 64:
            del self._agent_state.replies[next(iter(self._agent_state.replies))]

    async def _agent_response(
        self,
        request: web.Request,
        model: str,
        text: str,
        timeout: float,
        bridge: ToolBridge,
        stream: bool,
        messages: list,
        scope: str,
        request_key: str,
        image_paths: list[str] | None = None,
        repair_error: ToolProtocolError | None = None,
    ) -> web.Response:
        """Return validated calls/results with OpenAI-compatible SSE or JSON.

        Generation and one optional format repair finish before headers are
        committed, so protocol errors are genuine HTTP errors and no partial
        function can execute. No filesystem or shell tool is executed here.
        """
        from .completion_detector import DetectorBudgets

        budgets = DetectorBudgets.from_config(self._config.chatgpt, model)

        async def collect(prompt: str, attachments=None, *, repair=False) -> str:
            async def send() -> str:
                report("Correction du format de la réponse." if repair else "Préparation du message dans ChatGPT.")
                self._agent_state.begin(
                    request_key,
                    nonce=bridge.nonce,
                    prompt=prompt,
                    conversation=self._driver._current_conv_id,
                    repair_attempted=repair,
                )
                self._agent_state.next_send = time.time() + self._agent_state.interval
                self._agent_state.save()
                parts = []
                image_kwargs = {"image_paths": attachments} if attachments else {}
                async for chunk in self._driver.send_and_stream(
                    prompt,
                    timeout=timeout,
                    budgets=budgets,
                    model=model,
                    response_validator=bridge.validated_frame,
                    response_marker=bridge.opening,
                    **image_kwargs,
                ):
                    parts.append(chunk.delta)
                return "".join(parts)

            try:
                return await send()
            except ToolProtocolError:
                if not repair:
                    raise
                recovered = await self._recover_agent_reply(
                    bridge, prompt, request_key, self._driver._current_conv_id
                )
                if not recovered or recovered[0].get("tool_calls"):
                    raise
                # Reframe text only, after the same full-match recovery checks.
                # Never rewrite or reissue an action from an invalid response.
                return bridge.opening + json.dumps({
                    "content": recovered[0]["content"], "tool_calls": []
                }, ensure_ascii=False) + "</web2api_response>"

        self._agent_state.begin(request_key)
        async with asyncio.timeout(timeout if timeout > 0 else None):
            try:
                answer = await collect(
                    bridge.repair_prompt(repair_error) if repair_error else text,
                    None if repair_error else image_paths,
                    repair=repair_error is not None,
                )
                message = bridge.parse(answer)
            except ImageUploadError:
                # Unlike a lost response, a failed upload never reached the
                # send button. Let the user retry after correcting the draft.
                self._agent_state.complete(request_key)
                raise
            except ToolProtocolError as exc:
                if repair_error:
                    raise
                logger.warning("Agent response requires format repair: %s", exc)
                await self._agent_state.reserve()
                answer = await collect(bridge.repair_prompt(exc), repair=True)
                message = bridge.parse(answer)

        report("Réponse validée ; transmission à Codex.")
        conv_id = self._driver._current_conv_id or ""
        self._remember_agent_reply(request_key, messages, message, scope, conv_id)
        return await self._render_agent_reply(request, model, message, conv_id, stream)

    async def _render_agent_reply(self, request, model, message, conv_id, stream):
        calls = message.get("tool_calls", [])
        finish = "tool_calls" if calls else "stop"
        self._last_conv_id = conv_id
        self._last_successful_send_at = time.time()
        self._last_error = None
        logger.info(
            "Agent response: finish=%s tools=%s", finish, [c["function"]["name"] for c in calls]
        )
        common = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:29]}",
            "created": int(time.time()),
            "model": model,
        }
        if not stream:
            return web.json_response(
                {
                    **common,
                    "object": "chat.completion",
                    "conversation_id": conv_id,
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
        )
        await response.prepare(request)
        # Continue 2.0.0's fromChatCompletionChunk chooses content OR tools
        # with if/else-if. Combining both silently drops the tool call.
        # Separate deltas preserve commentary and let the Agent loop continue.
        deltas = []
        if message["content"] is not None:
            deltas.append({"role": "assistant", "content": message["content"]})
        if calls:
            deltas.append(
                {
                    "role": "assistant",
                    "tool_calls": [{"index": index, **call} for index, call in enumerate(calls)],
                }
            )
        for delta in deltas:
            await self._send_sse(
                response,
                {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
            )
        await self._send_sse(
            response,
            {
                **common,
                "object": "chat.completion.chunk",
                "conversation_id": conv_id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        )
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    async def _full_response(
        self, request: web.Request, model: str, text: str, timeout: float
    ) -> web.Response:
        """Non-streaming: collect all chunks, return one JSON.

        The send is wrapped in ``retry_on_rate_limit`` so a transient
        ChatGPT "Too many requests" pop-up is dismissed and retried
        transparently — the client only sees it (as a 429) if the limit
        persists across all retries.
        """
        # P1: resolve model-aware detector budgets from config.
        from .completion_detector import DetectorBudgets

        budgets = DetectorBudgets.from_config(self._config.chatgpt, model)

        async def _send_and_collect() -> str:
            collected = ""
            async for chunk in self._driver.send_and_stream(
                text,
                timeout=timeout,
                budgets=budgets,
                model=model,
            ):
                collected += chunk.delta
            return collected

        full_text = await _send_and_collect()

        conv_id = self._driver._current_conv_id or ""
        self._last_conv_id = conv_id
        self._last_successful_send_at = time.time()

        return web.json_response(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex[:29]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "conversation_id": conv_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": full_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    async def _stream_response(
        self, request: web.Request, model: str, text: str, timeout: float
    ) -> web.Response:
        """Streaming: SSE chunks as they arrive.

        Rate-limit handling for streaming is split, because once
        ``resp.prepare()`` commits the HTTP 200 status we can no longer send a
        429:

        - **Pre-flight** (before prepare): a single DOM scan. If throttled, we
          retry transparently (dismiss + backoff). If it persists, we return a
          proper 429 here while the status is still changeable.
        - **Mid-stream** (after prepare): a throttle is rare here (pre-flight
          cleared it), but if one occurs it falls back to the inline
          ``[Error: ...]`` SSE chunk — documented as a known limitation.
        """
        # P1: resolve model-aware detector budgets from config.
        from .completion_detector import DetectorBudgets

        budgets = DetectorBudgets.from_config(self._config.chatgpt, model)

        async def _preflight() -> None:
            """Raise RateLimitError if the pop-up is present right now."""
            try:
                scan = await self._driver._js_strict(
                    "(function(){var t=Array.from(document.querySelectorAll('[role=dialog],[role=alert]')).map(e=>e.textContent||'').join('\\n');"
                    "return JSON.stringify({text:t.slice(0,4000)});})()",
                    timeout=10,
                )
            except Exception:
                # CDP/JS error during scan — assume no rate limit (proceed).
                return
            try:
                body = json.loads(scan).get("text", "") if scan else ""
            except (json.JSONDecodeError, TypeError):
                body = ""
            if is_rate_limited_text(body):
                raise RateLimitError.from_text(body)

        # Transparent pre-flight retry — dismisses the pop-up and retries so a
        # transient limit never reaches the client as an error.
        try:
            await _preflight()
        except RateLimitError:
            # Persistent at pre-flight: still pre-prepare, so send a clean 429.
            raise

        # Circuit-open fail-fast (Phase 4 PR2): final check, after rate-limit
        # preflight but still before prepare() commits HTTP 200. A breaker may
        # have opened during model selection/navigation. After prepare() no
        # status change is possible, so this must stay pre-prepare.
        await self._check_circuit_or_recover()

        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        cid = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        created = int(time.time())

        # Role chunk
        await self._send_sse(
            resp,
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            },
        )

        try:
            async for chunk in self._driver.send_and_stream(
                text,
                timeout=timeout,
                budgets=budgets,
                model=model,
            ):
                if chunk.delta:
                    await self._send_sse(
                        resp,
                        {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk.delta},
                                    "finish_reason": None,
                                }
                            ],
                        },
                    )
                if chunk.finish_reason:
                    conv_id = self._driver._current_conv_id or ""
                    self._last_conv_id = conv_id
                    if chunk.finish_reason == "stop":
                        self._last_successful_send_at = time.time()
                    await self._send_sse(
                        resp,
                        {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "conversation_id": conv_id,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": chunk.finish_reason}
                            ],
                        },
                    )
        except RateLimitError as e:
            self._agent_state.penalize(e.retry_after)
            # Mid-stream throttle (rare after pre-flight). Status is locked at
            # 200, so we can't upgrade to 429; surface as an inline error chunk
            # with a recognizable marker so clients can detect it.
            logger.warning("Mid-stream rate limit: %s", e)
            await self._send_sse(
                resp,
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": f"\n\n[Error: rate_limit_exceeded — retry in {e.retry_after}s]"
                            },
                            "finish_reason": "error",
                        }
                    ],
                },
            )
        except AuthExpiredError:
            # Session expired mid-stream (status locked at 200). Surface with a
            # recognizable marker so clients can prompt re-login.
            logger.warning("Mid-stream auth expiry")
            await self._send_sse(
                resp,
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "\n\n[Error: auth_expired — re-login required]"},
                            "finish_reason": "error",
                        }
                    ],
                },
            )
        except GenerationStuckError as e:
            # Generation stalled mid-stream (status locked at 200). Surface the
            # phase + duration so the client can decide whether to retry.
            logger.warning("Mid-stream generation stuck: %s", e)
            await self._send_sse(
                resp,
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": f"\n\n[Error: generation_stuck — stalled in {e.phase} for {e.stalled_for_s:.0f}s]"
                            },
                            "finish_reason": "error",
                        }
                    ],
                },
            )
        except Exception as e:
            logger.error("Stream error: %s", e)
            await self._send_sse(
                resp,
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"\n\n[Error: {e}]"},
                            "finish_reason": "error",
                        }
                    ],
                },
            )

        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    @staticmethod
    async def _send_sse(resp: web.StreamResponse, data: dict) -> None:
        await resp.write(f"data: {json.dumps(data)}\n\n".encode())
