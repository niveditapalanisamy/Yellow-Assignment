
"""Bounded JSON transport.

Features:
- Captures HTTP error response bodies and rate-limit headers.
- Respects Retry-After (seconds or HTTP date).
- Uses bounded retries for explicitly retryable requests.
- Never automatically retries ambiguous writes unless retry=True.
- Respects the overall execution deadline.
- Never logs authorization headers or API keys.
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


class JsonHTTP:
    RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

    RATE_LIMIT_HEADERS = (
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-tokens",
    )

    def __init__(self, base, headers=None, timeout=30):
        self.base = base.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.deadline = None
        self.opener = urllib.request.build_opener(NoRedirect())

        self.max_attempts = 5
        self.max_retry_delay = 60

    @staticmethod
    def _log(message):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{timestamp}] [HTTP] {message}", flush=True)

    @staticmethod
    def _safe_error_body(raw):
        """Extract a short, useful error message without dumping large bodies."""
        if not raw:
            return "No response body"

        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))

            if isinstance(parsed, dict):
                error = parsed.get("error", parsed)
                if isinstance(error, dict):
                    message = error.get("message") or error.get("code")
                    if message:
                        return str(message)[:1000]

                return json.dumps(parsed, ensure_ascii=False)[:1000]

            return str(parsed)[:1000]

        except (ValueError, TypeError):
            return raw.decode("utf-8", errors="replace")[:1000]

    @staticmethod
    def _retry_after(headers):
        """Return Retry-After as seconds, supporting both valid formats."""
        value = headers.get("Retry-After")

        if not value:
            return None

        try:
            return max(0.0, float(value))
        except (ValueError, TypeError):
            pass

        try:
            retry_time = parsedate_to_datetime(value)

            if retry_time.tzinfo is None:
                retry_time = retry_time.replace(tzinfo=timezone.utc)

            return max(
                0.0,
                (retry_time - datetime.now(timezone.utc)).total_seconds()
            )

        except (TypeError, ValueError, OverflowError):
            return None

    def _rate_limit_details(self, headers):
        details = {}

        for header in self.RATE_LIMIT_HEADERS:
            value = headers.get(header)
            if value is not None:
                details[header] = value

        return details

    def _remaining_time(self):
        if self.deadline is None:
            return self.timeout

        return min(
            self.timeout,
            self.deadline - time.monotonic()
        )

    def _wait_before_retry(self, delay, status, attempt):
        remaining = self._remaining_time()

        if remaining <= 0 or delay >= remaining:
            raise APIError(
                "Execution deadline exceeded while waiting to retry",
                status=status
            )

        self._log(
            f"Retrying request: attempt={attempt + 1}, "
            f"status={status}, wait={delay:.1f}s"
        )

        time.sleep(delay)

    def request(self, method, path, json_body=None, retry=False):
        if not path.startswith("/") or "://" in path:
            raise APIError("Only relative API paths are allowed")

        body = (
            None
            if json_body is None
            else json.dumps(json_body).encode("utf-8")
        )

        attempts = self.max_attempts if retry else 1
        safe_path = path.split("?")[0]

        for attempt in range(attempts):
            remaining = self._remaining_time()

            if remaining <= 0:
                raise APIError("Execution deadline exceeded")

            req = urllib.request.Request(
                self.base + path,
                data=body,
                method=method,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **self.headers,
                },
            )

            try:
                with self.opener.open(req, timeout=remaining) as response:
                    raw = response.read()

                    if not raw:
                        return None

                    try:
                        return json.loads(raw)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise APIError(
                            f"{method} {safe_path}: invalid JSON response"
                        ) from exc

            except urllib.error.HTTPError as exc:
                raw_error = exc.read()

                error_message = self._safe_error_body(raw_error)
                rate_details = self._rate_limit_details(exc.headers)

                self._log(
                    f"HTTP error: method={method}, path={safe_path}, "
                    f"status={exc.code}, message={error_message}"
                )

                if rate_details:
                    self._log(
                        "Rate-limit headers: "
                        + json.dumps(rate_details, ensure_ascii=False)
                    )

                should_retry = (
                    retry
                    and exc.code in self.RETRYABLE_STATUSES
                    and attempt < attempts - 1
                )

                if should_retry:
                    retry_after = self._retry_after(exc.headers)

                    if retry_after is not None:
                        delay = retry_after
                    else:
                        delay = min(2 ** attempt, 20)

                    delay = min(delay, self.max_retry_delay)

                    self._wait_before_retry(
                        delay,
                        exc.code,
                        attempt
                    )
                    continue

                raise APIError(
                    f"{method} {safe_path}: HTTP {exc.code}: "
                    f"{error_message}",
                    status=exc.code,
                    details=rate_details
                ) from None

            except urllib.error.URLError as exc:
                reason = str(exc.reason)[:500]

                self._log(
                    f"Network error: method={method}, "
                    f"path={safe_path}, reason={reason}"
                )

                raise APIError(
                    f"{method} {safe_path}: network error: {reason}"
                ) from None

            except (TimeoutError, OSError) as exc:
                reason = str(exc)[:500]

                self._log(
                    f"Transport error: method={method}, "
                    f"path={safe_path}, reason={reason}"
                )

                raise APIError(
                    f"{method} {safe_path}: transport error: {reason}"
                ) from None

        raise APIError(
            f"{method} {safe_path}: maximum retry attempts exceeded"
        )
