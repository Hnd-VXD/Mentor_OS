# The journal: what was changed on this system, when, and after which request

This is for the agent, written so that a small model can follow it. On a system that is changed by talking to it, nobody remembers after a while what was done. The journal is the answer to that: a plain record that the tools keep by themselves, of every change made through them, under the request it was made for. This file says when to read it, how to read it, what it does and does not hold, how it is made, and how to make it again.

## What the user has

- **A record of every change the assistant made**, kept without anyone having to ask: packages installed and removed, settings (with the value before), services, files written, applications from Flathub, extensions, changes applied through the sandbox, commands run as root.
- **Under each request, what was done for it**, with the time, and the way back where there is one.
- **`mentor journal`** in a terminal, to read it without any model. Or they ask you: "what did you change last week?", "why is Bluetooth off?", "what have you installed?".

It looks like this:

```
2026-10-13  “install gimp and make the desktop dark”
  14:02  installed packages: gimp
         way back: package_remove, the same names
  14:03  setting org.gnome.desktop.interface color-scheme: 'default' -> 'prefer-dark'
         way back: settings_set org.gnome.desktop.interface color-scheme 'default'
```

## When to read it

Read the journal (tool: `journal_read`) **before you answer or act** in each of these cases. Do not answer from memory: you only remember this conversation, and the journal holds every conversation and every model that worked here before you.

| The user says, or you find | What to do |
|---|---|
| "What did you change / install / do?", "when", "why is X like this?" | `journal_read`, with `search` for the thing named, or `since` for the time named. Answer from what it says |
| Something stopped working, looks different, or is slow since some time | `journal_read` first, before any other search. What changed last, or changed that part, is the first suspect. Say what you found, then look further |
| "Undo that", "put it back as it was" | `journal_undo` with words of that request: it undoes **every** change under it, the last one first ("Undoing a request" below). Then tell the user what was put back |
| A red or yellow card about a failed service, a broken part of the desktop, a changed file | `journal_read` with `search` for the name: was it something done on purpose? |
| "Set my other computer up the same", "what would I have to do again after a reset?" | `journal_read` with `limit` 0: the changes, oldest first, are the list |
| You are in repair mode | `mentor journal -n 20` (step 1 of REPAIR.md): what was changed before the desktop went |
| You are about to change something a second time | `journal_read` with `search` for it, to see what was done before and why |

After reading, go to the places the journal points at when you need the detail:

| For | Look in |
|---|---|
| The files of a change applied through the sandbox | `change_list`, and `/var/lib/mentor/changes/ID/manifest.json` |
| The version of a file before a `file_write` | `file_restore` puts it back; the copies are in `~/.local/state/mentor/backups/` (home) and `/var/lib/mentor/backups/` (system) |
| Which versions an upgrade or an install brought | `/var/log/pacman.log` |
| Everything done as root, also what was refused | `mentor log -n 50` (`/var/log/mentor/audit.log`); this one you cannot write, so it is the proof |
| What was said in a conversation | `~/.local/state/mentor/history.jsonl` |
| What you or a model before you wrote down about a part it made | `~/.local/share/mentor/notes.md` |

## How to read it

`journal_read` takes four arguments, all optional:

| Argument | Meaning | Example |
|---|---|---|
| `search` | words that must all be there, in the change or in the request; letter case does not matter | `"bluetooth"`, `"gimp"`, `"color-scheme"` |
| `since` | the start of a date | `"2026-10"`, `"2026-10-13"` |
| `limit` | how many of the newest; 0 for all (default 40) | `0` |
| `all` | also the plain commands: what was only read, and what was run inside the sandbox | `true` |

The same from a terminal: `mentor journal [WORDS…] [--since DATE] [-n N] [--all] [--json]`.

Without `all` you see the changes. A line marked `(command)` is a command nobody said changes anything. A line marked `FAILED:` was tried and ended with an error: it may have changed nothing, or part of it.

### Undoing a request

One request often made several changes. "Put it back", "undo that", "I don't like it" means all of them. Use the tool `journal_undo`; do not undo the changes one by one with `settings_set`.

1. `journal_undo` with `search`: words of the request, or of one of its changes (`"night light"`, `"gimp"`, `"color-scheme"`). The user's words now ("the orange", "the colours") are often not in the journal: use the name of the thing (`"night light"` for screen colours that are too orange or blue, `"text size"`), or `journal_read` first to find the request. It finds the request and takes **every** change under it, also those the words did not name (a setting of another schema, such as `org.gnome.system.location enabled`, that was changed for it).
2. If it answers "more than one request matches", it has done nothing. Read the list (the newest last): "undo that" means the newest one, so call it again with its `conversation`. When the user means all of today's (several requests about the same thing, "make it warmer", "more orange"), call it again with `every_match` true: it takes back only the requests of the newest one's day, and lists the older ones as left alone. Those are choices the user made before; take one back only when the user names it. `search` matches the request's words and the names of what was changed, never the values: on 2026-10-22 "undo the night light", matched against everything, also took back the Console's theme `'night'` and a week-old "change theme to light", which turned the user's keep-awake extension off.
3. If a package, a system service or a system file is among the changes, give `explain` (the password is asked). Without it the tool does nothing and says so.
4. It answers with each change `ok` or `FAILED`, a setting with the value it is back to. Changes it "cannot undo by itself" (a command, a file that was new, an upgrade) it lists: tell the user about them; do another thing for them only with their yes.
5. Tell the user in one or two plain sentences what was put back. Never say a value "was like that before" unless the journal line shows it.

