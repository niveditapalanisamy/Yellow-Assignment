import io
import json
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from agent.http import APIError, JsonHTTP


class TransportTests(unittest.TestCase):
    def test_writes_are_not_retried_after_network_failure(self):
        http = JsonHTTP('https://example.com')
        with patch.object(http.opener, 'open', side_effect=URLError('SECRET VALUE')) as op:
            with self.assertRaises(APIError) as caught:
                http.request('POST', '/issue', {'fields': {}})
            self.assertEqual(op.call_count, 1)
            self.assertNotIn('SECRET', str(caught.exception))

    def test_rate_limit_reads_retry_with_bound(self):
        http = JsonHTTP('https://example.com')
        error = HTTPError('https://example.com', 429, 'limit', {'Retry-After': '900'}, io.BytesIO(b''))
        with patch.object(http.opener, 'open', side_effect=error) as op, patch('agent.http.time.sleep') as sleep:
            with self.assertRaises(APIError):
                http.request('GET', '/issue/TYN-1', retry=True)
            self.assertEqual(op.call_count, 3)
            self.assertTrue(all(x.args[0] <= 10 for x in sleep.call_args_list))

    def test_deadline_prevents_network_calls(self):
        http = JsonHTTP('https://example.com')
        http.deadline = time.monotonic() - 1
        with patch.object(http.opener, 'open') as op:
            with self.assertRaisesRegex(APIError, 'deadline'):
                http.request('GET', '/issue/TYN-1')
            op.assert_not_called()

    def test_absolute_path_not_accepted(self):
        with self.assertRaises(APIError):
            JsonHTTP('https://example.com').request('GET', 'https://attacker.example')
