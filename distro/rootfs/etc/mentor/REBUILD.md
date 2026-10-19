# Everything Mentor adds to the system, and how to put it back

This is for the agent, and written so that a small model can follow it step by step. Mentor is Arch Linux with GNOME, plus the files listed here. When one of them is lost, damaged, or broken by a new version of GNOME, the kernel or another program, this file says how to find out which, and how to make it work again. Do the steps in the order given. Do not skip the check at the end of a step. When a step does not give the result it says, stop and tell the user what you saw; do not improvise around it.

## The three things you have

1. **A copy of every file of Mentor's, exactly as it was built**: `/etc/mentor/source/rootfs/` holds each file at its own path (the copy of `/usr/local/bin/mentor-chat` is `/etc/mentor/source/rootfs/usr/local/bin/mentor-chat`). `/etc/mentor/source/build/` holds how the rest of the system was set up: `customize.sh` (the commands), `packages.x86_64` (the packages), `config.env`, and the start-up picture's parts in `splash/`.
2. **A list of what each file should contain**: `/etc/mentor/source/MANIFEST.sha256`.
3. **One instruction file per part**, in `/etc/mentor/`:

| File | What it covers |
|---|---|
| `REBUILD.md` | this one: every file, how to check them, how to put one back |
| `DESKTOP.md` | what is added to GNOME: the shell extension, key bindings, the taskbar; a new GNOME version |
| `ASSISTANT.md` | the assistant itself (mentor-chat): the window on the desktop, conversations, attachments, the bell |
| `ENGINES.md` | the models the assistant runs on: NVIDIA, Claude, ChatGPT, Gemini; picker, sign-in, usage |
| `TOOLS.md` | the tools the agent has, approval, the sandbox, undo, the rules it runs under |
| `BOOT.md` | starting safely after a change: trial start, going back by itself, the start-up picture; a new kernel |
| `SUGGESTIONS.md` | what the system brings up by itself: updates, disk, failed services, Arch and GNOME news, new apps, GitHub |
| `MONITOR.md` | a quiet watch on memory, processor and network: not built in, built on request from code kept here |
| `GAMING.md` | games: Steam, Lutris, Heroic, and the 32-bit graphics drivers they need; not built in, set up on request with the script kept here |
| `REPAIR.md` | repair mode: you on a text screen when the desktop does not come up; what to do there |
| `RECIPES.md` | recipes: writing down what was built so another Mentor can build it; following one |
| `FREEZES.md` | when the desktop freezes: its processor share, the watch from outside it, the record of each stall; when a program crashes: the card and how to look at it |
| `UPDATES.md` | updates of Mentor itself: the daily look, the signature, the card, how one is installed and tried |
| `ASKBAR.md` | the assistant's text box lifted over the program in front (Alt+Space, Super+Z), with a picture of the screen for the agent |
| `SETTINGS.md` | Mentor Settings: one short page of the user's choices in plain words; where each is kept |
| `SECURITY.md` | the firewall, the checks of the user's safety, the warning after outside text, the words before a password |
| `JOURNAL.md` | the journal: what was changed on this system, when and after which request; when to read it |
| `AGENT.md` | what every engine is told; the rules of work |
| `WINDOWS.md` | Mentor.exe on Windows and what of it reaches this system: its updates, Windows' sleep, the link to it (time zone, Windows Hello, cards), sound and microphone, Speed, USB devices, backups, the diagnostics file |

`/etc/mentor` is closed to you: you read these files, you cannot change them. What you make or change that they do not say yet, write in `~/.local/share/mentor/notes.md`, and read that file together with them.

## Step 1: find out what is wrong

Run these and read the output before doing anything else.

```
mentor verify
```

It prints one line for each file of Mentor's that is `missing` or `changed`, or says that every file is as it was built. Run as the user it also says "(1 file(s) only root may read were not checked: sudo mentor verify)": that is normal and no fault (a file only root may read, such as a sudoers file); Mentor's own self-check runs as root and covers it, so go on without it. If `mentor` itself does not start, this does the same:

```
sha256sum --quiet -c /etc/mentor/source/MANIFEST.sha256
```

Then:

```
mentor doctor
```

(tool: desktop_check). It says which parts of the desktop work right now. It does not look at every background service of Mentor's: when a feature has gone quiet (no crash card, no update card, no warnings) and doctor and verify are both clean, go to Step 2b.

Then `mentor journal -n 20` (tool: journal_read): what was changed on this system last, and for which request. A fault that began after one of those changes most likely comes from it.

