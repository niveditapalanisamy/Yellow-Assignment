"""OpenAI-compatible (Groq / Ollama) tool-calling adapter for the controller's action envelopes.

Evidence is passed through unchanged: no truncation or dropped history, because
decisions must cite exact comment text. Hard budgets live in the controller.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

from . import config
from .http import APIError, JsonHTTP


def _log(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f'[{timestamp}] [GROQ] {message}', flush=True)


def messages_for(system, contents):
    messages = [{'role': 'system', 'content': system}]
    for content in contents:
        parts = content.get('parts', [])
        if content['role'] == 'model':
            calls = [{'id': p['functionCall']['id'], 'type': 'function', 'function': {
                'name': p['functionCall']['name'],
                'arguments': json.dumps(p['functionCall']['args'], ensure_ascii=False)}}
                for p in parts if 'functionCall' in p]
            message = {'role': 'assistant',
                'content': '\n'.join(p['text'] for p in parts if 'text' in p) or None}
            if calls:
                message['tool_calls'] = calls
            messages.append(message)
        else:
            texts = [p['text'] for p in parts if 'text' in p]
            if texts:
                messages.append({'role': 'user', 'content': '\n'.join(texts)})
            for part in parts:
                if 'functionResponse' in part:
                    response = part['functionResponse']
                    messages.append({'role': 'tool', 'tool_call_id': response['id'],
                        'content': json.dumps(response['response'], ensure_ascii=False)})
    return messages


def json_schema(value):
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if isinstance(value, dict):
        return {key: item.lower() if key == 'type' and isinstance(item, str)
                else json_schema(item) for key, item in value.items()}
    return value


def _setting(name, default):
    """LLM_<NAME>, falling back to the original GROQ_<NAME> variable."""
    return os.getenv('LLM_' + name) or os.getenv('GROQ_' + name) or str(default)


def _int_setting(name, default, minimum):
    try:
        return max(minimum, int(_setting(name, default)))
    except ValueError:
        return default


class ChatModel:
    """OpenAI-compatible tool-calling client for Groq or Ollama (Cloud or local)."""

    def __init__(self, provider=None):
        settings = config.provider_settings(provider)
        key = settings['api_key']
        if settings['key_required'] and (not key or key.startswith('paste-')):
            raise APIError('Missing ' + settings['key_name'])
        self.provider = settings['provider']
        self.name = settings['model']
        try:
            self.min_interval = max(0.0, float(_setting('MIN_INTERVAL_SECONDS', 5)))
        except ValueError:
            self.min_interval = 5.0
        # Reasoning models spend part of this budget thinking before the tool call.
        self.max_completion_tokens = _int_setting('MAX_COMPLETION_TOKENS', 4096, 256)
        timeout = _int_setting('REQUEST_TIMEOUT_SECONDS', 90 if self.provider == 'groq' else 300, 5)
        self.last_call = 0.0
        headers = {'User-Agent': 'jira-release-agent/1.0'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        self.http = JsonHTTP(settings['base_url'], headers, timeout=timeout)

    MALFORMED_TOOL_CALL = ('tool call', 'tool_use_failed', 'failed to call a function')
    MALFORMED_TOOL_CALL_RETRIES = 2

    MIN_COMPLETION_BUDGET = 768

    def _fitting_completion_budget(self, exc, current):
        """For a 413 that states 'Limit N, Requested M', a completion budget that fits, else None."""
        if exc.status != 413:
            return None
        match = re.search(r'Limit (\d+), Requested (\d+)', str(exc))
        if not match:
            return None
        limit, requested = int(match.group(1)), int(match.group(2))
        budget = current - (requested - limit) - 64
        return budget if self.MIN_COMPLETION_BUDGET <= budget < current else None

    def invoke(self, system, contents, declarations):
        delay = max(0.0, self.last_call + self.min_interval - time.monotonic())
        if self.http.deadline and time.monotonic() + delay >= self.http.deadline:
            raise APIError('Model pacing would exceed execution deadline')
        if delay:
            time.sleep(delay)
        messages = messages_for(system, contents)
        self.last_call = time.monotonic()
        payload = {'model': self.name, 'messages': messages,
            'tools': [{'type': 'function', 'function': json_schema(d)} for d in declarations],
            'tool_choice': 'required', 'temperature': 0}
        # Ollama's OpenAI-compatible API reads max_tokens; Groq uses max_completion_tokens.
        payload['max_tokens' if self.provider == 'ollama' else 'max_completion_tokens'] = self.max_completion_tokens
        for attempt in range(self.MALFORMED_TOOL_CALL_RETRIES + 1):
            try:
                result = self.http.request('POST', '/chat/completions', json_body=payload, retry=True)
                break
            except APIError as exc:
                limit_key = 'max_tokens' if self.provider == 'ollama' else 'max_completion_tokens'
                smaller = self._fitting_completion_budget(exc, payload[limit_key])
                if smaller and attempt < self.MALFORMED_TOOL_CALL_RETRIES:
                    # Groq counts the reserved completion budget toward the per-request
                    # token limit; reserve less rather than abandoning the investigation.
                    _log(f'Request over provider token limit; completion budget {payload[limit_key]} -> {smaller}')
                    payload[limit_key] = smaller
                    continue
                # The provider rejected the model's own malformed tool-call JSON (Groq:
                # tool_use_failed). Nothing was executed, so sampling again is safe.
                malformed = exc.status == 400 and any(x in str(exc).lower() for x in self.MALFORMED_TOOL_CALL)
                if not malformed or attempt == self.MALFORMED_TOOL_CALL_RETRIES:
                    raise
                payload['temperature'] = 0.3  # identical sampling would likely repeat the error
                # The provider rejected the call before the model saw any feedback; tell it why
                # (e.g. a missing required field) so the next attempt can correct it.
                reason = str(exc).split('HTTP 400:', 1)[-1].strip()[:500]
                payload['messages'] = messages + [{'role': 'user', 'content':
                    'Your previous tool call was rejected by the API: ' + reason +
                    ' Call the tool again with valid JSON arguments that include every required field.'}]
                _log(f'Malformed tool call from model; resampling ({attempt + 1}/{self.MALFORMED_TOOL_CALL_RETRIES})')
                self.last_call = time.monotonic()
        choices = result.get('choices', []) if isinstance(result, dict) else []
        usage = (result.get('usage') or {}) if isinstance(result, dict) else {}
        if not choices:
            raise APIError(f'{self.provider} returned no choices')
        finish = choices[0].get('finish_reason')
        message = choices[0].get('message') or {}
        calls = message.get('tool_calls') or []
        _log(f'{self.name}: finish={finish} tool_calls={len(calls)} '
             f"prompt_tokens={usage.get('prompt_tokens')} completion_tokens={usage.get('completion_tokens')} "
             f'in {time.monotonic() - self.last_call:.1f}s')
        if finish == 'length':
            raise APIError('Model response hit the completion limit '
                f'({self.max_completion_tokens}); raise LLM_MAX_COMPLETION_TOKENS')
        # Some OpenAI-compatible servers report finish_reason=stop alongside tool calls.
        if not calls or finish not in ('tool_calls', 'stop'):
            raise APIError(f'{self.provider} returned no usable tool calls (finish_reason={finish})')
        parts = []
        if message.get('content'):
            parts.append({'text': message['content']})
        try:
            for call in calls:
                action = call['function']
                args = json.loads(action['arguments'])
                if not isinstance(args, dict) or not call['id'] or not action['name']:
                    raise ValueError('Invalid tool call')
                parts.append({'functionCall': {'id': call['id'], 'name': action['name'], 'args': args}})
        except (KeyError, TypeError, ValueError):
            raise APIError(f'{self.provider} returned an invalid tool call') from None
        return {'role': 'model', 'parts': parts}, usage


class GroqModel(ChatModel):
    def __init__(self):
        super().__init__('groq')


def create_model():
    """The model client for the configured LLM_PROVIDER."""
    return ChatModel()
