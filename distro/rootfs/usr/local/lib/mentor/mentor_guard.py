"""Unusual programs: what runs on this computer, and what of it looks wrong (SECURITY.md, "Unusual programs").

The user's wish, 2026-10-19, after seeing an AI agent find a cryptominer on someone's Mac: Mentor should look for
that by itself, and not only for mining, for anything that behaves as harmful programs do.

`scan()` runs as root every ten minutes (mentor-guard.service, from its timer), so that it sees every process
whoever runs it. No model is involved. It keeps
  - a record of every program it has seen run (/var/lib/mentor/guard/known.json, root's alone): where it came
    from (a package, Mentor, Flatpak, Steam, the user's own programs in ~/.local, or nowhere known), when it
    was first and last seen;
  - a list of what starts by itself or is loaded into every program (services, autostart, scheduled tasks,
    shell startup files, sudo rules, SSH keys, ld.so.preload), to see what is new;
and writes what looks wrong to /var/lib/mentor/guard/findings.json, which every user may read. The user's
session turns those into cards (mentor-watch --guard, started when the file changes); with "Let Mentor look
by itself" on, the assistant looks at once and says in a few words what it is. Nothing is stopped or removed
here, ever: that is for the user to decide, with the assistant (SECURITY.md).

`findings()` reads that file for anyone (mentor_security.checks, `mentor security`, mentor-watch).
"""
import glob
import hashlib
import json
import os
import pwd
import re
import subprocess
import time

STATE = "/var/lib/mentor/guard"
KNOWN = os.path.join(STATE, "known.json")          # programs seen: exe -> {first, last, origin}
WATCHED = os.path.join(STATE, "starts.json")       # what starts by itself: item -> hash
SAMPLES = os.path.join(STATE, "samples.json")      # processor time of each process at the last look
FINDINGS = os.path.join(STATE, "findings.json")    # what looks wrong now: for everyone to read
NET = os.path.join(STATE, "net.json")             # programs going online (mentor-netguard): for everyone to read
CHECK_EVERY = 7 * 86400   # the weekly check of the package files, when the user agrees (check_files)
MANIFEST = "/etc/mentor/source/MANIFEST.sha256"
PACMAN_LOG = "/var/log/pacman.log"

KEPT = 24 * 3600            # a new thing that starts by itself stays among the findings this long
HOT = 0.8                   # of one processor, ...
HOT_LOOKS = 2               # ... at this many looks in a row (ten minutes apart): working hard for a while
ODD_PLACES = ("/tmp/", "/var/tmp/", "/dev/shm/")
MINERS = re.compile(r"^(xmrig\S*|xmr-stak\S*|cpuminer\S*|minerd|ccminer|nbminer|t-rex|lolminer|ethminer|"
                    r"phoenixminer|srbminer\S*|nanominer|gminer|teamredminer|kdevtmpfsi|kinsing|bminer|"
                    r"cryptonight|rigel|onezerominer)$", re.I)
MINING_WORDS = re.compile(r"stratum\d?\+(tcp|ssl|tls)://|--donate-level|--coin[= ]monero|--algo[= ]rx/|-a rx/0|"
                          r"hashvault|supportxmr|moneroocean|nanopool|minexmr|c3pool|2miners|f2pool|nicehash|"
                          r"herominers|unmineable|xmrpool|randomx", re.I)
POOL_PORTS = {3333, 3334, 3357, 4444, 5555, 7777, 10128, 14433, 14444, 20128, 45560, 45700}
# The AI engines Mentor sets up for the user live in their home (npm's and the engines' own installers).
ENGINES = re.compile(r"^/home/[^/]+/\.local/(lib/node_modules/|bin/(agy|claude|codex|gemini)$|share/claude/)")
# Programs that run another file or code given to them: what they run is judged, not them (mentor-netguard
# program_of). Not gjs: GNOME's apps start as `gjs -m FILE`, where -m names a file.
INTERPRETERS = re.compile(r"^/usr/bin/(python3?(\.\d+)?|bash|sh|dash|zsh|perl|ruby|node|lua\S*|php)$")


