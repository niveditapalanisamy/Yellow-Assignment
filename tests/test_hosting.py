import base64
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from backend.main import create_server


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.password = 'synthetic-hosting-password-123456'
        self.server = create_server(0, public_url='https://yellow-test.onrender.com',
            username='reviewer', password=self.password, report_dir=Path(self.tmp.name))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, *, auth=True, host='yellow-test.onrender.com', origin=None, method='GET'):
        headers = {'Host': host}
        if auth:
            headers['Authorization'] = 'Basic ' + base64.b64encode(('reviewer:' + self.password).encode()).decode()
        if origin:
            headers['Origin'] = origin
        body = None
        if method == 'POST':
            headers['Content-Type'] = 'application/json'
            body = '{}'
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read().decode(), dict(response.getheaders())
        conn.close()
        return result

    def test_public_health_without_credentials(self):
        status, body, _ = self.request('/api/health', auth=False, host='internal-render-health-probe')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'status': 'ok'})

    def test_every_evidence_and_action_route_requires_login(self):
        for path in ('/', '/api/config', '/api/status', '/api/report/latest', '/api/report/json', '/api/report/trace'):
            status, body, headers = self.request(path, auth=False)
            self.assertEqual(status, 401, path)
            self.assertIn('Basic realm=', headers['WWW-Authenticate'])
            self.assertNotIn(self.password, body)
        for path in ('/api/import/start', '/api/assessment/run', '/api/import/dry-run'):
            self.assertEqual(self.request(path, auth=False, method='POST')[0], 401)

    def test_authenticated_external_host_and_origin(self):
        self.assertEqual(self.request('/')[0], 200)
        status, body, _ = self.request('/api/import/dry-run', method='POST', origin='https://yellow-test.onrender.com')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['comments'], 2059)

    def test_origin_and_host_cannot_be_supplied_by_untrusted_forwarded_headers(self):
        self.assertEqual(self.request('/api/config', host='evil.example')[0], 403)
        self.assertEqual(self.request('/api/import/start', origin='https://evil.example', method='POST')[0], 403)
        self.assertEqual(self.request('/api/import/start', origin='http://yellow-test.onrender.com', method='POST')[0], 403)

    def test_wrong_password_is_rejected(self):
        self.password = 'incorrect-password'
        self.assertEqual(self.request('/api/config')[0], 401)

    def test_original_report_is_available_with_empty_runtime_storage(self):
        status, body, _ = self.request('/api/report/json')
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(report['run_id'], '20261110T182810Z-2a8b998f')
        self.assertEqual(report['overall_decision'], 'BLOCKED')
        self.assertEqual(self.request('/api/report/trace')[0], 200)

    def test_public_startup_fails_without_strong_password_and_origin(self):
        for kwargs in ({}, {'password': 'short'}, {'password': self.password},
                       {'password': self.password, 'public_url': 'http://insecure.example'}):
            with self.assertRaises(ValueError):
                create_server(0, host='0.0.0.0', **kwargs)
