"""Minimal Cursor dashboard API client (stdlib)."""

import json
import urllib.error
import urllib.request

from . import __version__

BASE = "https://cursor.com"
USER_AGENT = "gnome-cursor-usage/%s" % __version__


class CursorAPIError(RuntimeError):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__("HTTP %s: %s" % (status, body[:300]))


class CursorClient:
    def __init__(self, cookie_value, timeout=30):
        self._cookie = "WorkosCursorSessionToken=" + cookie_value.replace("::", "%3A%3A")
        self._timeout = timeout

    def _request(self, path, method="GET", body=None):
        headers = {
            "Cookie": self._cookie,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Origin"] = BASE
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            raise CursorAPIError(exc.code, exc.read().decode("utf-8", "ignore"))
        return json.loads(raw) if raw else {}

    def me(self):
        return self._request("/api/auth/me")

    def current_period_usage(self):
        return self._request("/api/dashboard/get-current-period-usage", "POST", {})

    def usage_summary(self):
        return self._request("/api/usage-summary")

    def fetch_limits(self):
        """Return the richest billing-cycle payload across endpoints."""
        last_err = None
        best = None
        best_score = -1
        for fn in (self.current_period_usage, self.usage_summary):
            try:
                payload = fn()
                if not isinstance(payload, dict):
                    continue
                score = _limits_payload_score(payload)
                if score > best_score:
                    best = payload
                    best_score = score
            except (CursorAPIError, OSError, ValueError) as exc:
                last_err = exc
        if best is not None:
            return best
        if last_err is not None:
            raise last_err
        return None


def _limits_payload_score(payload):
    score = 0
    if payload.get("membershipType"):
        score += 2
    iu = payload.get("individualUsage") or {}
    for key in ("plan", "overall"):
        block = iu.get(key) or {}
        if block.get("used") is not None:
            score += 5
        if block.get("limit") is not None:
            score += 2
    if payload.get("planUsage"):
        score += 5
    if payload.get("autoModelSelectedDisplayMessage"):
        score += 1
    return score
