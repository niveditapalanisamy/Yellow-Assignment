
"""Groq REST tool-calling adapter with bounded context and token diagnostics."""
import json
import os
import time
from datetime import datetime, timezone

from . import config
from .http import APIError, JsonHTTP


def _env_int(name, default, minimum):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _log(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] [GROQ] {message}", flush=True)


def _compact_text(value, limit):
    """Bound a tool response while retaining its beginning and ending."""
    if not isinstance(value, str) or len(value) <= limit:
        return value

    marker = "\n...[TRUNCATED FOR CONTEXT LIMIT]...\n"
    remaining = max(0, limit - len(marker))
    head = int(remaining * 0.75)
    tail = remaining - head
    return value[:head] + marker + (value[-tail:] if tail else "")


def compact_contents(contents):
    """
    Preserve the initial task and recent tool interactions.

    Older interactions are removed as complete assistant/tool-response
    pairs so that orphaned tool-call IDs are not sent to Groq.
    """
    keep_rounds = _env_int("GROQ_KEEP_RECENT_ROUNDS", 3, 1)
    max_tool_chars = _env_int("GROQ_MAX_TOOL_RESULT_CHARS", 5000, 500)
    max_initial_chars = _env_int("GROQ_MAX_INITIAL_CONTEXT_CHARS", 12000, 2000)

    if not contents:
        return []

    # The first user message contains the target and manifest policy.
    initial = dict(contents[0])
    initial_parts = []
    for part in initial.get("parts", []):
        if "text" in part:
            initial_parts.append({
                **part,
                "text": _compact_text(part["text"], max_initial_chars),
            })
        else:
            initial_parts.append(part)
    initial["parts"] = initial_parts

    # Treat each assistant tool call and its following tool response as a pair.
    rounds = []
    pending = []

    for item in contents[1:]:
        pending.append(item)
        if item.get("role") == "user":
            rounds.append(pending)
            pending = []

    # Keep a trailing incomplete group only if present.
    if pending:
        rounds.append(pending)

    selected = rounds[-keep_rounds:]
    compacted = [initial]

    for group in selected:
        for item in group:
            copied = dict(item)
            new_parts = []

            for part in copied.get("parts", []):
                if "functionResponse" in part:
                    response = dict(part["functionResponse"])
                    raw = response.get("response", {})
                    serialized = json.dumps(raw, ensure_ascii=False)
                    bounded = _compact_text(serialized, max_tool_chars)
                    response["response"] = bounded
                    new_parts.append({"functionResponse": response})
                else:
                    new_parts.append(part)

            copied["parts"] = new_parts
            compacted.append(copied)

    return compacted


def messages_for(system, contents):
    """Convert controller messages into OpenAI-compatible chat messages."""
    contents = compact_contents(contents)
    messages = [{"role": "system", "content": system}]

    for content in contents:
        parts = content.get("parts", [])

        if content.get("role") == "model":
            calls = []

            for part in parts:
                if "functionCall" not in part:
                    continue

                function_call = part["functionCall"]
                calls.append({
                    "id": function_call["id"],
                    "type": "function",
                    "function": {
                        "name": function_call["name"],
                        "arguments": json.dumps(
                            function_call.get("args", {}),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                })

            text_parts = [
                part["text"] for part in parts if "text" in part
            ]

            # Do not send an assistant message with neither content nor calls.
            if calls or text_parts:
                assistant_message = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) or None,
                }
                if calls:
                    assistant_message["tool_calls"] = calls
                messages.append(assistant_message)

        else:
            texts = [part["text"] for part in parts if "text" in part]
            if texts:
                messages.append({
                    "role": "user",
                    "content": "\n".join(texts),
                })

            for part in parts:
                if "functionResponse" not in part:
                    continue

                response = part["functionResponse"]
                response_id = response.get("id")

                # A tool response must have its matching tool-call ID.
                if not response_id:
                    continue

                value = response.get("response", {})
                if not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False)

                messages.append({
                    "role": "tool",
                    "tool_call_id": response_id,
                    "content": value,
                })

    return messages


def json_schema(value):
    """Normalize JSON-schema type names for the API."""
    if isinstance(value, list):
        return [json_schema(item) for item in value]

    if isinstance(value, dict):
        return {
            key: (
                item.lower()
                if key == "type" and isinstance(item, str)
                else json_schema(item)
            )
            for key, item in value.items()
        }

    return value


