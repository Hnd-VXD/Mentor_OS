# Repair mode: the agent on a text screen, when the desktop does not come up

In the user's words: the desktop does not come up; a black screen after the start; Mentor does not start; there is no desktop.

This is for the agent, written so that a small model can follow it. Repair mode is the way back in when Mentor's desktop is gone: after a GNOME upgrade the assistant is no longer on the wallpaper, the shell does not start, or something of Mentor's own is broken so badly that there is no chat to ask in. The system is started with the bare minimum, without GNOME at all, and the user talks to you on a text screen. **If you are reading this because you were started in repair mode, go to "What to do when you are started in repair mode".**

## What the user has

- **A "Repair" button in the launcher on Windows** (and `Mentor.exe --repair`). It starts Mentor without its desktop: a black screen with text, logged in, with you already on it.
- **`mentor repair`**, the same conversation in any terminal, for when GNOME still runs and only the assistant is gone.
- **A conversation**: they type, you answer in plain text; each tool you call shows as a line `> name detail`.
- **Approval on the same screen**: when a tool needs root, the password is asked there. The preview of a sandbox change is shown as text, with `y` to apply and `d` to see the differences.
- **A few commands**: `/restart` (restart, to see whether the desktop comes up; that start is an ordinary one), `/engine` (talk to another engine), `/verify`, `/shell` (a command line; `mentor repair` comes back), `/help`.
- **If no engine is ready**, the screen says how to make one ready and how to check and put back Mentor's files by hand.

## What to do when you are started in repair mode

You cannot see the desktop from here, and tools that need it do not work: screen_capture, app_open, terminal_run, session_logout, window_mode, and the shell's part of desktop_check. Everything else works. Write plain text, short. Do these in order.

**1. Find out what is wrong. Change nothing yet.** Run each with run_command and read the answer.

| Command | What it tells |
|---|---|
| `mentor verify` | which of Mentor's own files are missing or changed |
| `mentor journal -n 20` | what the assistant changed last, and for which request: what was done just before the desktop went is the first suspect (JOURNAL.md) |
| `tail -80 /var/log/pacman.log` | what was installed or upgraded last, and when |
| `journalctl -b -1 -p err -o cat \| tail -40` | what the start before this one complained of |
| `journalctl -b -1 -o cat _COMM=gnome-shell \| tail -60` | what the desktop itself said in that start; lines with `mentor` or `JS ERROR` matter most |
| `journalctl -b -1 -o cat --user \| grep -B2 -A14 Traceback \| tail -40` | whether the assistant (mentor-chat) stopped with an error |
| `pacman -Q gnome-shell python gtk4 libadwaita` and `cat /usr/share/gnome-shell/extensions/mentor@mentor.local/metadata.json` | which GNOME is installed, and which versions Mentor's extension names |
| `mentor boot` | which kernel runs, which is known to work, whether a start was undone |
| `systemctl --failed --no-legend` | services that failed in this start |

(`-b -1` is the start before this one. If that was also a repair start, try `-b -2`.)

**2. Tell the user** in a few lines what you found and what you propose, and wait for their say.

**3. Mend it**, following the file for the part:

| What you found | Read | In short |
|---|---|---|
| Files of Mentor's missing or damaged | REBUILD.md, step 2 | the ones you may write: put back from `/etc/mentor/source/rootfs/` through the sandbox. The others: ask the user to type `/shell`, then `sudo mentor restore --all`, then `mentor repair` |
| GNOME is a major version the extension does not name, or the shell's log has errors from `mentor@mentor.local` | DESKTOP.md, "When GNOME moves to a new major version" and "Mending one part" | read the shell's own code for the names that failed, change that part of `extension.js`, add the version to `metadata.json`, `node --check` |
| The assistant stopped with a Python error | ASSISTANT.md, "When it is broken" | a damaged file: put back as built. A class or method of GTK or libadwaita that is gone: make that one replacement |
| An engine no longer answers | ENGINES.md | run it by hand and read what it says |
| The kernel, the initramfs, a module | BOOT.md | the old one starts by itself; find out why the new one failed |
| A package upgrade broke something that is not Mentor's | | find the package in pacman's log; its earlier version is in `/var/cache/pacman/pkg/` and can be put back with `pacman -U FILE` in the sandbox |
| The journal shows a change made just before the desktop went | JOURNAL.md | its "way back" line names the tool that undoes it (change_undo ID, file_restore, package_remove, settings_set to the value before). Say which change you mean and undo that one |
| Nothing of the above | | say so plainly, and that the launcher's "Restore points" (under **More options**, below the settings) goes back to before the change, at the cost of what was done since |

Work in the sandbox (sandbox_run, sandbox_changes, sandbox_apply) for anything outside the user's own folder. One part at a time.

