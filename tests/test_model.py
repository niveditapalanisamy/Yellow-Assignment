import unittest
from unittest.mock import patch

from agent.http import APIError
from agent.model import GeminiModel
from agent.tools import DECLARATIONS


class ModelTests(unittest.TestCase):
    def setUp(self):
        with patch('agent.config.GEMINI_API_KEY', 'synthetic-test-key'):
            self.model = GeminiModel()
        self.model.min_interval = 0

    def test_tool_response_signatures_and_usage_preserved(self):
        content = {'role': 'model', 'parts': [{'functionCall': {'name': 'get_record',
            'args': {'issue_key': 'TYN-1'}, 'id': 'call-test'}, 'thoughtSignature': 'opaque-test-signature'}]}
        result = {'candidates': [{'content': content, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 50, 'candidatesTokenCount': 10, 'thoughtsTokenCount': 20}}
        with patch.object(self.model.http, 'request', return_value=result) as request:
            response, usage = self.model.invoke('System policy', [{'role': 'user', 'parts': [{'text': 'Investigate'}]}], DECLARATIONS)
        self.assertEqual(response, content)
        self.assertEqual(usage['thoughtsTokenCount'], 20)
        payload = request.call_args.kwargs['json_body']
        self.assertEqual(payload['toolConfig']['functionCallingConfig']['mode'], 'ANY')
        self.assertEqual(payload['systemInstruction']['parts'][0]['text'], 'System policy')

    def test_incomplete_model_response_rejected(self):
        for response in ({}, {'candidates': [{'finishReason': 'MAX_TOKENS'}]},
                         {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'Ready!'}]}}]}):
            with patch.object(self.model.http, 'request', return_value=response):
                with self.assertRaises(APIError):
                    self.model.invoke('Policy', [], DECLARATIONS)
