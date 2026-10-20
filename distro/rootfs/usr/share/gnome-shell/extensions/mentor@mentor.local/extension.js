// Mentor in the shell.
//
// The assistant has no window of its own: it lives on the desktop, under every
// application, as part of the wallpaper. This extension is what puts it there
// and keeps the way to it short:
//  - the assistant's surface is made a desktop-type window, sized to the work area
//  - a click on the desktop, or Super+A, clears the windows away to reveal it;
//    Escape, or Super+A again, brings them back
//  - "Ask Mentor" in the right-click menu of every app icon
//  - the assistant as a result of the overview search
//  - switches in the system menu: full screen and the taskbar
//  - a way for the agent to see the screen
import Clutter from 'gi://Clutter';
import GdkPixbuf from 'gi://GdkPixbuf';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Config from 'resource:///org/gnome/shell/misc/config.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {AppMenu} from 'resource:///org/gnome/shell/ui/appMenu.js';
import {Spinner} from 'resource:///org/gnome/shell/ui/animation.js';
import {getInputSourceManager} from 'resource:///org/gnome/shell/ui/status/keyboard.js';
import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

const TASKBAR = 'dash-to-panel@jderose9.github.com';
const ASSISTANT = 'org.mentor.Chat';
const ASSISTANT_COMMAND = '/usr/local/bin/mentor-chat';
// The title of the assistant's text box over the windows (mentor-chat, toggle_ask); its desktop window is "Mentor".
const ASK_TITLE = 'Ask Mentor';

function ask(...args) {
    Gio.Subprocess.new([ASSISTANT_COMMAND, ...args], Gio.SubprocessFlags.NONE);
}

