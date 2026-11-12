import json
import unittest
from unittest.mock import patch

from agent.http import APIError
from agent.model import GroqModel
from agent.tools import DECLARATIONS


class ModelTests(unittest.TestCase):
    def setUp(self):
        with patch('agent.config.GROQ_API_KEY', 'synthetic-test-key'):
            self.model = GroqModel()
        self.model.min_interval = 0

    def result(self, arguments='{"issue_key":"TYN-1"}'):
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None,
            'tool_calls': [{'id': 'call-test', 'type': 'function', 'function': {
                'name': 'get_record', 'arguments': arguments}}]}}],
            'usage': {'prompt_tokens': 50, 'completion_tokens': 10, 'total_tokens': 60}}

    def test_tool_calls_schema_auth_and_usage(self):
        with patch.object(self.model.http, 'request', return_value=self.result()) as request:
            response, usage = self.model.invoke('System policy',
                [{'role': 'user', 'parts': [{'text': 'Investigate'}]}], DECLARATIONS)
        self.assertEqual(response['parts'][0]['functionCall'], {
            'id': 'call-test', 'name': 'get_record', 'args': {'issue_key': 'TYN-1'}})
        self.assertEqual(usage['total_tokens'], 60)
        payload = request.call_args.kwargs['json_body']
        self.assertEqual(request.call_args.args, ('POST', '/chat/completions'))
        self.assertEqual(self.model.http.base, 'https://api.groq.com/openai/v1')
        self.assertEqual(self.model.http.headers['Authorization'], 'Bearer synthetic-test-key')
        self.assertEqual(payload['tool_choice'], 'required')
        self.assertEqual(payload['temperature'], 0)
        self.assertEqual(payload['max_completion_tokens'], 4096)
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': 'System policy'})
        schema = payload['tools'][-1]['function']['parameters']
        self.assertEqual(schema['type'], 'object')
        self.assertEqual(schema['properties']['references']['type'], 'array')
        self.assertEqual(schema['properties']['references']['items']['properties']['quote']['type'], 'string')

    def test_tool_results_round_trip_with_call_ids(self):
        with patch.object(self.model.http, 'request', return_value=self.result()) as request:
            response, _ = self.model.invoke('Policy', [], DECLARATIONS)
            contents = [response, {'role': 'user', 'parts': [{'functionResponse': {
                'id': 'call-test', 'name': 'get_record', 'response': {'result': [1, 2]}}}]}]
            self.model.invoke('Policy', contents, DECLARATIONS)
        messages = request.call_args.kwargs['json_body']['messages']
        self.assertEqual(messages[1]['tool_calls'][0]['id'], 'call-test')
        self.assertEqual(json.loads(messages[1]['tool_calls'][0]['function']['arguments']), {'issue_key': 'TYN-1'})
        self.assertEqual(messages[2]['role'], 'tool')
        self.assertEqual(messages[2]['tool_call_id'], 'call-test')
        self.assertEqual(json.loads(messages[2]['content']), {'result': [1, 2]})

    def test_incomplete_model_response_rejected(self):
        for response in ({}, {'choices': [{'finish_reason': 'length'}]},
                         {'choices': [{'finish_reason': 'stop', 'message': {'content': 'Ready!'}}]},
                         {'choices': [{'finish_reason': 'tool_calls', 'message': {}}]}):
            with patch.object(self.model.http, 'request', return_value=response):
                with self.assertRaises(APIError):
                    self.model.invoke('Policy', [], DECLARATIONS)

    def test_malformed_tool_arguments_rejected(self):
        for arguments in ('not json', '[]', 'null'):
            with patch.object(self.model.http, 'request', return_value=self.result(arguments)):
                with self.assertRaises(APIError):
                    self.model.invoke('Policy', [], DECLARATIONS)

    def test_missing_key_rejected(self):
        with patch('agent.config.GROQ_API_KEY', ''):
            with self.assertRaisesRegex(APIError, 'Missing GROQ_API_KEY'):
                GroqModel()
