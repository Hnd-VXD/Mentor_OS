# The agent's tools, the approval of the user, and the sandbox

This is for the agent, written so that a small model can follow it. It describes the layer between a model and the system: what the user is meant to have, which file does what, how to tell that it works, and what to do when it does not. Almost every file here is one you cannot write (see "What you may not change"); when one of them is lost or damaged the user puts it back with `sudo mentor restore`, as REBUILD.md says. What you can do is find the fault and tell them exactly which file and why.

## What the user has

- **An agent that changes the system only through named tools.** Each tool does one thing (install a package, read a setting, write a file, run a command).
- **A dialog of GNOME's for anything that needs root**, saying what is asked. Packages and services ask for the password once in a while; a free command as root, or a change to a system file, asks every time and shows the command.
- **A sandbox**: changes to the system itself are first made on a private copy. The user sees a preview of the files that would change, and only what they accept is applied.
- **Undo** for every change applied that way, and a list of them.
- **Rules that hold even with approval** (`/etc/mentor/policy.toml`): packages and services that may not be removed or stopped, files that may not be written, commands that are refused.
- **A record** of everything done as root: `/var/log/mentor/audit.log` (`mentor log`).
- **A password dialog that says what for**: one short sentence of the agent's, in the user's language; and a yellow warning window first when the agent has just read text from outside (SECURITY.md).
- **A journal** of every change made through the tools, root or not, under the request it was made for: `mentor journal` (JOURNAL.md).

## How it hangs together

```
the model (through an engine; see ENGINES.md)
   |  MCP over standard input and output        (mentor-agent calls the tools directly)
/usr/local/bin/mentor-mcp                      runs as the user; lists the tools, calls them
   |
/usr/local/lib/mentor/mentor_tools.py          runs as the user: the tools themselves
   |  /run/mentor-root.sock  ->  mentor-rootd  ->  the approval dialog (polkit), saying what for
   |  (pkexec, with a fixed sentence, when that is not there)
/usr/local/lib/mentor/mentor-helper            root, action org.mentor.manage      packages, services
/usr/local/lib/mentor/mentor-sandbox           root, action org.mentor.sandbox     commands inside the sandbox
/usr/local/lib/mentor/mentor-root-shell        root, action org.mentor.root-shell  a free command
/usr/local/lib/mentor/mentor-write-file        root, action org.mentor.write-file  one system file: change it, put it back
/usr/local/lib/mentor/mentor-apply             root, action org.mentor.apply       apply a change the user has looked at
/usr/local/lib/mentor/mentor-undo              root, action org.mentor.undo        undo an applied change
   |  each is three lines that call:
/usr/local/lib/mentor/mentor_core.py           checks the request against policy.toml, does it, writes the audit log
   |     before pkexec: mentor_security.before_root -> mentor-explain   plain words, and the warning (SECURITY.md)
   |- mentor_sandbox.py                        the sandbox
   `- mentor_boot.py                           a change that was applied is on trial at the next start (BOOT.md)