def command_key(interpreter, rest):
    """How code given to an interpreter as text (`python3 -c …`, `bash -c …`, a script on stdin) is named in net.json
    and in Mentor's rules: the interpreter's path, a space, and the rest of its command line exactly."""
    return interpreter + " " + " ".join(rest)


def split_command(program):
    """(interpreter, the rest of its command line) for a command_key, or None for a program or script file."""
    first, _, rest = program.partition(" ")
    return (first, rest) if _ and INTERPRETERS.match(first) else None


def net_name(program):
    """(name, where) of a program going online, as the user sees it: "fetcher", "/home/USER/.cache"; for code given
    as text "python3 command", and the start of the command."""
    command = split_command(program)
    if command:
        text = " ".join(command[1].split())
        return f"{os.path.basename(command[0])} command", text if len(text) <= 80 else text[:79] + "…"
    return os.path.basename(program), os.path.dirname(program)


# --- small helpers ---------------------------------------------------------------------------------

def _load(path, empty):
    try:
        with open(path) as f:
            value = json.load(f)
        return value if isinstance(value, type(empty)) else empty
    except (OSError, ValueError):
        return empty


def _save(path, value, mode=0o600):
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    part = path + ".part"
    with open(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        json.dump(value, f, indent=1)
    os.chmod(part, mode)
    os.replace(part, path)


def _out(*argv, timeout=30):
    try:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _read(path, most=1 << 16):
    try:
        with open(path, "rb") as f:
            return f.read(most)
    except OSError:
        return b""


def _hash(path):
    try:
        if os.path.islink(path):
            return "link:" + os.readlink(path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _homes():
    """(user name, home) of the people who log in here."""
    found = []
    for entry in pwd.getpwall():
        if entry.pw_uid >= 1000 and entry.pw_uid < 60000 and os.path.isdir(entry.pw_dir):
            found.append((entry.pw_name, entry.pw_dir))
    return found


_owners = {}


def _package(path):
    """The package a file belongs to, or ""."""
    if path not in _owners:
        out = _out("pacman", "-Qqo", path, timeout=20).strip()
        _owners[path] = out.splitlines()[0] if out else ""
    return _owners[path]


def _mentor_files():
    try:
        with open(MANIFEST) as f:
            return {line.split(None, 1)[1].strip() for line in f if "  " in line}
    except OSError:
        return set()


def _mentor_journal_text():
    """What Mentor's assistant changed, as text, every user's: a path in it was Mentor's doing."""
    text = []
    for _name, home in _homes():
        text.append(_read(os.path.join(home, ".local/state/mentor/journal.jsonl"), 8 << 20).decode("utf-8", "replace"))
    return "\n".join(text)


def origin(exe, home_of_user=None):
    """Where a program comes from: package NAME, mentor, flatpak, steam, appimage, home (the user's own programs
    in ~/.local and the like), or none (nowhere known)."""
    if exe.startswith("/tmp/.mount_"):
        return "appimage"
    if "/flatpak/" in exe or exe.startswith(("/var/lib/flatpak/", "/app/")):
        return "flatpak"
    if "/Steam/" in exe or "/.steam/" in exe or "/steamapps/" in exe:
        return "steam"
    if exe.startswith(("/usr/", "/opt/", "/etc/")):
        if exe in _MENTOR:
            return "mentor"
        owner = _package(exe)
        if owner:
            return "package " + owner
        return "none"
    for _name, home in _homes():
        if exe.startswith(os.path.join(home, ".local/")) or exe.startswith(os.path.join(home, ".var/")):
            return "home"
    return "none"


_MENTOR = set()


# --- the processes --------------------------------------------------------------------------------

def processes():
    """Every user-space process: {pid, exe, name, cmdline, user, cgroup, ticks, start, parent}."""
    found = []
    for path in glob.glob("/proc/[0-9]*"):
        pid = int(path[6:])
        try:
            exe = os.readlink(path + "/exe")
        except OSError:
            continue  # a kernel thread, or gone
        stat = _read(path + "/stat").decode("utf-8", "replace")
        name = stat[stat.find("(") + 1:stat.rfind(")")] if "(" in stat else ""
        fields = stat[stat.rfind(")") + 2:].split()
        try:
            ticks = int(fields[11]) + int(fields[12])
            start = int(fields[19])
            parent = int(fields[1])
        except (IndexError, ValueError):
            continue
        raw = _read(path + "/cmdline", 4096)
        argv0 = raw.split(b"\0")[0].decode("utf-8", "replace").strip()  # the name the program gives itself
        cmdline = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        try:
            uid = os.stat(path).st_uid
            user = pwd.getpwuid(uid).pw_name
        except (OSError, KeyError):
            user = "?"
        cgroup = _read(path + "/cgroup").decode("utf-8", "replace").strip().split("::")[-1]
        found.append({"pid": pid, "exe": exe, "name": name, "argv0": argv0, "cmdline": cmdline[:400], "user": user,
                      "cgroup": cgroup, "ticks": ticks, "start": start, "parent": parent})
    return found


def connections():
    """pid -> [(state, remote address, remote port, local port)] for TCP and UDP sockets."""
    found = {}
    for line in _out("ss", "-Htunap").splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        state, local, remote = parts[1], parts[4], parts[5]
        for pid in re.findall(r"pid=(\d+)", line):
            lport = local.rpartition(":")[2]
            raddr, _, rport = remote.rpartition(":")
            found.setdefault(int(pid), []).append((state, raddr.strip("[]"), rport, lport, local.rpartition(":")[0]))
    return found


def _in_app(cgroup):
    """Started by the user from the desktop (an app scope): a game or an editor may well work hard."""
    return bool(re.search(r"/app-[^/]+\.scope$", cgroup)) and "-autostart" not in cgroup


def _describe(p, conns=None, rate=None):
    """A process in a few lines, for the assistant."""
    lines = [f"process {p['pid']} of {p['user']}: {p['exe']}", f"command line: {p['cmdline'] or p['name']}"]
    lines.append(f"started by process {p['parent']}; in {p['cgroup'] or '?'}")
    lines.append(f"comes from: {p.get('origin', '?')}")
    if rate is not None:
        lines.append(f"processor: {round(rate * 100)}% of one processor lately")
    if conns:
        lines.append("connections: " + ", ".join(f"{s} {a}:{rp}" for s, a, rp, _lp, _la in conns[:6]))
    try:
        st = os.stat(p["exe"].replace(" (deleted)", ""))
        lines.append("file: " + time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
                     + f", {st.st_size} bytes, sha256 {_hash(p['exe'])[:16]}…")
    except OSError:
        lines.append("file: no longer on the disk")
    return "\n".join(lines)


def trusted(p, journal):
    """A program that may work hard and wait for connections without a word: from a package, Mentor, Flatpak or
    Steam, one of the AI engines Mentor set up, or one Mentor's assistant installed (a recipe, say: its journal
    names it). The strong signs (mining, a disguise) count for every program."""
    exe = p["exe"].replace(" (deleted)", "")
    return (p["origin"].startswith("package") or p["origin"] in ("mentor", "flatpak", "steam", "appimage")
            or bool(ENGINES.match(exe)) or exe in journal)


def judge(p, mine, rate, hot_looks, journal):
    """(kind, level, title, text, why) when a process shows a sign of a harmful program, else None."""
    exe, name = p["exe"], p["name"]
    base = os.path.basename(exe.replace(" (deleted)", ""))
    remote_ports = {int(rp) for s, _a, rp, _lp, _la in mine if rp.isdigit() and s in ("ESTAB", "SYN-SENT")}
    known_one = trusted(p, journal)
    # Mining: the program's name, its command line, or a mining pool's port.
    if MINERS.match(base) or MINERS.match(name) or MINING_WORDS.search(p["cmdline"]) or (
            remote_ports & POOL_PORTS and not known_one):
        return ("miner", "problem", "A program is mining cryptocurrency on this computer",
                f"{base or name} is using this computer's processor to make money for someone else. It makes the "
                "computer hot and slow.",
                "It looks like a cryptocurrency miner: "
                + ("its name" if MINERS.match(base) or MINERS.match(name) else
                   "its command line" if MINING_WORDS.search(p["cmdline"]) else
                   "it talks to a port that mining pools use") + ".")
    # Hiding: a program named like one of the kernel's own threads ([kworker/0:1]) has no program file.
    if re.fullmatch(r"\[.+\]", p["argv0"]) or (name.startswith("[") and name.endswith("]")):
        return ("disguise", "problem", "A program is hiding under a system name",
                f"A program calls itself “{p['argv0'] or name}”, a name of the system's own, but it is {exe}.",
                "Its name is made to look like a kernel thread, which no real program does.")
    # Where programs do not live: temporary folders, or a program file deleted while it runs.
    odd = exe.startswith(ODD_PLACES) and not exe.startswith("/tmp/.mount_")
    gone = exe.endswith(" (deleted)") and not exe.startswith(("/usr/", "/opt/")) and p["origin"] not in ("flatpak", "steam")
    if odd or gone:
        busy = mine or (rate is not None and rate >= HOT)
        return ("odd-place", "problem" if busy else "warning",
                "A program is running from a place programs do not live",
                f"{exe} is running" + (" and using the network" if mine else "")
                + (" and working hard" if rate is not None and rate >= HOT else "") + ".",
                "Its program file is " + ("in a temporary folder, where downloads and harmful programs hide"
                                          if odd else "deleted from the disk while it keeps running") + ".")
    if known_one:
        return None
    # Working hard for a while, unknown, and not something the user opened from the desktop.
    if hot_looks >= HOT_LOOKS and not _in_app(p["cgroup"]):
        return ("busy", "warning", "An unknown program has been working hard for a while",
                f"{base} has used {round(rate * 100)}% of a processor for over {HOT_LOOKS * 10} minutes, and it was "
                "not opened from the desktop.",
                "It is not from a package and keeps the processor busy in the background.")
    # Waiting for connections from other computers, unknown.
    listens = [lp for s, _a, _rp, lp, la in mine if s in ("LISTEN", "UNCONN")
               and not la.strip("[]").startswith(("127.", "::1")) and "%lo" not in la]
    if listens:
        return ("listener", "warning", "An unknown program waits for connections from other computers",
                f"{base} listens on port {', '.join(sorted(set(listens))[:4])}. The firewall turns them away unless a "
                "rule lets them in.",
                "A program that is not from a package opened a port for other computers.")
    return None


# --- programs started (mentor-execlog) -------------------------------------------------------------

EXECLOG = "/var/log/mentor/exec.log"


def execlog_position():
    """Where the start log ends now: (inode, size)."""
    try:
        st = os.stat(EXECLOG)
        return [st.st_ino, st.st_size]
    except OSError:
        return None


def started_since(position):
    """The programs started since POSITION (from execlog_position), as processes for judge()."""
    found = []
    try:
        st = os.stat(EXECLOG)
    except OSError:
        return found
    offset = position[1] if position and position[0] == st.st_ino and position[1] <= st.st_size else 0
    if not position:
        return found  # the first look: everything before it is the past
    try:
        with open(EXECLOG, "rb") as f:
            f.seek(offset)
            data = f.read(32 << 20)
    except OSError:
        return found
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not e.get("exe"):
            continue
        found.append({"pid": e.get("pid", 0), "exe": e["exe"], "name": e.get("name", ""), "argv0": e.get("argv0", ""),
                      "cmdline": e.get("cmdline", ""), "user": e.get("user", "?"), "cgroup": e.get("cgroup", ""),
                      "parent": e.get("ppid", 0), "time": e.get("time", 0)})
    return found


# --- what starts by itself ----------------------------------------------------------------------

def starts():
    """Everything that makes a program start by itself or run inside others: path -> hash."""
    patterns = ["/etc/systemd/system/**/*", "/etc/systemd/user/**/*", "/etc/xdg/autostart/*",
                "/etc/cron*/**/*", "/var/spool/cron/**/*", "/etc/profile.d/*", "/etc/bash.bashrc", "/etc/profile",
                "/etc/environment", "/etc/ld.so.preload", "/etc/sudoers", "/etc/sudoers.d/*", "/etc/udev/rules.d/*",
                "/root/.ssh/authorized_keys", "/root/.bashrc", "/root/.profile"]
    for _name, home in _homes():
        patterns += [home + "/.config/systemd/user/**/*", home + "/.config/autostart/*", home + "/.bashrc",
                     home + "/.bash_profile", home + "/.profile", home + "/.zshrc", home + "/.zprofile",
                     home + "/.xprofile", home + "/.ssh/authorized_keys", home + "/.config/environment.d/*"]
    found = {}
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if os.path.isdir(path) and not os.path.islink(path):
                continue
            found[path] = _hash(path)
    return found


def _pacman_since(when):
    """Whether pacman changed anything since WHEN (a time): a package's own files may then have changed."""
    try:
        return os.path.getmtime(PACMAN_LOG) > when
    except OSError:
        return False


# --- the look -----------------------------------------------------------------------------------

def scan():
    """Look once (as root), keep the record, and write what looks wrong. Returns the findings."""
    global _MENTOR
    _MENTOR = _mentor_files()
    now = time.time()
    known = _load(KNOWN, {})
    learning = not known  # the very first look only learns: nothing is new on a computer seen for the first time
    procs = processes()
    conns = connections()
    tick = os.sysconf("SC_CLK_TCK")
    samples = _load(SAMPLES, {})
    last_look = samples.get("time", 0)
    hot = samples.get("hot", {})
    new_samples, new_hot = {}, {}
    findings = []

    for p in procs:
        exe = p["exe"]
        if exe not in known:
            known[exe] = {"first": now, "origin": origin(exe.replace(" (deleted)", ""))}
        known[exe]["last"] = now
        p["origin"] = known[exe]["origin"]
        key = f"{p['pid']}:{p['start']}"
        new_samples[key] = p["ticks"]
        rate = None
        if key in samples.get("ticks", {}) and now > last_look:
            rate = (p["ticks"] - samples["ticks"][key]) / tick / (now - last_look)
            if rate >= HOT:
                new_hot[key] = hot.get(key, 0) + 1
        p["rate"] = rate
    _save(SAMPLES, {"time": now, "ticks": new_samples, "hot": new_hot, "execlog": samples.get("execlog")})

    journal = _mentor_journal_text()
    seen_pids = set()
    for p in procs:
        mine = conns.get(p["pid"], [])
        verdict = judge(p, mine, p["rate"], new_hot.get(f"{p['pid']}:{p['start']}", 0), journal)
        if verdict and p["pid"] not in seen_pids:
            seen_pids.add(p["pid"])
            kind, level, title, text, why = verdict
            findings.append({"key": f"{kind}:{p['exe']}", "level": level, "title": title, "text": text,
                             "details": why + "\n\n" + _describe(p, mine, p["rate"]), "pid": p["pid"], "since": now})

    # Programs started since the last look (mentor-execlog), the short-lived among them: the same signs, but those
    # that need time or the network cannot be seen in a start alone.
    keys = {f["key"] for f in findings}
    for p in started_since(samples.get("execlog")):
        if p["exe"] not in known:
            known[p["exe"]] = {"first": p["time"], "origin": origin(p["exe"].replace(" (deleted)", ""))}
        known[p["exe"]]["last"] = max(known[p["exe"]].get("last", 0), p["time"])
        p["origin"] = known[p["exe"]]["origin"]
        verdict = judge(p, [], None, 0, journal)
        if verdict and f"{verdict[0]}:{p['exe']}" not in keys:
            kind, level, title, text, why = verdict
            keys.add(f"{kind}:{p['exe']}")
            if not os.path.exists(f"/proc/{p['pid']}"):
                text += " It ran briefly, at " + time.strftime("%H:%M", time.localtime(p["time"])) + \
                        ", and is not running now."
            findings.append({"key": f"{kind}:{p['exe']}", "level": level, "title": title, "text": text,
                             "details": why + "\n\nIt was started at "
                             + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p["time"]))
                             + " (mentor-execlog).\n" + _describe(p), "pid": p["pid"], "since": now})
    samples = _load(SAMPLES, {})
    samples["execlog"] = execlog_position()
    _save(SAMPLES, samples)

    # What starts by itself: new or changed since the last look.
    before = _load(WATCHED, {})
    current = starts()
    previous_findings = [f for f in _load(FINDINGS, {"found": []}).get("found", [])
                         if f.get("key", "").startswith(("starts:", "preload:", "setuid:")) and now - f.get("since", 0) < KEPT]
    if before and not learning:
        changed = [path for path, digest in current.items() if before.get(path) != digest]
        package_time = _pacman_since(before.get("__time__", 0) if isinstance(before.get("__time__"), (int, float)) else 0)
        new = []
        for path in changed:
            if path in _MENTOR:
                continue  # Mentor's own file: `mentor verify` looks after those
            if path in journal or os.path.basename(path) in journal:
                continue  # Mentor's assistant did it, and its journal says for which request
            owner = _package(path) if path.startswith(("/etc/", "/usr/")) else ""
            if owner and package_time:
                continue  # an upgrade replaced a package's own file
            if "/systemd/" in path and os.path.basename(os.path.dirname(path)).endswith(".wants") and \
                    (os.path.realpath(path) in _MENTOR or _package(os.path.realpath(path))):
                continue  # a package's own service switched on, or Mentor's (mentor-enable)
            new.append(path)
        preload = [p for p in new if p in ("/etc/ld.so.preload",) or (p == "/etc/environment" and b"LD_PRELOAD" in _read(p))]
        for path in preload:
            previous_findings.append({"key": f"preload:{path}", "level": "problem",
                                      "title": "Something is loaded into every program",
                                      "text": f"{path} makes every program load a library. Harmful programs use this to hide.",
                                      "details": f"{path} is new or changed:\n{_read(path, 2000).decode('utf-8', 'replace')}",
                                      "since": now})
        rest = [p for p in new if p not in preload]
        if rest:
            listed = "\n".join(f"{'new' if p not in before else 'changed'}  {p}" for p in rest[:12])
            previous_findings.append({"key": "starts:" + ",".join(sorted(rest)[:6]), "level": "warning",
                                      "title": "Something new starts by itself",
                                      "text": ", ".join(os.path.basename(p) for p in rest[:4])
                                      + (" and more" if len(rest) > 4 else "") + ": not by Mentor and not by an update.",
                                      "details": "These make a program start by itself (at login, on a timer, with "
                                                 "every terminal), and are new or changed since the last look, "
                                                 "neither by Mentor's assistant nor by a package update:\n" + listed,
                                      "since": now})
    current["__time__"] = now
    _save(WATCHED, current)

    # A file that runs with full power (setuid) in a temporary folder or a home.
    for folder in ("/tmp", "/var/tmp", "/dev/shm") + tuple(home for _n, home in _homes()):
        found = _out("find", folder, "-xdev", "-maxdepth", "4", "-type", "f", "-perm", "/6000", timeout=30).split()
        for path in found[:5]:
            if any(f.get("key") == f"setuid:{path}" for f in previous_findings):
                continue
            previous_findings.append({"key": f"setuid:{path}", "level": "problem",
                                      "title": "A file can run with full power from where it should not",
                                      "text": f"{path} runs as its owner, whoever starts it.",
                                      "details": f"{path} has the setuid or setgid bit, in {folder}.\n"
                                                 + _out("ls", "-la", path), "since": now})

    findings += previous_findings
    # programs not seen for three months are forgotten; those new this week that come from nowhere known are
    # listed for `mentor security` (the record itself is root's alone)
    known = {exe: k for exe, k in known.items() if now - k.get("last", now) < 90 * 86400}
    _save(KNOWN, known)
    fresh = sorted(exe for exe, k in known.items() if k.get("origin") == "none" and now - k.get("first", 0) < 7 * 86400
                   and not learning)
    old = _load(FINDINGS, {"found": []})
    if [f["key"] for f in old.get("found", [])] != [f["key"] for f in findings] or old.get("new") != fresh \
            or old.get("learning") != learning or not os.path.exists(FINDINGS):
        # only when something differs: a change of this file wakes the user's session (mentor-guard-notice.path)
        _save(FINDINGS, {"time": now, "found": findings, "learning": learning, "new": fresh}, mode=0o644)
    return findings


