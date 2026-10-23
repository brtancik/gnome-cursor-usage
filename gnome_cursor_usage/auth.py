"""Cursor web session resolution (adapted from cursor-usage, MIT)."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

KEYCHAIN_SERVICE = "cursor-access-token"
KEYCHAIN_ACCOUNT = "cursor-user"


class SessionNotFound(RuntimeError):
    """No usable session token was found."""


def _jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _cookie_id(claims):
    sub = claims.get("sub")
    return sub.split("|")[-1] if sub else None


def _from_env():
    return os.environ.get("CURSOR_SESSION_TOKEN")


def _from_macos_keychain():
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _from_keyring():
    try:
        import keyring
    except Exception:
        return None
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception:
        return None


def _state_db_candidates():
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    for app in ("Cursor", "Cursor Nightly"):
        yield base / app / "User" / "globalStorage" / "state.vscdb"


def _from_state_db():
    for path in _state_db_candidates():
        if not path.exists():
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key = ?",
                    ("cursorAuth/accessToken",),
                ).fetchone()
            finally:
                con.close()
        except Exception:
            continue
        if row and row[0]:
            value = row[0]
            if isinstance(value, bytes):
                value = value.decode("utf-8", "ignore")
            return value.strip().strip('"')
    return None


def _local_sources():
    """Local token lookup order.

    On Linux we skip python-keyring by default: KDE Wallet / Secret Service
    backends may show popups (e.g. kdewallet encrypted without GPG).
    Cursor state.vscdb is enough in practice.
    """
    if sys.platform == "darwin":
        return (
            ("macOS keychain", _from_macos_keychain),
            ("Cursor state DB", _from_state_db),
            ("OS keyring", _from_keyring),
        )
    sources = (
        ("Cursor state DB", _from_state_db),
        ("macOS keychain", _from_macos_keychain),
    )
    if os.environ.get("CURSOR_USAGE_TRY_KEYRING", "").strip() in ("1", "true", "yes"):
        return sources + (("OS keyring", _from_keyring),)
    return sources


def resolve_cookie_value(verbose=False):
    env = _from_env()
    if env:
        env = env.strip().replace("%3A%3A", "::")
        if "::" in env:
            if verbose:
                print("[auth] $CURSOR_SESSION_TOKEN", file=sys.stderr)
            return env
        cid = _cookie_id(_jwt_claims(env))
        if cid:
            if verbose:
                print("[auth] $CURSOR_SESSION_TOKEN", file=sys.stderr)
            return "%s::%s" % (cid, env)

    tried = ["$CURSOR_SESSION_TOKEN"]
    saw_api_key = False
    for name, source in _local_sources():
        tried.append(name)
        token = source()
        if not token:
            continue
        token = token.strip().replace("%3A%3A", "::")
        if "::" in token:
            if verbose:
                print("[auth] %s" % name, file=sys.stderr)
            return token
        claims = _jwt_claims(token)
        cid = _cookie_id(claims)
        if not cid:
            continue
        if claims.get("type") == "api_key_token":
            saw_api_key = True
            continue
        if verbose:
            print("[auth] %s" % name, file=sys.stderr)
        return "%s::%s" % (cid, token)

    hint = ""
    if saw_api_key:
        hint = (
            "\nFound api_key_token (Agent API), but the usage dashboard "
            "requires a web session."
        )
    raise SessionNotFound(
        "Could not find a Cursor session.\n"
        "Tried: %s.%s\n\n"
        "Log in to the Cursor app or set CURSOR_SESSION_TOKEN "
        "(WorkosCursorSessionToken cookie in the browser)."
        % (", ".join(tried), hint)
    )