```

- **mentor-mcp** speaks JSON-RPC, one message per line: `initialize` (answers with the protocol version, `capabilities: {"tools": {}}` and the text of `/etc/mentor/AGENT.md` as `instructions`), `ping`, `tools/list`, `tools/call`. A picture a tool returns goes out as an `image` part.
- **mentor_tools.py** holds the dictionary `TOOLS`: name -> (description, JSON schema of the arguments, function). `call(name, arguments)` returns (ok, text); `call_with_image` also a picture. Adding a tool is adding an entry there; if it needs root, also an action in `ACTIONS` of `mentor_core.py`; if it changes something, also an entry in `JOURNAL`, which is what gets it written into the journal (`mentor_journal.py`, JOURNAL.md).
- **The doors.** Each is a program of three lines (`mentor_core.main("manage")`, `("sandbox")`, `("shell")`, `("write")`, `("apply")`, `("undo")`). polkit knows them by their path (`org.freedesktop.policykit.exec.path` in `/usr/share/polkit-1/actions/org.mentor.policy`). `auth_admin_keep` for the first two means the password holds for a few minutes; `auth_admin` for the other four means every time. There are six and not one so that **the system's own password dialog can say which kind of thing is about to happen**: its words are the `<message>` of the action, fixed when the system is built, one for each door. They are written for someone who has never heard of root ("Mentor wants to practise a change on a private copy of your system, to see that it works. Your real system is not touched…"). These fixed sentences are what is shown only when pkexec does the asking. Ordinarily `mentor-rootd` asks, and the dialog shows the agent's own sentence for the occasion (the tool's `explain`; SECURITY.md). `mentor_core.main` refuses to run unless it is root and was started by pkexec (`PKEXEC_UID`).
- **Who asks for the password.** `_privileged` in `mentor_tools.py` first asks Mentor's own root service: it connects to `/run/mentor-root.sock` (`mentor-root.socket`, `Accept=yes`; each connection starts `mentor-root@.service`, which runs `/usr/local/lib/mentor/mentor-rootd` as root with the connection as its input and output) and sends one line of JSON: the helper's name, the action, its arguments, the agent's `explain`, whether the user wants the exact thing shown, and how many bytes follow for the helper's standard input. `mentor-rootd` finds out who is at the other end from the kernel (`SO_PEERCRED`), asks polkit for the helper's action (`DOORS`) about the Mentor chat window that process runs under, or about the process itself when it runs under none (`asker`: every message in the chat starts a new engine with new tool processes, and polkit keeps a password "for a few minutes" only for the one it was asked for, so a change that went over two messages asked again), with the words to show as the detail `polkit.message` (only root may set that, which is why this is a service and not pkexec), and when the user has said yes runs the same helper pkexec would, with `PKEXEC_UID` set to the user. It answers with what the helper printed and a last line `\0exit N`; 126 means the user said no, 127 that they may not say yes. **Nothing about who may do what changes: the same actions, the same user, the same password, the same checks in `mentor_core.py`.** While the dialog is open it watches the connection: when the caller goes away (the user pressed Stop, the engine gave up on the tool) it takes the question back, the dialog closes, and nothing is run (`approved`). A dialog left behind used to be a second dialog for whatever came next, and its yes ran something nobody waited for. When the socket is not there, `_privileged` uses pkexec as before, and the dialog then shows the fixed sentence of the action.
- **mentor_core.py**: `ACTIONS[mode][action]` is a function that checks the arguments and returns a command to run (or does the work and returns an exit status). A refusal raises `Denied`, is written to the log, and exits 3 with "denied by policy".
- **The sandbox** (`mentor_sandbox.py`): an overlay file system over `/`, in an image file `/var/lib/mentor/sandbox.img` (sparse, 24 GB, mounted at `/var/lib/mentor/sandbox`). Each conversation has its own layer, named by `MENTOR_SANDBOX`. A command runs in it as root inside a container (`systemd-nspawn`), so it cannot touch the running system. `/boot` cannot have an overlay, so the sandbox gets a copy of it. `scan()` lists what the layer added, changed or deleted; `report()` adds text differences; `apply()` copies it onto the real system and keeps what it replaced under `/var/lib/mentor/changes/ID/`; `undo(ID)` puts that back. Sandboxes do not outlive a restart.
- **The preview** (`mentor-review report.json`): a window with the summary, the files and their differences; it exits 0 when the user chooses to apply. `sandbox_apply` in mentor_tools shows it first, then asks for root.

## The tools

Packages: `package_search`, `package_info`, `package_list`, `package_install`, `package_remove`, `system_upgrade`. Flatpak: `flatpak_search`, `flatpak_install`, `flatpak_remove`. Settings: `settings_list`, `settings_get`, `settings_set`. Services: `service_status`, `service_control`. Files: `file_read` (whole, a part by lines, or the lines matching a search), `file_search` (a folder's contents, files by name, lines inside files), `file_write`, `file_restore`. Commands: `run_command` (as the user), `run_root_command`, `terminal_run` (in a window the user watches). Sandbox: `sandbox_run`, `sandbox_changes`, `sandbox_apply`, `sandbox_discard`, `change_list`, `change_undo`. Desktop: `window_mode`, `desktop_layout`, `wallpaper_set`, `app_open`, `extension_list`, `extension_status`, `extension_set`, `screen_capture`, `desktop_check`, `session_logout`. Start-up: `system_restart`, `boot_status`, `restore_point_create`. Learning how things are made: `shell_source` (GNOME Shell's own code), `package_peek` (the files of any package, installed or not). The desktop's and the system's services: `dbus`. Sound: `sound`. Network: `network_status`. Windows: `windows`. Applications: `app_info` (what one can do), `app_action` (do one of its actions). The log: `log_read`. The web: `web_search`, `web_read`. Other: `system_info`, `suggestions_status`, `suggestions_restore`, `journal_read`, `security_check`, `recipe_material`, `recipe_save`, `recipe_list`, `recipe_inspect`, `recipe_hub_look`, `recipe_share`, `recipe_fetch`, `recipe_report`, `recipe_update`, `recipe_withdraw`, `recipe_used`, `recipe_rate`.

### The tools made from what was done by hand

In October 2026 the journal of a real system showed 198 of 223 actions done with `run_command`, mostly three things done again and again, badly: reading GNOME Shell's own code by loading its libraries in python or gjs, downloading packages with curl to look inside them, and D-Bus calls written as gjs one-liners. Each became a tool (`mentor_tools.py`):

| Tool | How it works | Kept where |
|---|---|---|
| `shell_source` | a separate python (`_SHELL_DUMP`) loads `/usr/lib/gnome-shell/lib*.so` with ctypes, which registers the shell's resources, and `/usr/share/gnome-shell/*.gresource`, and writes every file under `/org/gnome/shell/` out; list, search (regular expression, at most 300 lines) and read (with line numbers) work on that copy; a short name that fits one file is that file | `~/.cache/mentor/shell-source/<gnome-shell --version>/`, `.complete` when whole: delete the folder to make it again |
| `package_peek` | an installed package: `pacman -Qlq` and the file itself; one that is not: `pacman -Sp` gives the address, curl downloads it once, `bsdtar -tf` / `-xOf` list and read it | `~/.cache/mentor/peek/` |
| `dbus` | list: `busctl --user|--system list --acquired`; introspect: `gdbus introspect`; call: `gdbus call` with the arguments in GVariant text. A call whose method does not start with Get, List, Is, Has, Can, Query, Lookup, Find, Describe, Introspect or Ping is written in the journal | |
| `sound` | `wpctl`: status, `set-volume -l 1.0` (0% to 100% only), `set-mute`, `set-default`, on `@DEFAULT_AUDIO_SINK@` or `@DEFAULT_AUDIO_SOURCE@`. Changes are journaled | |
| `network_status` | `nmcli` general, devices, active connections, Wi-Fi nearby. Joining a Wi-Fi network is left to the Settings panel (`app_open org.gnome.Settings.desktop`, argument `wifi`), because it needs a password | |

Faults: `shell_source` says the code "could not be taken out": the python error is in its answer; a new GNOME may have renamed `libshell-NN.so` (look at `ls /usr/lib/gnome-shell`). `package_peek` says "not in the package lists": the lists are old or the name is wrong (`package_search`). `sound` says "Translate ID error" for the microphone: there is none.

The second round, the same day, from the journal of the afternoon (41 of 47 actions by hand, nearly all from two requests for "a new page in Text Editor"): what an application can do was found with `--help`, `strings` and python on its program, `gresource`, its desktop file and D-Bus introspection (16 times), and what happened with `journalctl` and `systemctl --user status` (8). So:

| Tool | How it works |
|---|---|
| `app_info` | the desktop file (`_desktop_sections`: program, MIME types, `[Desktop Action …]` entries), the GApplication's actions over D-Bus while it runs (`org.gtk.Actions.DescribeAll` on `/org/gnome/TextEditor` for `org.gnome.TextEditor`, and on its first `…/window/N`), `PROGRAM --help`, and its open windows (`windows`). Many apps keep window actions (new tab) as widget actions that are not on D-Bus: then none are listed, and only a key press would do it |
| `app_action` | a desktop action by its name (`Gio.DesktopAppInfo.launch_action` in a scope of its own, as GNOME starts it), else `app.NAME` / `win.NAME` with `org.gtk.Actions.Activate`; then looks for a new window as `app_open` does |
| `log_read` | `journalctl` with `--user` (scope session, the default) or not (system), `--since`, `--until`, `-u`, `_COMM=`, `--grep` (not case-sensitive), `-p warning` (`problems_only`), at most 400 lines |

### Finding the next tools: `mentor tool-report`

For whoever looks after Mentor (the developer, or you when asked to improve the tools), not for the user. Read only. `mentor tool-report [--days 14] [--json]` (`/usr/local/lib/mentor/mentor_report.py`) reads the journal and the saved conversations and says: how many actions were raw commands; those commands in groups by what they ran (`program_of`: the first program that is not a wrapper or a filter, inline python and gjs told apart by what they reach for, file reading and searching put together as kinds), each with examples, the requests they came from, and a verdict: **a tool exists** (`COVERED`: point the agent at it or make its description clearer), **to improve** (`IMPROVE`: a tool does it, but not well enough), or **candidate for a new tool** (three times or more, none covers it); the requests with the most steps; the tools that failed most. A journal line of a command that changed something starts with the agent's own words ("Fixed …: command"), which are taken off before grouping.

Its first run, 2026-10-14, 14 days: 239 of 270 actions raw; the biggest gap files: listing and finding them (25), reading part of one (21: `file_read` reads only a whole file), searching inside them (10). So `file_read` took `start_line`, `lines`, `search` and `context` (a long file read whole says how many lines it has and that it was cut), and `file_search` came: with only `path` a folder's entries (kind, size, date; hidden ones with `hidden`), with `name` a filename pattern (fnmatch, not case-sensitive), with `contains` lines inside text files as file:line (files over 5 MB and binary ones skipped); it walks at most 20 000 files for a search inside them and 200 000 for names, skips .git, node_modules, caches, /proc, /sys and /dev, and gives at most 200 results, saying when it stopped. In `mentor_report.py` those kinds are now `COVERED`.

### The web: `web_search` and `web_read`

Every engine has them, whatever its own tools (Gemini had none: asked how to make Gradia take only an area, it read Gradia's code for 13 minutes, 2026-10-14). Pages come through `curl` (`_web_get`: DuckDuckGo cut off Python's own client), at most 3 MB, 30 s. `web_search` reads DuckDuckGo's page without scripts (`html.duckduckgo.com/html/`), and Bing's when that gives nothing; titles, addresses (DuckDuckGo's own `uddg` redirect taken off, its adverts left out) and a line each. `web_read` makes plain text of a page (`_PageText`: no scripts, styles, menus or forms; a line break at each block; empty list items left out), `part` by `part` for long ones; only http(s). Both note what they read as outside text (`mentor_security.saw`, kind web), so the yellow warning comes before a root action that follows. If search stops working, the page layout changed: look at `curl -s 'https://html.duckduckgo.com/html/?q=test'` for `result__a`, and at Bing's for `b_algo`.

`run_command` refuses a command that starts an application with a window (`_starts_an_app`: the first word of each part of the command, after `VAR=…` and wrappers such as nohup, setsid -f, timeout 5, nice -n 5, systemd-run, is the program of an installed desktop file that is not a terminal one). Such a command waited until the window was closed; the user closing it looked to the agent like a failure, and it started the app again and again. `--help`, `--version` and `--headless` are let through. The answer sends the agent to `app_open`.

`windows` and the end of `app_open` ask Mentor's shell extension for the user's windows (`org.mentor.Shell.Windows`, `FocusWindow`, `CloseWindow` on `/org/mentor/Shell`; JSON with id, title, app, name, focused, minimized, workspace; Mentor's own windows and those that skip the taskbar are left out). `app_open` notes the windows before, starts the app, and looks for a new one for up to 8 s: "Done: it is open. New window: …", or that the app had a window already, or that none came. A screenshot is not enough for this: a picture does not reach every model, and an agent that could not tell kept opening the app. When the extension is older than these methods (before the next login after an update), `windows` says so and `app_open` falls back to asking for a screen_capture.

`app_open` starts the app in a scope of its own (`systemd-run --user --scope`), as GNOME does: started inside the agent's, it was killed when the agent's turn ended or was stopped. Files and web addresses go through `gtk-launch`; options of the app's own program (`--new-window`) go to the program line of its desktop file (`_app_command`), because `gtk-launch` refuses them ("Unknown option") and opened nothing while the tool said "opened". It waits up to 3 s and reports a launcher that failed, with what it said.

`mentor tools` prints them with their descriptions; that list is the truth, this one a summary.

**The desktop session, whatever engine started the tools.** The tool server acts in the user's session: settings (dconf), extensions, windows, apps. Some engines start it with only a few environment variables (Codex keeps HOME, PATH, USER, LANG…), and without the session's address the settings service is "not reachable", and `gsettings` even says it succeeded while nothing was written. `_find_session()` in `mentor_tools.py` fills in `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS` (`/run/user/UID/bus`) and `WAYLAND_DISPLAY` when they are missing (2026-10-15: a user's widget could not be enabled).

**A new extension.** GNOME Shell reads new extensions only at login, so for one just written `gnome-extensions enable` answers that it does not exist. `extension_set` then puts it on `org.gnome.shell enabled-extensions` itself (when its folder with `metadata.json` exists) and says that it comes up after a log out (session_logout); after the next login its state is ACTIVE. An extension with no folder at all still gives the error.

## What you may not change

`ALWAYS_PROTECTED` in `mentor_core.py` and `[files] protected` in `policy.toml`. Writing to them is refused by `file_write`, skipped by `sandbox_apply` ("not applied, protected: …"), and a root command that names them is refused by the patterns in `[root_shell] deny_patterns`. This is on purpose: it is the layer that keeps the agent in check, the files that decide who is root, and what a failed start falls back on. Do not look for a way around it.

## How to tell that it works

| Check | Good answer |
|---|---|
| `mentor tools \| head -4` | names and descriptions |
| `mentor call system_info '{}'` | release, kernel, memory, disk |
| `mentor call package_search '{"query": "gimp"}'` | lines starting `extra/gimp` |
| `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \| mentor-mcp \| head -c 300` | JSON with `"tools"` |
| `pkaction --action-id org.mentor.manage` | the action is known to polkit |
| `systemctl is-active mentor-root.socket; ls -l /run/mentor-root.sock` | `active`, and the socket, mode `srw-rw-rw-` |
| `mentor call package_install '{"packages": ["cowsay"], "explain": "I am adding a small fun program, as you asked."}'` | the password dialog with that sentence; then `mentor log -n 1` shows `pkg_install` |
| `mentor call sandbox_run '{"command": "touch /etc/mentor-test"}'` then `mentor call sandbox_changes '{}'` | a dialog, then `/etc/mentor-test` listed as added; then `mentor call sandbox_discard '{}'` |
| `mentor log -n 5` | the last things done as root |
| `mentor journal -n 5` | the last changes, each under the request it was for |
| `mentor security` | the firewall is on; what else needs attention |
| `mentor changes` | the changes applied, newest first |
| `mentor notice warning "A test" "Nothing is wrong."` | a yellow card in the assistant's chat (ASSISTANT.md, "Notices") |

## When something here is broken

1. `mentor verify`. A file listed as missing or changed here is almost always the whole fault. Tell the user which, and that `sudo mentor restore PATH` puts it back.
2. `mentor tools` fails with a Python error: read the last line. `ModuleNotFoundError: mentor_core` or `mentor_tools` means a file in `/usr/local/lib/mentor` is gone. A `SyntaxError` names the file and line that is damaged. An error naming a Python class or module that is not Mentor's means Python itself moved on: read "After a new Python" below.
2a. A tool says "the connection to Mentor's root service broke" or "ended without saying how": `journalctl -b -u 'mentor-root@*' -n 20 -o cat` has the Python error of `mentor-rootd`. `Polkit` missing there means the package `polkit` or `python-gobject` lost its part. Until it is mended, the user can stop the service (`sudo systemctl stop mentor-root.socket`): the tools then go back to pkexec by themselves.
2b. The user is asked for the password again for one change: `org.mentor.manage` and `org.mentor.sandbox` are kept for 5 minutes for the chat window (`asker` in `mentor-rootd`); `apply`, `undo`, `write-file` and `root-shell` ask every time, by design. If a kept one asks again within minutes, the chat window was restarted, or `asker` did not find `/usr/local/bin/mentor-chat` above the tool process (`ps -o pid,ppid,args` up the chain). An engine that gives up on a tool and calls it again also asks again: Codex is given `mcp_servers.mentor.tool_timeout_sec` 7200 for that reason (`mentor-chat`, its own default is 60 s).
3. No dialog appears and a tool says "not authorized" or "No authentication agent": the session has no polkit agent (GNOME Shell is one), or the action file is gone. `pkaction --action-id org.mentor.manage` tells which.
4. "this helper only runs through pkexec": something called a helper directly. Nothing to fix.
5. The sandbox says it cannot mount, or a command in it fails at once: `systemd-nspawn` needs the package `systemd` (always there) and the kernel's `overlay` and `loop` modules; `modprobe overlay loop` as root, then try again. A new kernel that has not been restarted into has no modules for the running one: restart first.
6. After the fix, run the table above again.

### After a new Python

Mentor's programs use only Python's own library, plus `gi` (package `python-gobject`) for the windows. `mentor_core.py` needs `tomllib` (Python 3.11 and later). When a new Python removes or renames something they use, the error names the file, the line and the name. Find what replaces it in Python's "What's New" for that version, make the one change, and say to the user which file must be replaced; for a file you cannot write, give them the corrected file in their own folder and the command `sudo install -m 644 FILE /usr/local/lib/mentor/NAME` (755 for the programs).

## Making it again from nothing

Everything is in `/etc/mentor/source/rootfs/` at its own path. In this order, as root (the user runs it; you cannot):

```
src=/etc/mentor/source/rootfs
cp -a $src/usr/local/lib/mentor /usr/local/lib/        # mentor_journal.py among them
cp -a $src/usr/local/bin/mentor $src/usr/local/bin/mentor-mcp /usr/local/bin/
cp -a $src/usr/share/polkit-1/actions/org.mentor.policy /usr/share/polkit-1/actions/
cp -a $src/usr/local/lib/systemd/system/mentor-root.socket $src/usr/local/lib/systemd/system/mentor-root@.service /usr/local/lib/systemd/system/
systemctl daemon-reload && systemctl enable --now mentor-root.socket
cp -a $src/usr/local/lib/mentor/mentor-review /usr/local/lib/mentor/
cp -a $src/usr/share/applications/org.mentor.Review.desktop /usr/share/applications/
install -d -m 755 /var/log/mentor /var/lib/mentor
```

`/etc/mentor/policy.toml` and the instruction files are in `/etc/mentor/source/rootfs/etc/mentor/`. Needed packages: `python`, `polkit`, `python-gobject`, `libadwaita` (the preview window), `pacman-contrib`, `flatpak`. Then the checks above.
