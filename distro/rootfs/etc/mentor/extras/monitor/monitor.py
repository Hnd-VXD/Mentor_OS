#!/usr/bin/python3
"""A quiet watch on the system, for Mentor (see /etc/mentor/MONITOR.md).

Looks at the system every half minute with nothing but the kernel's own counters: how much
memory and processor time each application takes, whether the system is short of memory,
programs killed for lack of it, how much data goes out, what is listening. No model is
involved. When something is out of the ordinary for this computer, the user is told in the
assistant's chat, in a yellow card (a red one for a real problem), with a button that hands
the figures to the agent.

    monitor.py                    watch (what the service runs)
    monitor.py --once --print     look once and say what would be raised; raise nothing
    monitor.py --report [HOURS]   what was recorded, in a few lines (default: 24 hours)
    monitor.py --settings FILE    with any of the above: other settings than the user's

Runs as the user. Python's own library only.
"""
import collections
import json
import os
import re
import statistics
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or f"{HOME}/.local/state", "mentor-monitor")
SETTINGS = os.path.join(os.environ.get("XDG_CONFIG_HOME") or f"{HOME}/.config", "mentor-monitor", "settings.json")
SAMPLES, USUAL, RAISED, LISTENERS = (os.path.join(STATE, name) for name in
                                     ("samples.jsonl", "usual.json", "raised.json", "listeners.json"))
APPS = f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice"
NOTICES = os.path.join(os.environ.get("XDG_STATE_HOME") or f"{HOME}/.local/state", "mentor", "notices")
PROBLEMS = ("pressure", "oom")  # shown in red; the other kinds are warnings, in yellow
GB = 1 << 30
MB = 1 << 20

DEFAULTS = {
    "every": 30,                  # seconds between two looks
    "quiet_start": 600,           # nothing is raised this long after it starts: a login starts everything at once
    "remind_after_days": 3,       # the same finding is not raised again sooner
    "never": [],                  # kinds the user does not want to hear of
    "memory_share": 0.40,         # an application holding this share of the memory ...
    "memory_seconds": 300,        # ... for this long
    "memory_times_usual": 3,      # or this many times what is usual for it ...
    "memory_floor_gb": 1.0,       # ... and at least this much
    "growth_seconds": 1200,       # memory that went up for this long ...
    "growth_mb": 500,             # ... by this much in all ...
    "growth_rising": 0.8,         # ... in this share of the looks
    "pressure": 20,               # /proc/pressure/memory, some avg60, above this ...
    "pressure_seconds": 180,      # ... for this long
    "cpu_share": 0.90,            # of one processor ...
    "cpu_seconds": 900,           # ... for this long
    "upload_mb": 200,             # sent within ...
    "upload_seconds": 300,
    "upload_times_usual": 5,      # ... and this many times what is usual at that hour
    "learn_days": 3,              # what is usual is only trusted after this many days of looks
    "keep_days": 14,              # how long what was recorded is kept
}


def load(path, default):
    try:
        with open(path) as f:
            found = json.load(f)
        return found if isinstance(found, type(default)) else default
    except (OSError, ValueError):
        return default