// The assistant's surface: found when its window appears, turned into the desktop.
class DesktopLayer {
    constructor() {
        this._window = null;
        this._cleared = [];  // windows minimized to reveal the desktop
        this._floating = new Set();  // the assistant's text box over the windows (_float)
        this._showWhenReady = false;
        this._waits = new Set();  // timers of _whenTaskbarUp
        this._signals = [
            [global.display, global.display.connect('window-created', (_d, window) => this._watch(window))],
            [global.display, global.display.connect('workareas-changed', () => this._place())],
            [global.window_manager, global.window_manager.connect('confirm-display-change',
                () => this._keepScale())],
            // The assistant is on every workspace, with a conversation for each.
            [global.workspace_manager, global.workspace_manager.connect('active-workspace-changed',
                () => this._tellWorkspace())],
            [global.display, global.display.connect('notify::focus-window', () => this._focusWhenAlone())],
            [global.display, global.display.connect('grab-op-begin', (_d, window, op) => this._holdStill(window, op))],
            [global.display, global.display.connect('grab-op-end', (_d, window) => this._letGo(window))],
            [Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => {
                this._place();
                this._onScreenChanged();
            })],
        ];
        this._screen = this._screenNow();
        this._scaledAt = 0;  // when `mentor scale` was last run, in seconds
        this._matchHostScale();
        for (const actor of global.get_window_actors())
            this._watch(actor.meta_window);
    }

    get window() {
        return this._window;
    }

    // The screen's size in real pixels, and what it is scaled by.
    _screenNow() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return null;
        const scale = global.display.get_monitor_scale(monitor.index);
        return {width: Math.round(monitor.width * scale), height: Math.round(monitor.height * scale), scale};
    }

    // A new size (the window on the host was resized) gets the scale again. The same size
    // with another scale, when it is not `mentor scale` that has just set it, is the user
    // choosing one in Settings: that one is noted, and is the scale from then on.
    _onScreenChanged() {
        const before = this._screen, now = this._screenNow();
        this._screen = now;
        const sameSize = before && now &&
            Math.abs(before.width - now.width) <= 2 && Math.abs(before.height - now.height) <= 2;
        if (!sameSize) {
            this._matchHostScale();
        } else if (Math.abs(before.scale - now.scale) > 0.01 &&
                   GLib.get_monotonic_time() / 1000000 - this._scaledAt > 4) {
            try {
                const dir = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor']);
                GLib.mkdir_with_parents(dir, 0o700);
                GLib.file_set_contents(GLib.build_filenamev([dir, 'scale']), String(now.scale));
            } catch (e) {
                console.warn(`mentor: could not note the chosen scale: ${e.message}`);
            }
        }
    }

    // The desktop is scaled as the host's screen is, to be drawn sharp (`mentor scale`).
    // The shell drops the scale when the resolution changes, hence again after each change,
    // once it has settled. Done here, through the shell's own display settings, the same way as
    // `mentor scale` does it: started as a program it took 1.2 s, during which the user saw the
    // desktop unscaled each time the window was maximized or made full screen (2026-10-17).
    _matchHostScale() {
        if (this._scaleLater)
            GLib.source_remove(this._scaleLater);
        this._scaleLater = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            this._scaleLater = 0;
            this._whenTaskbarUp(() => {
                this._scaledAt = GLib.get_monotonic_time() / 1000000;
                this._applyScale().catch(e => {
                    console.warn(`mentor: scaling directly failed (${e.message}); mentor scale does it`);
                    try {
                        Gio.Subprocess.new(['/usr/local/bin/mentor', 'scale', '--keep'], Gio.SubprocessFlags.NONE);
                    } catch (e2) {
                        console.warn(`mentor: could not match the host's scale: ${e2.message}`);
                    }
                });
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    // `mentor scale` (cmd_scale in /usr/local/bin/mentor) in the shell: the host's scale, or the one the
    // user chose in Settings; the window's own size as the mode (the shell can hold on to the mode kept
    // from another size); of the scales the mode takes, quarter steps first, the largest not above what is
    // wanted. Kept (persistent), and the shell's question about keeping it answered (_keepScale).
    async _applyScale() {
        const read = path => {
            try {
                const [, bytes] = GLib.file_get_contents(path);
                const value = parseFloat(new TextDecoder().decode(bytes));
                return value > 0 ? value : 0;
            } catch {
                return 0;
            }
        };
        let wanted = read('/run/mentor/host-scale');
        if (!wanted)
            return;  // no launcher said anything
        wanted = read(GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'scale'])) || wanted;
        const call = (method, args, type) => Gio.DBus.session.call('org.gnome.Mutter.DisplayConfig',
            '/org/gnome/Mutter/DisplayConfig', 'org.gnome.Mutter.DisplayConfig', method, args,
            type ? new GLib.VariantType(type) : null, Gio.DBusCallFlags.NONE, 5000, null);
        const [serial, monitors, logical] = (await call('GetCurrentState', null,
            '(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})')).recursiveUnpack();
        if (logical.length !== 1)
            throw new Error(`${logical.length} logical monitors`);
        const [x, y, scale, transform, , specs] = logical[0];
        const connector = specs[0][0];
        const monitor = monitors.find(m => m[0][0] === connector);
        const current = monitor?.[1].find(m => m[6]['is-current']);
        if (!current)
            throw new Error('no current mode');
        const target = monitor[1].find(m => m[6]['is-preferred']) ?? current;
        let allowed = target[5].filter(s => Math.abs(s * 4 - Math.round(s * 4)) < 0.01);
        if (!allowed.length)
            allowed = target[5];
        if (!allowed.length)
            throw new Error('the mode lists no scales');
        const fits = allowed.filter(s => s <= wanted + 0.01);
        const chosen = fits.length ? Math.max(...fits)
            : allowed.reduce((a, b) => Math.abs(b - wanted) < Math.abs(a - wanted) ? b : a);
        if (target[0] === current[0] && Math.abs(scale - chosen) < 0.01)
            return;
        GLib.file_set_contents('/run/mentor/scale-kept', '');  // _keepScale answers the question
        await call('ApplyMonitorsConfig', new GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})', [serial, 2,
            [[x, y, chosen, transform, true, [[connector, target[0], {}]]]], {}]), null);
    }

    // A display setting that is to last makes the shell ask the user to confirm it within
    // twenty seconds. For the scale that `mentor scale` has just set there is nothing to
    // ask: answer the question as it comes up. Any other change is left to the user.
    _keepScale() {
        try {
            const info = Gio.File.new_for_path('/run/mentor/scale-kept').query_info(
                'time::modified', Gio.FileQueryInfoFlags.NONE, null);
            if (GLib.get_real_time() / 1000000 - info.get_modification_date_time().to_unix() > 10)
                return;
        } catch {
            return;  // not ours
        }
        for (const dialog of Main.layoutManager.modalDialogGroup.get_children()) {
            if (typeof dialog._onSuccess === 'function' && '_countDown' in dialog)
                dialog._onSuccess();
        }
    }

    // The taskbar starts in steps, and a change of the screen's size or scale in the middle
    // of them leaves it broken until the next login: its bar stays where it was and loses
    // its buttons. So what changes the screen (the scale, and the host showing its window,
    // which it does when told that the desktop is up) waits for the taskbar's panels.
    _whenTaskbarUp(action) {
        let tries = 0;
        const starting = () => global.settings.get_strv('enabled-extensions').includes(TASKBAR) &&
            !global.dashToPanel?.panels?.length && ++tries < 40;
        if (!starting()) {
            action();
            return;
        }
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            if (starting())
                return GLib.SOURCE_CONTINUE;
            this._waits.delete(id);
            action();
            return GLib.SOURCE_REMOVE;
        });
        this._waits.add(id);
    }

    // Nothing else has the keyboard (the session has just started, or the last window was closed): the
    // assistant takes it. On Wayland an app sees Ctrl only while it has the keyboard, so after a restart
    // Ctrl and the mouse wheel did not zoom the chat until the user clicked into it (2026-10-18); the shell
    // cannot help at the wheel itself, which goes to the app's window without passing through here.
    _focusWhenAlone() {
        if (this._focusLater)
            return;
        this._focusLater = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
            this._focusLater = 0;
            const window = this._window;
            if (window && !global.display.focus_window && !Main.overview.visible && !Main.modalCount)
                Main.activateWindow(window);
            return GLib.SOURCE_REMOVE;
        });
    }

    _tellWorkspace() {
        if (!this._window)
            return;
        try {
            ask('--workspace', String(global.workspace_manager.get_active_workspace_index()));
        } catch (e) {
            console.warn(`mentor: could not tell the assistant the workspace: ${e.message}`);
        }
    }

    // A new window says who it belongs to a moment after it is created.
    _watch(window) {
        if (this._adopt(window))
            return;
        const ids = ['notify::wm-class', 'notify::gtk-application-id', 'notify::title'].map(signal =>
            window.connect(signal, () => {
                if (this._adopt(window))
                    ids.forEach(id => window.disconnect(id));
            }));
    }

    // The text box over the windows: above them all, on every workspace, at the bottom
    // of the screen in the middle, and with the keyboard.
    _float(window) {
        const place = () => {
            const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
            const frame = window.get_frame_rect();
            window.move_frame(true, area.x + Math.floor((area.width - frame.width) / 2),
                area.y + area.height - frame.height - 12);
        };
        window.make_above();
        window.stick();
        // Never minimized: the assistant cannot tell (Wayland does not say so), so the box would stay
        // lifted out of the desktop and be seen nowhere, and the desktop had no text box (2026-10-17,
        // after the desktop was revealed while it was up). Esc or the same key puts it away.
        if (!this._floating.has(window)) {
            this._floating.add(window);
            window.connect('unmanaged', () => this._floating.delete(window));
            window.connect('notify::minimized', () => {
                if (window.minimized)
                    window.unminimize();
            });
        }
        window.connect('shown', () => {
            place();
            Main.activateWindow(window);
        });
        window.connect('size-changed', place);
        if (window.get_compositor_private()?.visible) {
            place();
            Main.activateWindow(window);
        }
    }

    _adopt(window) {
        if (window.get_wm_class() !== ASSISTANT && window.get_gtk_application_id() !== ASSISTANT)
            return false;
        // Its surface is a normal window when new, and already a desktop one when this
        // extension is started again while the assistant runs. Anything else is a dialog.
        const type = window.get_window_type();
        if (window === this._window || (type !== Meta.WindowType.NORMAL && type !== Meta.WindowType.DESKTOP))
            return true;
        // The assistant has one more window: its text box, lifted out of the desktop to be
        // shown over whatever is in front (Alt+Space), titled ASK_TITLE. Told apart by that
        // title: telling it by "the desktop is there already" took the assistant itself, started
        // again while its old window was still known here (an update), for the text box, and
        // the desktop became a window that could be moved, always on top.
        if (type === Meta.WindowType.NORMAL && window.get_title() === ASK_TITLE) {
            this._float(window);
            return true;
        }
        if (!window.get_title() && this._window && type === Meta.WindowType.NORMAL) {
            // No title yet: which of the two it is shows a moment later (notify::title, _watch).
            return false;
        }
        if (this._window && this._window !== window) {
            // A new assistant window while one is known: the assistant was started again. The
            // new one is the desktop; the old one, if it is still there, goes as it closes.
            this._window = null;
        }
        this._window = window;
        // A desktop window sits under all others and stays out of the taskbar,
        // Alt+Tab and the overview: mutter does the rest.
        window.set_type(Meta.WindowType.DESKTOP);
        window.stick();
        this._focusWhenAlone();
        window.connect('unmanaged', () => {
            if (this._window !== window)
                return;
            this._window = null;
            // The assistant is the desktop: one that has gone away (it crashed) is started
            // again after a moment, not more than once in a while.
            const id = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 3, () => {
                this._waits.delete(id);
                const now = GLib.get_monotonic_time();
                if (!this._window && now - (this._startedAt ?? 0) > 10 * GLib.USEC_PER_SEC) {
                    this._startedAt = now;
                    try {
                        ask();
                    } catch (e) {
                        console.warn(`mentor: could not start the assistant again: ${e.message}`);
                    }
                }
                return GLib.SOURCE_REMOVE;
            });
            this._waits.add(id);
        });
        // Nothing moves it, makes it smaller or hides it: put back at once. A dialog's header bar
        // inside it (History) acts as the window's title bar, and once dragged the whole desktop
        // aside and offered its window menu (Move, Hide, Always on Top); 2026-10-14.
        for (const signal of ['position-changed', 'size-changed'])
            window.connect(signal, () => this._keepPlace(window));
        window.connect('notify::minimized', () => {
            if (window === this._window && window.minimized)
                window.unminimize();
        });
        window.connect('notify::above', () => {
            if (window === this._window && window.above)
                window.unmake_above();
        });
        // It can only be moved once it has drawn itself for the first time.
        window.connect('shown', () => this._ready());
        if (window.get_compositor_private()?.visible)
            this._ready();
        return true;
    }

    _ready() {
        this._place();
        if (global.workspace_manager.get_active_workspace_index() > 0)
            this._tellWorkspace();
        // The assistant is on the desktop: this start has worked (see mentor_boot.py).
        this._whenTaskbarUp(() => {
            try {
                Gio.File.new_for_path('/run/mentor/desktop-ok').replace_contents(
                    '', null, false, Gio.FileCreateFlags.NONE, null);
            } catch (e) {
                console.warn(`mentor: could not report the desktop as up: ${e.message}`);
            }
        });
        if (this._showWhenReady)
            this.show();
    }

    // A drag that reaches the window manager moves the desktop window, and nothing can stop it once begun
    // (mutter 51 has no call for that, and a dialog of the desktop's, a picture's preview or History, is a
    // window attached to it: dragging around it drags the desktop). So while it is dragged, its picture is
    // shifted back by as much as it moved, in the same frame (_keepPlace, `translation`): on the screen it
    // stays still. When the drag ends it is put back in its place (_letGo). Before, it moved with the mouse
    // and was put back after each step, and it jittered (the user, 2026-10-19).
    _holdStill(window, op) {
        if (window !== this._window)
            return;
        const moves = [Meta.GrabOp.MOVING, Meta.GrabOp.MOVING_UNCONSTRAINED, Meta.GrabOp.KEYBOARD_MOVING];
        if (!moves.includes(op))
            return;
        this._held = true;
        this._holds = (this._holds ?? 0) + 1;
    }

    _letGo(window) {
        if (!this._held || window !== this._window)
            return;
        this._held = false;
        this._place();
        this._shift(window, 0, 0);
    }

    // The desktop's picture and those of its attached dialogs, which move with it
    _shift(window, x, y) {
        const windows = [window];
        window.foreach_transient(child => {
            windows.push(child);
            return true;
        });
        for (const w of windows) {
            const actor = w.get_compositor_private();
            if (actor) {
                actor.translation_x = x;
                actor.translation_y = y;
            }
        }
    }

    // Back where it belongs, once whatever moved it is done (not while it is being dragged).
    _keepPlace(window) {
        if (window !== this._window)
            return;
        const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        const frame = window.get_frame_rect();
        if (this._held) {  // being dragged: still on the screen, put back when it ends
            this._shift(window, area.x - frame.x, area.y - frame.y);
            return;
        }
        if (this._placing)
            return;
        if (frame.x === area.x && frame.y === area.y && frame.width === area.width && frame.height === area.height)
            return;
        if (frame.width === area.width && frame.height === area.height)
            this._putBack = (this._putBack ?? 0) + 1;  // moved, not resized
        this._placing = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._placing = 0;
            this._place();
            return GLib.SOURCE_REMOVE;
        });
    }

    _place() {
        if (!this._window)
            return;
        const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        this._window.move_resize_frame(false, area.x, area.y, area.width, area.height);
    }

    // Reveal the desktop and give it the keyboard.
    show() {
        this._showWhenReady = !this._window;
        if (!this._window) {
            // It is not running: start it, and show it once it is there. Not more than
            // once in a while, since a started assistant asks us to show it in turn.
            const now = GLib.get_monotonic_time();
            if (now - (this._startedAt ?? 0) > 10 * GLib.USEC_PER_SEC) {
                this._startedAt = now;
                ask();
            }
            return;
        }
        const workspace = global.workspace_manager.get_active_workspace();
        const inTheWay = workspace.list_windows().filter(window =>
            window !== this._window && !this._floating.has(window) && !window.minimized && window.showing_on_its_workspace() &&
            window.get_window_type() !== Meta.WindowType.DESKTOP && window.get_window_type() !== Meta.WindowType.DOCK);
        if (inTheWay.length) {
            this._cleared = global.display.sort_windows_by_stacking(inTheWay);
            this._cleared.forEach(window => window.minimize());
        }
        Main.overview.hide();
        this._window.activate(global.get_current_time());
    }

    // Put back the windows that show() cleared away. False if there were none.
    restore() {
        const back = this._cleared.filter(window => window.minimized && window.get_compositor_private());
        this._cleared = [];
        back.forEach(window => window.unminimize());
        back.at(-1)?.activate(global.get_current_time());
        return back.length > 0;
    }

    // Super+A: to the desktop, and back to what was on screen.
    toggle() {
        if (!this._window?.has_focus() || !this.restore())
            this.show();
    }

    destroy() {
        this._signals.forEach(([object, id]) => object.disconnect(id));
        this._waits.forEach(id => GLib.source_remove(id));
        this._waits.clear();
        if (this._scaleLater)
            GLib.source_remove(this._scaleLater);
        this._scaleLater = 0;
        if (this._placing)
            GLib.source_remove(this._placing);
        this._placing = 0;
        if (this._focusLater)
            GLib.source_remove(this._focusLater);
        this._focusLater = 0;
        this._window = null;
    }
}