class GroqModel:
    def __init__(self):
        if not config.GROQ_API_KEY:
            raise APIError("Missing GROQ_API_KEY")

        self.name = config.GROQ_MODEL
        self.min_interval = max(
            0.0,
            float(os.getenv("GROQ_MIN_INTERVAL_SECONDS", "60")),
        )

        self.last_call = 0.0

        request_timeout = _env_int(
            "GROQ_REQUEST_TIMEOUT_SECONDS", 90, 5
        )
        self.max_completion_tokens = _env_int(
            "GROQ_MAX_COMPLETION_TOKENS", 512, 128
        )

        self.http = JsonHTTP(
            "https://api.groq.com/openai/v1",
            {
                "Authorization": "Bearer " + config.GROQ_API_KEY,
                "User-Agent": "jira-release-agent/1.0",
            },
            timeout=request_timeout,
        )

        _log(
            f"Initialized: model={self.name}, "
            f"timeout={request_timeout}s, "
            f"minimum_interval={self.min_interval}s, "
            f"max_completion_tokens={self.max_completion_tokens}, "
            f"keep_recent_rounds={_env_int('GROQ_KEEP_RECENT_ROUNDS', 3, 1)}, "
            f"max_tool_chars={_env_int('GROQ_MAX_TOOL_RESULT_CHARS', 5000, 500)}"
        )

    def invoke(self, system, contents, declarations):
        """Send a bounded tool-calling request."""
        delay = max(
            0.0,
            self.last_call + self.min_interval - time.monotonic(),
        )

        if self.http.deadline and time.monotonic() + delay >= self.http.deadline:
            raise APIError("Model pacing would exceed execution deadline")

        if delay:
            _log(f"Rate pacing: waiting {delay:.1f}s")
            time.sleep(delay)

        messages = messages_for(system, contents)

        tools = [
            {
                "type": "function",
                "function": json_schema(declaration),
            }
            for declaration in declarations
        ]

        payload = {
            "model": self.name,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "temperature": 0,
            "max_completion_tokens": self.max_completion_tokens,
        }

        serialized_messages = json.dumps(
            messages, ensure_ascii=False, separators=(",", ":")
        )
        serialized_payload = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )

        message_bytes = len(serialized_messages.encode("utf-8"))
        payload_bytes = len(serialized_payload.encode("utf-8"))

        # Rough diagnostic only; actual tokenization varies by model.
        estimated_input_tokens = max(1, message_bytes // 4)

        _log(
            f"Request: messages={len(messages)}, tools={len(tools)}, "
            f"message_bytes={message_bytes}, payload_bytes={payload_bytes}, "
            f"estimated_input_tokens~{estimated_input_tokens}, "
            f"max_output_tokens={self.max_completion_tokens}"
        )

        request_started = time.monotonic()
        self.last_call = request_started

        try:
            result = self.http.request(
                "POST",
                "/chat/completions",
                json_body=payload,
                retry=True,
            )
        except Exception as exc:
            elapsed = time.monotonic() - request_started
            _log(
                f"Request failed after {elapsed:.1f}s: "
                f"{type(exc).__name__}: {exc}"
            )
            raise

        elapsed = time.monotonic() - request_started
        choices = result.get("choices", []) if isinstance(result, dict) else []

        if not choices:
            raise APIError("Groq returned an empty choices array")

        choice = choices[0]
        message = choice.get("message", {})
        calls = message.get("tool_calls", []) or []
        usage = result.get("usage", {}) or {}
        finish_reason = choice.get("finish_reason")

        _log(
            f"Response: elapsed={elapsed:.1f}s, "
            f"finish_reason={finish_reason}, tool_calls={len(calls)}, "
            f"prompt_tokens={usage.get('prompt_tokens', 'n/a')}, "
            f"completion_tokens={usage.get('completion_tokens', 'n/a')}, "
            f"total_tokens={usage.get('total_tokens', 'n/a')}"
        )

        if finish_reason != "tool_calls" or not calls:
            preview = str(message.get("content") or "").replace("\n", " ")[:200]
            if preview:
                _log(f"Model text preview: {preview}")

            raise APIError(
                "Groq returned no usable tool calls "
                f"(finish_reason={finish_reason})"
            )

        parts = []

        if message.get("content"):
            parts.append({"text": message["content"]})

        try:
            for tool_call in calls:
                action = tool_call["function"]
                arguments = json.loads(action["arguments"])

                if (
                    not isinstance(arguments, dict)
                    or not tool_call.get("id")
                    or not action.get("name")
                ):
                    raise ValueError("Invalid tool call fields")

                parts.append({
                    "functionCall": {
                        "id": tool_call["id"],
                        "name": action["name"],
                        "args": arguments,
                    }
                })

        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise APIError("Groq returned an invalid tool call") from None

        return {"role": "model", "parts": parts}, usage
