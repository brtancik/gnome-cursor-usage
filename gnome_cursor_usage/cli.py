"""Terminal mode (no GTK) to test auth and API."""

import argparse
import json
import sys
import time

from . import __version__
from .cache import CACHE_PATH, write_status_cache
from .constants import REFRESH_INTERVAL_SEC
from .limits import UsageSnapshot
from .service import UsageService

DEFAULT_INTERVAL_SEC = REFRESH_INTERVAL_SEC
_SESSION_ERROR_MARKERS = ("Could not find", "Não achei")


def _refresh(verbose=False):
    snap = UsageService(verbose=verbose).refresh()
    path = write_status_cache(snap)
    return snap, path


def _is_session_error(snap: UsageSnapshot) -> bool:
    if not snap.status_line:
        return False
    return any(m in snap.status_line for m in _SESSION_ERROR_MARKERS)


def main(argv=None):
    p = argparse.ArgumentParser(prog="gnome-cursor-usage", description="Cursor usage")
    p.add_argument("--fetch", action="store_true", help="call API and print summary")
    p.add_argument("--write-cache", action="store_true", help="write ~/.cache/.../status.json")
    p.add_argument(
        "--daemon",
        action="store_true",
        help="refresh cache in a loop (for GNOME extension)",
    )
    p.add_argument("--json", action="store_true", help="with --fetch, print raw JSON")
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SEC,
        help="daemon interval in seconds (default: constants.py)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-V", "--version", action="version", version=__version__)
    args = p.parse_args(argv)

    if args.daemon:
        interval = max(60, args.interval)
        while True:
            try:
                _refresh(verbose=args.verbose)
            except Exception as exc:
                write_status_cache(
                    UsageSnapshot(status_line="Update failed: %s" % exc),
                )
            time.sleep(interval)

    if not (args.fetch or args.write_cache):
        p.print_help()
        return 0

    snap, path = _refresh(verbose=args.verbose)
    if args.write_cache and not args.fetch:
        print(path)
        if _is_session_error(snap):
            return 2
        return 0

    if args.json:
        from dataclasses import asdict

        print(json.dumps(asdict(snap), indent=2, default=str))
        return 0

    for line in snap.menu_lines() or ["(no data)"]:
        print(line)
    print("Panel label:", snap.short_label(), "|", snap.tray_title())
    print("Cache:", CACHE_PATH)
    if _is_session_error(snap):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
