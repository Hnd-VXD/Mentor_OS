# Mentor's desktop: what it is made of, and how to make it again

This is for the agent. It lists everything Mentor adds to or changes in GNOME, what the user is meant to see, where it is done, what of GNOME it leans on, and how to tell that it works. Use it when something of Mentor's has stopped working, and above all when GNOME moves to a new major version: the aim then is that the user has the same things they had before, even where they have to be made another way.

`mentor doctor` (tool: desktop_check) says which parts work right now. Start there.

## How it hangs together

- **mentor-chat** (`/usr/local/bin/mentor-chat`, GTK 4 and libadwaita, Python) is the assistant: one frameless window with no background.
- **The shell extension** (`/usr/share/gnome-shell/extensions/mentor@mentor.local/`) makes that window the desktop and adds Mentor's pieces to the shell. It is set up part by part (`_part` in `extension.js`); a part that fails is logged, left out and reported by `Status`, and the others carry on.
- **Dash to Panel** (package `gnome-shell-extension-dash-to-panel`) is the taskbar; **AppIndicator support** the tray icons. Both are other people's extensions and break on their own schedule.
- **No "Dash to Panel has been updated!"**: Dash to Panel announces itself whenever its version differs from the `extension-version` it stored, on a fresh install and after each upgrade. `mentor-taskbar-quiet.service` (a user oneshot before `graphical-session-pre.target`, script `/usr/local/lib/mentor/mentor-taskbar-quiet`) stores the version from its `metadata.json` before the shell starts. It cannot be done from Mentor's extension: GNOME enables Dash to Panel before it.
- **Defaults** are in `/etc/dconf/db/local.d/00-mentor` (run `dconf update` after changing it): the enabled extensions, favourites, key bindings, wallpaper, dark style, animations off.
- **The launcher on Windows** (Mentor.exe) talks to the system inside over two serial ports: `org.mentor.control` (start-up reports, full screen, restore points, the game mouse) and `org.mentor.clipboard` (text and files, and the window's full-screen state).

## The parts of the extension

| Part (name in `Status`) | What the user has | What of the shell it leans on |
|---|---|---|
| `desktop` | The assistant is the desktop: under every window, on every workspace, as large as the work area. A click on it or Super+A clears the windows away; Escape or Super+A brings them back. | `Meta.Window.set_type(DESKTOP)`, `stick()`, `move_resize_frame`; `global.display` signals `window-created`, `workareas-changed`; `Main.layoutManager` `monitors-changed`, `getWorkAreaForMonitor`. The window is known by `wm_class` / `gtk_application_id` `org.mentor.Chat`. |
| `service` | Nothing to see: the D-Bus object `/org/mentor/Shell` (`org.mentor.Shell`: `Screenshot`, `Show`, `Restore`, `Toggle`, `Status`, `Ask`, `Windows`, `FocusWindow`, `CloseWindow`, `ScreenshotArea`, `ScreenshotWindow`, `SetClipboard`) on the shell's session bus name. screen_capture, Super+A, the assistant, the tools `windows`, `app_open` and `screen_text` (TOOLS.md), and Shift+Super+T use it. | `Shell.Screenshot`, `Gio.DBusExportedObject`. |
| `start on the desktop` | A session begins on the desktop, not in the overview. | `Main.layoutManager._startingUp` (private), signal `startup-complete`, `Main.overview.hide()`. |
| `system menu switches` | "Full Screen" and "Taskbar" in the system menu. Full Screen is lit while the window on Windows is full screen. | `QuickToggle`, `SystemIndicator`, `Main.panel.statusArea.quickSettings.addExternalIndicator`. The state comes from `/run/mentor/fullscreen`, written by mentor-clipboard. |
| `game mouse` | Mouse-look works in 3D games: while an app marked as a game is in front, the launcher gives the system a mouse that only moves; otherwise the normal pointer. See "The game mouse" below. | `global.display` `notify::focus-window`, `Shell.WindowTracker.get_window_app`, `Shell.App.get_app_info().get_categories()`, `Main.overview` signals `showing` / `hiding`. Asks the launcher through `mentor game-mouse --send on|off`. |
| `app grid click` | A click on the empty space of the app grid closes it; the click that closes an open folder does not. | `Main.overview._overview.controls.appDisplay` and its `_currentDialog` (both private), `Clutter.ClickGesture` (older: `ClickAction`). |
| `search` | Typing in the overview offers "Ask Mentor" with the typed words. | The search provider interface of `Main.overview.searchController`. |
| (in `desktop`) the text box over a program | The assistant's own text box, lifted out of the desktop by Alt+Space and Super+Z (`mentor-chat --ask`), is a second window of the assistant: `_adopt` makes it float above the others, on every workspace, in the middle of the bottom of the screen (`_float`). All of it is in ASKBAR.md. | `Meta.Window.make_above`, `stick`, `move_frame`, `Main.activateWindow`. |
| `app menus` | "Ask Mentor…" in the right-click menu of every app icon. | `AppMenu.prototype.open` and `addAction` (overridden with `InjectionManager`). |

Inside `desktop` (class `DesktopLayer`) there is more that leans on the shell:

- **The start has worked**: when the assistant's window has drawn itself and the taskbar's panels exist, `/run/mentor/desktop-ok` is written. A start that tries a change is only kept if this file appears within three minutes (`mentor_boot.py`). If this part is broken, every upgrade is undone at the next start. That is the safety, not a fault: fix the part, not the check.
- **Waiting for the taskbar** (`_whenTaskbarUp`): Dash to Panel 74 sets itself up in steps and breaks for the session if the screen changes in the middle. So the scale and the report above wait for `global.dashToPanel.panels`. If Dash to Panel changes how it starts, this is where to look.
- **Sharp text** (`_matchHostScale`, `mentor scale`): the desktop takes the scale of the Windows screen (`/run/mentor/host-scale`, from the launcher). Not every scale fits every resolution (200% does not fit an odd height, as when the window is maximized at 2880x1659): `_supported_scales` asks mutter (`GetCurrentState`) which ones the mode takes, and the largest quarter step (125%, 150%…) not above the wanted one is used, so a maximized window on a 200% screen gets 150% instead of staying at 100%. It is set with mutter's `gdctl set --persistent`, which makes the shell ask "Keep these display settings?"; `_keepScale` answers that by finding the dialog among `Main.layoutManager.modalDialogGroup` and calling its `_onSuccess` (private). A scale the user picks in Settings is theirs (`_onScreenChanged`, `~/.config/mentor/scale`).
- **A conversation for each workspace**: `active-workspace-changed` tells mentor-chat (`mentor-chat --workspace N`).

## Outside the extension

| What | Where | How to tell it works |
|---|---|---|
| Key bindings: Super+A to the assistant, Ctrl+Alt+F and Super+F11 full screen; Shift+Super+S a screenshot of an area the user drags out (not Print: that is Windows', whose Snipping Tool takes it even while Mentor is full screen and whose picture comes into Mentor's clipboard; bound here too, both pickers came up at once) (`mentor screenshot --area`: the extension's `ScreenshotArea` and `pickArea`, Mentor's own picker in place of GNOME's overlay: the screen dims a little, the pointer is a cross, a white box follows the drag; Esc or the right button cancels and nothing opens; a click without dragging is the whole screen), Alt+Print of the window in front (`ScreenshotWindow`), saved in Pictures/Screenshots and opened in Gradia to draw on, copy or save. Shift+Super+T copies the text in an area the user drags out (`mentor capture-text`; see "Copy text from the screen" below). No permission is asked: only the shell may read the screen on Wayland, which is why area pickers of other apps (Shutter, Gradia's own --screenshot=INTERACTIVE) give the whole screen or GNOME's overlay. GNOME's own screenshot keys are off (`show-screenshot-ui`, `screenshot`, `screenshot-window` empty) | `00-mentor` (`media-keys/custom-keybindings`) | `gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings` |
| "Ask Mentor…" on files and folders in Files | `/usr/share/nautilus-python/extensions/mentor.py` (needs `nautilus-python`; Files loads it with `/usr/lib/nautilus/extensions-4/libnautilus-python.so`). A new Files that changes how add-ons work (Files 43 did) makes the item vanish with no error anywhere, so `mentor doctor` tries it the way Files does after every login (`FILES_PROBE` in `/usr/local/bin/mentor`: the newest Nautilus typelib, `MenuProvider.get_file_items(files)` and `get_background_items(current_folder)`, the add-on giving its two items) and says `WARN "Ask Mentor…" in Files: WHY`. To mend: read the new `Nautilus-*.typelib` methods (`python3 -c` with `gi.require_version('Nautilus', VERSION)`), and nautilus-python's own examples (`package_peek nautilus-python`), then adapt mentor.py in the sandbox | right-click a file in Files; `mentor doctor` |
| The clipboard shared with Windows, files included | `/usr/local/lib/mentor/mentor-clipboard` (GTK 3 on X11 through Xwayland, started at login) and `mentor-clipboard-files` (GTK 4) | `pgrep -f lib/mentor/mentor-clipboard` |
| Space to preview in Files, as on a Mac: select a file, Space shows it (pictures, PDFs, text, audio, video), Space again closes it | the `sushi` package (GNOME's NautilusPreviewer, started by D-Bus when Files asks); nothing of Mentor's | `pacman -Q sushi`; in Files select a picture and press Space |
| Pictures from Windows: a snip with Windows' own PrtScr / Snipping Tool (Windows keeps that key even while Mentor is full screen) is on Mentor's clipboard as a picture; Ctrl+V pastes it anywhere, and in the chat attaches it. One way only, Windows to Mentor | Mentor.exe (`SendImage`: on a clipboard change with a picture, a PNG of at most 32 MB, sent once, as `{"image": "<base64>"}` on the clipboard port) and `mentor-clipboard` (`on_message`: `GdkPixbuf` loader, `set_image`; the PNG is also kept as `~/.cache/mentor/host-picture.png`, removed by `on_targets` on any later clipboard change but its own). GNOME fails to pass a large picture (an X11 INCR transfer; gnome-shell logs `meta_x11_selection_input_stream_read_async ... finalized without ever returning`) on to Wayland windows, so Ctrl+V in the chat (`on_entry_key` → `paste_host_picture`) takes that file first; a failed read of a Wayland picture logs `paste: the picture could not be read` | copy a picture on Windows, then in Mentor: `python3 -c` with Gtk 3 `Clipboard.wait_for_image()`, or Ctrl+V in the chat |
| Suggestions behind the bell | `mentor-advisor` and its timer; shown by mentor-chat | `systemctl is-enabled mentor-advisor.timer` |
| The start-up picture | plymouth theme `mentor` in `/usr/share/plymouth/themes/mentor`, inside the initramfs | `plymouth-set-default-theme` |
| Wallpapers | `/usr/share/backgrounds/mentor/`, listed in `/usr/share/gnome-background-properties/mentor.xml` | Settings, Appearance |
| Settings that does not freeze: GNOME Settings is drawn without OpenGL (`GSK_RENDERER=cairo`), however it is started. See "Settings" below | `/usr/local/bin/gnome-control-center` (ahead of `/usr/bin` in PATH) and `/usr/local/share/dbus-1/services/org.gnome.Settings.service` (found before GNOME's own) | open Settings from the app grid, then `tr '\0' '\n' < /proc/$(pgrep -f -o gnome-control-center)/environ \| grep GSK` says `GSK_RENDERER=cairo` |
| The languages GNOME offers: Settings, System, Region & Language lists about 37 languages. See "Languages" below | `mentor-enable` makes their locales (`/etc/locale.gen`, `locale-gen`) | `localectl list-locales` lists `de_DE.UTF-8` among others |
| Chromium with uBlock Origin Lite | `/etc/chromium/policies/managed/mentor.json` | `chrome://policy` |

mentor-chat itself leans on libadwaita (`Adw.TabView`, `Adw.AlertDialog`, `Adw.Dialog`, `Adw.SwitchRow`, `Adw.WrapBox`) and GTK 4. A new GNOME brings new versions of both; a class that has gone shows as a Python traceback in the journal (`journalctl -b --user | grep -A12 mentor-chat`), and the desktop then stays empty.

## When GNOME moves to a new major version

The extension only loads on the versions in the `shell-version` list of its `metadata.json`. On another version the shell leaves it out, the start does not report itself, and the upgrade is undone three minutes later. So the order is:

1. **Before upgrading, read what changed.** In the sandbox, install the new `gnome-shell` and read the shell's own code for the things in the tables above (it is packed in `/usr/lib/gnome-shell/libshell-*.so`; `gresource extract` from `glib2-devel` gets a file out, e.g. `/org/gnome/shell/ui/appDisplay.js`). Check each private name this file mentions. The release notes and the extension porting guide (gjs.guide/extensions/upgrading) name the breaking changes.
2. **Adapt in the sandbox**: change `extension.js` where something moved, keep each part in its own `_part`, and add the new version to `shell-version`. Where a thing can no longer be done the old way, make the same thing for the user another way, and say so. Do the same check for Dash to Panel: if its package does not yet support the new shell, say that the taskbar will be missing until it does, and that the "Taskbar" switch turns it off meanwhile.
3. **Tell the user** what will be the same, what will differ and what may be missing, and that a start that does not reach the desktop undoes everything by itself. Upgrade only when they say so (system_upgrade with gnome_major_ok), together with sandbox_apply of the adapted files, so that both arrive in the same start.
4. **After the restart**, read boot_status, then desktop_check, then screen_capture. Right-click the desktop and check that its menu is still exactly as AGENT.md lays it out (Hide chat, New conversation | Report a problem… | Change Background…, Mentor Settings…, Settings): the user chose it, and it must come through an upgrade unchanged. Mend the parts reported broken, one at a time; a changed extension is only loaded at login (session_logout). Then go through the "outside the extension" table.
5. **Write down what you changed.** You cannot change this file (nothing in `/etc/mentor` is yours to write). When a part is done differently from now on, put it in `~/.local/share/mentor/notes.md`: the part, the file and lines, what the shell now offers in place of what it had, and how to tell that it works. `mentor verify` will list `extension.js` as changed from then on; the note is what says that this is right.

The same order, from step 4, serves when something of Mentor's breaks without an upgrade.

Do not get around the checks: no upgrade with run_root_command, no switching off of the shell's version check, no writing of `/run/mentor/desktop-ok` by hand. They are what lets the user try this without risk.

## Mending one part, step by step

For a small model: do exactly this, one part at a time.

**1. Find the part that is broken.**

```
mentor doctor
```

Each line starts with `ok`, `BROKEN`, or `WARN` for a small part that is gone (a yellow card, not a red one: mentor-watch's `doctor-minor`). A line `BROKEN part: NAME: MESSAGE` names a part of the extension and the error it stopped with. The same, with the place in the code:

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

**The desktop cannot be moved, hidden or closed by mistake.** A dialog inside the assistant (History, Suggestions) has its frame and header act as the window's title bar: on 2026-10-14 dragging History's header moved the whole desktop, and a right click offered its window menu (Move, Hide, Always on Top, Close). So: the dialogs have a plain header (`dialog_header` in `mentor-chat`, not `Adw.HeaderBar`); the shell shows no window menu for the desktop window (`showWindowMenuForWindow` of `Main.wm._windowMenuManager`, overridden in the `desktop` part); and whatever moves, resizes, minimizes or puts it above is undone at once (`_keepPlace`, `notify::minimized`, `notify::above` in `_adopt`).

**Which assistant window is which** (`_adopt`): the desktop window is titled "Mentor", the text box over the windows (Alt+Space) "Ask Mentor" (`ASK_TITLE`). Only a window with that title is floated (`_float`: above all, on every workspace, at the bottom); any other assistant window becomes the desktop, taking the place of one still known. It was told apart by "a desktop window is known already": on 2026-10-14 the assistant, started again by an update while its old window was still known here, was taken for the text box, and the desktop became a window that could be moved, always on top, with a window menu. A window with no title yet waits for it (`notify::title`). `Status` says `assistant_on_desktop` true only when the known window really is a desktop-type window (`mentor doctor`: "the assistant is the desktop").

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

## Copy text from the screen

**What the user has.** Shift+Super+T, then drag over any text on the screen (in a picture, a video, a program that does not let them select it). The text is read and put on the clipboard, and a small notification says "Text copied" with its beginning; Ctrl+V pastes it, in Mentor and in Windows. Esc or the right button cancels. A click without dragging takes the whole screen. When there is no text there it says "No text found". You can do the same: the tool `screen_text` (TOOLS.md). Taken from Omarchy's `bin/omarchy-capture-text` (github.com/omacom/omarchy, MIT).

**How it is made.**
1. The key: `00-mentor`, `custom-keybindings/mentor-text`, `binding='<Shift><Super>t'`, `command='/usr/local/bin/mentor capture-text'`.
2. `cmd_capture_text` in `/usr/local/bin/mentor` calls `mentor_tools.capture_text("pick")`, and says how it went with `notify-send --app-name=Mentor`.
3. `capture_text` asks the shell for the area: `org.mentor.Shell.ScreenshotArea` (the same picker as Shift+Super+S), into `$XDG_RUNTIME_DIR/mentor-text-PID.png`, removed afterwards.
4. `read_text` makes the picture twice as large (ffmpeg, lanczos: tesseract is made for 300 dpi scans, a screen's letters are small) and runs `tesseract PICTURE - -l eng+ell` with `OMP_THREAD_LIMIT=1`. That limit matters: with its own threads tesseract took 92 seconds for one screen in the VM, alone 1 second. The languages: those in `~/.config/mentor/text-languages` (`eng+ell+deu`) when it exists, else English, Greek and the language of the user's locale, of those installed (`tesseract --list-langs`). Not every installed one: Gradia brings Afrikaans with it, and Afrikaans read `4471-B` as `44/1-8`.
5. The picture is kept as `$XDG_RUNTIME_DIR/mentor-last-text.png` (memory, only the user's, replaced by the next one, gone at log out), for step "When the copied text came out wrong" below.
6. `clipboard_set` puts the text on the clipboard through the shell: `busctl --user -- call org.gnome.Shell /org/mentor/Shell org.mentor.Shell SetClipboard s TEXT`, which is `St.Clipboard.set_text` in the extension. A program cannot simply do it: GNOME has no data-control protocol for `wl-copy`, and a clipboard owner has to stay running. The shared clipboard passes it on to Windows.

**When the copied text came out wrong** (the user says so: "fix the text I copied", "the Greek came out wrong"). The key itself never sends anything to a model: it stays fast, works without an engine, and what people copy (a password, an account number) is not sent anywhere unasked. When they ask:
1. `screen_text` with `area` `last` and `copy` false. It returns what OCR read and the picture it read it from.
2. Look at the picture and write the text as it really is, line by line, the same words, nothing added.
3. `screen_text` with `set_clipboard` set to that text.
4. Say in one sentence that the corrected text is on the clipboard (Ctrl+V).
If it says no picture is kept, they have logged out since: ask them to press Shift+Super+T and copy it again, then do this. When you read the screen with `screen_text` yourself, the picture comes with it the same way: correct the text from it before you use or copy it.

**Packages.** `tesseract`, `tesseract-data-eng`, `tesseract-data-ell` (Mentor's package list). `tesseract` itself also comes with Gradia (through `python-pytesseract`).

**Another language.** When the user reads text in another language: `package_install tesseract-data-XXX` (XXX: `deu` German, `fra` French, `spa` Spanish, `ita` Italian, `tur` Turkish, `rus` Russian, `ara` Arabic, `chi_sim` Chinese; `package_search tesseract-data` lists them all), then write the languages to use, joined with `+`, into `~/.config/mentor/text-languages` (file_write), for example `eng+ell+deu`. Fewer languages read better: keep to what they use.

**Check.**

| Check | Good answer |
|---|---|
| `tesseract --list-langs` | `eng` and `ell` among them |
| `gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings` | ends with `.../custom-keybindings/mentor-text/` |
| `gdbus introspect --session --dest org.gnome.Shell --object-path /org/mentor/Shell \| grep SetClipboard` | `SetClipboard(in  s text);` |
| `mentor call screen_text '{"area": "screen", "copy": false}'` | `The text read …` and the words on the screen, in about 5 seconds |

**When it does not work.**
- The key does nothing: the user's own `custom-keybindings` list overrides Mentor's (someone added a key of their own). `gsettings get` as above; if `mentor-text` is missing, add `'/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/mentor-text/'` to the list with `settings_set` (keep every entry that is there).
- "The text could not be copied", and `screen_text` says SetClipboard is unknown: the extension in use is older than the file (a new extension is loaded at the next login): session_logout, or a restart.
- `screen_text` says tesseract is not installed: `package_install tesseract tesseract-data-eng tesseract-data-ell`.
- It reads wrong letters: OCR is never perfect. A larger area around the words, or the text made larger on the screen (Ctrl and + in most programs), helps; so does having only the right languages (above).

Tested headless 2026-10-17: the key and a drag over a text editor and a web page, English and Greek, Esc, an area with no text, a whole screen in about 5 seconds. A line mixing Greek and English can still come out with a word in the wrong alphabet.

## The game mouse

**What the user has.** In 3D games (shooters such as QC:DE or GZDoom, anything that turns the view with the mouse) the view turns when they move the mouse. Nothing to switch on: it happens by itself while a game is in front, and the normal pointer is back as soon as they leave the game.

**Why it is needed.** Mentor's window on Windows normally gives the system inside a *tablet*: it says where the pointer is, not how far it moved. That is what makes the pointer glide in and out of Mentor's window with no clicking. A game that holds the pointer (Wayland pointer lock) turns the view by how far the mouse moved, and a tablet never says that: menus work, the view does not move. The *game mouse* is a second pointer (QEMU `virtio-mouse-pci`, "QEMU Virtio Mouse") that only says how far it moved. Only one of the two is in use at a time; the launcher switches.

**How it works.**
1. The shell extension's part `game mouse` (`class GameMouse` in `extension.js`) watches the window in front. It wants the game mouse when the app in front has `Game` in the `Categories` of its desktop file, or its app id is in `games` in `~/.config/mentor/game-mouse.json`, and the overview is not open. `"mode": "on"` there wants it always, `"off"` never; `"auto"` (or no file) is the above.
2. When what it wants changes, it runs `mentor game-mouse --send on` (or `off`) `--front APP-ID`. That sends `{"game-mouse": true}` on `org.mentor.control` and waits up to 5 seconds for the answer, `{"game-mouse": true, "ok": true}`. What came back is kept in `/run/user/UID/mentor-game-mouse.json` (`on`, `front`, `time`, and `error` when it did not work).
3. Mentor.exe (`HostBridge.OnGameMouse`, `KeepMouse`) asks QEMU for its mice (QMP `query-mice`) and makes the one asked for the one in use (`human-monitor-command` `mouse_set N`). It checks again every 2 seconds.
4. QEMU's window follows by itself. With the game mouse it **holds the Windows pointer after a click in Mentor's window**; in full screen it already holds it. **Ctrl+Alt+G** lets go of it in a normal window. In full screen it keeps the pointer until the game mouse is off, which is as soon as the user leaves the game (Super, Alt+Tab, or closing the game).

**What to tell the user.** One sentence, in their language. Do not explain tablets or QEMU. For example:
- When a game's view does not turn: "I switched on the game mouse: click once inside the game, and the view now turns with the mouse."
- If they are stuck with the pointer inside Mentor's window: "Press Ctrl+Alt+G to get the pointer back to Windows."
- If they ask why the pointer is "caught" in a game: "In games Mentor keeps the mouse inside so you can look around; leaving the game, or Ctrl+Alt+G, gives it back."

**When the view still does not turn in a game.** Do these in order.
1. `mentor game-mouse` (tool: `game_mouse` with no arguments). It prints the setting, what is in use now and what is in front.
2. If it says `The launcher could not do it` and mentions a Mentor.exe from before the game mouse, the user's Mentor.exe is too old. Nothing inside Mentor can fix that. Tell them: "Your Mentor program on Windows needs updating for this: close Mentor, run MentorSetup.exe again and choose the same folder. It only fetches the new program, and nothing inside Mentor is lost." The download page is https://github.com/Hnd-VXD/Mentor_OS/releases/latest.
3. If the game was not counted as a game (`Now: the normal pointer` while it was in front), find its app id. Ask the user to bring the game to the front, then use the `windows` tool. Then run `game_mouse` with `add_game` set to that id, for example `org.zdoom.GZDoom`. Tell the user to switch to the game again.
4. If it is in use (`Now: the game mouse`) and the view still does not move, the user may not have clicked into Mentor's window yet. Ask them to click once inside the game.
5. Still nothing: set `mode` `on`, so the game mouse is used for everything, and let the user try. Set it back to `auto` afterwards: with `on`, the pointer needs a click to enter Mentor's window and Ctrl+Alt+G to leave it.
6. Never change the game's own settings, files or launch options for mouse-look.

**Check that it works** (in a test system started by Mentor.exe):
1. `gdbus call --session --dest org.gnome.Shell --object-path /org/mentor/Shell --method org.mentor.Shell.Status` must show `"game mouse": "ok"` in `parts`.
2. `mentor game-mouse on`, wait 3 seconds, then `mentor game-mouse` must say `Now: the game mouse`. Then `mentor game-mouse auto`.
3. `grep '^N: Name' /proc/bus/input/devices` lists `QEMU Virtio Mouse` (the game mouse) and `QEMU QEMU USB Tablet` (the normal pointer). Without the Virtio Mouse, the user's Mentor.exe is from before the game mouse (step 2 above).

**If the part is broken** after a GNOME update (`mentor doctor` says `game mouse: broken: ...`), read the error. It leans only on `global.display` `notify::focus-window`, `Shell.WindowTracker.get_default().get_window_app(window)`, `app.get_app_info().get_categories()` and the overview's `showing` / `hiding` signals: look up what replaced them (`shell_source`) and adapt `GameMouse` in the sandbox. Until it is mended, `mentor game-mouse on` still works by hand: it only needs the launcher.

## Settings

**What the user has.** GNOME Settings opens and moves between pages without freezing.

**Why it is made so.** On 2026-10-17, Settings froze each time the user left the Mouse & Touchpad page: the page plays small gesture videos, and when it was left GTK's OpenGL context was lost in the VM (`gdk_gl_context_make_current() failed` in the journal, three times, then a window that does not answer). Drawn without OpenGL (`GSK_RENDERER=cairo`) it does not happen, and Settings is plain enough not to need OpenGL.

**How.** Settings is started two ways, and both go through Mentor's wrapper `/usr/local/bin/gnome-control-center`, which sets `GSK_RENDERER=cairo` (unless it is set already) and runs `/usr/bin/gnome-control-center`:
1. From the app grid, the taskbar and the system menu, by D-Bus: its desktop file says `DBusActivatable=true`, so the `Exec` line of a desktop file is never used. `/usr/local/share/dbus-1/services/org.gnome.Settings.service` is found before GNOME's `/usr/share/dbus-1/services/org.gnome.Settings.service` and starts the wrapper.
2. As a command (`gnome-control-center`, the desktop menu's Settings, the agent): `/usr/local/bin` comes before `/usr/bin` in PATH.

Do not put `env GSK_RENDERER=cairo` into a copy of `org.gnome.Settings.desktop` in `~/.local/share/applications`: it does nothing when Settings is started by D-Bus, and the copy hides every later change to GNOME's own file.

**Check.** Open Settings from the app grid. Then `tr '\0' '\n' < /proc/$(pgrep -f -o gnome-control-center)/environ | grep GSK` says `GSK_RENDERER=cairo`. Go to Mouse & Touchpad, then to another page: it answers.

**If Settings freezes anyway.** Read `journalctl -b -o cat _COMM=gnome-control-center | tail -20`. If `GSK_RENDERER` is not in its environment (the check above), one of the two files is missing: `sudo mentor restore /usr/local/bin/gnome-control-center /usr/local/share/dbus-1/services/org.gnome.Settings.service` (the user runs it), then close Settings and open it again.

## Languages

**What the user has.** Settings, System, Region & Language, Language lists about 37 languages: English (US and UK), German, French, Spanish, Italian, Portuguese, Dutch, Polish, Czech, Slovak, Slovenian, Croatian, Hungarian, Romanian, Bulgarian, Greek, Russian, Ukrainian, Turkish, Swedish, Danish, Norwegian, Finnish, Estonian, Latvian, Lithuanian, Japanese, Chinese, Korean, Arabic, Hebrew, Indonesian and Thai. Choosing one changes GNOME and its apps after a log out.

**How.** GNOME's translations come with its packages, all of them. A language is only listed once its locale is made: `mentor-enable` (run by the image build and by every update) uncomments those languages' `xx_YY.UTF-8 UTF-8` lines in `/etc/locale.gen` and runs `locale-gen`.

**Mentor's own words stay English**: the chat's buttons and cards, Mentor Settings and the desktop menu. The assistant itself answers in the user's language. Say so when a user changes the language.

**When the user asks for a language.**
1. If it is in the list above: tell them: "Open Settings, System, Region & Language, Language, choose it, then log out and in again." Or set it for them through AccountsService (`busctl call org.freedesktop.Accounts /org/freedesktop/Accounts/User$(id -u) org.freedesktop.Accounts.User SetLanguage s de_DE.UTF-8`, which asks for the password), then ask them to log out.
2. If it is not listed: find its line with `grep -n "xx_YY" /etc/locale.gen` (some have no `.UTF-8` in the name, for example `hi_IN UTF-8`). Uncomment it and run `locale-gen` as root, in the sandbox, and apply. Then do step 1.
3. Check: `localectl list-locales` lists it.
