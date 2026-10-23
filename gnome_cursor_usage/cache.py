"""On-disk cache for the GNOME Shell extension."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .constants import CACHE_POLL_SEC, REFRESH_INTERVAL_SEC
from .limits import UsageSnapshot, _money

CACHE_PATH = Path.home() / ".cache" / "gnome-cursor-usage" / "status.json"
DASHBOARD_URL = "https://cursor.com/dashboard/usage"


def _money_bar_label(snap: UsageSnapshot) -> str | None:
    if snap.used_cents is None or not snap.limit_cents:
        return None
    return "%s / %s" % (_money(snap.used_cents), _money(snap.limit_cents))


def write_status_cache(snap: UsageSnapshot) -> Path:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": snap.short_label(),
        "title": snap.tray_title(),
        "money_label": _money_bar_label(snap),
        "used_cents": snap.used_cents,
        "limit_cents": snap.limit_cents,
        "remaining_cents": snap.remaining_cents,
        "menu_lines": snap.menu_lines(),
        "dashboard_url": DASHBOARD_URL,
        "cache_poll_sec": CACHE_POLL_SEC,
        "refresh_interval_sec": REFRESH_INTERVAL_SEC,
        "snapshot": asdict(snap),
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return CACHE_PATH