// What other programs may ask of the shell. On Wayland only the shell can take a
// screenshot without asking each time; Show and Toggle are the way to the desktop.
const SERVICE = `
<node>
  <interface name="org.mentor.Shell">
    <method name="Screenshot">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="written"/>
    </method>
    <method name="ScreenshotArea">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="written"/>
    </method>
    <method name="ScreenshotWindow">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="written"/>
    </method>
    <method name="Show"/>
    <method name="Restore"/>
    <method name="Toggle"/>
    <method name="Ask"/>
    <method name="Status">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="Windows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="FocusWindow">
      <arg type="t" direction="in" name="id"/>
      <arg type="b" direction="out" name="done"/>
    </method>
    <method name="CloseWindow">
      <arg type="t" direction="in" name="id"/>
      <arg type="b" direction="out" name="done"/>
    </method>
    <method name="SetClipboard">
      <arg type="s" direction="in" name="text"/>
    </method>
    <method name="NextInputSource"/>
    <method name="SetClipboardImage">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="done"/>
    </method>
    <method name="PictureMenu">
      <arg type="s" direction="in" name="path"/>
    </method>
    <method name="HostPictureMenu">
      <arg type="s" direction="in" name="path"/>
    </method>
    <method name="AwaitCopy">
      <arg type="s" direction="in" name="pattern"/>
    </method>
  </interface>
</node>`;

// The user's own windows: normal windows and dialogs of every app but Mentor's assistant.
function userWindows() {
    return global.get_window_actors().map(actor => actor.meta_window).filter(window =>
        window && !window.skip_taskbar &&
        [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG].includes(window.get_window_type()) &&
        window.get_wm_class() !== ASSISTANT && window.get_gtk_application_id() !== ASSISTANT);
}

// A size in words: 240 KB, 1.8 MB.
function bytesText(n) {
    return n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

// What to do with a screenshot, in a menu where the pointer is, as soon as it is taken (the user's wish,
// 2026-10-20): copy it, a smaller copy (75%, 50%, 30%: what makes a paste into a web page smaller, for Chromium
// takes only PNG from the clipboard and makes every pasted picture PNG anyway; tested), save it as JPG next to it,
// save it elsewhere (mentor save-picture: a dialog), edit it (Gradia), show it in its folder. DESKTOP.md, "Screenshots".
// The picture menu open now: a newer picture closes it (two Print Screens in a row left two menus, 2026-10-20).
let shownPictureMenu = null;

function pictureMenu(path, fromWindows = false) {
    shownPictureMenu?.close();
    const file = Gio.File.new_for_path(path);
    const picture = GdkPixbuf.Pixbuf.new_from_file(path);
    const [width, height] = [picture.get_width(), picture.get_height()];
    const size = file.query_info('standard::size', Gio.FileQueryInfoFlags.NONE, null).get_size();
    const [x, y] = global.get_pointer();
    const anchor = new St.Widget({x, y, width: 1, height: 1, reactive: false});
    Main.uiGroup.add_child(anchor);
    const menu = new PopupMenu.PopupMenu(anchor, 0, St.Side.TOP);
    const manager = new PopupMenu.PopupMenuManager(anchor);
    manager.addMenu(menu);
    Main.uiGroup.add_child(menu.actor);
    const told = (title, text) => Main.notify(title, text);
    const copy = (bytes, what) => {
        St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'image/png', bytes);
        told('Copied', what);
    };
    const run = argv => {
        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (e) {
            told('That could not be opened', e.message);
        }
    };
    // A picture from Windows (Print Screen, the Snipping Tool) is on the clipboard already and kept only while it
    // is: saving it puts it in Pictures/Screenshots, as Mentor's own screenshots.
    const folder = GLib.build_filenamev([GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) ??
        GLib.build_filenamev([GLib.get_home_dir(), 'Pictures']), 'Screenshots']);
    const stem = fromWindows
        ? GLib.build_filenamev([folder, GLib.DateTime.new_now_local().format('Picture from Windows %Y-%m-%d %H-%M-%S')])
        : path.replace(/\.png$/i, '');
    const keep = () => {  // the picture as a PNG file of its own, for Edit and Save as…
        if (!fromWindows)
            return path;
        GLib.mkdir_with_parents(folder, 0o755);
        if (!GLib.file_test(`${stem}.png`, GLib.FileTest.EXISTS))
            file.copy(Gio.File.new_for_path(`${stem}.png`), Gio.FileCopyFlags.NONE, null, null);
        return `${stem}.png`;
    };
    const heading = new PopupMenu.PopupMenuItem(
        `${fromWindows ? 'Picture from Windows' : 'Screenshot'} · ${width} × ${height} · ${bytesText(size)}`,
        {reactive: false});
    menu.addMenuItem(heading);
    menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    if (!fromWindows)  // a picture from Windows is on the clipboard already
        menu.addAction('Copy', () => copy(file.load_bytes(null)[0], `${width} × ${height}, ${bytesText(size)}`));
    const smaller = new PopupMenu.PopupSubMenuMenuItem('Copy smaller');
    for (const percent of [75, 50, 30]) {
        const w = Math.max(1, Math.round(width * percent / 100)), h = Math.max(1, Math.round(height * percent / 100));
        smaller.menu.addAction(`${percent}% · ${w} × ${h}`, () => {
            const [, data] = picture.scale_simple(w, h, GdkPixbuf.InterpType.HYPER).save_to_bufferv('png', [], []);
            copy(new GLib.Bytes(data), `${w} × ${h}, ${bytesText(data.length)}`);
        });
    }
    menu.addMenuItem(smaller);
    // Copy in format: PNG, JPG or WebP (the user's wish, 2026-10-20). PNG: the picture itself. JPG and WebP go on the clipboard
    // as a file (in ~/.cache/mentor/copied, text/uri-list), the way web pages and Files take them: as a picture
    // (image/jpeg) Chromium pastes nothing; as a file it gets a real .jpg / .webp (tested). Only the newest is kept.
    // WebP by Pillow (python-pillow), quality 85: GdkPixbuf's WebP (glycin) is always lossless, as big as the PNG.
    // A 1280 x 800 screenshot: PNG 1.2 MB, JPG 135 KB, WebP 64 KB.
    const as = new PopupMenu.PopupSubMenuMenuItem('Copy in format');
    as.menu.addAction(`PNG \u00b7 sharpest \u00b7 ${bytesText(size)}`,
        () => copy(file.load_bytes(null)[0], `PNG, ${width} \u00d7 ${height}, ${bytesText(size)}`));
    const copyFile = (name, ext, make) => {
        try {
            const copied = GLib.build_filenamev([GLib.get_user_cache_dir(), 'mentor', 'copied']);
            GLib.mkdir_with_parents(copied, 0o700);
            const old = Gio.File.new_for_path(copied).enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
            for (let info; (info = old.next_file(null));)
                Gio.File.new_for_path(GLib.build_filenamev([copied, info.get_name()])).delete(null);
            const made = GLib.build_filenamev([copied, `${GLib.path_get_basename(stem)}.${ext}`]);
            make(made, () => {
                const bytes = Gio.File.new_for_path(made).query_info('standard::size', Gio.FileQueryInfoFlags.NONE, null).get_size();
                St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'text/uri-list',
                    new GLib.Bytes(new TextEncoder().encode(`${GLib.filename_to_uri(made, null)}\r\n`)));
                told(`Copied as ${name}`, `${width} \u00d7 ${height}, ${bytesText(bytes)}`);
            });
        } catch (e) {
            told(`It could not be copied as ${name}`, e.message);
        }
    };
    as.menu.addAction('JPG \u00b7 smaller', () => copyFile('JPG', 'jpg', (made, done) => {
        picture.savev(made, 'jpeg', ['quality'], ['90']);
        done();
    }));
    as.menu.addAction('WebP \u00b7 smallest', () => copyFile('WebP', 'webp', (made, done) => {
        let source = path;
        if (!GLib.file_test(source, GLib.FileTest.EXISTS)) {  // the picture from Windows, gone with a later copy
            source = made.replace(/\.webp$/, '.png');
            picture.savev(source, 'png', [], []);
        }
        const pillow = Gio.Subprocess.new(['python3', '-I', '-c',
            'import sys; from PIL import Image\n' +
            'im = Image.open(sys.argv[1])\n' +
            'if im.mode != "RGB" and not (im.mode == "RGBA" and im.getchannel("A").getextrema() != (255, 255)):\n' +
            '    im = im.convert("RGB")\n' +
            'im.save(sys.argv[2], "WEBP", quality=85, method=4)', source, made], Gio.SubprocessFlags.STDERR_PIPE);
        pillow.communicate_utf8_async(null, null, (_p, result) => {
            try {
                const [, , err] = pillow.communicate_utf8_finish(result);
                if (!pillow.get_successful())
                    throw new Error(err?.trim().split('\n').pop() || 'Pillow failed');
                done();
            } catch (e) {
                told('It could not be copied as WebP', e.message);
            }
        });
    }));
    menu.addMenuItem(as);
    // The words in the picture, read (OCR) and put on the clipboard as text, as Shift+Super+T does for an area
    // (mentor capture-text --file; the user's wish, 2026-10-20). It tells how it went in a notification.
    menu.addAction('Copy text', () => {
        let source = path;
        if (!GLib.file_test(source, GLib.FileTest.EXISTS)) {  // the picture from Windows, gone with a later copy
            source = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'mentor-picture-text.png']);
            picture.savev(source, 'png', [], []);
        }
        run(['/usr/local/bin/mentor', 'capture-text', '--file', source]);
    });
    menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    // A JPG (quality 90): a screenshot's beside its PNG, a picture from Windows' in Pictures/Screenshots. For a picture
    // from Windows it is the plain "Save" (the user's wish, 2026-10-20: one Save, and a JPG); "Save as…" gives PNG too.
    menu.addAction(fromWindows ? 'Save' : 'Save as JPG', () => {
        const jpg = `${stem}.jpg`;
        try {
            GLib.mkdir_with_parents(folder, 0o755);
            picture.savev(jpg, 'jpeg', ['quality'], ['90']);
            const made = Gio.File.new_for_path(jpg).query_info('standard::size', Gio.FileQueryInfoFlags.NONE, null).get_size();
            told(fromWindows ? 'Saved' : 'Saved as JPG', fromWindows
                ? `${GLib.path_get_basename(jpg)}, ${bytesText(made)}, in Pictures/Screenshots`
                : `${GLib.path_get_basename(jpg)}, ${bytesText(made)} (the PNG was ${bytesText(size)})`);
        } catch (e) {
            told('It could not be saved', e.message);
        }
    });
    menu.addAction('Save as…', () => run(['/usr/local/bin/mentor', 'save-picture', '--folder', folder, path]));
    menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    menu.addAction('Edit', () => run(['systemd-run', '--user', '--scope', '--quiet', '--collect', '--', 'gradia', keep()]));
    if (!fromWindows) {
        menu.addAction('Show in folder', () => run(['nautilus', '--select', path]));
    } else {
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        // Off and on again in Mentor Settings, More choices ("A menu after Print Screen").
        menu.addAction('Don’t show this after Print Screen', () => {
            run(['python3', '-c', 'import sys; sys.path.insert(0, "/usr/local/lib/mentor"); import mentor_settings; ' +
                'mentor_settings.put("picture_menu", False)']);
            told('No more menu after Print Screen', 'Mentor Settings, More choices, brings it back.');
        });
    }
    // Snipped while working in Windows, the menu would wait unseen in Mentor's window: it closes by itself.
    let closing = 0;
    if (fromWindows) {
        closing = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 20, () => {
            closing = 0;
            menu.close();
            return GLib.SOURCE_REMOVE;
        });
    }
    menu.connect('open-state-changed', (_menu, open) => {
        if (!open) {
            if (shownPictureMenu === menu)
                shownPictureMenu = null;
            if (closing)
                GLib.source_remove(closing);
            closing = 0;
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                menu.destroy();
                anchor.destroy();
                return GLib.SOURCE_REMOVE;
            });
        }
    });
    shownPictureMenu = menu;
    menu.open(true);
}

