"""Gemini REST function-calling adapter; preserves full model parts/thought signatures."""
import os
import time
from urllib.parse import quote
from . import config
from .http import APIError, JsonHTTP


class GeminiModel:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise APIError('Missing GEMINI_API_KEY')
        self.name = config.GEMINI_MODEL
        self.min_interval = max(0, float(os.getenv('GEMINI_MIN_INTERVAL_SECONDS', '5')))
        self.last_call = 0
        self.http = JsonHTTP('https://generativelanguage.googleapis.com/v1beta',
            {'x-goog-api-key': config.GEMINI_API_KEY}, timeout=90)

    def invoke(self, system, contents, declarations):
        delay = max(0, self.last_call + self.min_interval - time.monotonic())
        if self.http.deadline and time.monotonic() + delay >= self.http.deadline:
            raise APIError('Model pacing would exceed execution deadline')
        if delay:
            time.sleep(delay)
        self.last_call = time.monotonic()
        result = self.http.request('POST', '/models/' + quote(self.name, safe='-._') + ':generateContent', json_body={
            'systemInstruction': {'parts': [{'text': system}]}, 'contents': contents,
            'tools': [{'functionDeclarations': declarations}],
            'toolConfig': {'functionCallingConfig': {'mode': 'ANY'}},
            'generationConfig': {'temperature': 1, 'maxOutputTokens': 8192,
                'thinkingConfig': {'thinkingLevel': 'LOW'}}}, retry=True)
        candidates = result.get('candidates', [])
        if not candidates or candidates[0].get('finishReason') not in (None, 'STOP'):
            raise APIError('Gemini returned no usable candidate or an incomplete response')
        content = candidates[0].get('content', {})
        if not any('functionCall' in p for p in content.get('parts', [])):
            raise APIError('Gemini did not select a tool action')
        return content, result.get('usageMetadata', {})
