import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const BIN_PATH_FILE = GLib.build_filenamev([
    GLib.get_home_dir(),
    '.config',
    'gnome-cursor-usage',
    'bin-path',
]);
const CACHE = GLib.build_filenamev(
    [GLib.get_home_dir(), '.cache', 'gnome-cursor-usage', 'status.json'],
);

function resolveFetchBin() {
    try {
        const [ok, contents] = GLib.file_get_contents(BIN_PATH_FILE);
        if (ok) {
            const line = new TextDecoder().decode(contents).trim().split('\n')[0].trim();
            if (line && GLib.file_test(line, GLib.FileTest.IS_EXECUTABLE))
                return line;
        }
    } catch {
        // install.sh has not been run yet
    }
    return GLib.build_filenamev([
        GLib.get_home_dir(),
        'Scripts',
        'gnome-cursor-usage',
        'bin',
        'gnome-cursor-usage',
    ]);
}

const DEFAULT_CACHE_POLL_SEC = 30;

// panelLeft index 1 = right after Activities / Applications (index 0).
const PANEL_LEFT_POSITION = 1;

function cachePollSecFromFile() {
    try {
        const data = readJsonFile(CACHE);
        const poll = data.cache_poll_sec ?? DEFAULT_CACHE_POLL_SEC;
        return Math.max(10, poll);
    } catch {
        return DEFAULT_CACHE_POLL_SEC;
    }
}

const BAR_WIDTH = 168;
const BAR_HEIGHT = 18;
const BAR_RADIUS = 4;

const TRACK = [0.14, 0.14, 0.16, 1];
const FILL_NORMAL = [0.32, 0.32, 0.35, 1];
const FILL_WARN = [0.86, 0.68, 0.16, 1];
const FILL_CRITICAL = [0.52, 0.11, 0.18, 1];

const LABEL_DEFAULT = '#f0f0f0';
const LABEL_ON_WARN = '#1a1a1a';

function fillRgbaForPct(pct) {
    if (pct >= 95)
        return FILL_CRITICAL;
    if (pct >= 80)
        return FILL_WARN;
    return FILL_NORMAL;
}

function labelColorForPct(pct) {
    if (pct >= 80 && pct < 95)
        return LABEL_ON_WARN;
    return LABEL_DEFAULT;
}

function paintRoundedRect(cr, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    if (radius <= 0 || w <= 0 || h <= 0) {
        cr.rectangle(x, y, w, h);
        return;
    }
    if (w <= radius * 2) {
        cr.newSubPath();
        cr.arc(x + w / 2, y + h / 2, w / 2, 0, 2 * Math.PI);
        cr.closePath();
        return;
    }
    cr.newSubPath();
    cr.arc(x + radius, y + radius, radius, Math.PI, (3 * Math.PI) / 2);
    cr.arc(x + w - radius, y + radius, radius, (3 * Math.PI) / 2, 0);
    cr.arc(x + w - radius, y + h - radius, radius, 0, Math.PI / 2);
    cr.arc(x + radius, y + h - radius, radius, Math.PI / 2, Math.PI);
    cr.closePath();
}

function readJsonFile(path) {
    const [ok, contents] = GLib.file_get_contents(path);
    if (!ok)
        throw new Error(`cannot read ${path}`);
    const text = new TextDecoder().decode(contents);
    return JSON.parse(text);
}

