"""Where Mentor's tools fall short, from what the agent really did: `mentor tool-report`.

Read only. It reads the journal (mentor_journal.PATH: every action with its tool, what it did,
whether it worked and the request it was for) and the saved conversations (each request with its
steps and how long they took), and says:

  - how much was done with raw commands (run_command, run_root_command, terminal_run) rather than
    with a tool made for it;
  - those commands in groups, by the program they ran (journalctl, strings, python3 -c, ...), with
    examples and the requests they came from, and for each group whether a tool already covers it
    (then the agent was not told well enough, or the tool's description is unclear) or not (then a
    new tool is a candidate);
  - the requests that took the most steps or time, and the tools that failed most.

Twice on 2026-10-14 reading the journal by hand showed the next tools to make (TOOLS.md, "The
tools made from what was done by hand"); this does that reading. See /etc/mentor/TOOLS.md.
"""
import collections
import json
import os
import re
import shlex
import time

import mentor_journal

STATE = mentor_journal.STATE
CONVERSATIONS = os.path.join(STATE, "conversations.json")
RAW = ("run_command", "run_root_command", "terminal_run")
WRAPPERS = {"nohup", "setsid", "exec", "env", "command", "stdbuf", "nice", "timeout", "sudo", "time"}
FILTERS = {"grep", "head", "tail", "sort", "uniq", "wc", "cut", "awk", "tr", "less", "cat", "sed", "xargs"}

# Programs that do the same kind of thing, reported as one group.
KINDS = {"cat": "reading part of a file", "head": "reading part of a file", "tail": "reading part of a file",
         "sed": "reading part of a file", "awk": "reading part of a file", "less": "reading part of a file",
         "grep": "searching inside files", "rg": "searching inside files",
         "ls": "listing and finding files", "find": "listing and finding files", "which": "listing and finding files",
         "stat": "listing and finding files", "locate": "listing and finding files"}

# A group that a tool does, but not well enough: what to improve in it. (Reading part of a file and
# searching in files were here until file_read took a line range and a search, and file_search came.)
IMPROVE = {}

# program (or group) -> the tool that already does it. A group listed here that still comes up means
# the agent was not pointed at the tool; one that is not is a candidate for a new tool.
COVERED = {
    "journalctl": "log_read", "systemctl": "service_status / service_control / log_read",
    "ps": "windows / app_info", "pgrep": "windows / app_info", "pidof": "windows / app_info",
    "strings": "app_info", "gresource": "app_info / shell_source", "busctl": "dbus", "gdbus": "dbus",
    "gjs": "dbus / shell_source", "gsettings": "settings_get / settings_set / settings_list",
    "dconf": "settings_get / settings_set", "wpctl": "sound", "pactl": "sound", "nmcli": "network_status",
    "xdg-open": "app_open", "gtk-launch": "app_open", "gio": "app_open / file_read",
    "gnome-extensions": "extension_list / extension_status / extension_set", "pacman": "package_* tools",
    "flatpak": "flatpak_* tools", "curl": "package_peek (packages); WebFetch (pages)",
    "python3 (D-Bus)": "dbus", "python3 (shell's code)": "shell_source", "python3 (processes)": "windows / app_info",
    "python3 (a program's insides)": "app_info", "Mentor's own code and notes": "(the tools' descriptions)",
    "reading part of a file": "file_read (start_line, lines, search)",
    "searching inside files": "file_search (contains)", "listing and finding files": "file_search (path, name)",
}