`preview` true only lists what it would do. A request that was itself an undo (`journal_undo` ran for it) is never taken back by a later undo: to have that thing again, do it again as asked. A change that was undone once is not undone again, and what `journal_undo` does is written in the journal like any change, with `undid` naming the line it took back.

Example: "the screen is too blue in the evening" made three changes, `night-light-schedule-automatic: false -> true`, `night-light-temperature: uint32 2700 -> uint32 2000` and `org.gnome.system.location enabled: false -> true`. "Put the colours back" is one call, `journal_undo {"search": "night light"}`, and all three go back. A model that turned off only Night Light and called the rest "as it was" was wrong (2026-10-22): that is why the tool exists.

By hand (no `journal_undo`, or it failed): undo each change by its "way back" line, the last one first; for a setting, the value before is the one on the left of `->`. Check each one with `settings_get` or `package_info`.

## What you have to do for it

Almost nothing: the tools write the journal themselves. One thing is yours:

- **When you use `run_command` or `terminal_run` for something that changes the system** (a file in the home folder, a setting written with a command, a program installed with a script), fill in `changes`: a few words on what it changes. `{"command": "echo \"alias ll='ls -l'\" >> ~/.bashrc", "changes": "adds the ll alias to the shell"}`. Without it the command is kept as a plain command and is not shown among the changes. Leave `changes` out for a command that only reads.
- Prefer the named tools (`settings_set`, `file_write`, `package_install`) over a command that does the same: they write a better line, with the value before and the way back.
- Do not write to the journal file yourself, do not tidy it, do not remove lines from it. If a line is wrong, say so to the user.

## What it does not hold

Say this to the user when it matters; do not let them think the journal is more than it is.

- **What the user did themselves**, in Settings, in a terminal, in an application. Only what went through the tools is written.
- **What is inside a command.** For `run_root_command` and `run_command` the command is written as it was given; what a script it started did is not.
- **Proof.** The file is in the user's own folder, and whoever can run commands as the user can change it. What was done as root is also in `/var/log/mentor/audit.log`, which the agent cannot write.
- **Changes from before the journal existed** on this system. The sandbox's changes (`change_list`), `/var/log/pacman.log` and the audit log go further back.

## How it is made

| What | Where | What it does |
|---|---|---|
| The record | `~/.local/state/mentor/journal.jsonl` | one JSON object per line, added at the end, never rewritten |
| Which request a conversation is on | `~/.local/state/mentor/requests/NAME.txt`, NAME being the conversation's sandbox (`tab-1a2b3c4d`, `repair`) | written by the assistant (`note_request` in `mentor-chat`) and by repair mode (`mentor_repair.py`) each time a message is handed to an engine |
| Writing and reading | `/usr/local/lib/mentor/mentor_journal.py` | `note_request`, `request`, `record` (adds a line), `entries` (reads, searches), `readable` (the text for a person) |
| When a line is written | `call_with_image` in `/usr/local/lib/mentor/mentor_tools.py`, through `_journal` | after every tool call. The table `JOURNAL` there gives, for each tool that changes something, the function that makes the line. A tool not in it only reads |
| The tools | `journal_read` and `journal_undo` in `TOOLS` of `mentor_tools.py` | what you call |
| Undoing a request | `journal_undo`, `_undo_requests` (which lines), `_undo_call` (the call that takes one line back, read from its `undo` text) in `mentor_tools.py` | each way back is run through `call`, so it asks, checks and is journaled as if you had called it; `_undoing` adds `undid` to its line |
| The command | `mentor journal` in `/usr/local/bin/mentor` (`cmd_journal`) | what the user calls |

A line:

```
{"time": "2026-10-13T14:02:11+0300", "tool": "package_install", "kind": "change",
 "what": "installed packages: gimp", "ok": true, "undo": "package_remove, the same names",
 "request": "install gimp and make the desktop dark", "conversation": "tab-1a2b3c4d"}
```

`undid` is there on a line written by `journal_undo`: the time, tool and `what` of the line it took back. Such lines are never undone as a request of their own, and the line they name is not undone again. `mentor-chat` does not offer a recipe for them.

`after_reading` is there when the agent had read text from outside (a web page, a downloaded file) since the user's last message: the change was made with the warning shown (SECURITY.md). Such a line is the first to look at when something was changed that nobody asked for.

`kind` is `change` or `command`. A recipe posted to the recipes site, one downloaded from it and a report to it are changes too: a line each. `ok` is whether the tool ended without an error. `undo` is there only when there is a way back. `request` is empty when a tool was called by hand (`mentor call …`) or by the system.

Every engine (Claude Code, Codex, the Antigravity CLI, mentor-agent) can change the system only through these tools: their own shells and file-writing tools are switched off (ENGINES.md). That is why one place is enough. The name of the sandbox reaches the tools in the environment (`MENTOR_SANDBOX`), and the request is found by it.