**4. Check what can be checked from here**: `mentor verify`; `node --check` on a changed `extension.js`; `python3 -c "import ast; ast.parse(open('/usr/local/bin/mentor-chat').read())"` on a changed assistant. Whether the desktop comes up can only be seen by starting it.

**5. Say that you are done**, what you changed, and that they should type `/restart`. Say what to do if the desktop still does not come up: start the launcher's Repair again and tell you so; you then look at the log of that start (step 1) for the next error.

**6. Write what you changed** in `~/.local/share/mentor/notes.md`, and when a file of Mentor's is now changed on purpose and works, `mentor verify --accept`.

## How it is made

| What | Where | What it does |
|---|---|---|
| The launcher's button | `Mentor.exe` on Windows (source: `launcher/Mentor.cs`, `--repair`) | starts QEMU with `-smbios type=11,value=io.systemd.boot.kernel-cmdline-extra=systemd.unit=mentor-repair.target mentor.repair=1`. systemd-boot reads that from the firmware and adds it to the kernel's command line. No desktop is waited for; a restart from there is an ordinary start |
| The target | `/usr/local/lib/systemd/system/mentor-repair.target` | everything of `multi-user.target` (network, services), no display manager, and the console below |
| Starting again from nothing | The launcher window on Windows has **Start over…** (under **More options**, below the settings, folded away at first). Its window says everything that is lost (files, apps, settings, conversations, recipes, sign-ins, the NVIDIA key, restore points), offers **Back up first**, and has one switch, off by default: "Also download the newest Mentor (about 2.3 GB)". Off, it deletes the installation and starts from the system already on the computer (updates then bring it up to date). On, it downloads the newest release from GitHub, checks it, and only then deletes the installation; that one also brings what updates cannot (a new kernel, users, the boot splash: UPDATES.md). Mentor.exe from before 2026-10-18 had these as two buttons, **Reinstall** and **Start over**. Suggest it only as a last resort, after saying what is lost, and only after the user has backed up or copied what they want to keep | `launcher/Mentor.cs`: `StartOverDialog`, `Reinstall` (resumes a dropped download; `MENTOR_RELEASE` points it at another address for a test); `launcher/LauncherWindow.cs`: `fresh.Click` |
| The emergency console | Ctrl+Alt+Backspace on a running system opens the same conversation on tty3, with the desktop still running behind it (`MENTOR_EMERGENCY=1`: its own prompt, opening and `/desktop`): FREEZES.md | |
| Gemini reaching for its own tools | The Antigravity CLI may not use its own tools here; a refusal ends its turn. As in the chat, the console tells it once to use the Mentor tools (call_mcp_tool) and sets it going again on the same request (`ask(..., carried=True)`); only a second refusal is shown as "it reached for a tool of its own… Ask again." | |
| How the console looks | `mentor_repair.py`: `banner()` draws `LOGO` ("Mentor" in ASCII letters, light cyan down to blue) with a yellow line under it ("repair mode", or "emergency console - you are not stuck"); `render()` draws the agent's answers: engines write Markdown whatever they are told, so the marks are taken out, headings and **bold** shown bright, `code` in cyan, ``` blocks indented in cyan and not wrapped, bullets as dots; `chips()` paints the commands and keys in green in every line said, `paint()` the agent's steps in grey, and the prompt `you>` is green (`PROMPT_MARK`; readline is imported for line editing). Colour only on a terminal (`COLOR`). The emergency console keeps the console's usual letter size (`setfont`, the user preferred it, 2026-10-15); the repair start is drawn by kmscon, as the emergency console is: letters of 16 pixels times the host's screen scaling (`opt/mentor/scale` in fw_cfg), 1000 lines kept that the mouse wheel or Shift+PgUp / Shift+PgDn scroll back to, a blinking cursor, and a pointer of its own (a cursor plane, as the desktop's: QEMU's window then treats the pointer as it does on the desktop). Without kmscon, the kernel's console: the usual 8x16 up to a scaling of 1.2, `LatGrkCyr-12x22` below 2, the usual doubled (16x32) from 2, the cursor shown again (`vt.global_cursor_default=0` hides it), no scrollback (`mentor-repair-console`; the kernel's console always doubled and stretched was too big, kept nothing that scrolled away and had no cursor, the user, 2026-10-23). The launcher draws this screen in its window's real pixels (`video=Virtual-1:WxH` on the command line; kmscon takes the size the window asks for) | |
| The console | `/usr/local/lib/systemd/system/mentor-repair-console.service`, running `/usr/local/lib/mentor/mentor-repair-console` (which takes the console to use, `tty1` when none is named) | in place of the login prompt on the first console: `kmscon --vt=1 --switchvt --font-size N --login -- /bin/login -f USER` (if kmscon is missing or ends within 5 seconds, `agetty --autologin USER` on tty1) for the user the desktop logs in by itself (`AutomaticLogin` in `/etc/gdm/custom.conf`, otherwise user 1000), with letters sized by the host's screen scaling (above), and it tells the launcher `{"boot": "repair"}` on `org.mentor.control`, which then swaps its loading window for this screen (no word within 20 seconds of `starting`: it does so anyway). A real login, so that there is a session for approvals |
| What opens on it | `/etc/profile.d/mentor-repair.sh` | on the first console, when the kernel's command line has `mentor.repair=1`: runs `mentor repair` once |
| The conversation | `/usr/local/lib/mentor/mentor_repair.py`, started by `mentor repair` | finds an engine that is ready (the one the assistant was set to first: `engine` in `~/.config/mentor/chat.json`), runs it once per message exactly as the assistant does (ENGINES.md), prints its text and tool calls |
| Approvals | `APPROVALS` in `mentor_repair.py` | a polkit agent of the user's own for the console (`PolkitAgent.TextListener`, registered for the session). Without it pkexec asks by itself and is refused ("No session for cookie"): it asks as root, and the answer is expected from the user |
| The text preview | `_review_on_console` in `mentor_tools.py` | used by sandbox_apply when there is no `WAYLAND_DISPLAY` or `DISPLAY` |
| The safe start does not interfere | `ConditionKernelCommandLine=!mentor.repair=1` in `mentor-boot-deadline.service` | a repair start never shows a desktop, and must not be restarted for that |

