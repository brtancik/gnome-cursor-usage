"""Parse dashboard usage/limit payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

_PERCENT_RE = re.compile(r"used\s+(\d+(?:\.\d+)?)\s*%", re.I)


def _optional_f(d, k):
    if k not in d:
        return None
    try:
        v = d[k]
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _optional_i(d, k):
    if k not in d:
        return None
    try:
        v = d[k]
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _money(cents):
    return "$%s" % format(cents / 100.0, ",.2f")


def _parse_billing_cycle_end_date(payload) -> date | None:
    raw = payload.get("billingCycleEnd")
    if raw is None:
        return None
    try:
        s = str(raw).strip()
        if s.isdigit():
            ms = int(s)
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (TypeError, ValueError, OSError):
        return None


def _parse_reset_date(payload):
    d = _parse_billing_cycle_end_date(payload)
    return d.isoformat() if d else None


def _days_until_reset(end: date | None) -> int | None:
    if end is None:
        return None
    today = datetime.now().astimezone().date()
    return max(0, (end - today).days)


def _format_resets_on_line(end_str: str, days: int | None) -> str:
    if days is None:
        return "Resets on: %s" % end_str
    if days == 0:
        return "Resets on: %s (today)" % end_str
    if days == 1:
        return "Resets on: %s (1 day remaining)" % end_str
    return "Resets on: %s (%d days remaining)" % (end_str, days)


@dataclass
class UsageSnapshot:
    email: str | None = None
    membership_type: str | None = None
    is_unlimited: bool = False
    auto_percent_used: float | None = None
    api_percent_used: float | None = None
    headline_percent_used: float | None = None
    used_cents: int | None = None
    limit_cents: int | None = None
    remaining_cents: int | None = None
    on_demand_used_cents: int | None = None
    billing_cycle_end: str | None = None
    days_until_reset: int | None = None
    status_line: str | None = None
    fetched_at: datetime | None = None

    def short_label(self) -> str:
        if self.headline_percent_used is not None:
            return "%d%%" % int(round(self.headline_percent_used))
        if self.remaining_cents is not None and self.limit_cents:
            left = max(0, self.remaining_cents)
            return _money(left).replace("$", "$", 1)
        if self.is_unlimited:
            return "∞"
        return "—"

    def tray_title(self) -> str:
        if self.headline_percent_used is not None:
            left = max(0.0, 100.0 - self.headline_percent_used)
            return "%.0f%% remaining" % left
        return "Cursor usage"

    def menu_lines(self) -> list[str]:
        lines = []
        if self.email:
            lines.append(self.email)
        if self.membership_type:
            lines.append("Plan: %s" % self.membership_type)
        if self.is_unlimited:
            lines.append("Unlimited usage this cycle")
        if self.auto_percent_used is not None:
            lines.append("Auto/Composer: %.1f%% used" % self.auto_percent_used)
        if self.api_percent_used is not None:
            lines.append("Other models: %.1f%% used" % self.api_percent_used)
        if self.used_cents is not None and self.limit_cents:
            rem = self.remaining_cents
            if rem is None:
                rem = max(0, self.limit_cents - self.used_cents)
            lines.append(
                "Included: %s / %s (%s remaining)"
                % (_money(self.used_cents), _money(self.limit_cents), _money(rem))
            )
        if self.on_demand_used_cents is not None:
            lines.append("On-demand: %s" % _money(self.on_demand_used_cents))
        if self.billing_cycle_end:
            lines.append(_format_resets_on_line(self.billing_cycle_end, self.days_until_reset))
        if self.status_line:
            lines.append(self.status_line)
        if self.fetched_at:
            lines.append(
                "Updated: %s"
                % self.fetched_at.astimezone().strftime("%-I:%M:%S %p %m/%d")
            )
        return lines


def _parse_message_percents(payload):
    found = []
    for key in (
        "autoModelSelectedDisplayMessage",
        "namedModelSelectedDisplayMessage",
    ):
        msg = payload.get(key) or ""
        m = _PERCENT_RE.search(str(msg))
        if m:
            found.append(float(m.group(1)))
    return found


def _plan_block(payload):
    iu = payload.get("individualUsage") or {}
    return (
        payload.get("planUsage")
        or iu.get("plan")
        or iu.get("overall")
        or {}
    )


def snapshot_from_limits(payload: dict, email: str | None = None) -> UsageSnapshot:
    plan = _plan_block(payload)
    on_demand = (payload.get("individualUsage") or {}).get("onDemand") or {}
    team_od = (payload.get("teamUsage") or {}).get("onDemand") or {}

    auto_pct = _optional_f(plan, "autoPercentUsed")
    api_pct = _optional_f(plan, "apiPercentUsed")
    total_pct = _optional_f(plan, "totalPercentUsed")

    used = _optional_i(plan, "totalSpend")
    if used is None:
        used = _optional_i(plan, "used")

    limit = _optional_i(plan, "limit") if "limit" in plan else None
    remaining = _optional_i(plan, "remaining") if "remaining" in plan else None
    if remaining is None and limit is not None and used is not None:
        remaining = max(0, limit - used)

    headline = total_pct
    if headline is None:
        parts = [p for p in (auto_pct, api_pct) if p is not None]
        headline = max(parts) if parts else None
    if headline is None and limit and used is not None and limit > 0:
        headline = min(100.0, 100.0 * used / limit)
    msg_pcts = _parse_message_percents(payload)
    if headline is None and msg_pcts:
        headline = max(msg_pcts)
    elif msg_pcts:
        headline = max(headline or 0.0, max(msg_pcts))

    status_bits = []
    for key in (
        "autoModelSelectedDisplayMessage",
        "namedModelSelectedDisplayMessage",
    ):
        msg = payload.get(key)
        if msg:
            status_bits.append(str(msg))

    cycle_end = _parse_billing_cycle_end_date(payload)
    return UsageSnapshot(
        email=email,
        membership_type=payload.get("membershipType"),
        is_unlimited=bool(payload.get("isUnlimited")),
        auto_percent_used=auto_pct,
        api_percent_used=api_pct,
        headline_percent_used=headline,
        used_cents=used,
        limit_cents=limit,
        remaining_cents=remaining,
        on_demand_used_cents=_optional_i(on_demand, "used")
        if on_demand.get("used") is not None
        else _optional_i(team_od, "used"),
        billing_cycle_end=cycle_end.isoformat() if cycle_end else None,
        days_until_reset=_days_until_reset(cycle_end),
        status_line=status_bits[0] if status_bits else None,
        fetched_at=datetime.now(timezone.utc),
    )