Then read `~/.local/share/mentor/notes.md` if it exists. **A file that verify calls changed is not a fault if the notes say it was changed on purpose** (for example the extension, adapted to a new GNOME). Only a file that is missing, or changed with no note, or changed and no longer working, is to be put back.

When you have changed a file of Mentor's on purpose, and it works, say so: `mentor verify --accept`. From then on verify lists it as `accepted` and not as a fault, until it changes again. Mentor checks itself this way after every login and a few times a day (mentor-watch); what it finds missing, changed without being accepted, or broken is shown to the user as a red card in the chat.

## Step 2: put a file back as it was built

There are two kinds of files.

**Files you may write** (everything not in the next list). Use sandbox_run, then sandbox_changes to look, then sandbox_apply:

```
install -D -m 644 /etc/mentor/source/rootfs/PATH /PATH
```

Use `-m 755` for the programs: everything in `/usr/local/bin/` and the files in `/usr/local/lib/mentor/` whose names have no `.py`. The copy has the right mode already, so this always gives the right one:

```
cp -a /etc/mentor/source/rootfs/PATH /PATH
```

**Files you may not write**: anything under `/etc/mentor`, `/usr/local/lib/mentor`, `/var/lib/mentor`, `/var/log/mentor`, `/usr/share/polkit-1`, `/boot/mentor`, the files `/usr/local/bin/mentor`, `/usr/local/bin/mentor-mcp`, `/etc/pacman.d/hooks/zz-mentor-boot.hook` and `/etc/tmpfiles.d/mentor.conf`, and the `mentor-boot-*` units. (The exact list is `ALWAYS_PROTECTED` in `mentor_core.py`, with `[files] protected` of `policy.toml`.) They are the layer that keeps the agent in check, and you are not the one to rewrite it. Ask the user to run this in a terminal (open one for them with terminal_run only if they agree):

```
sudo mentor restore PATH
```

or, for every file that verify lists, `sudo mentor restore --all`. It keeps what was there as `PATH.before-restore`. If `mentor` does not start: `sudo cp -a /etc/mentor/source/rootfs/PATH /PATH`.

After putting a file back, run `mentor verify` again: the file must no longer be listed. Then do what the table below says in "takes effect".

## Step 2b: a service of Mentor's that is switched off

`mentor verify` checks files, not whether a service is switched on: a service can be off while every file is as built. `mentor doctor` then says `WARN ... is off`, or a feature quietly stops (no crash card, no update card, the "Dash to Panel has been updated!" notice at each login). Which are switched on, and how, is `/usr/local/lib/mentor/mentor-enable` (read it with `cat`; it is the one list):