All of these are files you cannot write: they are the way back in, and stay as built. The user puts them back with `sudo mentor restore PATH` (REBUILD.md).

It leans on: systemd-boot reading `io.systemd.boot.kernel-cmdline-extra` from SMBIOS (a systemd of the last few years); `kmscon` (package `kmscon`), or `agetty` and `setfont` (packages `util-linux`, `kbd`); polkit's Python bindings (`Polkit` and `PolkitAgent` through `python-gobject`); the engines' own programs.

## How to tell that it works

| Check | Good answer |
|---|---|
| `systemctl cat mentor-repair.target mentor-repair-console.service \| head -3` | the units are found |
| `systemd-analyze verify /usr/local/lib/systemd/system/mentor-repair.target` | no errors |
| `mentor repair` in a terminal | the heading "Mentor, repair mode.", the result of `mentor verify`, then "Talking to NAME." and an answer |
| in it, ask for something that needs root (restart a harmless service) | the password is asked on the same screen and, when right, the action is done (`mentor log -n 1`) |
| the launcher's Repair button | a text screen, logged in, with the same conversation; `/restart` starts the desktop |

## When repair mode itself is broken

In the user's words: repair mode does not work; only a login prompt on the text screen; mentor repair shows an error; nothing starts at all.

- **The text screen shows a login prompt and nothing else**: the target was reached, the console was not. Log in (the user's name and password), then `mentor repair`. Why: `systemctl status mentor-repair-console.service`.
- **`mentor repair` ends with a Python error**: a file in `/usr/local/lib/mentor` is damaged or missing. The screen then prints how to check and put files back by hand: `sha256sum --quiet -c /etc/mentor/source/MANIFEST.sha256`, and `sudo cp -a /etc/mentor/source/rootfs/PATH /PATH`.
- **No engine is ready**: the NVIDIA models need only a key in `~/.config/mentor/keys/nvidia`. Claude and ChatGPT can be signed in to from the text screen (`/usr/local/lib/mentor/mentor-engine claude`); they print an address to open in a browser on another device. Gemini's sign-in is kept in the session's keyring; if it cannot be read here, use another engine.
- **The desktop starts though Repair was pressed**: the kernel's command line did not get the addition (`cat /proc/cmdline` should end in `systemd.unit=mentor-repair.target mentor.repair=1`). Then a newer systemd-boot may read it differently: its manual page (`man systemd-boot`, "SMBIOS Type 11 Strings") says how. From a running system the text screen is reached with `sudo systemctl isolate mentor-repair.target`; there, type `mentor repair`.
- **No internet here** (an engine cannot connect, a download fails): Mentor's guard on programs going online keeps programs it does not know offline until the user answers, and nothing can answer on this screen. `/usr/local/lib/mentor/mentor-netguard list` shows what waits; with the user's yes, `/usr/local/lib/mentor/mentor-netguard allow 'PATH'` lets one out (no password). `grep DefaultAction /etc/opensnitchd/default-config.json` saying `deny` while `systemctl is-active mentor-netguard` is not `active`: as root `/usr/local/lib/mentor/mentor-netguard default allow` (SECURITY.md, "Programs going online" and "When it is broken" 6f).
- **Nothing starts at all**: this is beyond repair mode. The launcher's "Restore points" (under **More options**) goes back to a moment when the system worked.
