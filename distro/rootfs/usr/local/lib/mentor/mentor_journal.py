"""The journal: what the agent changed on this system, when, and after which request.

Every engine reaches the system through the same door (mentor_tools.call_with_image), and
that door writes a line here for each call that changes something, and for each command.
The assistant says which request a conversation is working on (note_request); the tools
find it by the name of the conversation's sandbox.

One JSON object per line, in the user's own folder:

    {"time": "2026-10-13T14:02:11+0300", "tool": "package_install", "kind": "change",
     "what": "installed packages: gimp", "ok": true, "undo": "package_remove",
     "request": "install gimp", "conversation": "c3f1"}

`kind` is "change" for something that changed the system, "command" for a command nobody
said changes anything (reading, or work inside the sandbox). See /etc/mentor/JOURNAL.md.
"""
import json
import os
import re
import time

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mentor")
PATH = os.path.join(STATE, "journal.jsonl")
REQUESTS = os.path.join(STATE, "requests")
MAX_REQUEST = 400
MAX_WHAT = 2000
BY_HAND = "(no request: a tool called by hand, or by the system)"


def _request_path(conversation):
    return os.path.join(REQUESTS, re.sub(r"[^A-Za-z0-9._-]", "_", conversation or "default") + ".txt")


def _short(text, most):
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[:most - 1] + "…"


def note_request(conversation, text):
    """Called by whoever hands the agent a message: what the user asked, for the lines that follow."""
    try:
        os.makedirs(REQUESTS, exist_ok=True)
        with open(_request_path(conversation), "w", encoding="utf-8") as f:
            f.write(_short(text, MAX_REQUEST))
    except OSError:
        pass  # the journal then says less; the request itself must not fail for it


def request(conversation):
    try:
        with open(_request_path(conversation), encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def record(tool, what, kind="change", ok=True, conversation=None, **more):
    """Add a line. `more` is kept as given (undo, id, before, …); empty values are left out."""
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "kind": kind,
             "what": _short(what, MAX_WHAT), "ok": bool(ok),
             **{name: value for name, value in more.items() if value not in (None, "")},
             "request": request(conversation) if conversation else "", "conversation": conversation or ""}
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")  # one write: lines of two agents do not mix
    except OSError:
        pass
    return entry


def entries(search="", limit=40, everything=False, since=None):
    """The newest `limit` lines that match, oldest first, and how many plain commands were
    left out. `search` is words that must all be in the line (any letter case); `since` is
    the start of a time, as written in the lines: 2026-10 or 2026-10-13."""
    words = search.lower().split()
    found, left_out = [], 0
    try:
        with open(PATH, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or "what" not in entry:
            continue
        if since and str(entry.get("time", "")) < since:
            continue
        if words and not all(word in line.lower() for word in words):
            continue
        if entry.get("kind") != "change" and not everything:
            left_out += 1
            continue
        found.append(entry)
    return found[-limit:] if limit else found, left_out


def readable(found, left_out=0):
    """The lines as text for a person: each request once, and under it what was done for it."""
    out, last = [], None
    for entry in found:
        moment = str(entry.get("time", ""))
        day, clock = moment[:10], moment[11:16]
        group = (entry.get("request", ""), entry.get("conversation", ""), day)
        if group != last:
            asked = f"“{entry['request']}”" if entry.get("request") else BY_HAND
            out.append(f"\n{day}  {asked}")
            last = group
        mark = "" if entry.get("ok", True) else "FAILED: "
        mark += "" if entry.get("kind") == "change" else "(command) "
        out.append(f"  {clock}  {mark}{entry.get('what', '')}")
        if entry.get("undo") and entry.get("ok", True):
            out.append(f"         way back: {entry['undo']}")
        if entry.get("undid"):
            out.append("         (this took back an earlier change, with journal_undo)")
        if entry.get("after_reading"):
            out.append(f"         done after reading text from outside ({entry['after_reading']})")
    if not out:
        out.append("No change is written in the journal yet, or none that matches.")
    if left_out:
        out.append(f"\n{left_out} plain command(s) are not shown (reading, and work inside the sandbox). "
                   "With them: mentor journal --all, or journal_read with all set to true.")
    return "\n".join(out).strip()