def _parse_time(stamp):
    try:
        return time.mktime(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0


def program_of(command):
    """The group a raw command belongs to: the first program it runs that is not a wrapper or a
    filter, with inline scripts told apart by what they reach for."""
    name = _program(command)
    return KINDS.get(name, name)


def _program(command):
    text = str(command)
    if "/usr/local/lib/mentor" in text or "/etc/mentor" in text or "mentor_tools" in text:
        return "Mentor's own code and notes"
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        words = text.split()
    first = None
    start = True
    for i, word in enumerate(words):
        if word in (";", "&", "&&", "||", "|", "(", ")"):
            start = True
            continue
        if not start:
            continue
        if re.fullmatch(r"[A-Za-z_]\w*=.*", word) or word in WRAPPERS:
            continue
        start = False
        name = os.path.basename(word)
        if first is None:
            first = name
        if name not in FILTERS:
            first = name
            if name in ("python3", "python", "gjs", "bash", "sh") and "-c" in words[i + 1:i + 3]:
                lowered = text.lower()
                if "dbus" in lowered or "gio.dbus" in lowered:
                    return f"{name} (D-Bus)" if name != "gjs" else "gjs"
                if "resources_lookup" in lowered or "libshell" in lowered or "resource:///" in lowered:
                    return f"{name} (shell's code)" if name != "gjs" else "gjs"
                if "ps aux" in lowered or "subprocess" in lowered and "'ps'" in lowered:
                    return f"{name} (processes)"
                if "open('/usr/bin" in lowered or 'open("/usr/bin' in lowered:
                    return f"{name} (a program's insides)"
                return f"{name} -c (a script)"
            break
    return first or "?"


def _journal(since):
    rows = []
    try:
        with open(mentor_journal.PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if _parse_time(row.get("time")) >= since:
                    rows.append(row)
    except OSError:
        pass
    return rows


def _turns():
    """[(request, steps [(tool, detail, failed)], seconds or None)] of the saved conversations."""
    try:
        with open(CONVERSATIONS, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return []
    turns = []
    for conversation in saved if isinstance(saved, list) else []:
        current = None
        for item in conversation.get("history", []):
            if item.get("user") and item.get("text"):
                current = [item["text"], [], None]
                turns.append(current)
            elif current is not None and "tool" in item:
                current[1].append((item["tool"], item.get("detail", ""), item.get("failed")))
            elif current is not None and "took" in item:
                current[2] = (current[2] or 0) + int(item["took"] or 0)
    return turns


def report(days=14):
    """The report as a dict (what --json prints)."""
    since = time.time() - days * 86400
    rows = _journal(since)
    by_tool = collections.Counter(r.get("tool", "?") for r in rows)
    raw = [r for r in rows if r.get("tool") in RAW]
    groups = collections.defaultdict(list)
    for r in raw:
        what = str(r.get("what", ""))
        if r.get("kind") == "change" and ": " in what:  # "<what it says it changed>: <the command>"
            what = what.split(": ", 1)[1]
            r = dict(r, what=what)
        groups[program_of(what)].append(r)
    listed = []
    for name, found in sorted(groups.items(), key=lambda item: -len(item[1])):
        examples, seen = [], set()
        for r in found:
            what = " ".join(str(r.get("what", "")).split())[:140]
            if what not in seen:
                seen.add(what)
                examples.append(what)
        requests = collections.Counter(str(r.get("request") or "")[:80] for r in found)
        listed.append({"group": name, "count": len(found), "covered_by": COVERED.get(name), "improve": IMPROVE.get(name),
                       "examples": examples[:3], "requests": [q for q, _ in requests.most_common(3) if q]})
    failed = collections.Counter(r.get("tool", "?") for r in rows if r.get("ok") is False)
    turns = sorted(_turns(), key=lambda t: (-len(t[1]), -(t[2] or 0)))
    longest = [{"request": t[0][:100], "steps": len(t[1]), "seconds": t[2],
                "tools": collections.Counter(s[0] for s in t[1]).most_common(4),
                "failed_steps": sum(1 for s in t[1] if s[2])} for t in turns[:5] if t[1]]
    return {"days": days, "actions": len(rows), "raw": len(raw), "by_tool": by_tool.most_common(12),
            "groups": listed, "failed": failed.most_common(6), "longest": longest}


def text(r):
    """The report in words, for a terminal."""
    out = [f"Mentor's tools over the last {r['days']} days: {r['actions']} actions written in the journal."]
    if not r["actions"]:
        return out[0] + "\nNothing to go on yet."
    share = round(100 * r["raw"] / r["actions"])
    out.append(f"{r['raw']} of them ({share}%) were raw commands rather than a tool made for the job.")
    out.append("Most used: " + ", ".join(f"{t} {n}" for t, n in r["by_tool"]))
    if r["groups"]:
        out += ["", "RAW COMMANDS, BY WHAT THEY RAN"]
        for g in r["groups"]:
            note = (f"TO IMPROVE: {g['improve']}" if g.get("improve") else
                    f"a tool exists: {g['covered_by']} (point the agent at it, or make its description clearer)"
                    if g["covered_by"] else ("CANDIDATE FOR A NEW TOOL" if g["count"] >= 3 else "seen rarely"))
            out.append(f"  {g['count']:>3} × {g['group']}: {note}")
            for e in g["examples"]:
                out.append(f"        e.g. {e}")
            if g["requests"]:
                out.append("        for: " + " | ".join(g["requests"]))
    if r["longest"]:
        out += ["", "THE LONGEST REQUESTS (a missing or unclear tool shows here even without raw commands)"]
        for t in r["longest"]:
            took = f", {t['seconds'] // 60}:{t['seconds'] % 60:02d}" if t["seconds"] else ""
            failed = f", {t['failed_steps']} failed" if t["failed_steps"] else ""
            out.append(f"  {t['steps']:>3} steps{took}{failed}: “{t['request']}”  ("
                       + ", ".join(f"{tool} {n}" for tool, n in t["tools"]) + ")")
    if r["failed"]:
        out += ["", "TOOLS THAT FAILED MOST: " + ", ".join(f"{t} {n}" for t, n in r["failed"])]
    ideas = [g for g in r["groups"] if not g["covered_by"] and not g.get("improve") and g["count"] >= 3]
    better = [g for g in r["groups"] if g.get("improve") and g["count"] >= 3]
    nudges = [g for g in r["groups"] if g["covered_by"] and g["count"] >= 3]
    out += ["", "IN SHORT"]
    out.append("  New tools to consider: " + (", ".join(f"{g['group']} ({g['count']})" for g in ideas) if ideas else "none stand out"))
    out.append("  Tools to improve: " + ("; ".join(f"{g['improve']} ({g['count']})" for g in better) if better else "none"))
    out.append("  Tools the agent did not reach for: " + (", ".join(f"{g['covered_by']} (for {g['group']}, {g['count']})" for g in nudges)
                                                          if nudges else "none"))
    return "\n".join(out)