// Mentor's own area picker, in place of GNOME's screenshot overlay: the screen dims a little, the
// pointer is a cross, a box is dragged out. Esc or the right button cancels; a click without
// dragging is the whole screen. Resolves to [x, y, width, height] in stage pixels, or null.
function pickArea() {
    return new Promise(resolve => {
        const shade = new St.Widget({
            reactive: true, can_focus: true, x: 0, y: 0, width: global.stage.width, height: global.stage.height,
            style: 'background-color: rgba(0, 0, 0, 0.28);',
        });
        const box = new St.Widget({
            visible: false,
            style: 'border: 2px solid rgba(255, 255, 255, 0.95); background-color: rgba(255, 255, 255, 0.10);',
        });
        shade.add_child(box);
        Main.uiGroup.add_child(shade);
        shade.set_cursor_type?.(Clutter.CursorType.CROSSHAIR);
        const grab = Main.pushModal(shade);
        let start = null, finished = false;
        const finish = area => {
            if (finished)
                return;
            finished = true;
            Main.popModal(grab);
            shade.destroy();
            resolve(area);
        };
        const span = ([x, y]) => [Math.min(start[0], x), Math.min(start[1], y), Math.abs(x - start[0]), Math.abs(y - start[1])];
        shade.connect('button-press-event', (_actor, event) => {
            if (event.get_button() !== Clutter.BUTTON_PRIMARY)
                finish(null);
            else
                start = event.get_coords();
            return Clutter.EVENT_STOP;
        });
        shade.connect('motion-event', (_actor, event) => {
            if (!start)
                return Clutter.EVENT_PROPAGATE;
            const [x, y, width, height] = span(event.get_coords());
            box.set_position(x, y);
            box.set_size(width, height);
            box.show();
            return Clutter.EVENT_STOP;
        });
        shade.connect('button-release-event', (_actor, event) => {
            if (!start)
                return Clutter.EVENT_STOP;
            const [x, y, width, height] = span(event.get_coords());
            finish(width < 4 || height < 4
                ? [0, 0, global.stage.width, global.stage.height]
                : [Math.round(x), Math.round(y), Math.round(width), Math.round(height)]);
            return Clutter.EVENT_STOP;
        });
        shade.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() === Clutter.KEY_Escape)
                finish(null);
            return Clutter.EVENT_STOP;
        });
        shade.grab_key_focus();
    });
}

class ShellService {
    constructor(desktop, status) {
        this._desktop = desktop;
        this._status = status;
        this._object = Gio.DBusExportedObject.wrapJSObject(SERVICE, this);
        this._object.export(Gio.DBus.session, '/org/mentor/Shell');
    }

    async ScreenshotAsync([path], invocation) {
        try {
            const stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.PRIVATE, null);
            await new Shell.Screenshot().screenshot(false, stream);
            stream.close(null);
            invocation.return_value(new GLib.Variant('(b)', [true]));
        } catch (e) {
            invocation.return_dbus_error('org.mentor.Shell.Error', e.message);
        }
    }

    // An area the user drags out (mentor screenshot --area, Print Screen): false when cancelled.
    async ScreenshotAreaAsync([path], invocation) {
        try {
            const area = await pickArea();
            if (!area) {
                invocation.return_value(new GLib.Variant('(b)', [false]));
                return;
            }
            // The shade is gone: one frame without it before the picture is taken.
            await new Promise(done => GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
                done();
                return GLib.SOURCE_REMOVE;
            }));
            const stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.PRIVATE, null);
            await new Shell.Screenshot().screenshot_area(...area, stream);
            stream.close(null);
            invocation.return_value(new GLib.Variant('(b)', [true]));
        } catch (e) {
            invocation.return_dbus_error('org.mentor.Shell.Error', e.message);
        }
    }

    // The window in front, with its frame (mentor screenshot --window).
    async ScreenshotWindowAsync([path], invocation) {
        try {
            const stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.PRIVATE, null);
            await new Shell.Screenshot().screenshot_window(true, false, stream);
            stream.close(null);
            invocation.return_value(new GLib.Variant('(b)', [true]));
        } catch (e) {
            invocation.return_dbus_error('org.mentor.Shell.Error', e.message);
        }
    }

    Show() {
        this._desktop?.show();
    }

    Restore() {
        this._desktop?.restore();
    }

    Toggle() {
        this._desktop?.toggle();
    }

    // The assistant's text box, brought up over whatever is in front (see ASK_WINDOW below).
    Ask() {
        ask('--ask');
    }

    // Which parts of Mentor in the shell are working (see `mentor doctor`, /etc/mentor/DESKTOP.md).
    Status() {
        return JSON.stringify(this._status());
    }

    // The windows the user has open, in words: the agent's way to know that an app it opened is
    // really there (a picture of the screen does not reach every model). Mentor's own are left out.
    Windows() {
        const tracker = Shell.WindowTracker.get_default();
        const focused = global.display.get_focus_window();
        return JSON.stringify(userWindows().map(window => ({
            id: window.get_id(),
            title: window.get_title() ?? '',
            app: tracker.get_window_app(window)?.get_id() ?? '',
            name: tracker.get_window_app(window)?.get_name() ?? '',
            focused: window === focused,
            minimized: window.minimized,
            workspace: window.get_workspace()?.index() ?? -1,
        })));
    }

    FocusWindow(id) {
        const window = userWindows().find(w => w.get_id() === Number(id));
        if (!window)
            return false;
        Main.activateWindow(window);
        return true;
    }

    // As the window's own close button: the app may still ask about unsaved work.
    CloseWindow(id) {
        const window = userWindows().find(w => w.get_id() === Number(id));
        if (!window)
            return false;
        window.delete(global.get_current_time());
        return true;
    }

    // Text onto the clipboard for a program with no window to hold it (`mentor capture-text`, the
    // screen_text tool): GNOME offers no data-control protocol, so wl-copy cannot do it there.
    SetClipboard(text) {
        St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
    }

    // A picture copied on Windows, onto the clipboard by the shell itself (mentor-clipboard calls this with
    // the PNG it keeps). Held by mentor-clipboard, an X11 program, a picture over about 256 KB never reached
    // Wayland programs: Chromium waited for it and its page hung ("Page Unresponsive", the user pasting a
    // screenshot into a forum, 2026-10-19). Held by the shell, every program gets it whole. Only a PNG.
    SetClipboardImage(path) {
        try {
            const [, contents] = Gio.File.new_for_path(path).load_contents(null);
            const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
            if (contents.length < 8 || png.some((b, i) => contents[i] !== b))
                return false;
            St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'image/png',
                new GLib.Bytes(contents));
            return true;
        } catch (e) {
            console.error(`mentor: SetClipboardImage: ${e.message}`);
            return false;
        }
    }

    // Alt+Shift, as on Windows (mentor-emergency-key, which reads the keyboards, calls this when the two
    // are pressed and let go with no other key): the next keyboard layout, as GNOME's own layout-switch
    // keys do. GNOME's Alt+Shift option switches on press and took Alt+Shift+Tab and Alt+Shift+F along.
    NextInputSource() {
        const manager = getInputSourceManager();
        if (Object.keys(manager.inputSources).length > 1)
            manager._modifiersSwitcher();
    }

    // A screenshot just taken: the menu of what to do with it, where the pointer is (mentor screenshot).
    PictureMenu(path) {
        try {
            pictureMenu(path);
        } catch (e) {
            console.error(`mentor: PictureMenu: ${e.message}`);
            Gio.Subprocess.new(['systemd-run', '--user', '--scope', '--quiet', '--collect', '--', 'gradia', path],
                Gio.SubprocessFlags.NONE);
        }
    }

    // A picture that came from Windows (Print Screen): the same menu (mentor-clipboard, when picture_menu is on).
    HostPictureMenu(path) {
        try {
            pictureMenu(path, true);
        } catch (e) {
            console.error(`mentor: HostPictureMenu: ${e.message}`);
        }
    }

    // The key card's "Open NVIDIA's page" (mentor-chat, show_connect): the page opens over the desktop and
    // hides the card (the user, 2026-10-19). Until text that matches PATTERN (a JavaScript regular
    // expression, the whole of it) is copied, or for 15 minutes, the clipboard is watched here, where a copy
    // in any program is seen (a window not in front hears of none on Wayland); then the desktop comes to
    // the front as with Super+A, and the card, in front again, takes the key from the clipboard itself.
    // The text is only compared here, never kept or sent on. A second call replaces the first.
    AwaitCopy(pattern) {
        this._stopAwaiting?.();
        let match;
        try {
            match = new RegExp(`^(?:${pattern})$`);
        } catch (e) {
            return;
        }
        const selection = global.display.get_selection();
        const stop = () => {
            selection.disconnect(watch);
            GLib.source_remove(timeout);
            this._stopAwaiting = null;
        };
        const watch = selection.connect('owner-changed', (_selection, type) => {
            if (type !== Meta.SelectionType.SELECTION_CLIPBOARD)
                return;
            St.Clipboard.get_default().get_text(St.ClipboardType.CLIPBOARD, (_clipboard, text) => {
                if (this._stopAwaiting === stop && text && match.test(text.trim())) {
                    stop();
                    this.Show();
                }
            });
        });
        const timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 15 * 60, () => {
            selection.disconnect(watch);
            this._stopAwaiting = null;
            return GLib.SOURCE_REMOVE;
        });
        this._stopAwaiting = stop;
    }

    destroy() {
        this._stopAwaiting?.();
        this._object.unexport();
    }
}

