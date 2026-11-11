"""Groq REST tool-calling adapter for the controller's action envelopes."""
import json
import os
import time
from . import config
from .http import APIError, JsonHTTP


def messages_for(system, contents):
    messages = [{'role': 'system', 'content': system}]
    for content in contents:
        parts = content.get('parts', [])
        if content['role'] == 'model':
            calls = [{'id': p['functionCall']['id'], 'type': 'function', 'function': {
                'name': p['functionCall']['name'],
                'arguments': json.dumps(p['functionCall']['args'])}}
                for p in parts if 'functionCall' in p]
            messages.append({'role': 'assistant',
                'content': '\n'.join(p['text'] for p in parts if 'text' in p) or None,
                'tool_calls': calls})
        else:
            texts = [p['text'] for p in parts if 'text' in p]
            if texts:
                messages.append({'role': 'user', 'content': '\n'.join(texts)})
            for part in parts:
                if 'functionResponse' in part:
                    response = part['functionResponse']
                    messages.append({'role': 'tool', 'tool_call_id': response['id'],
                        'content': json.dumps(response['response'])})
    return messages


def json_schema(value):
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if isinstance(value, dict):
        return {key: item.lower() if key == 'type' and isinstance(item, str)
                else json_schema(item) for key, item in value.items()}
    return value


class GroqModel:
    def __init__(self):
        if not config.GROQ_API_KEY:
            raise APIError('Missing GROQ_API_KEY')
        self.name = config.GROQ_MODEL
        self.min_interval = max(0, float(os.getenv('GROQ_MIN_INTERVAL_SECONDS', '5')))
        self.last_call = 0
        self.http = JsonHTTP('https://api.groq.com/openai/v1',
            {'Authorization': 'Bearer ' + config.GROQ_API_KEY,
             'User-Agent': 'jira-release-agent/1.0'}, timeout=90)

    def invoke(self, system, contents, declarations):
        delay = max(0, self.last_call + self.min_interval - time.monotonic())
        if self.http.deadline and time.monotonic() + delay >= self.http.deadline:
            raise APIError('Model pacing would exceed execution deadline')
        if delay:
            time.sleep(delay)
        self.last_call = time.monotonic()
        result = self.http.request('POST', '/chat/completions', json_body={
            'model': self.name, 'messages': messages_for(system, contents),
            'tools': [{'type': 'function', 'function': json_schema(d)} for d in declarations],
            'tool_choice': 'required', 'temperature': 0, 'max_completion_tokens': 8192}, retry=True)
        choices = result.get('choices', [])
        if not choices or choices[0].get('finish_reason') != 'tool_calls':
            raise APIError('Groq returned no usable tool calls or an incomplete response')
        message = choices[0].get('message', {})
        calls = message.get('tool_calls', [])
        if not calls:
            raise APIError('Groq did not select a tool action')
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
            raise APIError('Groq returned an invalid tool call') from None
        return {'role': 'model', 'parts': parts}, result.get('usage', {})
