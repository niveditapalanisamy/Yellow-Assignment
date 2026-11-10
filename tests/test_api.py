from http.client import HTTPConnection
import json
import threading
import unittest

from backend.main import create_server


class APITests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = response.status, response.read().decode(), dict(response.getheaders())
        conn.close()
        return result

    def test_dashboard_health_and_configuration_do_not_expose_credentials(self):
        status, body, headers = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Assessment scope', body)
        self.assertIn('Content-Security-Policy', headers)
        self.assertEqual(self.request('GET', '/api/health')[0], 200)
        status, body, _ = self.request('GET', '/api/config')
        self.assertEqual(status, 200)
        from agent import config
        for secret in (config.JIRA_API_TOKEN, config.GEMINI_API_KEY):
            if secret:
                self.assertNotIn(secret, body)

    def test_dry_run_endpoint(self):
        status, body, _ = self.request('POST', '/api/import/dry-run', '{}', {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['comments'], 2059)

    def test_cross_origin_and_rebinding_requests_rejected(self):
        status, _, _ = self.request('POST', '/api/import/start', '{}',
            {'Content-Type': 'application/json', 'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('GET', '/api/config', headers={'Host': 'evil.example'})
        self.assertEqual(status, 403)

    def test_invalid_requests(self):
        self.assertEqual(self.request('GET', '/nonexistent')[0], 404)
        self.assertEqual(self.request('POST', '/api/import/start', '{}')[0], 415)
        self.assertEqual(self.request('POST', '/api/import/start', '[]', {'Content-Type': 'application/json'})[0], 400)