# --- package files (the weekly check, when the user agrees) --------------------------------------------

def check_state_path():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mentor",
                        "filecheck.json")


def check_due():
    """Whether a week has gone by since the last check of the package files (mentor-watch reminds with a card)."""
    return time.time() - _load(check_state_path(), {}).get("time", 0) >= CHECK_EVERY


def check_files():
    """Compare every installed package's files with what the package installed (`pacman -Qkk`), outside /etc (where
    settings are meant to change). As the user, no password: system files are readable by everyone; what cannot
    be read is skipped. A harmful program can replace a system program (ps, ls, sudo) to hide or to listen: that
    shows here. Returns (changed now, new since the last check, how many packages); the user wants it done once a
    week, when they press Check now on the reminder card (the user's wish, 2026-10-20)."""
    state = _load(check_state_path(), {})
    try:  # pacman writes the counts to its output and each difference ("warning: …") to its error output: both
        out = subprocess.run(["nice", "-n", "19", "ionice", "-c", "3", "pacman", "-Qkk"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace", timeout=1800,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    changed = sorted({m.group(2) for m in re.finditer(
        r"(?m)^warning: ([^:]+): (/\S+) \((SHA256 checksum|Size) mismatch\)", out) if not m.group(2).startswith("/etc/")})
    packages = len(re.findall(r"(?m)^\S+: \d+ total files", out))
    before = set(state.get("changed", [])) if "changed" in state else None
    new = [path for path in changed if before is not None and path not in before]
    _save(check_state_path(), {"time": time.time(), "changed": changed, "packages": packages}, mode=0o600)
    return changed, new, packages, before is None


