"""Polite HTTP client: per-host rate limiting, retries with exponential backoff
and jitter (honouring Retry-After), and robots.txt checks for non-API pages."""
from __future__ import annotations

import logging
import random
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from hunt.config import get_settings

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

# Minimum seconds between requests to the same host.
HOST_INTERVALS = {
    "raw.githubusercontent.com": 0.0,
    "boards-api.greenhouse.io": 0.35,
    "api.lever.co": 0.35,
    "api.ashbyhq.com": 0.5,
    "api.smartrecruiters.com": 0.5,
}
DEFAULT_INTERVAL = 1.0
WORKDAY_INTERVAL = 1.0

# Public JSON APIs intended for programmatic access: robots.txt does not apply.
API_HOSTS = {"raw.githubusercontent.com", "boards-api.greenhouse.io", "api.lever.co",
             "api.ashbyhq.com", "api.smartrecruiters.com"}


class TransientHTTPError(Exception):
    """Retries exhausted on a retryable failure; callers may re-queue."""


class PermanentHTTPError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class RobotsDisallowed(Exception):
    pass


class PoliteClient:
    def __init__(self, max_retries: int = 4, base_delay: float = 1.0, max_delay: float = 30.0,
                 timeout: float = 25.0, sleep=time.sleep):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": get_settings().user_agent, "Accept": "application/json, text/html;q=0.9"},
        )
        self.request_count = 0

    def close(self) -> None:
        self.client.close()

    def _interval(self, host: str) -> float:
        if host in HOST_INTERVALS:
            return HOST_INTERVALS[host]
        if host.endswith("myworkdayjobs.com"):
            return WORKDAY_INTERVAL
        return DEFAULT_INTERVAL

    def _throttle(self, host: str) -> None:
        interval = self._interval(host)
        with self._lock:
            now = time.monotonic()
            wait = self._last.get(host, 0.0) + interval - now
            self._last[host] = max(now, self._last.get(host, 0.0) + interval)
        if wait > 0:
            self._sleep(wait)

    def robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host in API_HOSTS or "/wday/cxs/" in parts.path:
            return True
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.client.get(f"{parts.scheme}://{host}/robots.txt", timeout=10)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
                else:
                    self._robots[host] = None  # no robots.txt -> allowed
            except httpx.HTTPError:
                self._robots[host] = None
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(get_settings().user_agent, url)

    def request(self, method: str, url: str, *, check_robots: bool = False, **kwargs) -> httpx.Response:
        if check_robots and not self.robots_allowed(url):
            raise RobotsDisallowed(url)
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            try:
                self.request_count += 1
                resp = self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                delay = self._backoff(attempt)
                log.warning("%s %s failed (%s); retry in %.1fs", method, url, e, delay)
                self._sleep(delay)
                continue
            if resp.status_code in RETRY_STATUS:
                last_exc = PermanentHTTPError(resp.status_code, url)
                delay = self._retry_after(resp) or self._backoff(attempt)
                log.warning("%s %s -> %s; retry in %.1fs", method, url, resp.status_code, delay)
                self._sleep(delay)
                continue
            if resp.status_code >= 400:
                raise PermanentHTTPError(resp.status_code, url)
            return resp
        raise TransientHTTPError(f"{method} {url}: retries exhausted ({last_exc})")

    def get_json(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs).json()

    def post_json(self, url: str, payload: dict, **kwargs):
        return self.request("POST", url, json=payload, **kwargs).json()

    def _backoff(self, attempt: int) -> float:
        return min(self.base_delay * (2 ** attempt), self.max_delay) + random.uniform(0, self.base_delay)

    def _retry_after(self, resp: httpx.Response) -> float | None:
        ra = resp.headers.get("retry-after")
        if ra and ra.isdigit():
            return min(float(ra), 120.0)
        return None
