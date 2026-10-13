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
- **Who asks for the password.** `_privileged` in `mentor_tools.py` first asks Mentor's own root service: it connects to `/run/mentor-root.sock` (`mentor-root.socket`, `Accept=yes`; each connection starts `mentor-root@.service`, which runs `/usr/local/lib/mentor/mentor-rootd` as root with the connection as its input and output) and sends one line of JSON: the helper's name, the action, its arguments, the agent's `explain`, whether the user wants the exact thing shown, and how many bytes follow for the helper's standard input. `mentor-rootd` finds out who is at the other end from the kernel (`SO_PEERCRED`), asks polkit about that process for the helper's action (`DOORS`), with the words to show as the detail `polkit.message` (only root may set that, which is why this is a service and not pkexec), and when the user has said yes runs the same helper pkexec would, with `PKEXEC_UID` set to the user. It answers with what the helper printed and a last line `\0exit N`; 126 means the user said no, 127 that they may not say yes. **Nothing about who may do what changes: the same actions, the same user, the same password, the same checks in `mentor_core.py`.** When the socket is not there, `_privileged` uses pkexec as before, and the dialog then shows the fixed sentence of the action.
- **mentor_core.py**: `ACTIONS[mode][action]` is a function that checks the arguments and returns a command to run (or does the work and returns an exit status). A refusal raises `Denied`, is written to the log, and exits 3 with "denied by policy".
- **The sandbox** (`mentor_sandbox.py`): an overlay file system over `/`, in an image file `/var/lib/mentor/sandbox.img` (sparse, 24 GB, mounted at `/var/lib/mentor/sandbox`). Each conversation has its own layer, named by `MENTOR_SANDBOX`. A command runs in it as root inside a container (`systemd-nspawn`), so it cannot touch the running system. `/boot` cannot have an overlay, so the sandbox gets a copy of it. `scan()` lists what the layer added, changed or deleted; `report()` adds text differences; `apply()` copies it onto the real system and keeps what it replaced under `/var/lib/mentor/changes/ID/`; `undo(ID)` puts that back. Sandboxes do not outlive a restart.
- **The preview** (`mentor-review report.json`): a window with the summary, the files and their differences; it exits 0 when the user chooses to apply. `sandbox_apply` in mentor_tools shows it first, then asks for root.

## The tools

Packages: `package_search`, `package_info`, `package_list`, `package_install`, `package_remove`, `system_upgrade`. Flatpak: `flatpak_search`, `flatpak_install`, `flatpak_remove`. Settings: `settings_list`, `settings_get`, `settings_set`. Services: `service_status`, `service_control`. Files: `file_read`, `file_write`, `file_restore`. Commands: `run_command` (as the user), `run_root_command`, `terminal_run` (in a window the user watches). Sandbox: `sandbox_run`, `sandbox_changes`, `sandbox_apply`, `sandbox_discard`, `change_list`, `change_undo`. Desktop: `window_mode`, `desktop_layout`, `wallpaper_set`, `app_open`, `extension_list`, `extension_status`, `extension_set`, `screen_capture`, `desktop_check`, `session_logout`. Start-up: `system_restart`, `boot_status`, `restore_point_create`. Other: `system_info`, `suggestions_status`, `suggestions_restore`, `journal_read`, `security_check`, `recipe_material`, `recipe_save`, `recipe_list`, `recipe_inspect`, `recipe_hub_look`, `recipe_share`, `recipe_fetch`, `recipe_report`.

`mentor tools` prints them with their descriptions; that list is the truth, this one a summary.

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