Not written: a call the user did not approve (the dialog dismissed, a refusal by the rules), a sandbox change they declined in the preview, an upgrade that stopped to ask about a new GNOME. Nothing changed in those.

All of these files except the record itself and the requests are ones you cannot write (TOOLS.md, "What you may not change").

## How to tell that it works

| Check | Good answer |
|---|---|
| `mentor journal -n 5` | the last changes, each under its request; or "No change is written in the journal yet" on a new system |
| `mentor call settings_set '{"schema": "org.gnome.desktop.interface", "key": "clock-show-seconds", "value": "true"}'` then `mentor journal -n 1` | a line `setting org.gnome.desktop.interface clock-show-seconds: false -> true` under "(no request: a tool called by hand…)"; then set it back to `false` |
| `mentor call run_command '{"command": "true"}'`, then `mentor journal --all -n 1` | a line `(command) true` |
| ask the assistant for a small change (the clock with seconds), then `mentor journal -n 1` | the change, under the words you typed |
| `mentor call journal_read '{"search": "clock"}'` | the same lines as text |
| `mentor call settings_set '{"schema": "org.gnome.desktop.interface", "key": "clock-show-seconds", "value": "true"}'`, then `mentor call journal_undo '{"search": "clock-show-seconds"}'` | `ok  setting … clock-show-seconds: false -> true  (back to false)`; `gsettings get org.gnome.desktop.interface clock-show-seconds` says `false`; a second `journal_undo` says it was undone already |
| `tail -1 ~/.local/state/mentor/journal.jsonl \| python3 -m json.tool` | valid JSON with `time`, `tool`, `what` |

## When it is broken

In the user's words: the journal is empty; changes are not written down; mentor journal shows an error; the record of changes is gone.

1. **Changes are made but no line appears.** `mentor verify`: is `mentor_journal.py` or `mentor_tools.py` missing or changed? Then `python3 -c "import sys; sys.path.insert(0, '/usr/local/lib/mentor'); import mentor_journal; print(mentor_journal.PATH)"`: an error names the fault. `ls -ld ~/.local/state/mentor`: the folder must be the user's and writable. A full disk (`df -h /`) also stops the writing; the tools go on working without the journal, on purpose.
2. **Lines appear but the request is empty or is an older one.** The file in `~/.local/state/mentor/requests/` for that conversation is not written: `ls -l ~/.local/state/mentor/requests/` after sending a message. Its time must be that of the message. If not, `note_request` in `mentor-chat` is not called (a damaged or older `mentor-chat`: `mentor verify`).
3. **`mentor journal` ends with a Python error.** The last line names the file and the line. A line of the record that is not valid JSON is skipped, so a damaged record does not cause this; a damaged `mentor_journal.py` does. The user puts it back: `sudo mentor restore /usr/local/lib/mentor/mentor_journal.py`.
4. **The record is gone.** It is not made again from nothing, but much of it can be told from elsewhere: `change_list` (sandbox changes), `mentor log -n 200` (everything done as root), `/var/log/pacman.log` (packages), `~/.local/state/mentor/history.jsonl` (what was asked). Tell the user what these say; do not write a made-up journal.

## Making it again from nothing

The four places in "How it is made" are all of it. The files are in `/etc/mentor/source/rootfs/` at their own paths; the user puts back the ones you cannot write (`sudo mentor restore PATH`). If `mentor_tools.py` has to be mended by hand, these are the parts that belong to the journal:

```python
import mentor_journal                      # at the top

_noted = {}                                # what the call in progress adds: "before", "declined"

# in _privileged, after running pkexec:
if code in (126, 127) or (code == 3 and "denied by policy" in out):
    _noted["declined"] = True              # not approved: nothing was done

# in settings_set, before setting:
code, before = _run(["gsettings", "get", a["schema"], a["key"]])
_noted["before"] = before.strip() if code == 0 else None

JOURNAL = {                                # tool -> function(arguments, output)
    "package_install": lambda a, out: (f"installed packages: {', '.join(a['packages'])}", "package_remove, the same names"),
    # … one entry for each tool that changes something; returns the line, or
    # (line, way back), or (line, way back, "command"), or None for "nothing changed"
}

def _journal(name, a, code, out):
    try:
        describe = JOURNAL.get(name)
        line = None if not describe or _noted.get("declined") else describe(a, out)
        if line is None:
            return
        what, undo, kind = (line, None, "change") if isinstance(line, str) else (*line, "change")[:3]
        mentor_journal.record(name, what, kind, code == 0, os.environ.get("MENTOR_SANDBOX"), undo=undo)
    except Exception:
        pass                               # the journal is never in the way of the tool

# in call_with_image: `_noted.clear()` before the tool runs, `_journal(name, arguments or {}, code, out)` after
```

A new tool that changes something gets an entry in `JOURNAL` in the same change. If its way back is a tool call, write the `undo` text as `TOOL ARGUMENTS` and teach `_undo_call` to read it, so that `journal_undo` can run it. Then the checks above.