# --- for everyone -------------------------------------------------------------------------------

def _boot():
    """(this start's id, when it began): a program still waiting after a restart is told of again when it tries."""
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            boot = f.read().strip()
        with open("/proc/stat") as f:
            began = next((float(line.split()[1]) for line in f if line.startswith("btime ")), 0.0)
    except (OSError, ValueError, IndexError):
        return "", 0.0
    return boot, began


def net_findings():
    """Unknown programs waiting to go online (mentor-netguard keeps them offline until the user answers), as findings:
    one card each, again after a restart only when it tries again. Answered ones (allowed, blocked) are not."""
    import mentor_geo
    data = _load(NET, {})
    boot, began = _boot()
    found = []
    for program, entry in data.get("unknown", {}).items():
        if program not in data.get("waiting", {}) or program in data.get("blocked", {}) or entry.get("last", 0) < began:
            continue
        places = entry.get("destinations", [])
        hosts = [p for p in places if not p.endswith(":53")] or places
        shown = [mentor_geo.where(p, entry.get("ips")) for p in hosts[-3:]]  # looked up by the guard (resolver)
        name, folder = net_name(program)
        found.append({"key": f"net:{boot}:{program}", "level": "warning", "program": program,
                      "title": f"{name} wants to go online",
                      "text": "To " + "; ".join(shown) + ". Mentor does not know this program, so it stays offline "
                              "until you answer.",
                      "details": f"{program} is not from a package, Mentor, an app store, or something Mentor's "
                                 f"assistant installed, and it tried to connect to the internet "
                                 f"({entry.get('count', 0)} time(s); first "
                                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('first', 0)))}, last "
                                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('last', 0)))}). Run by "
                                 f"user id {entry.get('user', '?')}, as: {entry.get('args', '')}\nWhere it tried to go: "
                                 + ", ".join(mentor_geo.where(p, entry.get("ips")) for p in places[-12:])
                                 + "\n\nIt is kept offline until the user answers (the card has Allow and Block). "
                                 "With the user's yes, run_command `/usr/local/lib/mentor/mentor-netguard allow '" + program
                                 + "'` lets it go online, `/usr/local/lib/mentor/mentor-netguard block '" + program + "'` blocks it (no password for "
                                 "either; Mentor Settings, Security, can let a blocked one out again).",
                      "since": entry.get("first", 0)})
    return found


