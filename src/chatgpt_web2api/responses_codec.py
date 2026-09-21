"""Lossless client-tool envelope translation for the native Responses route.

Client tool execution stays in Codex. Provider-hosted web search declarations
are explicitly described as unavailable; they must not block local tools.
Unsupported modalities and unknown tools fail before sending.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from .tool_bridge import ToolRequestError


def alias(name, namespace=None):
    if not isinstance(name, str) or not name:
        raise ToolRequestError("A client tool requires a name")
    key = f"{namespace}__{name}" if namespace else name
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
        return key
    return "tool_" + hashlib.sha256(key.encode()).hexdigest()[:32]


def content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ToolRequestError("Responses content must be text or a content array")
    result = []
    for part in value:
        if not isinstance(part, dict):
            raise ToolRequestError("Invalid Responses content part")
        kind = part.get("type")
        if kind in {"input_text", "output_text", "text"} and isinstance(part.get("text"), str):
            result.append({"type": "text", "text": part["text"]})
        elif kind == "refusal" and isinstance(part.get("refusal"), str):
            result.append({"type": "text", "text": part["refusal"]})
        elif kind == "input_image" and isinstance(part.get("image_url"), str):
            result.append({"type": "image_url", "image_url": {
                "url": part["image_url"], "detail": part.get("detail", "auto"),
            }})
        else:
            raise ToolRequestError(f"Unsupported Responses content type: {kind}")
    # Match Chat Completions' canonical text history across native tool turns.
    if all(p["type"] == "text" for p in result):
        return "\n".join(p["text"] for p in result)
    return result


class ResponsesCodec:
    def __init__(self, body):
        if not isinstance(body, dict) or body.get("model", "auto") != "auto":
            raise ToolRequestError("This Responses route requires an object and model=auto")
        if body.get("previous_response_id"):
            raise ToolRequestError("Send the complete input history; previous_response_id is not supported")
        if body.get("background"):
            raise ToolRequestError("Background Responses are not supported")
        self.native = {}
        self.unavailable_hosted = []
        tools = []

        def add(tool, namespace=None):
            if not isinstance(tool, dict):
                raise ToolRequestError("Invalid Responses tool")
            if tool.get("type") == "namespace":
                if namespace or not isinstance(tool.get("tools"), list):
                    raise ToolRequestError("Invalid tool namespace")
                for child in tool["tools"]:
                    add(child, tool.get("name"))
                return
            kind = tool.get("type")
            if kind in {"web_search", "web_search_preview"} and namespace is None:
                # Codex declares its provider-hosted search even for local tasks.
                # This browser bridge cannot execute that provider API. Keep the
                # limitation explicit without disabling the client's real tools.
                self.unavailable_hosted.append(kind)
                return
            if kind not in {"function", "custom"}:
                raise ToolRequestError(f"Unsupported hosted tool: {kind}; use a client callable tool")
            name = alias(tool.get("name"), namespace)
            if name in self.native:
                raise ToolRequestError("Duplicate Responses tool")
            self.native[name] = {"name": tool["name"], "type": kind, "namespace": namespace}
            description = tool.get("description", "")
            if namespace:
                description = f"Client tool {namespace}.{tool['name']}. " + description
            if kind == "custom":
                description += "\nNative freeform input; return its exact source in arguments.input."
                if tool.get("format"):
                    description += "\nInput format: " + json.dumps(tool["format"], ensure_ascii=False)
                schema = {"type": "object", "properties": {"input": {"type": "string"}},
                          "required": ["input"], "additionalProperties": False}
            else:
                schema = tool.get("parameters", {"type": "object", "properties": {}})
            tools.append({"type": "function", "function": {
                "name": name, "description": description, "parameters": schema,
            }})

        if not isinstance(body.get("tools", []), list):
            raise ToolRequestError("tools must be an array")
        for tool in body.get("tools", []):
            add(tool)
        messages = []
        instructions = body.get("instructions")
        if instructions is not None:
            if not isinstance(instructions, str):
                raise ToolRequestError("instructions must be text")
            if instructions:
                messages.append({"role": "system", "content": instructions})
        if self.unavailable_hosted:
            messages.append({"role": "developer", "content": (
                "Transport capability notice: provider-hosted "
                + ", ".join(sorted(set(self.unavailable_hosted)))
                + " cannot be executed by this bridge. Client tools listed below remain available. "
                "For web access, discover a client-provided browser/search tool if available. "
                "Do not infer that local tools or Computer Use are unavailable from this hosted-search limitation."
            )})
        items = body.get("input", [])
        if isinstance(items, str):
            items = [{"role": "user", "content": items}]
        if not isinstance(items, list):
            raise ToolRequestError("input must be text or an array")
        for item in items:
            if not isinstance(item, dict):
                raise ToolRequestError("Invalid input item")
            kind = item.get("type", "message")
            if kind == "reasoning":
                # Public bridge status and opaque provider reasoning are not
                # instructions or function results. Neither is replayed as chat.
                continue
            if kind == "message":
                role = item.get("role")
                if role not in {"user", "assistant", "developer", "system"}:
                    raise ToolRequestError("Invalid message role")
                messages.append({"role": role, "content": content(item.get("content", ""))})
            elif kind in {"function_call", "custom_tool_call"}:
                name = alias(item.get("name"), item.get("namespace"))
                if not isinstance(item.get("call_id"), str) or not item["call_id"]:
                    raise ToolRequestError("Tool call requires call_id")
                arguments = item.get("arguments", "{}")
                if kind == "custom_tool_call":
                    if not isinstance(item.get("input"), str):
                        raise ToolRequestError("Custom tool input must be text")
                    arguments = json.dumps({"input": item["input"]}, ensure_ascii=False)
                if not isinstance(arguments, str):
                    raise ToolRequestError("Tool arguments must be JSON text")
                # Native Responses represents commentary and its calls as
                # separate items; our history matcher uses one assistant turn.
                if not messages or messages[-1]["role"] != "assistant":
                    messages.append({"role": "assistant", "content": None})
                messages[-1].setdefault("tool_calls", []).append({
                    "id": item["call_id"], "type": "function",
                    "function": {"name": name, "arguments": arguments},
                })
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                messages.append({"role": "tool", "tool_call_id": item.get("call_id"),
                                 "content": content(item.get("output", ""))})
            else:
                raise ToolRequestError(f"Unsupported Responses input item: {kind}")
        choice = body.get("tool_choice", "auto")
        if isinstance(choice, dict):
            if choice.get("type") not in {"function", "custom"}:
                raise ToolRequestError("Unsupported Responses tool_choice")
            choice = {"type": "function", "function": {"name": alias(choice.get("name"), choice.get("namespace"))}}
        self.chat = {"model": "auto", "stream": False, "messages": messages,
                     "tools": tools, "tool_choice": choice,
                     "parallel_tool_calls": body.get("parallel_tool_calls", True)}

    def output(self, message):
        items = []
        calls = message.get("tool_calls", [])
        if message.get("content"):
            items.append({"type": "message", "id": "msg_" + uuid.uuid4().hex,
                          "role": "assistant", "status": "completed",
                          "phase": "commentary" if calls else "final_answer",
                          "content": [{"type": "output_text", "text": message["content"], "annotations": []}]})
        for call in calls:
            spec = self.native[call["function"]["name"]]
            item = {"type": "custom_tool_call" if spec["type"] == "custom" else "function_call",
                    "id": ("ctc_" if spec["type"] == "custom" else "fc_") + uuid.uuid4().hex,
                    "status": "completed",
                    "call_id": call["id"], "name": spec["name"]}
            if spec["namespace"]:
                item["namespace"] = spec["namespace"]
            if spec["type"] == "custom":
                item["input"] = json.loads(call["function"]["arguments"])["input"]
            else:
                item["arguments"] = call["function"]["arguments"]
            items.append(item)
        return items
