from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.main import create_server


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = create_server(0, public_url='https://yellow-test.onrender.com',
            report_dir=Path(self.tmp.name))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, *, host='yellow-test.onrender.com', origin=None, method='GET'):
        headers = {'Host': host}
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
        status, body, _ = self.request('/api/health', host='internal-render-health-probe')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'status': 'ok'})

    def test_dashboard_and_reports_never_challenge_for_login(self):
        for path in ('/', '/api/config', '/api/status', '/api/report/latest', '/api/report/json', '/api/report/trace'):
            status, _, headers = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertNotIn('WWW-Authenticate', headers)

    def test_public_external_origin_can_validate_dataset(self):
        status, body, _ = self.request('/api/import/dry-run', method='POST', origin='https://yellow-test.onrender.com')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['comments'], 2059)

    def test_host_and_origin_checks_still_apply(self):
        self.assertEqual(self.request('/api/config', host='evil.example')[0], 403)
        self.assertEqual(self.request('/api/import/start', origin='https://evil.example', method='POST')[0], 403)
        self.assertEqual(self.request('/api/import/start', origin='http://yellow-test.onrender.com', method='POST')[0], 403)

    def test_live_assessment_and_import_can_start_without_credentials(self):
        # Mock job execution only: anonymous HTTP access is real, no paid calls or Jira writes in unit tests.
        with patch.object(self.server.application, 'start', return_value=True) as start:
            self.assertEqual(self.request('/api/assessment/run', method='POST')[0], 202)
            start.assert_called_with('assessment', {})
            self.assertEqual(self.request('/api/import/start', method='POST')[0], 202)
            start.assert_called_with('import', {})

    def test_original_report_is_available_with_empty_runtime_storage(self):
        status, body, _ = self.request('/api/report/json')
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(report['run_id'], '20261110T182810Z-2a8b998f')
        self.assertEqual(report['overall_decision'], 'BLOCKED')
        self.assertEqual(self.request('/api/report/trace')[0], 200)

    def test_public_startup_needs_https_origin_but_not_password(self):
        for kwargs in ({}, {'public_url': 'http://insecure.example'}):
            with self.assertRaises(ValueError):
                create_server(0, host='0.0.0.0', **kwargs)
        server = create_server(0, host='0.0.0.0', public_url='https://yellow-test.onrender.com')
        self.addCleanup(server.server_close)
        self.assertEqual(server.public_url, 'https://yellow-test.onrender.com')