- **The user's services, switched on for every user** (`systemctl --global enable`): `mentor-watch.timer`, `mentor-firewall-watch.service`, `mentor-recipe-watch.service`, `mentor-taskbar-quiet.service`, `mentor-crash-watch.service`.
  Check, as the user: `systemctl --global is-enabled NAME` must say `enabled`. The user's own `systemctl --user is-enabled NAME` follows it: `disabled` there while the global one is off says nothing more; only `masked`, or `disabled` while the global one is `enabled`, is the user's own setting. Fix: the global one is root's (sandbox_apply, or run_root_command): `systemctl --global enable NAME`; a user's own `disabled`/`masked` is undone as the user: `systemctl --user unmask NAME; systemctl --user enable NAME`. Then start it now, as the user, so no logout is needed: `systemctl --user daemon-reload; systemctl --user start NAME` (without the reload the user's systemd still thinks it is disabled) (a `.timer`: start the timer, not its service). `mentor-taskbar-quiet` runs once at login; start it now too, so the stored version is put right before the next login.
- **The system's services** (`systemctl enable`): `gdm`, `NetworkManager`, `systemd-timesyncd`, `qemu-guest-agent`, `mentor-boot-check`, `mentor-boot-deadline`, `mentor-boot-confirm.path`, `mentor-boot-arm`, `mentor-advisor.timer`, `mentor-update-check.timer`, `nftables`, `mentor-root.socket`, `mentor-power-button`, `mentor-sentinel`, `mentor-emergency-key`.
  Check: `systemctl is-enabled NAME` says `enabled`, `systemctl is-active NAME` says `active` (a `.timer`: `systemctl list-timers NAME` shows a next run; a oneshot such as `mentor-boot-check` is `inactive` between runs, which is fine). Fix (service_control or sandbox_apply, root): `systemctl enable --now NAME`. For a `.timer` that was off, also run its service once (`systemctl start mentor-update-check.service` for `mentor-update-check.timer`): until it has run, `list-timers` shows the NEXT column as `-` and the timer waits. The `mentor-boot-*` units are the user's to switch on (`sudo systemctl enable NAME`): they are the safe start, outside your reach. Never switch `nftables` off or leave it off: SECURITY.md.

Look in `mentor journal -n 20` whether it was switched off on purpose (the user asked for it): then ask before switching it on again. Nothing there about it (the usual case, it says nothing of how): switch it on, it is part of Mentor as built. The `explain` for the password: "I am switching back on a small part of Mentor that had been turned off." Good answer at the end: `mentor doctor` has no `WARN ... is off` line left. Both halves are needed: the enable is what lasts (the next login, the next start), the start is what makes it work now; no logout or restart is needed for any of these. If the password is refused, do not try another way: tell the user in one sentence what is off and that you can switch it on when they agree.

## Step 3: when the file as built no longer works

This is the case after a new GNOME, kernel, Python or other program: the file is there and unchanged, and it fails. Then putting it back does nothing. Go to the instruction file of that part (the table below names it), which says what of other people's software the part leans on, how to see the error, and how to make the same thing the new way. Work in the sandbox, test, apply, write what you changed in the notes.

## Every file

"Write" says whether you may change it (yes) or the user must (user). "Takes effect" says what has to happen for a changed file to be used.

### The assistant and what starts it

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/local/bin/mentor-chat` | the assistant: the window that is the desktop | yes | at login, or start it again | ASSISTANT.md, ENGINES.md |
| `/usr/share/icons/hicolor/scalable/actions/mentor-thumb-up-symbolic.svg`, `mentor-thumb-down-symbolic.svg` | the thumbs in the Recipes app and in the "Did it work?" card | user | next start of the app | RECIPES.md |
| `/usr/local/bin/mentor-agent` | the engine for the NVIDIA and OpenAI models | yes | next message | ENGINES.md |
| `/etc/xdg/autostart/mentor-desktop.desktop` | starts mentor-chat at login | yes | login | ASSISTANT.md |
| `/usr/local/bin/mentor-settings` | Mentor Settings: the window for the user's choices about safety, suggestions, warnings, and the journal to read | yes | next time it is opened | SETTINGS.md |
| `/usr/local/bin/mentor-recipes` | the Recipes app: used recipes (thumbs, take away), written here (open, share), downloaded and not used, and a button to the site | user | next start | RECIPES.md |
| `/usr/share/applications/org.mentor.Recipes.desktop` | puts the Recipes app in the application grid | yes | at once | RECIPES.md |
| `/usr/share/icons/hicolor/scalable/apps/org.mentor.Recipes.svg` | the Recipes app's icon (a recipe card with `</>` and a bookmark); `gtk-update-icon-cache -f /usr/share/icons/hicolor` after changing it | yes | at once | RECIPES.md |
| `/usr/share/applications/org.mentor.Settings.desktop` | puts it in the application grid | yes | at once | SETTINGS.md |
| `/usr/share/icons/hicolor/256x256/apps/org.mentor.Settings.png`, `/usr/share/icons/hicolor/512x512/apps/org.mentor.Settings.png` | its icon (the owl in a rounded square); `gtk-update-icon-cache -f /usr/share/icons/hicolor` after changing it | yes | at once | SETTINGS.md |
| `/usr/local/lib/mentor/mentor_pointer.py` | the mouse pointer of Mentor Settings and `mentor pointer`: black (Adwaita), white or the accent color, made from Adwaita's pointer into `~/.local/share/icons/Mentor-pointer-*`, and its size | user | at once | DESKTOP.md "Pointer" |
| `/usr/local/lib/mentor/mentor_colors.py` | the window colors of Mentor Settings and `mentor colors`: 20 sets of tones written into the user's `~/.config/gtk-4.0/gtk.css` and `gtk-3.0/gtk.css`, the tones for the taskbar and the shell's menus (`~/.config/mentor/taskbar-color`), and the window buttons as yellow, green and red rounded squares (`buttons()`, a block of its own in the same two files, put back by the assistant at every start) | user | when a program is opened again | DESKTOP.md "Window colors", "Window buttons" |
| `/usr/share/gnome-shell/extensions/mentor@mentor.local/stylesheet-light.css`, `stylesheet-dark.css` | the taskbar's nine dots dark in light style; the nearly empty dark one makes the shell swap the two when the style changes | yes | login (session_logout) | DESKTOP.md "Window colors" |
| `/usr/local/lib/mentor/mentor_settings.py` | reads and writes the file of those choices (`~/.config/mentor/settings.json`) | user | next call | SETTINGS.md |
| `/usr/share/applications/org.mentor.Chat.desktop` | gives the assistant its name and icon (Mentor Settings' owl, `Icon=org.mentor.Settings`) | yes | login | ASSISTANT.md |
| `/usr/share/icons/hicolor/256x256/apps/org.mentor.Chat.png` | the icon; run `gtk-update-icon-cache -q -f /usr/share/icons/hicolor` after | yes | login | ASSISTANT.md |
| `/usr/local/lib/mentor/mentor-engine` | signs in to Claude, ChatGPT, Gemini; downloads their program | user | next sign-in | ENGINES.md |
| `/usr/local/lib/mentor/mentor-usage` | asks an account how much of its allowance is used | user | next message | ENGINES.md |
| `/etc/profile.d/mentor-path.sh` | puts `~/.local/bin` on the path, where the engines' programs are | yes | login | ENGINES.md |

### The desktop

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js`, `metadata.json` | the shell extension: makes the assistant the desktop, system menu switches, search, app menus, the ask bar, the game mouse; and for Window colors the parts `taskbar color`, `menu colors` (the shell's menus in the set's tones) and `keep style` (light or dark stays the set's, with a notice; the Dark Style switch hidden) | yes | login (session_logout) | DESKTOP.md |
| `/etc/dconf/db/local.d/00-mentor`, `/etc/dconf/profile/user` | the defaults: enabled extensions, favourites, keys (Super+A, Alt+Space and Super+Z for the ask bar), dark style, wallpaper. Run `dconf update` after | yes | login | DESKTOP.md |
| `/usr/share/nautilus-python/extensions/mentor.py` | "Ask Mentor…" in Files | yes | `nautilus -q` | DESKTOP.md |
| `/usr/share/backgrounds/mentor/*.jpg`, `/usr/share/gnome-background-properties/mentor.xml` | the wallpapers and their list in Settings | yes | at once | DESKTOP.md |
| `/etc/chromium/policies/managed/mentor.json` | Chromium comes with uBlock Origin Lite | yes | next start of Chromium | DESKTOP.md |
| `/etc/chromium-flags.conf` | `--no-first-run`: no blank "Additional Terms of Service" window at Chromium's first start | yes | next start of Chromium | DESKTOP.md |
| `/etc/chromium/policies/recommended/mentor.json` | Chromium's Memory Saver on (`HighEfficiencyModeEnabled`, `MemorySaverModeSavings` 1): tabs not looked at for a while sleep; recommended, so the user can turn it off | yes | next start of Chromium | DESKTOP.md |
| `/usr/local/lib/mentor/mentor-noexec`, `/etc/systemd/system/mentor-noexec.service` | no programs from temporary folders (`/tmp`, `/var/tmp`, `/dev/shm` noexec) | yes | next start | SECURITY.md |
| `/usr/local/lib/mentor/mentor-execlog`, `/etc/systemd/system/mentor-execlog.service` | the record of every program started, `/var/log/mentor/exec.log` | yes | `systemctl restart mentor-execlog` | SECURITY.md |
| `/usr/local/lib/mentor/mentor-netguard`, `/etc/systemd/system/mentor-netguard.service`, `/etc/systemd/system/opensnitchd.service.d/mentor.conf` | the guard on programs going online: OpenSnitch's daemon (package `opensnitch`) with Mentor as its interface | yes | `systemctl restart mentor-netguard opensnitchd` | SECURITY.md |
| `/usr/local/lib/mentor/mentor_guard.py`, `/usr/local/lib/mentor/mentor-guard`, `/etc/systemd/system/mentor-guard.service`, `/etc/systemd/system/mentor-guard.timer`, `/etc/systemd/user/mentor-guard-notice.path`, `/etc/systemd/user/mentor-guard-notice.service` | the watch for unusual programs: a look as root every ten minutes, cards in the user's session | yes | the timer's next look; the path unit at the next login | SECURITY.md |
| `/etc/systemd/system.conf.d/90-mentor-stop-timeout.conf`, `/etc/systemd/user.conf.d/90-mentor-stop-timeout.conf` | `DefaultTimeoutStopSec=30s`: a shutdown waits at most 30 seconds for a program that does not stop | yes | next start | DESKTOP.md |
| `/etc/systemd/zram-generator.conf`, `/etc/sysctl.d/90-mentor-zram.conf` | compressed memory (zram swap, package `zram-generator`) and the swap settings for it | yes | next start | DESKTOP.md |
| `/usr/local/share/applications/*.desktop` | hides the launchers of developer tools that came as dependencies; puts OpenCode in the app grid | yes | at once | DESKTOP.md |
| `/usr/local/lib/mentor/mentor-clipboard`, `mentor-clipboard-files` | the clipboard shared with Windows, files included | user | login | DESKTOP.md |
| `/etc/xdg/autostart/mentor-clipboard.desktop` | starts it at login, on X11 (`GDK_BACKEND=x11`) | yes | login | DESKTOP.md |
| `/usr/local/bin/gnome-control-center`, `/usr/local/share/dbus-1/services/org.gnome.Settings.service` | GNOME Settings drawn without OpenGL, however it is started (it froze after Mouse & Touchpad) | user | next start of Settings | DESKTOP.md |
| `/etc/udev/rules.d/70-mentor-clipboard.rules` | lets the user open the two channels to the launcher on Windows | yes | `udevadm control --reload; udevadm trigger` | DESKTOP.md |

### The agent's tools and rules

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/local/bin/mentor` | the command: `mentor tools, call, doctor, verify, restore, repair, notice, journal, recipes, security, settings, ask, log, boot, …` | user | at once | TOOLS.md |
| `/usr/local/bin/mentor-mcp` | gives the tools to Claude Code, Codex and the Antigravity CLI (MCP) | user | next message | TOOLS.md |
| `/usr/local/lib/mentor/mentor_tools.py` | the tools, the user's side; among them reading text on the screen (`screen_text`, `capture_text`, with `mentor capture-text` for Shift+Super+T), reminders (`reminder_*`) and web apps (`webapp_*`) | user | next message | TOOLS.md; DESKTOP.md "Copy text from the screen" |
| `~/.config/systemd/user/mentor-reminder-ID.timer`, `.service`, `~/.local/state/mentor/reminders/ID.json` | one reminder each, made by `reminder_set` and removed when it is due or cancelled; not in the image | yes | `systemctl --user daemon-reload` | TOOLS.md "Reminders" |
| `~/.local/share/applications/mentor-webapp-NAME.desktop`, `~/.local/share/mentor/webapp-icons/NAME.png` | one web app each, made by `webapp_install`; not in the image | yes | at once | TOOLS.md "Web apps" |
| `/etc/mentor/extras/gaming/setup-gaming.sh` | sets up games on request (multilib, the 32-bit graphics drivers, Steam, Lutris); not run in the image | user | when run | GAMING.md |
| `/etc/mentor/extras/monitor/monitor.py`, `mentor-monitor.service`, `test-settings.json` | the quiet watch on memory, processor and network, its user service, and settings for trying it; not run in the image, copied to the user's folders on request | user | when set up | MONITOR.md |
| `/usr/local/lib/mentor/mentor_report.py` | `mentor tool-report`: where the tools fall short, from the journal | user | next run | TOOLS.md |
| `/usr/local/lib/mentor/mentor_journal.py` | the journal: writes down each change the tools make, under the request it was for; reads it back | user | next message | JOURNAL.md |
| `/usr/local/lib/mentor/mentor_security.py` | the safety checks; what was read from outside; what is said before a password | user | next message | SECURITY.md |
| `/usr/local/lib/mentor/mentor-explain` | the window with the plain words, and the yellow warning, before a password | user | next call | SECURITY.md |
| `/etc/nftables.conf`, `/etc/nftables.d/00-example.nft`, `/etc/systemd/system/nftables.service.d/mentor.conf` | the firewall: what comes in from other computers is refused; and its service made to count as running while the rules are loaded. `systemctl reload nftables` after | yes | reload | SECURITY.md |
| `/usr/local/lib/mentor/mentor_hub.py` | the client of the recipes site: its own key, signed posts and reports, reading the list, finding similar recipes | user | next message | RECIPES.md |
| `/usr/local/lib/mentor/mentor_recipes.py` | the material for a recipe from the journal, the folder, and the check for secrets | user | next message | RECIPES.md |
| `/usr/local/lib/mentor/mentor_core.py` | the root side: checks each request against the rules, does it, writes the log | user | next call | TOOLS.md |
| `/usr/local/lib/mentor/mentor-helper`, `mentor-sandbox`, `mentor-root-shell`, `mentor-write-file`, `mentor-apply`, `mentor-undo` | the doors to root, one for each password dialog and its words | user | next call | TOOLS.md |
| `/usr/local/lib/mentor/mentor-power-button`, `/etc/systemd/system/mentor-power-button.service` | the power button powers off (the launcher's proper shut down) | root | at once | BOOT.md |
| `/usr/local/lib/mentor/mentor-sentinel`, `/etc/systemd/system/mentor-sentinel.service`, `/etc/systemd/user/session.slice.d/50-mentor-desktop-first.conf` | the watch on freezes (it acts too: lowers a busy app, closes the largest when memory runs out), and the desktop's processor share | root | at once (the share: at the next login) | FREEZES.md |
| `/usr/local/lib/mentor/mentor-emergency-key`, `/etc/systemd/system/mentor-emergency-key.service`, `/usr/local/lib/systemd/system/mentor-emergency-console.service`, `/usr/local/lib/mentor/mentor-emergency-console` (needs the `kmscon` package) | Ctrl+Alt+Backspace: the agent on tty3 beside a frozen desktop, at the window's size | root | at once | FREEZES.md |
| `/usr/local/lib/mentor/mentor_update.py`, `/usr/local/lib/mentor/mentor-update`, `/usr/local/lib/mentor/mentor-enable`, `/usr/local/lib/systemd/system/mentor-update-check.service`, `mentor-update-check.timer`, `mentor-update-apply.service`, `/etc/polkit-1/rules.d/50-mentor-update.rules`, `/etc/mentor/update-signers` | updates of Mentor itself; the setup an image and every update share | root | the next look (timer) | UPDATES.md |
| `/etc/systemd/user/mentor-taskbar-quiet.service`, `/usr/local/lib/mentor/mentor-taskbar-quiet` | no "Dash to Panel has been updated!" notice | user | the next login | DESKTOP.md |
| `/etc/systemd/system/service.d/10-mentor-no-watchdog.conf`, `/etc/systemd/user/service.d/10-mentor-no-watchdog.conf` | no service is killed as hung after Windows slept | root | next start | BOOT.md |
| `/usr/local/lib/mentor/mentor-rootd` | asks for the password in place of pkexec, so that the dialog can say what for in the agent's own sentence; leaves that sentence for Windows Hello's prompt (`hello_hint`) | user | next call | TOOLS.md, WINDOWS.md |
| `/usr/local/lib/mentor/mentor-host-link`, `/usr/local/lib/systemd/system/mentor-host-link.service`, `/etc/udev/rules.d/70-mentor-host.rules` | the root-only link to Mentor.exe on Windows: the time zone follows Windows', Windows Hello, cards from Mentor.exe, the logs for its diagnostics file. `chmod 755` the first | user | `systemctl daemon-reload; udevadm control --reload; udevadm trigger --subsystem-match=virtio-ports` | WINDOWS.md |
| `/usr/local/lib/mentor/mentor-volume` | one volume for Windows and Mentor: the virtual output whose volume is Windows' (run as the user by mentor-host-link). `chmod 755` | user | next start of mentor-host-link | WINDOWS.md, section 5 |
| `/usr/local/lib/mentor/mentor-hello`, `/etc/pam.d/polkit-1`, `/etc/pam.d/sudo` | Windows Hello in place of the password when the user switched it on in Mentor.exe; the password always works. `chmod 755` the first | user | at once | WINDOWS.md |
| `/usr/local/lib/systemd/system/mentor-root.socket`, `mentor-root@.service` | where the tools reach it (`/run/mentor-root.sock`), one start for each request | user | `systemctl daemon-reload` | TOOLS.md |
| `/usr/local/lib/mentor/mentor_sandbox.py` | the sandbox: try on a copy, preview, apply, undo | user | next call | TOOLS.md |
| `/usr/local/lib/mentor/mentor-review` | the preview window of a change | user | next preview | TOOLS.md |
| `/usr/share/applications/org.mentor.Review.desktop` | its name and icon | yes | at once | TOOLS.md |
| `/usr/share/polkit-1/actions/org.mentor.policy` | the password dialogs: for each door, the plain words the system shows | user | at once | TOOLS.md |
| `/etc/mentor/policy.toml` | what stays forbidden even with approval | user | next call | TOOLS.md |
| `/etc/mentor/mcp.json` | names the tool server for Claude Code | user | next message | ENGINES.md |
| `/etc/mentor/*.md` | these instructions | user | next message | |

### Starting safely

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/local/lib/mentor/mentor_boot.py`, `mentor-boot` | trial start, going back after a failed one | user | next start | BOOT.md |
| `/usr/local/lib/systemd/system/mentor-boot-*.service`, `.path` | when each step runs | user | `systemctl daemon-reload` | BOOT.md |
| `/etc/pacman.d/hooks/zz-mentor-boot.hook` | after every package change: note what the next start has to prove | user | next pacman run | BOOT.md |
| `/etc/tmpfiles.d/mentor.conf` | makes `/run/mentor`, where the desktop says it is up | user | `systemd-tmpfiles --create` | BOOT.md |
| `/etc/plymouth/plymouthd.conf` | chooses the start-up picture `mentor` | yes | `mkinitcpio -P`, next start | BOOT.md |

### Repair mode

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/local/lib/mentor/mentor_repair.py` | the conversation with the agent on a text screen (`mentor repair`) | user | next run | REPAIR.md |
| `/usr/local/lib/systemd/system/mentor-repair.target`, `mentor-repair-console.service` | the start without a desktop, and its logged-in console | user | `systemctl daemon-reload` | REPAIR.md |
| `/usr/local/lib/mentor/mentor-repair-console` | logs the user in on that console | user | next repair start | REPAIR.md |
| `/etc/profile.d/mentor-repair.sh` | opens the conversation on that console | user | next repair start | REPAIR.md |

### What the system brings up by itself

| File | What it is | Write | Takes effect | Read |
|---|---|---|---|---|
| `/usr/local/lib/mentor/mentor-advisor` | looks for waiting updates, a filling disk, failed services, and the news | user | next run | SUGGESTIONS.md |
| `/usr/local/lib/systemd/system/mentor-advisor.service`, `.timer` | runs it four minutes after the start and twice a day | yes | `systemctl daemon-reload` | SUGGESTIONS.md |
| `/usr/local/lib/mentor/mentor-watch` | checks Mentor itself, the user's safety (SECURITY.md), the disk and failed services; what it finds becomes a yellow or red card in the chat | user | next run | SUGGESTIONS.md |
| `/usr/local/lib/mentor/mentor-firewall-watch` | has the agent look, by itself and once for each burst, when the firewall turns other computers away | user | `systemctl --user restart mentor-firewall-watch` | SECURITY.md |
| `/etc/systemd/user/mentor-firewall-watch.service` | runs it while the user is logged in | yes | `systemctl --user daemon-reload` | SECURITY.md |
| `/usr/local/lib/mentor/mentor-recipe-watch` | starts looking at a recipe by itself when one is downloaded, wherever the browser saves it; says "not for you" when a program it needs is missing | user | `systemctl --user restart mentor-recipe-watch` | RECIPES.md |
| `/etc/systemd/user/mentor-recipe-watch.service` | runs it while the user is logged in | yes | `systemctl --user daemon-reload` | RECIPES.md |
| `/usr/local/lib/mentor/mentor-crash-watch` | a yellow card in the chat when a program crashes (from systemd-coredump's record in the journal), the same program at most once a minute | user | `systemctl --user restart mentor-crash-watch` | FREEZES.md |
| `/etc/systemd/user/mentor-crash-watch.service` | runs it while the user is logged in | yes | `systemctl --user daemon-reload` | FREEZES.md |
| `/etc/systemd/user/mentor-watch.service`, `.timer` | runs it three minutes after login and every six hours | yes | `systemctl --user daemon-reload` | SUGGESTIONS.md |

## What was done when the system was built, besides the files

The files alone are not the whole of it. `/etc/mentor/source/build/customize.sh` ran once, as root, when the image was made. If a part of this is lost, these are the commands, to run in the sandbox (replace USER by the user's name):

```
# The packages Mentor needs (the full list is /etc/mentor/source/build/packages.x86_64)
pacman -S --needed $(sed 's/#.*//; /^[[:space:]]*$/d' /etc/mentor/source/build/packages.x86_64)

# Log in without a password prompt, straight to the desktop
printf '[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=USER\n' > /etc/gdm/custom.conf

# The defaults of the desktop, from /etc/dconf/db/local.d/00-mentor
dconf update

# What has to run
systemctl set-default graphical.target
systemctl enable gdm.service NetworkManager.service systemd-timesyncd.service qemu-guest-agent.service
systemctl enable mentor-boot-check.service mentor-boot-deadline.service mentor-boot-confirm.path mentor-boot-arm.service
systemctl enable mentor-advisor.timer
systemctl enable nftables.service          # the firewall
systemctl enable mentor-root.socket        # who asks for the password, saying what for
systemctl enable mentor-power-button.service  # the power button powers off
systemctl enable mentor-sentinel.service      # the watch on freezes
systemctl enable mentor-emergency-key.service # Ctrl+Alt+Backspace
systemctl --global enable mentor-watch.timer mentor-firewall-watch.service mentor-recipe-watch.service
systemctl --global enable mentor-crash-watch.service   # a card when a program crashes

# Where the root side writes its log
install -d -m 755 /var/log/mentor

# The icon
gtk-update-icon-cache -q -f /usr/share/icons/hicolor
```

Also done there: `/etc/pam.d/gdm-password` and `gdm-autologin` are gdm's own files without `pam_gnome_keyring.so`, so that typing the password at the login screen (after a log out) does not lock the "login" keyring with it; a keyring that got a password that way is opened again with `mentor keyring` (the user types the password once). Also done there, each explained in the file named: the name of the system in `/etc/os-release` (NAME="Mentor", ID=mentor, ID_LIKE=arch); a keyring without a password for new users, in `/etc/skel/.local/share/keyrings/` (with automatic login there is no password to unlock one with); the user in group `wheel` and `%wheel ALL=(ALL:ALL) ALL` in `/etc/sudoers.d/10-wheel`; the start-up picture (BOOT.md); the boot loader entries (BOOT.md). Read `customize.sh` itself for the exact lines.

Do not use `systemctl enable` on the `mentor-boot-*` units through run_root_command to get around a refusal; ask the user to run the line.

## How to tell that all of it works

Run these in order. Each line says what a good answer looks like.

| Check | Good answer |
|---|---|
| `mentor verify` | every file as built, or only files the notes explain |
| `mentor doctor` | "Everything of Mentor's desktop is in place." |
| `mentor tools \| head -3` | the first tools and what they do |
| `mentor call system_info '{}'` | the system's release, kernel, memory |
| `mentor boot` | which kernel runs, which is known to work, nothing waiting unless you changed something |
| `mentor journal -n 3` | the last changes under their requests, or that none is written yet |
| `mentor security` | "ok  the firewall refuses what comes in…"; findings are for the user to hear of |
| `systemctl is-enabled mentor-advisor.timer mentor-boot-check.service` | `enabled` twice |
| `systemctl --user is-enabled mentor-watch.timer mentor-firewall-watch.service mentor-recipe-watch.service mentor-crash-watch.service` | `enabled` four times |
| `systemctl is-active mentor-root.socket` | `active` |
| `pgrep -af bin/mentor-chat` | one line: the assistant is running |
| `pgrep -af lib/mentor/mentor-clipboard` | one line |
| `journalctl -b --user -o cat \| grep -A12 Traceback` | nothing |
| screen_capture | the assistant on the wallpaper, the taskbar at the bottom |

## When Mentor itself changes

These files are checked against Mentor before every image and every update is made: `build/check-docs.py` in Mentor's source, run by `build.sh`. A build stops when one of these is missing, and says which and where:

- a file of Mentor's (each line of `MANIFEST.sha256`) with no row in the tables above;
- a part of the shell extension with no row in DESKTOP.md "The parts of the extension";
- a `mentor` command with no row in TOOLS.md "The `mentor` command", or a tool that TOOLS.md (or the file this table names for `mentor_tools.py`) does not name;
- a file named in "Read" above that does not exist, or a reference such as DESKTOP.md "Window colors" to a heading, bold name or table row that is not there;
- a path of Mentor's in backticks that is neither in the image nor made while it runs.

So what is in this system is in these files. If you still find a file of Mentor's that no row names, the docs are behind: tell the user, and write what you learn about it in `~/.local/share/mentor/notes.md`.

## Rules for this work

- One part at a time. Finish and check it before the next.
- In the sandbox first, for anything outside the user's own folder.
- Say to the user what you found and what you are about to do before you change anything, and what is the same and what differs afterwards.
- Never get around a refusal: not by another tool, not by another path, not by switching a check off. A refusal means the user does it, or it is not done.
- Write what you changed in `~/.local/share/mentor/notes.md`: the date, the file, why, and how to tell that it works. Then `mentor verify --accept` for a file of Mentor's that is now changed on purpose.
- When there is no chat to work in (the desktop does not come up), the user reaches you through repair mode: REPAIR.md.
