"""Bounded JSON transport. Ambiguous writes are never automatically retried."""
import json
import time
import urllib.error
import urllib.request


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonHTTP:
    def __init__(self, base, headers=None, timeout=30):
        self.base, self.headers, self.timeout = base.rstrip('/'), headers or {}, timeout
        self.deadline = None
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, json_body=None, retry=False):
        if not path.startswith('/') or '://' in path:
            raise APIError('Only relative API paths are allowed')
        body = None if json_body is None else json.dumps(json_body).encode('utf-8')
        for attempt in range(5 if retry else 1):
            remaining = self.timeout if self.deadline is None else min(self.timeout, self.deadline - time.monotonic())
            if remaining <= 0:
                raise APIError('Execution deadline exceeded')
            req = urllib.request.Request(self.base + path, data=body, method=method,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json', **self.headers})
            try:
                with self.opener.open(req, timeout=remaining) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                if retry and (exc.code == 429 or exc.code >= 500) and attempt < 4:
                    try:
                        delay = min(float(exc.headers.get('Retry-After', min(2 ** attempt, 20))), 30)
                    except ValueError:
                        delay = min(2 ** attempt, 20)
                    if self.deadline and time.monotonic() + delay >= self.deadline:
                        raise APIError('Execution deadline exceeded', exc.code) from None
                    time.sleep(max(0, delay))
                    continue
                raise APIError(f'{method} {path.split("?")[0]}: HTTP {exc.code}', exc.code) from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                raise APIError(f'{method} {path.split("?")[0]}: network failure or invalid JSON response') from None
