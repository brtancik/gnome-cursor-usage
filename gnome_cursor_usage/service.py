"""Fetch usage from cursor.com."""

from __future__ import annotations

from .api import CursorAPIError, CursorClient
from .auth import SessionNotFound, resolve_cookie_value
from .limits import UsageSnapshot, snapshot_from_limits


class UsageService:
    def __init__(self, verbose=False):
        self._verbose = verbose
        self._cookie: str | None = None
        self._email: str | None = None

    def refresh(self) -> UsageSnapshot:
        try:
            self._cookie = resolve_cookie_value(verbose=self._verbose)
        except SessionNotFound as exc:
            return UsageSnapshot(status_line=str(exc))

        client = CursorClient(self._cookie)
        try:
            me = client.me()
            self._email = me.get("email")
            if not me.get("id"):
                return UsageSnapshot(
                    email=self._email,
                    status_line="Session expired — log in to Cursor again.",
                )
            payload = client.fetch_limits()
            if not payload:
                return UsageSnapshot(
                    email=self._email,
                    status_line="API returned no usage limit data.",
                )
            return snapshot_from_limits(payload, email=self._email)
        except CursorAPIError as exc:
            msg = "HTTP %s error while fetching usage." % exc.status
            if exc.status in (401, 403):
                msg = "Session expired — open Cursor and log in again."
            return UsageSnapshot(email=self._email, status_line=msg)
        except OSError as exc:
            return UsageSnapshot(
                email=self._email,
                status_line="Network error: %s" % exc,
            )
