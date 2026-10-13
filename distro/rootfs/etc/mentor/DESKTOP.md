# Mentor's desktop: what it is made of, and how to make it again

This is for the agent. It lists everything Mentor adds to or changes in GNOME, what the user is meant to see, where it is done, what of GNOME it leans on, and how to tell that it works. Use it when something of Mentor's has stopped working, and above all when GNOME moves to a new major version: the aim then is that the user has the same things they had before, even where they have to be made another way.

`mentor doctor` (tool: desktop_check) says which parts work right now. Start there.

## How it hangs together

- **mentor-chat** (`/usr/local/bin/mentor-chat`, GTK 4 and libadwaita, Python) is the assistant: one frameless window with no background.
- **The shell extension** (`/usr/share/gnome-shell/extensions/mentor@mentor.local/`) makes that window the desktop and adds Mentor's pieces to the shell. It is set up part by part (`_part` in `extension.js`); a part that fails is logged, left out and reported by `Status`, and the others carry on.
- **Dash to Panel** (package `gnome-shell-extension-dash-to-panel`) is the taskbar; **AppIndicator support** the tray icons. Both are other people's extensions and break on their own schedule.
- **Defaults** are in `/etc/dconf/db/local.d/00-mentor` (run `dconf update` after changing it): the enabled extensions, favourites, key bindings, wallpaper, dark style, animations off.
- **The launcher on Windows** (Mentor.exe) talks to the system inside over two serial ports: `org.mentor.control` (start-up reports, full screen, restore points) and `org.mentor.clipboard` (text and files, and the window's full-screen state).

## The parts of the extension

| Part (name in `Status`) | What the user has | What of the shell it leans on |
|---|---|---|
| `desktop` | The assistant is the desktop: under every window, on every workspace, as large as the work area. A click on it or Super+A clears the windows away; Escape or Super+A brings them back. | `Meta.Window.set_type(DESKTOP)`, `stick()`, `move_resize_frame`; `global.display` signals `window-created`, `workareas-changed`; `Main.layoutManager` `monitors-changed`, `getWorkAreaForMonitor`. The window is known by `wm_class` / `gtk_application_id` `org.mentor.Chat`. |
| `service` | Nothing to see: the D-Bus object `/org/mentor/Shell` (`org.mentor.Shell`: `Screenshot`, `Show`, `Restore`, `Toggle`, `Status`, `Ask`) on the shell's session bus name. screen_capture, Super+A and the assistant use it. | `Shell.Screenshot`, `Gio.DBusExportedObject`. |
| `start on the desktop` | A session begins on the desktop, not in the overview. | `Main.layoutManager._startingUp` (private), signal `startup-complete`, `Main.overview.hide()`. |
| `system menu switches` | "Full Screen" and "Taskbar" in the system menu. Full Screen is lit while the window on Windows is full screen. | `QuickToggle`, `SystemIndicator`, `Main.panel.statusArea.quickSettings.addExternalIndicator`. The state comes from `/run/mentor/fullscreen`, written by mentor-clipboard. |
| `app grid click` | A click on the empty space of the app grid closes it; the click that closes an open folder does not. | `Main.overview._overview.controls.appDisplay` and its `_currentDialog` (both private), `Clutter.ClickGesture` (older: `ClickAction`). |
| `search` | Typing in the overview offers "Ask Mentor" with the typed words. | The search provider interface of `Main.overview.searchController`. |
| (in `desktop`) the text box over a program | The assistant's own text box, lifted out of the desktop by Alt+Space and Super+Z (`mentor-chat --ask`), is a second window of the assistant: `_adopt` makes it float above the others, on every workspace, in the middle of the bottom of the screen (`_float`). All of it is in ASKBAR.md. | `Meta.Window.make_above`, `stick`, `move_frame`, `Main.activateWindow`. |
| `app menus` | "Ask Mentor…" in the right-click menu of every app icon. | `AppMenu.prototype.open` and `addAction` (overridden with `InjectionManager`). |

Inside `desktop` (class `DesktopLayer`) there is more that leans on the shell:

- **The start has worked**: when the assistant's window has drawn itself and the taskbar's panels exist, `/run/mentor/desktop-ok` is written. A start that tries a change is only kept if this file appears within three minutes (`mentor_boot.py`). If this part is broken, every upgrade is undone at the next start. That is the safety, not a fault: fix the part, not the check.
- **Waiting for the taskbar** (`_whenTaskbarUp`): Dash to Panel 74 sets itself up in steps and breaks for the session if the screen changes in the middle. So the scale and the report above wait for `global.dashToPanel.panels`. If Dash to Panel changes how it starts, this is where to look.
- **Sharp text** (`_matchHostScale`, `mentor scale`): the desktop takes the scale of the Windows screen (`/run/mentor/host-scale`, from the launcher). It is set with mutter's `gdctl set --persistent`, which makes the shell ask "Keep these display settings?"; `_keepScale` answers that by finding the dialog among `Main.layoutManager.modalDialogGroup` and calling its `_onSuccess` (private). A scale the user picks in Settings is theirs (`_onScreenChanged`, `~/.config/mentor/scale`).
- **A conversation for each workspace**: `active-workspace-changed` tells mentor-chat (`mentor-chat --workspace N`).

## Outside the extension

| What | Where | How to tell it works |
|---|---|---|
| Key bindings: Super+A to the assistant, Ctrl+Alt+F and Super+F11 full screen, Print and Shift+Super+S screenshot | `00-mentor` (`media-keys/custom-keybindings`) | `gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings` |
| "Ask Mentor…" on files and folders in Files | `/usr/share/nautilus-python/extensions/mentor.py` (needs `python-nautilus`) | right-click a file in Files |
| The clipboard shared with Windows, files included | `/usr/local/lib/mentor/mentor-clipboard` (GTK 3 on X11 through Xwayland, started at login) and `mentor-clipboard-files` (GTK 4) | `pgrep -f lib/mentor/mentor-clipboard` |
| Suggestions behind the bell | `mentor-advisor` and its timer; shown by mentor-chat | `systemctl is-enabled mentor-advisor.timer` |
| The start-up picture | plymouth theme `mentor` in `/usr/share/plymouth/themes/mentor`, inside the initramfs | `plymouth-set-default-theme` |
| Wallpapers | `/usr/share/backgrounds/mentor/`, listed in `/usr/share/gnome-background-properties/mentor.xml` | Settings, Appearance |
| Chromium with uBlock Origin Lite | `/etc/chromium/policies/managed/mentor.json` | `chrome://policy` |

mentor-chat itself leans on libadwaita (`Adw.TabView`, `Adw.AlertDialog`, `Adw.Dialog`, `Adw.SwitchRow`, `Adw.WrapBox`) and GTK 4. A new GNOME brings new versions of both; a class that has gone shows as a Python traceback in the journal (`journalctl -b --user | grep -A12 mentor-chat`), and the desktop then stays empty.

## When GNOME moves to a new major version

The extension only loads on the versions in the `shell-version` list of its `metadata.json`. On another version the shell leaves it out, the start does not report itself, and the upgrade is undone three minutes later. So the order is:

1. **Before upgrading, read what changed.** In the sandbox, install the new `gnome-shell` and read the shell's own code for the things in the tables above (it is packed in `/usr/lib/gnome-shell/libshell-*.so`; `gresource extract` from `glib2-devel` gets a file out, e.g. `/org/gnome/shell/ui/appDisplay.js`). Check each private name this file mentions. The release notes and the extension porting guide (gjs.guide/extensions/upgrading) name the breaking changes.
2. **Adapt in the sandbox**: change `extension.js` where something moved, keep each part in its own `_part`, and add the new version to `shell-version`. Where a thing can no longer be done the old way, make the same thing for the user another way, and say so. Do the same check for Dash to Panel: if its package does not yet support the new shell, say that the taskbar will be missing until it does, and that the "Taskbar" switch turns it off meanwhile.
3. **Tell the user** what will be the same, what will differ and what may be missing, and that a start that does not reach the desktop undoes everything by itself. Upgrade only when they say so (system_upgrade with gnome_major_ok), together with sandbox_apply of the adapted files, so that both arrive in the same start.
4. **After the restart**, read boot_status, then desktop_check, then screen_capture. Mend the parts reported broken, one at a time; a changed extension is only loaded at login (session_logout). Then go through the "outside the extension" table.
5. **Write down what you changed.** You cannot change this file (nothing in `/etc/mentor` is yours to write). When a part is done differently from now on, put it in `~/.local/share/mentor/notes.md`: the part, the file and lines, what the shell now offers in place of what it had, and how to tell that it works. `mentor verify` will list `extension.js` as changed from then on; the note is what says that this is right.

The same order, from step 4, serves when something of Mentor's breaks without an upgrade.

Do not get around the checks: no upgrade with run_root_command, no switching off of the shell's version check, no writing of `/run/mentor/desktop-ok` by hand. They are what lets the user try this without risk.

## Mending one part, step by step

For a small model: do exactly this, one part at a time.

**1. Find the part that is broken.**

```
mentor doctor
```

Each line starts with `ok` or `BROKEN`. A line `BROKEN part: NAME: MESSAGE` names a part of the extension and the error it stopped with. The same, with the place in the code:

```
journalctl -b -o cat _COMM=gnome-shell | grep -A8 'mentor: the part'
```

If `mentor doctor` says the extension's state is `OUT OF DATE`, the shell is a version the extension does not name: read "When GNOME moves to a new major version" above. If it says `ERROR`, the whole file failed to load (a syntax error, or an import that no longer exists): `gnome-extensions info mentor@mentor.local` shows the error.

**2. Read how the part is made.** The extension is one file, `/usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js`. Every part is set up inside `enable()` like this, and nowhere else:

```js
this._part('app menus', () => {
    // ... set the part up; anything that throws here marks only this part as broken ...
    return () => { /* how to take it down again */ };
});
```

`_part(name, setUp)` runs `setUp` inside `try`, keeps what it returns for `disable()`, and records `ok` or `broken: MESSAGE` under the name, which is what `Status` and `mentor doctor` report. So a broken part never takes the others with it. Keep that shape: one `_part` per thing the user has, the taking-down returned from it.

The classes above `MentorExtension` in the file: `DesktopLayer` (the assistant as the desktop: finds the window whose application id is `org.mentor.Chat`, makes it a desktop-type window, sizes it to the work area, clears the windows away and brings them back, writes `/run/mentor/desktop-ok`), `ShellService` (the D-Bus object `/org/mentor/Shell`), `FullScreenToggle`, `TaskbarToggle` and `Indicator` (the switches in the system menu), `AskProvider` (the search result).

**3. Find what changed in the shell.** The error names what is missing (`X is not a function`, `X is undefined`, `Cannot read properties of undefined (reading 'X')`). The table "The parts of the extension" says which names of the shell each part leans on. Read the shell's own code for that name in the version that is installed:

```
pacman -S --needed glib2-devel            # in the sandbox: gives gresource
lib=$(ls /usr/lib/gnome-shell/libshell-*.so | head -1)
gresource list "$lib" | grep -i appMenu   # find the file
gresource extract "$lib" /org/gnome/shell/ui/appMenu.js | less
```

Look for what replaces the name: a method renamed, a property moved to another object, a signal with another name. The extension porting guide at gjs.guide/extensions/upgrading lists the changes of each GNOME version.

**4. Change only that part**, in the sandbox (sandbox_run), on the installed file. Keep the old way working where you can, so the extension still loads on the version before:

```js
const grid = Main.overview._overview.controls.appDisplay ?? Main.overview._overview._controls.appDisplay;
```

If the shell is a new major version, add its number to `shell-version` in `metadata.json` in the same change.

**5. Check the file before applying**: a syntax error breaks every part at once.

```
node --check /usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js
```

(inside the sandbox, on the changed file; `node` is installed. It checks the syntax only, not the names of the shell.)

**6. Apply** (sandbox_changes, sandbox_apply), then ask the user to log out and in (session_logout): the shell loads an extension only at login.

**7. Check**: `mentor doctor` again, then screen_capture. If the part is still broken, the error has changed: go back to step 3 with the new one. If the desktop did not come up at all, the start is undone by itself within three minutes when it was a trial (BOOT.md); otherwise put the file back as built and start over:

```
cp -a /etc/mentor/source/rootfs/usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js /usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js
```

**8. Write it down** in `~/.local/share/mentor/notes.md`.

## Putting the desktop's files back as built

All of these you may write, in the sandbox. `src=/etc/mentor/source/rootfs`.

| What is missing or damaged | Put back with | Then |
|---|---|---|
| The extension | `cp -a $src/usr/share/gnome-shell/extensions/mentor@mentor.local /usr/share/gnome-shell/extensions/` | log out and in |
| The defaults (keys, extensions switched on, wallpaper, dark style) | `cp -a $src/etc/dconf/db/local.d/00-mentor /etc/dconf/db/local.d/; cp -a $src/etc/dconf/profile/user /etc/dconf/profile/; dconf update` | log out and in |
| "Ask Mentor…" in Files | `cp -a $src/usr/share/nautilus-python/extensions/mentor.py /usr/share/nautilus-python/extensions/` | `nautilus -q` |
| Wallpapers | `cp -a $src/usr/share/backgrounds/mentor /usr/share/backgrounds/; cp -a $src/usr/share/gnome-background-properties/mentor.xml /usr/share/gnome-background-properties/` | at once |
| Chromium's ad blocker | `install -D -m 644 $src/etc/chromium/policies/managed/mentor.json /etc/chromium/policies/managed/mentor.json` | next start of Chromium |
| Hidden and added launchers | `cp -a $src/usr/local/share/applications/. /usr/local/share/applications/` | at once |
| The clipboard's start at login | `cp -a $src/etc/xdg/autostart/mentor-clipboard.desktop /etc/xdg/autostart/` | log out and in |
| The channels to the launcher | `cp -a $src/etc/udev/rules.d/70-mentor-clipboard.rules /etc/udev/rules.d/; udevadm control --reload; udevadm trigger` | at once |
| The clipboard program itself (`/usr/local/lib/mentor/mentor-clipboard`, `mentor-clipboard-files`) | the user: `sudo mentor restore /usr/local/lib/mentor/mentor-clipboard` | log out and in |

A user who changed a setting keeps their own value: the defaults in `00-mentor` only count where the user has set nothing. To see what a user has set over them: `dconf dump /org/gnome/shell/`.

The packages the desktop needs: `gnome-shell`, `gdm`, `gnome-shell-extension-dash-to-panel`, `gnome-shell-extension-appindicator`, `python-nautilus`, `libnotify`, `xorg-xwayland`, `gtk3`, `python-gobject` (the whole list: `/etc/mentor/source/build/packages.x86_64`).

## The shared clipboard, for mending it

`/usr/local/lib/mentor/mentor-clipboard` talks to the launcher on Windows over the virtio port `org.mentor.clipboard` (`/dev/virtio-ports/org.mentor.clipboard`), one JSON object per line: `{"text": "..."}` for text; for copied files `{"files": id, "count": n, "bytes": total}`, then `{"dir": id, "name": path}` and `{"file": id, "name": path, "size": n}` with `{"chunk": id, "data": base64}` as many as needed, then `{"files-end": id}` (or `{"files-cancel": id}`; `{"files-refused": why}` when a copy is too large). It runs on X11 through Xwayland on purpose (`GDK_BACKEND=x11` in its autostart file): a Wayland program sees the clipboard only while it has the keyboard, an X11 one always, and GNOME mirrors the clipboard between the two. So it needs `xorg-xwayland` and GTK 3. Files that arrive are put on the clipboard by `mentor-clipboard-files` (GTK 4). The udev rule gives the logged-in user the two ports.

Check: `pgrep -af lib/mentor/mentor-clipboard` (one line); `ls -l /dev/virtio-ports/` (the two ports, when started by the launcher; on a real computer there are none and the clipboard is simply not shared); its errors: `journalctl -b --user -o cat | grep -i -A8 mentor-clipboard`.