// Both switches change the panel the menu hangs from, so the menu closes first.
function afterClosingMenu(action) {
    Main.panel.statusArea.quickSettings?.menu.close();
    GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
        action();
        return GLib.SOURCE_REMOVE;
    });
}

// The VM's window belongs to the launcher on the host. The switch asks it to flip the
// window, and is on when the launcher says the window is full screen: it reports that
// to the clipboard service, which keeps it in a file.
const FULL_SCREEN = '/run/mentor/fullscreen';
const FullScreenToggle = GObject.registerClass(
class FullScreenToggle extends QuickToggle {
    constructor() {
        super({title: 'Full Screen', subtitle: 'Ctrl+Alt+F', iconName: 'view-fullscreen-symbolic'});
        this.connect('clicked', () => afterClosingMenu(() =>
            Gio.Subprocess.new(['/usr/local/bin/mentor', 'window', 'toggle'], Gio.SubprocessFlags.NONE)));
        this._file = Gio.File.new_for_path(FULL_SCREEN);
        this._monitor = this._file.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._changed = this._monitor.connect('changed', () => this._sync());
        this._sync();
    }

    _sync() {
        let on = false;
        try {
            on = new TextDecoder().decode(this._file.load_contents(null)[1]).trim() === '1';
        } catch {
            // not said yet, or no launcher that says it
        }
        this.checked = on;
    }

    destroy() {
        this._monitor.disconnect(this._changed);
        this._monitor.cancel();
        super.destroy();
    }
});

// The game mouse (DESKTOP.md, "The game mouse"): the launcher gives the system inside a pointer
// that only moves, which games need to turn the view while they hold the pointer, instead of the
// one that follows where the pointer is on the host. It is asked for while an app marked as a game
// (Categories=Game in its desktop file, or listed in the settings) is in front and the overview is
// not, and given back otherwise. The settings (`mentor game-mouse`, the game_mouse tool) can make
// it always or never. Each request is `mentor game-mouse --send`, one at a time.
const GAME_MOUSE_SETTINGS = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'game-mouse.json']);
class GameMouse {
    constructor() {
        this._file = Gio.File.new_for_path(GAME_MOUSE_SETTINGS);
        this._monitor = this._file.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._overview = false;
        this._sent = null;  // what the launcher was last asked for; null: nothing yet
        this._busy = false;
        this._signals = [
            [this._monitor, this._monitor.connect('changed', () => this._read())],
            [global.display, global.display.connect('notify::focus-window', () => this._sync())],
            [Main.overview, Main.overview.connect('showing', () => {
                this._overview = true;
                this._sync();
            })],
            [Main.overview, Main.overview.connect('hiding', () => {
                this._overview = false;
                this._sync();
            })],
        ];
        this._read();
    }

    _read() {
        this._settings = {mode: 'auto', games: []};
        try {
            Object.assign(this._settings, JSON.parse(new TextDecoder().decode(this._file.load_contents(null)[1])));
        } catch {
            // none yet: auto
        }
        this._sync();
    }

    _front() {
        const window = global.display.focus_window;
        return window ? Shell.WindowTracker.get_default().get_window_app(window) : null;
    }

    _wanted(app) {
        if (this._settings.mode === 'on' || this._settings.mode === 'off')
            return this._settings.mode === 'on';
        if (!app || this._overview)
            return false;
        const categories = (app.get_app_info()?.get_categories() ?? '').split(';');
        return categories.includes('Game') || (this._settings.games ?? []).includes(app.get_id());
    }

    _sync() {
        if (this._busy)
            return;  // looked at again when the request under way is done
        const app = this._front();
        const on = this._wanted(app);
        if (on === this._sent)  // the first look always asks: a launcher left on the game mouse by an earlier session
            return;
        this._busy = true;
        this._send(on, app?.get_id() ?? '', () => {
            this._busy = false;
            this._sent = on;
            if (!this._gone)
                this._sync();
        });
    }

    _send(on, front, done) {
        try {
            const process = Gio.Subprocess.new(['/usr/local/bin/mentor', 'game-mouse', '--send', on ? 'on' : 'off',
                '--front', front], Gio.SubprocessFlags.NONE);
            process.wait_async(null, () => done?.());
        } catch (e) {
            console.error(`mentor: game mouse: ${e.message}`);
            done?.();
        }
    }

    destroy() {
        this._gone = true;
        for (const [object, id] of this._signals)
            object.disconnect(id);
        this._monitor.cancel();
        if (this._sent)  // the desktop's pointer back, as the lock screen and the next session expect it
            this._send(false, '', null);
    }
}

// On: a permanent taskbar at the bottom. Off: stock GNOME.
const TaskbarToggle = GObject.registerClass(
class TaskbarToggle extends QuickToggle {
    constructor() {
        super({title: 'Taskbar', iconName: 'view-continuous-symbolic'});
        this._settings = new Gio.Settings({schema_id: 'org.gnome.shell'});
        this._changed = this._settings.connect('changed::enabled-extensions', () => this._sync());
        this._sync();
        this.connect('clicked', () => {
            const enable = !this.checked;
            afterClosingMenu(() => {
                if (enable)
                    Main.extensionManager.enableExtension(TASKBAR);
                else
                    Main.extensionManager.disableExtension(TASKBAR);
            });
        });
    }

    _sync() {
        this.checked = this._settings.get_strv('enabled-extensions').includes(TASKBAR);
    }

    destroy() {
        this._settings.disconnect(this._changed);
        super.destroy();
    }
});