function formatMoney(cents) {
    if (cents == null || !Number.isFinite(cents))
        return '—';
    return `$${(cents / 100).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

function moneyLabelFromData(data) {
    if (data.money_label)
        return data.money_label;
    const snap = data.snapshot ?? {};
    const used = snap.used_cents;
    const limit = snap.limit_cents;
    if (used == null || !limit)
        return '— / —';
    return `${formatMoney(used)} / ${formatMoney(limit)}`;
}

function formatFetchedAt(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime()))
        return null;
    const time = d.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
    });
    const date = d.toLocaleDateString('en-US', {
        month: '2-digit',
        day: '2-digit',
    });
    return `${time} ${date}`;
}

/** Panel menu text from structured snapshot (not cached menu_lines strings). */
function menuLinesFromSnapshot(snap) {
    if (!snap || typeof snap !== 'object')
        return [];

    const lines = [];
    if (snap.email)
        lines.push(String(snap.email));
    if (snap.membership_type)
        lines.push(`Plan: ${snap.membership_type}`);
    if (snap.is_unlimited)
        lines.push('Unlimited usage this cycle');
    if (typeof snap.auto_percent_used === 'number')
        lines.push(`Auto/Composer: ${snap.auto_percent_used.toFixed(1)}% used`);
    if (typeof snap.api_percent_used === 'number')
        lines.push(`Other models: ${snap.api_percent_used.toFixed(1)}% used`);
    if (snap.used_cents != null && snap.limit_cents) {
        let rem = snap.remaining_cents;
        if (rem == null)
            rem = Math.max(0, snap.limit_cents - snap.used_cents);
        lines.push(
            `Included: ${formatMoney(snap.used_cents)} / ${formatMoney(snap.limit_cents)} (${formatMoney(rem)} remaining)`,
        );
    }
    if (snap.on_demand_used_cents != null)
        lines.push(`On-demand: ${formatMoney(snap.on_demand_used_cents)}`);
    if (snap.billing_cycle_end)
        lines.push(`Resets on: ${snap.billing_cycle_end}`);
    if (snap.status_line)
        lines.push(String(snap.status_line));
    if (snap.fetched_at) {
        const when = formatFetchedAt(snap.fetched_at);
        if (when)
            lines.push(`Updated: ${when}`);
    }
    return lines;
}

function markPassive(actor) {
    if (!actor)
        return;
    actor.reactive = false;
    actor.can_focus = false;
    actor.track_hover = false;
}

const CURSOR_ICON_SIZE = 14;

function cursorAppGIcon(extensionDir) {
    const bundled = extensionDir.get_child('icons/cursor.png');
    const system = Gio.File.new_for_path('/usr/share/pixmaps/co.anysphere.cursor.png');
    for (const file of [bundled, system]) {
        try {
            if (file.query_exists(null))
                return new Gio.FileIcon({file});
        } catch {
            // try next path
        }
    }
    return null;
}

function usagePercent(data) {
    const snap = data.snapshot ?? {};
    if (typeof snap.headline_percent_used === 'number')
        return snap.headline_percent_used;
    const used = snap.used_cents;
    const limit = snap.limit_cents;
    if (used != null && limit > 0)
        return (used / limit) * 100;
    const label = String(data.label ?? '').replace('%', '').trim();
    const parsed = parseFloat(label);
    return Number.isFinite(parsed) ? parsed : 0;
}

export default class CursorUsageExtension extends Extension {
    enable() {
        this._usagePct = 0;
        this._menuLines = [];
        this._dashboardUrl = 'https://cursor.com/dashboard/usage';

        this._indicator = new PanelMenu.Button(0.0, 'Cursor usage', false);
        this._indicator.y_align = Clutter.ActorAlign.CENTER;
        this._indicator.y_expand = true;
        this._indicator.x_expand = false;
        this._indicator.reactive = true;
        this._indicator.track_hover = true;
        this._indicator.style = (
            'padding: 14px 32px; margin: 0 14px; ' +
            '-natural-hpadding: 24px; -minimum-hpadding: 24px;'
        );

        this._container = new St.BoxLayout({
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            y_expand: true,
            x_expand: false,
            reactive: true,
            track_hover: true,
            style: 'spacing: 14px; padding: 6px 0; margin: 0;',
        });

        this._brandBox = new St.BoxLayout({
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            style: 'spacing: 3px;',
        });

        const cursorGIcon = cursorAppGIcon(this.dir);
        if (cursorGIcon) {
            this._cursorIcon = new St.Icon({
                gicon: cursorGIcon,
                icon_size: CURSOR_ICON_SIZE,
                y_align: Clutter.ActorAlign.CENTER,
            });
            markPassive(this._cursorIcon);
        }

        this._titleLabel = new St.Label({
            text: 'Cursor Usage',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-size: 10px; font-weight: 500; color: #c8c8c8;',
        });

        this._barShell = new St.Widget({
            width: BAR_WIDTH,
            height: BAR_HEIGHT,
            clip_to_allocation: true,
            layout_manager: new Clutter.BinLayout(),
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: false,
        });

        this._barPaint = new St.DrawingArea({
            width: BAR_WIDTH,
            height: BAR_HEIGHT,
            x_expand: false,
            y_expand: false,
        });
        this._barPaint.connect('repaint', () => this._paintBar());

        this._moneyLabel = new St.Label({
            text: '— / —',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-size: 10px; font-weight: 700; color: #f0f0f0;',
        });

        this._barShell.add_child(this._barPaint);
        this._barShell.add_child(this._moneyLabel);

        markPassive(this._brandBox);
        markPassive(this._titleLabel);
        markPassive(this._barShell);
        markPassive(this._barPaint);
        markPassive(this._moneyLabel);

        if (this._cursorIcon)
            this._brandBox.add_child(this._cursorIcon);
        this._brandBox.add_child(this._titleLabel);
        this._container.add_child(this._brandBox);
        this._container.add_child(this._barShell);
        this._indicator.add_child(this._container);

        this._openItem = new PopupMenu.PopupMenuItem('Open usage dashboard');
        this._openItem.connect('activate', () => {
            GLib.spawn_command_line_async(`xdg-open '${this._dashboardUrl}'`);
        });
        this._indicator.menu.addMenuItem(this._openItem);

        this._benchItem = new PopupMenu.PopupMenuItem('View model benchmark');
        this._benchItem.connect('activate', () => {
            GLib.spawn_command_line_async(
                "xdg-open 'https://cursor.com/cursorbench'",
            );
        });
        this._indicator.menu.addMenuItem(this._benchItem);

        this._refreshItem = new PopupMenu.PopupMenuItem('Refresh now');
        this._refreshItem.connect('activate', () => this._requestCacheRefresh());
        this._indicator.menu.addMenuItem(this._refreshItem);

        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const pollSec = cachePollSecFromFile();

        this._syncFromCache();

        this._pollId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, pollSec, () => {
            this._syncFromCache();
            return GLib.SOURCE_CONTINUE;
        });

        Main.panel.addToStatusArea(
            this.uuid,
            this._indicator,
            PANEL_LEFT_POSITION,
            'left',
        );
    }

    disable() {
        if (this._pollId) {
            GLib.source_remove(this._pollId);
            this._pollId = 0;
        }
        if (this._refreshPollId) {
            GLib.source_remove(this._refreshPollId);
            this._refreshPollId = 0;
        }
        if (this._refreshProc) {
            try {
                this._refreshProc.force_exit();
            } catch {
                // ignore
            }
            this._refreshProc = null;
        }
        this._indicator?.destroy();
        this._indicator = null;
    }

    _paintBar() {
        const cr = this._barPaint.get_context();
        const w = BAR_WIDTH;
        const h = BAR_HEIGHT;
        const pct = Math.max(0, Math.min(100, this._usagePct));
        const fillW = (w * pct) / 100;

        cr.save();
        paintRoundedRect(cr, 0, 0, w, h, BAR_RADIUS);
        cr.setSourceRGBA(...TRACK);
        cr.fill();
        cr.restore();

        if (fillW > 0) {
            cr.save();
            cr.rectangle(0, 0, fillW, h);
            cr.clip();
            paintRoundedRect(cr, 0, 0, w, h, BAR_RADIUS);
            cr.setSourceRGBA(...fillRgbaForPct(pct));
            cr.fill();
            cr.restore();
        }
    }

    _requestCacheRefresh() {
        if (this._refreshProc)
            return;

        const fetchBin = resolveFetchBin();

        try {
            this._refreshProc = Gio.Subprocess.new(
                [fetchBin, '--write-cache'],
                Gio.SubprocessFlags.STDERR_SILENCE | Gio.SubprocessFlags.STDOUT_SILENCE,
            );
        } catch (e) {
            console.error(`gnome-cursor-usage refresh spawn: ${e}`);
            GLib.spawn_command_line_async(`${fetchBin} --write-cache`);
            this._pollCacheUntilFresh(12);
            return;
        }

        this._refreshProc.wait_check_async(null, (proc, result) => {
            this._refreshProc = null;
            try {
                proc.wait_check_finish(result);
            } catch (e) {
                console.error(`gnome-cursor-usage refresh: ${e}`);
            }
            this._syncFromCache();
        });
    }

    _pollCacheUntilFresh(maxAttempts) {
        const mtimeBefore = this._cacheMtimeNs();
        let attempts = 0;
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            attempts += 1;
            this._syncFromCache();
            const changed = this._cacheMtimeNs() > mtimeBefore;
            if (changed || attempts >= maxAttempts)
                return GLib.SOURCE_REMOVE;
            return GLib.SOURCE_CONTINUE;
        });
        this._refreshPollId = id;
    }

    _cacheMtimeNs() {
        try {
            const info = Gio.File.new_for_path(CACHE).query_info(
                'time::modification',
                Gio.FileQueryInfoFlags.NONE,
                null,
            );
            if (typeof info.get_modification_time_ns === 'function')
                return info.get_modification_time_ns();
            return Number(info.get_attribute_uint64('time.modification')) * 1_000_000_000;
        } catch {
            return 0;
        }
    }

    _applyUsage(pct, moneyText) {
        const clamped = Math.max(0, Math.min(100, pct));
        this._usagePct = clamped;
        const money = moneyText ?? '— / —';
        this._moneyLabel.text = `${money} · ${Math.round(clamped)}%`;
        this._moneyLabel.style = (
            `font-size: 10px; font-weight: 700; color: ${labelColorForPct(clamped)};`
        );
        this._barPaint.queue_repaint();
    }

    _syncFromCache() {
        let data;
        try {
            data = readJsonFile(CACHE);
        } catch {
            this._applyUsage(0, '— / —');
            return;
        }

        this._applyUsage(usagePercent(data), moneyLabelFromData(data));
        this._dashboardUrl = data.dashboard_url ?? this._dashboardUrl;
        try {
            const lines = menuLinesFromSnapshot(data.snapshot);
            this._rebuildInfoItems(
                lines.length > 0 ? lines : (data.menu_lines ?? []),
            );
        } catch (e) {
            logError(e, 'gnome-cursor-usage menu');
        }
    }

    _rebuildInfoItems(lines) {
        for (const item of this._menuLines)
            item.destroy();
        this._menuLines = [];

        for (const line of lines) {
            const item = new PopupMenu.PopupMenuItem(line);
            item.reactive = false;
            this._indicator.menu.addMenuItem(item, 0);
            this._menuLines.push(item);
        }
    }
}
