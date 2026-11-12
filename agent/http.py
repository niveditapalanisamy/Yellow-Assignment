"""Bounded JSON transport.

- Captures a short provider error message and rate-limit headers for diagnosis.
- Honors Retry-After (seconds or HTTP date), capped, for explicitly retryable requests.
- Fails fast on daily quota exhaustion, which a short retry cannot fix.
- Never automatically retries ambiguous writes unless retry=True.
- Respects the overall execution deadline.
- Never logs authorization headers, request bodies or network error details.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class APIError(RuntimeError):
    def __init__(self, message, status=None, details=None):
        super().__init__(message)
        self.status = status
        self.details = details


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _log(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f'[{timestamp}] [HTTP] {message}', flush=True)


class JsonHTTP:
    RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
    RATE_LIMIT_HEADERS = ('retry-after', 'x-ratelimit-limit-requests', 'x-ratelimit-remaining-requests',
        'x-ratelimit-reset-requests', 'x-ratelimit-limit-tokens', 'x-ratelimit-remaining-tokens',
        'x-ratelimit-reset-tokens')
    # Quota windows that a bounded in-run retry cannot recover from.
    NON_RECOVERABLE_QUOTA = ('per day', '(TPD)', '(RPD)')

    def __init__(self, base, headers=None, timeout=30):
        self.base = base.rstrip('/')
        self.headers = headers or {}
        self.timeout = timeout
        self.deadline = None
        self.opener = urllib.request.build_opener(NoRedirect())
        self.max_attempts = 5
        self.max_retry_delay = 30

    @staticmethod
    def _error_message(raw):
        """A short provider error message; never the full response body."""
        if not raw:
            return ''
        try:
            parsed = json.loads(raw.decode('utf-8', errors='replace'))
        except (ValueError, TypeError):
            return raw.decode('utf-8', errors='replace')[:300]
        error = parsed.get('error', parsed) if isinstance(parsed, dict) else parsed
        if isinstance(error, dict):
            return str(error.get('message') or error.get('code') or '')[:300]
        if isinstance(parsed, dict) and parsed.get('errorMessages'):
            return '; '.join(map(str, parsed['errorMessages']))[:300]
        return str(error)[:300]

    @staticmethod
    def _retry_after(headers):
        value = headers.get('Retry-After') if headers else None
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    def request(self, method, path, json_body=None, retry=False):
        if not path.startswith('/') or '://' in path:
            raise APIError('Only relative API paths are allowed')
        body = None if json_body is None else json.dumps(json_body).encode('utf-8')
        safe_path = path.split('?')[0]
        attempts = self.max_attempts if retry else 1
        for attempt in range(attempts):
            remaining = self.timeout if self.deadline is None else min(self.timeout, self.deadline - time.monotonic())
            if remaining <= 0:
                raise APIError('Execution deadline exceeded')
            req = urllib.request.Request(self.base + path, data=body, method=method,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json', **self.headers})
            try:
                with self.opener.open(req, timeout=remaining) as response:
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                message = self._error_message(exc.read())
                details = {h: exc.headers.get(h) for h in self.RATE_LIMIT_HEADERS
                           if exc.headers and exc.headers.get(h) is not None}
                _log(f'{method} {safe_path}: HTTP {exc.code}' + (f': {message}' if message else ''))
                quota_exhausted = exc.code == 429 and any(x in message for x in self.NON_RECOVERABLE_QUOTA)
                if retry and exc.code in self.RETRYABLE_STATUSES and not quota_exhausted and attempt < attempts - 1:
                    delay = self._retry_after(exc.headers)
                    delay = min(2 ** attempt, 20) if delay is None else delay
                    delay = min(delay, self.max_retry_delay)
                    if self.deadline is not None and time.monotonic() + delay >= self.deadline:
                        raise APIError('Execution deadline exceeded while waiting to retry', exc.code, details) from None
                    _log(f'Retrying {method} {safe_path} in {delay:.1f}s (attempt {attempt + 2}/{attempts})')
                    time.sleep(delay)
                    continue
                suffix = f': {message}' if message else ''
                raise APIError(f'{method} {safe_path}: HTTP {exc.code}{suffix}', exc.code, details) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                # The reason can echo host or proxy details; keep it out of errors and logs.
                _log(f'{method} {safe_path}: network failure')
                raise APIError(f'{method} {safe_path}: network failure') from None
            if not raw:
                return None
            try:
                return json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise APIError(f'{method} {safe_path}: invalid JSON response') from None
        raise APIError(f'{method} {safe_path}: maximum retry attempts exceeded')