def save(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w") as f:
        json.dump(value, f)
    os.replace(path + ".new", path)


def output(*argv, timeout=20):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def number(path):
    try:
        with open(path) as f:
            return int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def app_name(group):
    """org.gnome.Nautilus from app-gnome-org.gnome.Nautilus-1234.scope, as systemd writes it."""
    name = re.sub(r"\\x([0-9a-f]{2})", lambda m: chr(int(m.group(1), 16)), group)
    name = re.sub(r"\.(scope|slice|service)$", "", name).removeprefix("app-")
    name = re.sub(r"^(gnome|flatpak|dbus-:[\d.]+)-", "", name)
    return re.sub(r"-\d+$", "", name) or group


def applications():
    """{name: (bytes of memory, microseconds of processor time so far)}, added up per application."""
    found = {}
    try:
        groups = os.listdir(APPS)
    except OSError:
        return found
    for group in groups:
        path = os.path.join(APPS, group)
        if not group.startswith("app-") or not os.path.isdir(path):
            continue
        memory, cpu = number(f"{path}/memory.current"), 0
        try:
            with open(f"{path}/cpu.stat") as f:
                cpu = int(f.readline().split()[1])
        except (OSError, ValueError, IndexError):
            pass
        name = app_name(group)
        before = found.get(name, (0, 0))
        found[name] = (before[0] + memory, before[1] + cpu)
    return found


def system():
    """Memory in all and free for use, the pressure for it, bytes sent and received."""
    memory = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                memory[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    pressure = 0.0
    try:
        with open("/proc/pressure/memory") as f:
            pressure = float(re.search(r"avg60=([\d.]+)", f.readline()).group(1))
    except (OSError, AttributeError, ValueError):
        pass
    received = sent = 0
    try:
        with open("/proc/net/dev") as f:
            for line in f.read().splitlines()[2:]:
                name, _, rest = line.partition(":")
                fields = rest.split()
                if name.strip() != "lo" and len(fields) >= 9:
                    received, sent = received + int(fields[0]), sent + int(fields[8])
    except (OSError, ValueError):
        pass
    return {"total": memory.get("MemTotal", 0), "available": memory.get("MemAvailable", 0),
            "pressure": pressure, "received": received, "sent": sent}


def listening():
    """What is being listened on, as "tcp 8080" and the like. Not what only this computer can reach."""
    found = set()
    for line in output("ss", "-H", "-tunl").splitlines():
        parts = line.split()
        if len(parts) >= 5 and not re.match(r"(127\.|\[::1\]|localhost)", parts[4]):
            found.add(f"{parts[0]} {parts[4].rsplit(':', 1)[-1]}")
    return found


def talking():
    """The programs with connections open now, most connections first: "chromium (12)"."""
    count = collections.Counter(re.findall(r'users:\(\("([^"]+)"', output("ss", "-H", "-tunp")))
    return ", ".join(f"{name} ({n})" for name, n in count.most_common(6))


def killed_since(moment):
    lines = output("journalctl", "-k", "-o", "cat", "--no-pager", f"--since=@{int(moment)}").splitlines()
    return [line.strip()[:200] for line in lines if re.search(r"Out of memory|oom-kill|Killed process", line)][:3]


def size(amount):
    return f"{amount / GB:.1f} GB" if amount >= GB else f"{amount / MB:.0f} MB"


class Watch:
    def __init__(self, settings):
        self.s = settings
        self.started = time.time()
        self.apps = collections.defaultdict(collections.deque)  # name -> (time, memory, share of a processor)
        self.whole = collections.deque()                         # (time, pressure, bytes sent)
        self.before = None                                       # the look before this one
        self.usual = load(USUAL, {})
        self.raised = load(RAISED, {})
        self.known = load(LISTENERS, {})
        self.period = {"since": time.time(), "apps": {}, "pressure": 0.0, "sent": 0, "received": 0, "raised": []}
        self.last_kill_check = time.time()

    # --- looking ---------------------------------------------------------------------

    def look(self):
        now, apps, whole = time.time(), applications(), system()
        longest = max(self.s[key] for key in self.s if key.endswith("_seconds")) + 120
        if self.before:
            then, apps_then, whole_then = self.before
            passed = max(now - then, 0.001)
            for name, (memory, cpu) in apps.items():
                share = max(0.0, (cpu - apps_then.get(name, (0, cpu))[1]) / 1e6 / passed)
                row = self.apps[name]
                row.append((now, memory, share))
                while row and now - row[0][0] > longest:
                    row.popleft()
                kept = self.period["apps"].setdefault(name, [0, 0.0])
                kept[0], kept[1] = max(kept[0], memory), kept[1] + share * passed
            for name in [name for name in self.apps if name not in apps]:
                del self.apps[name]
            sent, received = (max(0, whole[key] - whole_then[key]) for key in ("sent", "received"))
            self.whole.append((now, whole["pressure"], sent))
            while self.whole and now - self.whole[0][0] > longest:
                self.whole.popleft()
            self.period["pressure"] = max(self.period["pressure"], whole["pressure"])
            self.period["sent"] += sent
            self.period["received"] += received
        self.before = (now, apps, whole)
        return now, whole

    def lasting(self, rows, seconds, test):
        """True when the test held for every look of the last `seconds`, and those cover them."""
        if not rows or rows[-1][0] - rows[0][0] < seconds * 0.9:
            return False
        return all(test(row) for row in rows if rows[-1][0] - row[0] <= seconds)

    def learned(self, name):
        known = self.usual.get(name) or {}
        return known.get("value") if known.get("days", 0) >= self.s["learn_days"] else None

    def findings(self, now, whole):
        """(kind, what it is about, title, text of the notification, request for the assistant)."""
        s, found = self.s, []
        for name, rows in self.apps.items():
            memory, usual = rows[-1][1], self.learned("memory:" + name)
            if whole["total"] and self.lasting(rows, s["memory_seconds"], lambda r: r[1] > s["memory_share"] * whole["total"]):
                found.append(("memory", name, f"{name} is using a lot of memory",
                              f"{size(memory)} of {size(whole['total'])}, for {s['memory_seconds'] // 60} minutes.",
                              f"The application {name} has held {size(memory)} of this computer's {size(whole['total'])} "
                              f"of memory for {s['memory_seconds'] // 60} minutes"
                              + (f"; it usually holds about {size(usual)}" if usual else "") + "."))
            elif usual and memory > s["memory_floor_gb"] * GB and self.lasting(
                    rows, s["memory_seconds"], lambda r: r[1] > s["memory_times_usual"] * usual):
                found.append(("memory", name, f"{name} is using far more memory than usual",
                              f"{size(memory)} now; about {size(usual)} is usual for it.",
                              f"The application {name} holds {size(memory)} of memory; about {size(usual)} is usual for it "
                              f"on this computer. It has been so for {s['memory_seconds'] // 60} minutes."))
            window = [r for r in rows if rows[-1][0] - r[0] <= s["growth_seconds"]]
            if len(window) >= 5 and window[-1][0] - window[0][0] >= s["growth_seconds"] * 0.9:
                rising = sum(b[1] > a[1] for a, b in zip(window, window[1:])) / (len(window) - 1)
                grown = window[-1][1] - window[0][1]
                if rising >= s["growth_rising"] and grown > s["growth_mb"] * MB:
                    found.append(("growth", name, f"{name}'s memory keeps growing",
                                  f"Up by {size(grown)} in {s['growth_seconds'] // 60} minutes, to {size(memory)}.",
                                  f"The memory of the application {name} has been going up steadily: by {size(grown)} in "
                                  f"{s['growth_seconds'] // 60} minutes, to {size(memory)} now. That looks like a leak."))
            if self.lasting(rows, s["cpu_seconds"], lambda r: r[2] > s["cpu_share"]):
                busy = statistics.fmean(r[2] for r in rows if rows[-1][0] - r[0] <= s["cpu_seconds"])
                found.append(("cpu", name, f"{name} is keeping the processor busy",
                              f"About {busy * 100:.0f}% of one processor for {s['cpu_seconds'] // 60} minutes.",
                              f"The application {name} has used about {busy * 100:.0f}% of one processor for "
                              f"{s['cpu_seconds'] // 60} minutes without a pause."))
        if self.lasting(self.whole, s["pressure_seconds"], lambda r: r[1] > s["pressure"]):
            largest = sorted(((rows[-1][1], name) for name, rows in self.apps.items()), reverse=True)[:5]
            found.append(("pressure", "system", "The system is short of memory",
                          f"Programs spent {self.whole[-1][1]:.0f}% of the last minute waiting for it.",
                          f"This computer is short of memory: programs spent {self.whole[-1][1]:.0f}% of the last minute "
                          f"waiting for it, for {s['pressure_seconds'] // 60} minutes now. {size(whole['available'])} of "
                          f"{size(whole['total'])} are free for use. The largest applications: "
                          + ", ".join(f"{name} {size(memory)}" for memory, name in largest) + "."))
        sent = sum(r[2] for r in self.whole if self.whole and self.whole[-1][0] - r[0] <= s["upload_seconds"])
        usual = self.learned("sent:%02d" % time.localtime(now).tm_hour)
        covered = bool(self.whole) and self.whole[-1][0] - self.whole[0][0] >= s["upload_seconds"] * 0.9
        if covered and sent > s["upload_mb"] * MB and (usual is None or sent > s["upload_times_usual"] * usual):
            found.append(("upload", "system", "A lot of data is being sent",
                          f"{size(sent)} went out in the last {s['upload_seconds'] // 60} minutes.",
                          f"This computer sent {size(sent)} to the network in the last {s['upload_seconds'] // 60} minutes"
                          + (f"; about {size(usual)} is usual at this hour" if usual else "")
                          + f". Programs with connections open now: {talking() or 'none seen'}. How much each of them "
                            "sent is not known."))
        if now - self.last_kill_check >= 60:
            for line in killed_since(self.last_kill_check):
                found.append(("oom", line[:60], "A program was stopped for lack of memory", line[:120],
                              f"The kernel stopped a program because the memory ran out. Its own words: {line}"))
            self.last_kill_check = now
            today, heard = time.strftime("%Y-%m-%d"), listening()
            first_day = not self.known
            for port in heard:
                if port not in self.known:
                    self.known[port] = today
                    if not first_day:
                        found.append(("listener", port, "Something new is listening for connections",
                                      f"{port}, which was not open before today.",
                                      f"A program on this computer has started listening for connections on {port} "
                                      "(other computers on the network can reach it). It was not open on any earlier day."))
            save(LISTENERS, self.known)
        return found

    # --- speaking ----------------------------------------------------------------------

    def raise_one(self, found, now, say):
        """The first finding that may be raised now. One at a time."""
        if now - self.started < self.s["quiet_start"]:
            return None
        for kind, about, title, text, request in found:
            key = f"{kind}:{about}"
            if kind in self.s["never"] or now - self.raised.get(key, 0) < self.s["remind_after_days"] * 86400:
                continue
            self.raised[key] = now
            save(RAISED, self.raised)
            self.period["raised"].append(title)
            request += " Find out why and tell me what it means and what can be done. Do not close or change anything before I agree."
            if say:
                notify(kind, title, text, request)
            return title, text, request
        return None

    # --- remembering -------------------------------------------------------------------

    def record(self, now, force=False):
        """Every five minutes: one line of what was seen, and what is usual follows a little."""
        period = self.period
        if not force and now - period["since"] < 300:
            return
        top = sorted(period["apps"].items(), key=lambda item: -item[1][0])[:10]
        line = {"t": int(now), "pressure": round(period["pressure"], 1), "sent": period["sent"],
                "received": period["received"], "raised": period["raised"],
                "apps": {name: [peak, round(seconds, 1)] for name, (peak, seconds) in top}}
        os.makedirs(STATE, exist_ok=True)
        with open(SAMPLES, "a") as f:
            f.write(json.dumps(line) + "\n")
        today = time.strftime("%Y-%m-%d")
        learn = [("memory:" + name, peak) for name, (peak, _) in period["apps"].items()]
        learn.append(("sent:%02d" % time.localtime(now).tm_hour, period["sent"]))
        for key, value in learn:
            known = self.usual.setdefault(key, {"value": value, "days": 0, "day": ""})
            known["value"] = known["value"] * 0.95 + value * 0.05  # follows slowly: one odd day changes little
            if known["day"] != today:
                known["day"], known["days"] = today, known["days"] + 1
        save(USUAL, self.usual)
        if time.localtime(now).tm_hour == 4 and time.localtime(period["since"]).tm_hour != 4:
            prune(self.s["keep_days"])
        self.period = {"since": now, "apps": {}, "pressure": 0.0, "sent": 0, "received": 0, "raised": []}


def notify(kind, title, text, request):
    """Leave it for the assistant, which shows it in the chat as a card: yellow for a warning,
    red for a problem, with a button that hands the request to the agent (and a notification
    when the desktop is covered). See NOTICES_DIR in mentor-chat."""
    os.makedirs(NOTICES, exist_ok=True)
    path = os.path.join(NOTICES, f"{time.time():.3f}-monitor.json")
    with open(path + ".new", "w") as f:
        json.dump({"level": "problem" if kind in PROBLEMS else "warning", "title": title, "text": text,
                   "prompt": request}, f)
    os.replace(path + ".new", path)
    if not output("pgrep", "-u", str(os.getuid()), "-f", "bin/mentor-chat").strip():  # nobody there to show it
        output("notify-send", "--app-name=Mentor", "--icon=dialog-warning", title, text)


def prune(days):
    try:
        with open(SAMPLES) as f:
            lines = f.readlines()
    except OSError:
        return
    kept = []
    for line in lines:
        try:
            if time.time() - json.loads(line)["t"] < days * 86400:
                kept.append(line)
        except (ValueError, KeyError, TypeError):
            pass
    with open(SAMPLES + ".new", "w") as f:
        f.writelines(kept)
    os.replace(SAMPLES + ".new", SAMPLES)


def report(hours):
    """What was recorded, for the assistant to answer from: forty lines at most."""
    lines = []
    try:
        with open(SAMPLES) as f:
            for line in f:
                try:
                    sample = json.loads(line)
                    if time.time() - sample["t"] <= hours * 3600:
                        lines.append(sample)
                except (ValueError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    if not lines:
        return f"Nothing was recorded in the last {hours:g} hours. Is the watch running? (systemctl --user status mentor-monitor)"
    peak, busy = collections.Counter(), collections.Counter()
    for sample in lines:
        for name, (memory, seconds) in sample.get("apps", {}).items():
            peak[name] = max(peak[name], memory)
            busy[name] += seconds
    said = [f"The last {hours:g} hours, from {len(lines)} records "
            f"({time.strftime('%d %b %H:%M', time.localtime(lines[0]['t']))} to "
            f"{time.strftime('%d %b %H:%M', time.localtime(lines[-1]['t']))}).",
            "", "Most memory at its highest:"]
    said += [f"  {name}: {size(memory)}" for name, memory in peak.most_common(8)]
    said += ["", "Most processor time:"]
    said += [f"  {name}: {seconds / 60:.0f} minutes" for name, seconds in busy.most_common(6) if seconds >= 30]
    tight = [s for s in lines if s.get("pressure", 0) >= 10]
    worst = max(tight, key=lambda s: s["pressure"]) if tight else None
    said += ["", f"Short of memory: {len(tight)} of the records"
             + (f", worst {worst['pressure']:.0f}% at {time.strftime('%d %b %H:%M', time.localtime(worst['t']))}"
                if worst else "") + "."]
    said.append(f"Data: {size(sum(s.get('sent', 0) for s in lines))} sent, "
                f"{size(sum(s.get('received', 0) for s in lines))} received.")
    most = max(lines, key=lambda s: s.get("sent", 0))
    if most.get("sent", 0) > 50 * MB:
        said.append(f"  Most in one record: {size(most['sent'])} sent around "
                    f"{time.strftime('%d %b %H:%M', time.localtime(most['t']))}.")
    raised = [f"  {time.strftime('%d %b %H:%M', time.localtime(s['t']))}: {title}" for s in lines for title in s.get("raised", [])]
    said += ["", "Raised with the user:"] + (raised[-8:] or ["  nothing"])
    return "\n".join(said[:40])


def main():
    args = sys.argv[1:]
    path = args[args.index("--settings") + 1] if "--settings" in args and args.index("--settings") + 1 < len(args) else SETTINGS
    settings = {**DEFAULTS, **load(path, {})}
    if "--report" in args:
        after = args[args.index("--report") + 1:]
        print(report(float(after[0]) if after and re.fullmatch(r"[\d.]+", after[0]) else 24))
        return 0
    watch = Watch(settings)
    if "--once" in args:
        # Two looks a few seconds apart: the processor's share is a difference. Nothing lasts
        # long in that time, so the settings given should ask for no more than a few seconds.
        watch.look()
        time.sleep(3)
        now, whole = watch.look()
        found = watch.findings(now, whole)
        if "--print" in args:
            apps = sorted(((rows[-1][1], name) for name, rows in watch.apps.items()), reverse=True)
            print("Applications seen: " + ", ".join(f"{name} {size(memory)}" for memory, name in apps[:12]))
            print(f"Memory: {size(whole['available'])} of {size(whole['total'])} free for use; pressure {whole['pressure']:.1f}.")
            print("Would be raised:" if found else "Nothing would be raised.")
            for kind, about, title, text, _request in found:
                print(f"  [{kind}] {title}: {text}")
        return 0
    while True:
        now, whole = watch.look()
        watch.raise_one(watch.findings(now, whole), now, say=True)
        watch.record(now)
        time.sleep(max(5, settings["every"]))


if __name__ == "__main__":
    sys.exit(main())