def findings():
    """(key, level, title, text, request for the assistant) from the last look, most urgent first."""
    data = _load(FINDINGS, {"found": []})
    found = sorted(data.get("found", []) + net_findings(), key=lambda f: f.get("level") != "problem")
    for f in found:
        yield ("guard-" + f.get("key", "?"), f.get("level", "warning"), f.get("title", "Something looks wrong"),
               f.get("text", ""), request(f))


def request(f):
    return (f"Mentor's watch for unusual programs found this: {f.get('title')}.\n\n{f.get('details', '')}\n\n"
            "Follow /etc/mentor/SECURITY.md, \"Unusual programs\": look closely, reading only (where the program "
            "came from, when its file appeared, what started it, what it talks to, the journal and pacman's log), "
            "and tell me in plain words what it is, whether it is harmful, and what you would do. Do not stop, "
            "change or remove anything before I agree.")


def last_look():
    """When the last look was, or None."""
    try:
        return os.path.getmtime(SAMPLES)
    except OSError:
        return None


def summary():
    """Lines for `mentor security`: when it last looked, and programs new this week that come from nowhere known."""
    when = last_look()
    if when is None:
        return ["Unusual programs: not looked at yet (mentor-guard.timer)"]
    data = _load(FINDINGS, {})
    lines = [f"Unusual programs: last looked at {time.strftime('%H:%M', time.localtime(when))}"
             + (" (still learning what is usual here)" if data.get("learning") else "")]
    # the protections themselves: each named when it is not working
    for unit, what in (("mentor-guard.timer", "the watch for unusual programs"),
                       ("mentor-execlog.service", "the record of programs started"),
                       ("opensnitchd.service", "the guard on programs going online (OpenSnitch's daemon)"),
                       ("mentor-netguard.service", "the guard on programs going online (Mentor's side)")):
        if _out("systemctl", "is-active", unit).strip() != "active":
            lines.append(f"NOT WORKING: {what} ({unit}; SECURITY.md)")
    if data.get("new"):
        lines.append("Programs first seen this week that come from no package, app store or Mentor: "
                     + ", ".join(data["new"][:8]) + (" and more" if len(data["new"]) > 8 else ""))
    return lines
