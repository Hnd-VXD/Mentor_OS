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
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Config from 'resource:///org/gnome/shell/misc/config.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {AppMenu} from 'resource:///org/gnome/shell/ui/appMenu.js';
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
    // once it has settled.
    _matchHostScale() {
        if (this._scaleLater)
            GLib.source_remove(this._scaleLater);
        this._scaleLater = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600, () => {
            this._scaleLater = 0;
            this._whenTaskbarUp(() => {
                try {
                    this._scaledAt = GLib.get_monotonic_time() / 1000000;
                    Gio.Subprocess.new(['/usr/local/bin/mentor', 'scale', '--keep'], Gio.SubprocessFlags.NONE);
                } catch (e) {
                    console.warn(`mentor: could not match the host's scale: ${e.message}`);
                }
            });
            return GLib.SOURCE_REMOVE;
        });
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

    // Back where it belongs, once whatever moved it is done (not while it is being dragged).
    _keepPlace(window) {
        if (window !== this._window || this._placing)
            return;
        const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        const frame = window.get_frame_rect();
        if (frame.x === area.x && frame.y === area.y && frame.width === area.width && frame.height === area.height)
            return;
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
            window !== this._window && !window.minimized && window.showing_on_its_workspace() &&
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
  </interface>
</node>`;

// The user's own windows: normal windows and dialogs of every app but Mentor's assistant.
function userWindows() {
    return global.get_window_actors().map(actor => actor.meta_window).filter(window =>
        window && !window.skip_taskbar &&
        [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG].includes(window.get_window_type()) &&
        window.get_wm_class() !== ASSISTANT && window.get_gtk_application_id() !== ASSISTANT);
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

    destroy() {
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
            taskbar_panels: global.dashToPanel?.panels?.length ?? 0,
        };
    }

    enable() {
        this._parts = {};
        this._undo = [];
        this._desktop = null;

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
