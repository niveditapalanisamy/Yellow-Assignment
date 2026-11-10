"""Public dashboard/API with loopback defaults and trusted-origin Render hosting."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from agent import config

ROOT = Path(__file__).resolve().parents[1]


class Application:
    def __init__(self, report_dir=None):
        self.lock = threading.Lock()
        self.state = {'status': 'idle', 'operation': None, 'error': None}
        self.latest = None
        self.report_dir = Path(report_dir or ROOT/config.REPORT_DIR)

    def start(self, operation, payload):
        project = payload.get('project', config.JIRA_PROJECT_KEY)
        label = payload.get('dataset_label', config.JIRA_DATASET_LABEL)
        release = payload.get('release', 'R2.4')
        if not isinstance(release, str) or not release or len(release) > 100:
            raise ValueError('Invalid release')
        from agent.jira_client import JiraClient
        # Validate credentials and scope before starting background work.
        JiraClient(project, label)
        with self.lock:
            if self.state['status'] == 'running':
                return False
            self.state = {'status': 'running', 'operation': operation, 'error': None,
                'started_at': datetime.now(timezone.utc).isoformat()}
        thread = threading.Thread(target=self._run, args=(operation, project, label, release), daemon=True)
        thread.start()
        return True

    def _run(self, operation, project, label, release):
        try:
            if operation == 'import':
                from importer.jira_importer import run
                self.report_dir.mkdir(parents=True, exist_ok=True)
                result = run(ROOT/'inputs/dataset.json', project=project, summary_path=self.report_dir/'import_summary.json')
                status = 'failed' if result['failures'] else 'completed'
            else:
                from agent.graph import assess
                result = assess(project, label, release, output_dir=self.report_dir)
                status = result['execution_status'].lower()
                with self.lock:
                    self.latest = result
            with self.lock:
                self.state.update({'status': status, 'result': result,
                    'finished_at': datetime.now(timezone.utc).isoformat()})
        except Exception as exc:
            with self.lock:
                self.state.update({'status': 'failed', 'error': str(exc)})


class Handler(BaseHTTPRequestHandler):
    server_version = 'ReleaseEvidence/2.0'

    def log_message(self, fmt, *args):
        # No request bodies, configuration values or authentication headers in logs.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def send(self, status, data, content_type='application/json', headers=None):
        raw = json.dumps(data).encode('utf-8') if content_type == 'application/json' else data.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def local_request(self):
        host = self.headers.get('Host', '').lower()
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origins = {'http://' + x for x in expected}
        if self.server.public_url:
            expected.add(urlsplit(self.server.public_url).netloc.lower())
            origins.add(self.server.public_url)
        origin = self.headers.get('Origin')
        return host in expected and (not origin or origin in origins)

    def guard(self):
        if not self.local_request():
            self.send(403, {'error': 'Untrusted host or origin'})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        # Render health probes never receive credentials or evidence.
        if path == '/api/health':
            return self.send(200, {'status': 'ok'})
        if not self.guard():
            return
        app = self.server.application
        if path == '/':
            return self.send(200, (ROOT/'frontend/index.html').read_text(encoding='utf-8'), 'text/html')
        if path == '/api/config':
            return self.send(200, {'project': config.JIRA_PROJECT_KEY, 'dataset_label': config.JIRA_DATASET_LABEL,
                'model': config.GEMINI_MODEL, 'jira_configured': bool(config.JIRA_API_TOKEN),
                'model_configured': bool(config.GEMINI_API_KEY)})
        if path in ('/api/status', '/api/import/status', '/api/assessment/status'):
            with app.lock:
                state = dict(app.state)
            return self.send(200, state)
        if path in ('/api/report/latest', '/api/report/json', '/api/report/trace'):
            latest = app.latest
            if latest is None:
                paths = sorted(app.report_dir.glob('*/report.json'))
                # The original submitted report remains available across ephemeral deploys.
                if not paths and (ROOT/'submission/report.json').exists():
                    paths = [ROOT/'submission/report.json']
                if paths:
                    latest = json.loads(paths[-1].read_text(encoding='utf-8'))
                    latest['report_path'] = str(paths[-1].with_name('report.md'))
                    latest['trace_path'] = str(paths[-1].with_name('trace.jsonl'))
            if latest is None:
                return self.send(404, {'error': 'No assessment report exists yet'})
            if path.endswith('/json'):
                return self.send(200, latest)
            report_path = latest['trace_path'] if path.endswith('/trace') else latest['report_path']
            return self.send(200, Path(report_path).read_text(encoding='utf-8'), 'text/plain')
        return self.send(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.guard():
            return
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.send(415, {'error': 'Use application/json'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 16384:
                return self.send(413, {'error': 'Request is too large'})
            payload = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(payload, dict):
                raise ValueError('Request must be an object')
            path = urlsplit(self.path).path
            if path == '/api/import/dry-run':
                from importer.jira_importer import validate_dataset
                data = validate_dataset(ROOT/'inputs/dataset.json')
                return self.send(200, {'success': True, 'records': len(data['records']),
                    'comments': sum(len(r['comments']) for r in data['records']),
                    'relationships': sum(len(r['links']) for r in data['records']), 'dataset_label': data['dataset_label']})
            if path not in ('/api/import/start', '/api/assessment/run'):
                return self.send(404, {'error': 'Not found'})
            operation = 'import' if path == '/api/import/start' else 'assessment'
            if not self.server.application.start(operation, payload):
                return self.send(409, {'error': 'An operation is already running'})
            return self.send(202, {'started': True, 'operation': operation})
        except (ValueError, RuntimeError, TypeError) as exc:
            return self.send(400, {'error': str(exc)})


def create_server(port=8000, host='127.0.0.1', public_url=None, report_dir=None):
    if public_url:
        parsed = urlsplit(public_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('PUBLIC_BASE_URL must be an HTTPS origin')
        public_url = public_url.rstrip('/')
    if host not in ('127.0.0.1', 'localhost', '::1') or public_url:
        if not public_url:
            raise ValueError('Public hosting requires PUBLIC_BASE_URL or RENDER_EXTERNAL_URL')
    server = ThreadingHTTPServer((host, port), Handler)
    server.public_url = public_url
    server.application = Application(report_dir)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8000')))
    parser.add_argument('--host', default=os.getenv('HOST', '0.0.0.0' if os.getenv('RENDER') == 'true' else '127.0.0.1'))
    args = parser.parse_args()
    server = create_server(args.port, args.host,
        public_url=os.getenv('PUBLIC_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL'))
    print(f'Release Evidence Agent listening on {args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