const Indicator = GObject.registerClass(
class Indicator extends SystemIndicator {
    constructor() {
        super();
        this.quickSettingsItems.push(new FullScreenToggle(), new TaskbarToggle());
    }

    destroy() {
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

// Whatever is typed in the overview can be handed to the assistant: one result,
// "Ask Mentor", that takes the typed text to the desktop as the request.
class AskProvider {
    constructor(app) {
        this.id = 'mentor';
        this.appInfo = app.get_app_info();
        this.isRemoteProvider = false;
        this.canLaunchSearch = false;
        this._icon = app.get_icon();
    }

    // The id carries the text: the shell caches a result's name and description by id.
    async getInitialResultSet(terms) {
        const query = terms.join(' ').trim();
        return query.length >= 4 ? [`ask:${query}`] : [];
    }

    getSubsearchResultSet(_previous, terms) {
        return this.getInitialResultSet(terms);
    }

    async getResultMetas(ids) {
        return ids.map(id => ({
            id,
            name: 'Ask Mentor',
            description: id.slice('ask:'.length),
            createIcon: size => new St.Icon({gicon: this._icon, icon_size: size}),
        }));
    }

    filterResults(results, maxNumber) {
        return results.slice(0, maxNumber);
    }

    activateResult(_id, terms) {
        ask(terms.join(' '));
    }

    launchSearch() {}

    createResultObject() {
        return null;
    }
}

// True when nothing draws the screen but the processor: a virtio-gpu without 3D (its feature bit 0,
// VIRTIO_GPU_F_VIRGL, is off in /sys/bus/virtio/devices/*/features), or no render node of any GPU
// driver at all (/dev/dri/renderD*).
function drawnWithoutGraphicsCard() {
    const read = path => {
        try {
            return new TextDecoder().decode(GLib.file_get_contents(path)[1]).trim();
        } catch (e) {
            return '';
        }
    };
    const list = path => {
        try {
            const names = [];
            const children = Gio.File.new_for_path(path).enumerate_children('standard::name', 0, null);
            let info;
            while ((info = children.next_file(null)))
                names.push(info.get_name());
            return names;
        } catch (e) {
            return [];
        }
    };
    if (!list('/dev/dri').some(name => name.startsWith('renderD')))
        return true;
    for (const device of list('/sys/bus/virtio/devices')) {
        let driver = '';
        try {
            driver = GLib.file_read_link(`/sys/bus/virtio/devices/${device}/driver`);
        } catch (e) {}  // a device without a driver
        if (driver.endsWith('/virtio_gpu') && !read(`/sys/bus/virtio/devices/${device}/features`).startsWith('1'))
            return true;
    }
    return false;
}

export default class MentorExtension extends Extension {
    // The parts are set up one by one. One that a new version of the shell has broken is
    // noted and left out; the others still work, and `mentor doctor` says which is which.
    // What each part is for, what of the shell it leans on and how to tell that it works
    // is written down in /etc/mentor/DESKTOP.md: keep the two in step.
    _part(name, setUp) {
        try {
            const undo = setUp();
            this._undo.push(undo);
            this._parts[name] = 'ok';
        } catch (e) {
            this._parts[name] = `broken: ${e.message}`;
            console.error(`mentor: the part "${name}" could not be set up: ${e.message}\n${e.stack}`);
        }
    }

    _status() {
        return {
            shell: Config.PACKAGE_VERSION,
            parts: this._parts,
            // a window known as the desktop, and one that really is one (not a window that can be moved)
            assistant_on_desktop: this._desktop?.window?.get_window_type() === Meta.WindowType.DESKTOP,
            // times the desktop was moved (by a drag that reached the window manager) and put back
            // (_keepPlace): it should stay 0 (DESKTOP.md, "The desktop cannot be moved")
            desktop_put_back: this._desktop?._putBack ?? 0,
            // drags of the desktop held still on the screen (_holdStill)
            desktop_drags_held: this._desktop?._holds ?? 0,
            taskbar_panels: global.dashToPanel?.panels?.length ?? 0,
            // whether the shell animates now, and why not when it does not (DESKTOP.md, "Animations")
            animations: St.Settings.get().enable_animations ? 'on'
                : this._animationsHeld ? 'held back: no graphics card draws the screen' : 'off in the settings',
        };
    }

    enable() {
        this._parts = {};
        this._undo = [];
        this._desktop = null;

        // Animations are on (00-mentor), except where the screen is drawn without a graphics card: there
        // the processor draws each frame and they make the desktop feel slow. That is the launcher's
        // Graphics card switch off (virtio-gpu without 3D), or no GPU driver at all. A real graphics card,
        // in the VM or on a PC of its own, keeps them. The user's own setting is not touched: the shell
        // holds them back for this session only. DESKTOP.md, "Animations".
        this._part('animations', () => {
            this._animationsHeld = drawnWithoutGraphicsCard();
            if (!this._animationsHeld)
                return () => {};
            St.Settings.get().inhibit_animations();
            return () => {
                St.Settings.get().uninhibit_animations();
                this._animationsHeld = false;
            };
        });

        this._part('desktop', () => {
            this._desktop = new DesktopLayer();
            // No window menu for the desktop: a right click on a dialog inside it (History) offered
            // Move, Hide, Always on Top and Close for the whole desktop (2026-10-14).
            const injections = new InjectionManager();
            const desktop = this._desktop;
            injections.overrideMethod(Main.wm._windowMenuManager, 'showWindowMenuForWindow', original => function (window, ...rest) {
                if (window && window === desktop.window)
                    return;
                original.call(this, window, ...rest);
            });
            return () => {
                injections.clear();
                this._desktop.destroy();
                this._desktop = null;
            };
        });

        this._part('service', () => {
            const service = new ShellService(this._desktop, () => this._status());
            return () => service.destroy();
        });

        // A session starts on the desktop, where the assistant is, not in the overview.
        // The taskbar means to see to that as well, but starts too late to do it every time;
        // and the shell may be through with starting, overview and all, before it gets here.
        this._part('start on the desktop', () => {
            let startup = 0, later = 0;
            const leaveOverview = () => {
                Main.overview.hide();
                later = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1500, () => {
                    later = 0;
                    Main.overview.hide();
                    return GLib.SOURCE_REMOVE;
                });
            };
            if (Main.layoutManager._startingUp) {
                startup = Main.layoutManager.connect('startup-complete', () => {
                    Main.layoutManager.disconnect(startup);
                    startup = 0;
                    leaveOverview();
                });
            } else if (global.get_window_actors().length === 0) {  // nothing open yet: the session is new
                leaveOverview();
            }
            return () => {
                if (startup)
                    Main.layoutManager.disconnect(startup);
                if (later)
                    GLib.source_remove(later);
            };
        });

        this._part('system menu switches', () => {
            const indicator = new Indicator();
            Main.panel.statusArea.quickSettings.addExternalIndicator(indicator);
            return () => indicator.destroy();
        });

        this._part('game mouse', () => {
            const gameMouse = new GameMouse();
            return () => gameMouse.destroy();
        });

        // In the app grid, a click on the empty space around the icons leaves it, as a click
        // beside the windows leaves the overview. Not the click that closes an open folder.
        // Space in Files: the preview (Sushi, org.gnome.NautilusPreviewer) shows its window only once it has
        // started, which for a big file, or its first time, took long enough to wonder whether Space did
        // anything (the user, 2026-10-19). Files' request (ShowFile on org.gnome.NautilusPreviewer2) is seen
        // through dbus-monitor; if no preview window has come a quarter of a second later, a card "Opening
        // preview…" with a spinner shows over the window in front, until the preview's window comes (or 20 s).
        this._part('preview wait', () => {
            const PREVIEWER = /nautiluspreviewer|sushi/i;
            const isPreview = window => window && (PREVIEWER.test(window.get_wm_class() ?? '') ||
                PREVIEWER.test(window.get_gtk_application_id() ?? ''));
            let card = null, spinner = null, later = 0, giveUp = 0;
            const hide = () => {
                if (later)
                    GLib.source_remove(later);
                if (giveUp)
                    GLib.source_remove(giveUp);
                later = giveUp = 0;
                spinner?.stop();
                card?.destroy();
                card = spinner = null;
            };
            const show = () => {
                later = 0;
                if (global.display.list_all_windows().some(isPreview))
                    return GLib.SOURCE_REMOVE;  // it is already there (Space again closes it)
                spinner = new Spinner(24);
                const label = new St.Label({text: 'Opening preview…', y_align: Clutter.ActorAlign.CENTER});
                card = new St.BoxLayout({style: 'background-color: rgba(30, 30, 33, 0.92); color: #ffffff; ' +
                    'border-radius: 14px; padding: 14px 20px; spacing: 12px; font-weight: bold;'});
                card.add_child(spinner);
                card.add_child(label);
                Main.layoutManager.addTopChrome(card);
                const front = global.display.focus_window;
                const area = front ? front.get_frame_rect()
                    : Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
                const [, width] = card.get_preferred_width(-1);
                const [, height] = card.get_preferred_height(-1);
                card.set_position(Math.round(area.x + (area.width - width) / 2), Math.round(area.y + (area.height - height) / 2));
                spinner.play();
                // A new window's class is set after it is made (window-created came too early to tell, tested
                // 2026-10-19): look every 0.3 s while the card shows, 20 s at most.
                let looks = 0;
                giveUp = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
                    if (++looks < 67 && !global.display.list_all_windows().some(isPreview))
                        return GLib.SOURCE_CONTINUE;
                    giveUp = 0;
                    hide();
                    return GLib.SOURCE_REMOVE;
                });
                return GLib.SOURCE_REMOVE;
            };
            // dbus-monitor prints each request it sees; one line with "member=ShowFile" is one Space
            const monitor = Gio.Subprocess.new(['dbus-monitor', '--session',
                "type='method_call',interface='org.gnome.NautilusPreviewer2',member='ShowFile'"],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            const lines = new Gio.DataInputStream({base_stream: monitor.get_stdout_pipe()});
            const cancel = new Gio.Cancellable();
            const read = () => lines.read_line_async(GLib.PRIORITY_DEFAULT, cancel, (stream, result) => {
                let line;
                try {
                    [line] = stream.read_line_finish_utf8(result);
                } catch (e) {
                    return;  // cancelled, or dbus-monitor ended
                }
                if (line === null)
                    return;
                if (line.includes('member=ShowFile') && !later && !card)
                    later = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, show);
                read();
            });
            read();
            return () => {
                cancel.cancel();
                monitor.force_exit();
                hide();
            };
        });

        // Every app in the app grid (Show Apps), the ones pinned to the taskbar too: GNOME leaves out the
        // favorites (Files, Chromium, Console), as its dash shows them, and the user looked for them in vain
        // (2026-10-19). While the grid and its folders list their apps (_loadApps), they are told that no app
        // is a favorite; pinning, the taskbar and the right-click menus are untouched.
        this._part('pinned apps in the grid', () => {
            const grid = Main.overview._overview.controls.appDisplay ?? Main.overview._overview._controls?.appDisplay;
            if (!grid?._loadApps)
                throw new Error('the app grid has no _loadApps');
            const injections = new InjectionManager();
            const wrapped = new Set();
            const unpinned = (view, run) => {
                const favorites = view._appFavorites;
                view._appFavorites = Object.create(favorites, {isFavorite: {value: () => false}});
                try {
                    return run();
                } finally {
                    view._appFavorites = favorites;
                }
            };
            const wrap = proto => {
                if (!proto?._loadApps || wrapped.has(proto))
                    return;
                wrapped.add(proto);
                injections.overrideMethod(proto, '_loadApps', original => function (...args) {
                    return unpinned(this, () => original.call(this, ...args));
                });
            };
            const appDisplay = Object.getPrototypeOf(grid);
            wrap(appDisplay);
            // Dragging a pinned app inside the grid: GNOME takes it for one dragged from the dash, makes a
            // stand-in icon for it ("is not part of the IconGridLayout") and, on the drop, unpins it from the
            // taskbar (found 2026-10-19). An icon that is the grid's own is not a favorite there either; one
            // dragged in from the taskbar is still handled as GNOME does.
            for (const method of ['_onDragBegin', 'acceptDrop']) {
                if (!appDisplay[method])
                    continue;
                injections.overrideMethod(appDisplay, method, original => function (...args) {
                    const source = method === 'acceptDrop' ? args[0] : args[1];
                    const own = source?.id && this._items?.get?.(source.id) === source;
                    return own ? unpinned(this, () => original.call(this, ...args)) : original.call(this, ...args);
                });
            }
            // A folder's picture (its first four apps, drawn when the folder's own settings change) could
            // stay without the pinned apps while the folder itself listed them all: the user's new folder showed
            // only Gradia of Bitwarden, Chromium and Gradia (2026-10-19; not reproduced, so whatever the cause).
            // Each time a folder lists its apps again, its picture is drawn again from that list.
            const folderView = Object.getPrototypeOf(grid._folderIcons?.[0]?.view ?? {});
            if (folderView?._redisplay && folderView !== appDisplay) {
                injections.overrideMethod(folderView, '_redisplay', original => function (...args) {
                    const result = original.call(this, ...args);
                    grid._folderIcons?.find(icon => icon.view === this)?.icon?.update?.();
                    return result;
                });
            }
            wrap(folderView);  // FolderView, not exported
            grid._redisplay();
            // a folder view made after this (the first folder of a new layout) is a FolderView too
            if (!wrapped.size || wrapped.size < 2) {
                wrap(Object.getPrototypeOf(grid._folderIcons?.[0]?.view ?? {}));
                grid._redisplay();
            }
            return () => {
                injections.clear();
                grid._redisplay();
            };
        });

        // The pointer no larger than the virtual graphics card's own pointer can hold (64 by 64 pixels): past
        // that GNOME draws it into the picture itself ("Can't handle cursor size 72x72"), and in Mentor's
        // window the card's last pointer stayed beside it, two pointers (the user, size 48 at 150%,
        // 2026-10-19). While the scale makes the chosen size too large, the next smaller one is used; the
        // chosen one comes back with a smaller scale. The user's choice is kept in ~/.config/mentor/pointer-size
        // (Mentor Settings, Pointer writes it; a change made elsewhere is taken as the new choice). Only on the
        // virtual card (virtio_gpu): a real one has a larger pointer plane, or none of this trouble.
        this._part('pointer fits', () => {
            if (!GLib.file_test('/sys/module/virtio_gpu', GLib.FileTest.IS_DIR))
                return () => {};
            const SIZES = [24, 30, 36, 48, 72, 96];
            const LARGEST = 64;
            const settings = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
            const path = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'pointer-size']);
            const chosen = () => {
                try {
                    const size = parseInt(new TextDecoder().decode(GLib.file_get_contents(path)[1]));
                    if (size > 0)
                        return size;
                } catch (e) {}
                return null;
            };
            const choose = size => {
                GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o755);
                GLib.file_set_contents(path, `${size}\n`);
            };
            let ours = null;  // the size set here, told apart from one the user set
            const fit = () => {
                let scale = 1;
                for (let i = 0; i < global.display.get_n_monitors(); i++)
                    scale = Math.max(scale, global.display.get_monitor_scale(i));
                const want = chosen() ?? settings.get_int('cursor-size');
                const size = SIZES.filter(s => s <= want && s * scale <= LARGEST).pop() ?? SIZES[0];
                if (settings.get_int('cursor-size') !== size) {
                    ours = size;
                    settings.set_int('cursor-size', size);
                }
            };
            if (chosen() === null)
                choose(settings.get_int('cursor-size'));
            const changed = settings.connect('changed::cursor-size', () => {
                const size = settings.get_int('cursor-size');
                if (size === ours)
                    return;
                choose(size);  // the user's own change (GNOME Settings, Accessibility; or Mentor Settings)
                fit();
            });
            const monitors = Main.layoutManager.connect('monitors-changed', fit);
            fit();
            // The fitted size stays when the part stops: it stops at every screen lock, where the chosen one
            // would bring the two pointers back.
            return () => {
                settings.disconnect(changed);
                Main.layoutManager.disconnect(monitors);
            };
        });

        this._part('app grid click', () => {
            const grid = Main.overview._overview?.controls?.appDisplay;
            if (!grid)
                throw new Error('the app grid is not where it was (Main.overview._overview.controls.appDisplay)');
            let folderWasOpen = false;
            const press = grid.connect('captured-event', (_actor, event) => {
                if (event.type() === Clutter.EventType.BUTTON_PRESS)
                    folderWasOpen = !!grid._currentDialog;
                return Clutter.EVENT_PROPAGATE;
            });
            const leave = () => {
                if (!folderWasOpen && !grid._currentDialog)
                    Main.overview.hide();
            };
            let click;
            if (Clutter.ClickGesture) {
                click = new Clutter.ClickGesture();
                click.connect('recognize', leave);
            } else {
                click = new Clutter.ClickAction();
                click.connect('clicked', leave);
            }
            grid.add_action(click);
            return () => {
                grid.disconnect(press);
                grid.remove_action(click);
            };
        });

        this._part('search', () => {
            const assistant = Shell.AppSystem.get_default().lookup_app(`${ASSISTANT}.desktop`);
            if (!assistant)
                throw new Error(`${ASSISTANT}.desktop is not installed`);
            const search = new AskProvider(assistant);
            Main.overview.searchController.addProvider(search);
            return () => Main.overview.searchController.removeProvider(search);
        });

        // AppMenu is the menu behind app icons in the dash, the app grid and the
        // taskbar. Each one gets the item the first time it opens.
        this._part('app menus', () => {
            const items = new Set();
            const injections = new InjectionManager();
            injections.overrideMethod(AppMenu.prototype, 'open', original => function (...args) {
                if (!this._mentorItem) {
                    this._mentorItem = this.addAction('Ask Mentor…', () => {
                        Main.overview.hide();
                        ask('--app', this._app.get_id());
                    });
                    this._mentorItem.connect('destroy', () => items.delete(this._mentorItem));
                    items.add(this._mentorItem);
                }
                this._mentorItem.visible = this._app !== null;
                return original.call(this, ...args);
            });
            return () => {
                injections.clear();
                items.forEach(item => item.destroy());
            };
        });

        // The taskbar in the tone of the user's window colors (mentor_colors.py writes it into
        // ~/.config/mentor/taskbar-color: "#f3ebcf light"), only while GNOME's style is the set's own:
        // switched to dark by hand on a light set, the taskbar's text turned light on the light tone and
        // could not be read (2026-10-18). Then the taskbar has GNOME's own colors until the style matches
        // again. Dash to Panel's own settings, trans-use-custom-bg and trans-bg-color. DESKTOP.md, "Window colors".
        this._part('taskbar color', () => {
            const note = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'taskbar-color']);
            const style = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
            const source = Gio.SettingsSchemaSource.get_default();
            if (!source.lookup('org.gnome.shell.extensions.dash-to-panel', true))
                return () => {};  // no Dash to Panel: nothing to color
            const taskbar = new Gio.Settings({schema_id: 'org.gnome.shell.extensions.dash-to-panel'});
            const sync = () => {
                let wanted = null;
                try {
                    const [color, kind] = new TextDecoder().decode(GLib.file_get_contents(note)[1]).trim().split(/\s+/);
                    wanted = {color, light: kind === 'light'};
                } catch (e) {
                    lightBar = false;  // no set of Mentor's: the taskbar is the user's or GNOME's, left alone
                    mark();
                    lines();
                    return;
                }
                const light = style.get_string('color-scheme') === 'prefer-light';
                const use = wanted.light === light;
                if (use && taskbar.get_string('trans-bg-color') !== wanted.color)
                    taskbar.set_string('trans-bg-color', wanted.color);
                if (taskbar.get_boolean('trans-use-custom-bg') !== use)
                    taskbar.set_boolean('trans-use-custom-bg', use);
                lightBar = use && wanted.light;
                mark();
                lines();
            };
            // The line under an open app (Dash to Panel's "running indicator") and the shade behind the one in
            // front are light by default and could not be seen on a light tone (the user, 2026-10-19): dark on
            // it, Dash to Panel's own again otherwise; only Mentor's values are put back, never the user's own.
            const DARK = '#3d3d3d';
            const DOTS = [1, 2, 3, 4].flatMap(n => [`dot-color-${n}`, `dot-color-unfocused-${n}`]);
            const lines = () => {
                if (lightBar) {
                    for (const key of DOTS) {
                        if (taskbar.get_string(key) !== DARK)
                            taskbar.set_string(key, DARK);
                    }
                    if (!taskbar.get_boolean('dot-color-override'))
                        taskbar.set_boolean('dot-color-override', true);
                    if (taskbar.get_string('focus-highlight-color') !== '#000000')
                        taskbar.set_string('focus-highlight-color', '#000000');
                    if (taskbar.get_int('focus-highlight-opacity') !== 12)
                        taskbar.set_int('focus-highlight-opacity', 12);
                } else if (taskbar.get_string('dot-color-1') === DARK) {
                    for (const key of [...DOTS, 'dot-color-override', 'focus-highlight-color', 'focus-highlight-opacity'])
                        taskbar.reset(key);
                }
            };
            // A light tone: its text stays dark in the overview too (Show Apps). The taskbar is GNOME's own
            // panel (#panel), which the overview gives white text (#panel:overview, for its dark background):
            // on the light tone it could not be read (the user, 2026-10-19). The class is what
            // stylesheet-light.css darkens; Dash to Panel makes its panels anew now and then (panels-created).
            let lightBar = false;
            const mark = () => {
                for (const panel of global.dashToPanel?.panels ?? []) {
                    if (panel.panel?.add_style_class_name)
                        (lightBar ? panel.panel.add_style_class_name : panel.panel.remove_style_class_name)
                            .call(panel.panel, 'mentor-light-taskbar');
                }
            };
            const remade = global.dashToPanel?.connect?.('panels-created', mark) ?? 0;
            const changed = style.connect('changed::color-scheme', sync);
            // another set of the same style (Cream to GNOME light) leaves the style as it was: the note says it
            const watch = Gio.File.new_for_path(note).monitor_file(Gio.FileMonitorFlags.NONE, null);
            const noted = watch.connect('changed', () => sync());
            sync();
            return () => {
                watch.disconnect(noted);
                watch.cancel();
                style.disconnect(changed);
                if (remade)
                    global.dashToPanel?.disconnect?.(remade);
                lightBar = false;
                mark();
                lines();
            };
        });

        // While a set of Mentor's Window colors is in use, GNOME's light or dark style is the set's own:
        // a change of it from anywhere else (Settings, Appearance, Style; a command) is put back, and the
        // quick menu's "Dark Style" switch, which would only spring back, is hidden. Switched by hand,
        // windows, taskbar and menus no longer matched (the user's wish, 2026-10-19: "ignore whatever the
        // user clicks"). With GNOME's own sets (no ~/.config/mentor/taskbar-color) the style is free as in
        // GNOME. mentor_colors.apply writes that file before it changes the style. DESKTOP.md, "Window colors".
        this._part('keep style', () => {
            const note = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'taskbar-color']);
            const style = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
            const toggle = Main.panel.statusArea.quickSettings?._darkMode?.quickSettingsItems?.[0] ?? null;
            let pending = 0, told = 0;
            const kind = () => {
                try {
                    return new TextDecoder().decode(GLib.file_get_contents(note)[1]).trim().split(/\s+/)[1] ?? null;
                } catch (e) {
                    return null;  // GNOME's own colors: the style is the user's
                }
            };
            const sync = (byUser = true) => {
                pending = 0;
                const wanted = kind();
                if (toggle)
                    toggle.visible = !wanted;
                const scheme = wanted === 'light' ? 'prefer-light' : wanted === 'dark' ? 'prefer-dark' : null;
                if (scheme && style.get_string('color-scheme') !== scheme) {
                    style.set_string('color-scheme', scheme);
                    // Say why the click did nothing (the user's wish), once for a run of clicks.
                    const now = GLib.get_monotonic_time();
                    if (byUser && now - told > 10 * GLib.USEC_PER_SEC) {
                        told = now;
                        Main.notify('Light and dark come with your window colors',
                            'Mentor keeps them matched. To change them, pick another set in Mentor Settings, Window colors.');
                    }
                }
                return GLib.SOURCE_REMOVE;
            };
            let quiet = false;
            const later = byUser => {
                quiet ||= !byUser;
                if (!pending) {
                    // at once, not after a wait: with 300 ms the other style showed for about a second
                    // (the shell draws its theme anew each time), 2026-10-19
                    pending = GLib.idle_add(GLib.PRIORITY_HIGH, () => {
                        const by = !quiet;
                        quiet = false;
                        return sync(by);
                    });
                }
            };
            const watch = Gio.File.new_for_path(note).monitor_file(Gio.FileMonitorFlags.NONE, null);
            // a new set picked: Mentor changes the style itself a moment later, nothing to tell
            const noted = watch.connect('changed', () => later(false));
            const styled = style.connect('changed::color-scheme', () => later(true));
            sync(false);  // at the start: put right quietly
            return () => {
                if (pending)
                    GLib.source_remove(pending);
                watch.disconnect(noted);
                watch.cancel();
                style.disconnect(styled);
                if (toggle)
                    toggle.visible = true;
            };
        });

        // The shell's own menus (the quick menu, the calendar and notifications, the keyboard menu) in the
        // tones of the user's window colors too (the user's wish, 2026-10-18), while GNOME's style is the
        // set's own: only backgrounds; GNOME's text colors and its accent stay. A stylesheet made from the
        // tones in ~/.config/mentor/taskbar-color, loaded on top of the shell's theme, again when the shell
        // makes its theme anew (a change of style). DESKTOP.md, "Window colors".
        this._part('menu colors', () => {
            const note = GLib.build_filenamev([GLib.get_user_config_dir(), 'mentor', 'taskbar-color']);
            const style = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
            const context = St.ThemeContext.get_for_stage(global.stage);
            let loaded = null, sheet = null, count = 0, busy = false, pending = 0;
            const old = [];
            // Each set of tones in a file of its own, loaded once, taken off the theme it was loaded on and
            // off the current one too: on a change of style the shell makes a new theme and copies the extra
            // stylesheets onto it (main.js, loadTheme). A file is deleted only two changes later, as the shell
            // may still copy it: a missing one stops the shell's change of style. Found in the test, 2026-10-18.
            const unload = () => {
                if (sheet) {
                    for (const theme of new Set([loaded, context.get_theme()])) {
                        try {
                            theme?.unload_stylesheet(sheet);
                        } catch (e) {}
                    }
                    old.push(sheet);
                    while (old.length > 2) {
                        try {
                            old.shift().delete(null);
                        } catch (e) {}
                    }
                }
                loaded = sheet = null;
            };
            const sync = () => {
                busy = true;  // loading and unloading change the theme, and that calls us again
                try {
                    paint();
                } finally {
                    busy = false;
                }
            };
            // after the change, once: never in the middle of the shell's own change of theme
            const later = () => {
                if (!busy && !pending) {
                    pending = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                        pending = 0;
                        sync();
                        return GLib.SOURCE_REMOVE;
                    });
                }
            };
            // The overview too (Show Apps, the search, the folders): its background in the set's window tone, the
            // folders, the search box and the results a little off it, the names in the set's text color. GNOME
            // keeps it black in every style; with a light set it stood dark under a light taskbar (the user,
            // 2026-10-20). Only colors: GNOME's sizes and shapes stay.
            const overview = (window, ink, light) => {
                const raised = `st-mix(${ink}, ${window}, ${light ? 7 : 9}%)`;
                const hover = `st-mix(${ink}, ${window}, ${light ? 12 : 15}%)`;
                return `
#overviewGroup { background-color: ${window}; }
.overview-tile, .grid-search-result, .app-folder-dialog .overview-tile { color: ${ink}; }
.overview-tile:hover, .grid-search-result:hover, .overview-tile:focus, .grid-search-result:focus,
.overview-tile:selected, .grid-search-result:selected, .overview-tile:highlighted, .grid-search-result:highlighted,
.overview-tile:checked, .grid-search-result:checked, .overview-tile:active, .grid-search-result:active { background-color: ${hover}; color: ${ink}; }
.list-search-result .list-search-result-title, .search-provider-icon .list-search-provider-content,
.search-provider-icon StLabel, .list-search-provider-details, .list-search-provider-details StLabel { color: ${ink}; }
.list-search-result:selected, .list-search-result:highlighted, .search-provider-icon:selected { background-color: ${hover}; color: ${ink}; }
.app-folder { background-color: ${raised}; color: ${ink}; box-shadow: none; }
.app-folder:hover, .app-folder:focus { background-color: ${hover}; color: ${ink}; }
.app-folder-dialog { background-color: ${raised}; color: ${ink}; }
.app-folder-dialog .folder-name-label, .app-folder-dialog .folder-name-entry { color: ${ink}; }
.search-entry { background-color: ${raised}; color: ${ink}; border-color: transparent; }
.search-entry:focus { background-color: ${hover}; }
.search-entry .search-entry-icon, .search-entry StLabel.hint-text { color: st-transparentize(${ink}, 0.4); }
.search-section-content { background-color: ${raised}; color: ${ink}; border-color: transparent; }
.list-search-result:hover, .list-search-result:focus, .search-provider-icon:hover, .search-provider-icon:focus { background-color: ${hover}; }
.list-search-result .list-search-result-description { color: st-transparentize(${ink}, 0.3); }
.page-indicator .page-indicator-icon { background-color: ${ink}; }
`;
            };
            const paint = () => {
                unload();
                let tones;
                try {
                    tones = new TextDecoder().decode(GLib.file_get_contents(note)[1]).trim().split(/\s+/);
                } catch (e) {
                    return;  // GNOME's own colors
                }
                // The fifth field, when there is one, is the menus' own tone: an accent set has its color in
                // the title bars and taskbar, and GNOME's dark grey in the menus, where lit switches in the
                // accent color could not be told from the rest on the same color (2026-10-19).
                const [bar, kind, window] = tones;
                const header = tones[4] ?? bar;
                const light = kind === 'light';
                if (!window || light !== (style.get_string('color-scheme') === 'prefer-light'))
                    return;  // the style was switched by hand: GNOME's own menus fit it
                const shade = (color, amount) => light ? `st-darken(${color}, ${amount}%)` : `st-lighten(${color}, ${amount}%)`;
                const ink = light ? '#222226' : '#ffffff';
                const tile = light ? window : `st-lighten(${header}, 6%)`;
                const css = `
.popup-menu-content, .candidate-popup-content { background-color: ${header}; border-color: ${shade(header, 6)}; }
.calendar .calendar-day-heading, .calendar .calendar-day, .calendar .calendar-month-header .calendar-month-label { background-color: ${header}; }
.calendar .calendar-day:hover, .calendar .calendar-day-heading:hover { background-color: ${shade(header, 6)}; }
.quick-toggle-menu, .message, .events-button, .world-clocks-button, .weather-button { background-color: ${tile}; }
.events-button:hover, .world-clocks-button:hover, .weather-button:hover, .message:hover { background-color: ${shade(tile, 4)}; }
.quick-toggle, .quick-settings .icon-button, .quick-toggle-has-menu .quick-toggle-menu-button { background-color: st-mix(${ink}, ${header}, ${light ? 12 : 9}%); }
.quick-toggle:hover, .quick-settings .icon-button:hover { background-color: ${shade(`st-mix(${ink}, ${header}, ${light ? 12 : 9}%)`, 6)}; }
.quick-toggle:checked, .calendar .calendar-day.calendar-today { color: -st-accent-fg-color; background-color: -st-accent-color; }
.quick-toggle:checked:hover, .calendar .calendar-day.calendar-today:hover { background-color: ${light ? 'st-darken' : 'st-lighten'}(-st-accent-color, 4%); }
.quick-toggle-has-menu .quick-toggle-menu-button:checked { color: -st-accent-fg-color; background-color: st-mix(-st-accent-color, ${light ? '#ffffff, 85%' : '#222226, 92%'}); }
.quick-toggle-has-menu .quick-toggle-menu-button:checked:hover { background-color: ${light ? 'st-lighten' : 'st-darken'}(st-mix(-st-accent-color, ${light ? '#ffffff, 85%' : '#222226, 92%'}), 4%); }
${overview(window, ink, light)}`;
                try {
                    sheet = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_runtime_dir(),
                        `mentor-menu-colors-${++count}.css`]));
                    sheet.replace_contents(new TextEncoder().encode(css), null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
                    loaded = context.get_theme();
                    loaded.load_stylesheet(sheet);
                } catch (e) {
                    console.warn(`mentor: the menu colors could not be loaded: ${e.message}`);
                    loaded = null;
                }
            };
            const watch = Gio.File.new_for_path(note).monitor_file(Gio.FileMonitorFlags.NONE, null);
            const noted = watch.connect('changed', later);
            const styled = style.connect('changed::color-scheme', later);
            const themed = context.connect('changed', () => {
                if (loaded !== context.get_theme())
                    later();  // a new theme (the style changed): load ours on it again
            });
            sync();
            return () => {
                if (pending)
                    GLib.source_remove(pending);
                watch.disconnect(noted);
                watch.cancel();
                style.disconnect(styled);
                context.disconnect(themed);
                unload();
            };
        });
    }

    disable() {
        for (const undo of this._undo.reverse()) {
            try {
                undo();
            } catch (e) {
                console.error(`mentor: ${e.message}`);
            }
        }
        this._undo = [];
        this._parts = {};
    }
}
