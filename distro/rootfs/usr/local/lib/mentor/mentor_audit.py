"""Who touched the user's secrets: a few rules for the kernel's audit (auditd, package audit), and reading what
they caught. Used as root by mentor_guard (each look) and mentor-investigate. /etc/mentor/SECURITY.md,
"Who touched passwords and keys".

The rules that do not depend on a home are in /etc/audit/rules.d/mentor.rules. Those of a home and of a browser's
profile (its folder has a different name on each computer, and appears at the browser's first start) are added by
refresh() at each look, so they are not kept in a file."""
import glob
import os
import re
import subprocess

LOG = "/var/log/audit/audit.log"
SECRETS, BROWSER, STARTS, OWN = "mentor-secrets", "mentor-browser", "mentor-starts", "mentor-own"
KEYS = (SECRETS, BROWSER, STARTS, OWN)
RECORD = re.compile(r"^type=(\w+) msg=audit\((\d+)\.\d+:(\d+)\):(.*)$")
FIELD = re.compile(r'(\w+)=("[^"]*"|\S+)')
BROWSER_FILES = ("Cookies", "Network/Cookies", "Login Data", "Web Data")
BROWSER_FOLDERS = (".config/chromium", ".config/google-chrome", ".config/BraveSoftware/Brave-Browser",
                   ".var/app/org.chromium.Chromium/config/chromium")
MOZILLA_FOLDERS = (".mozilla/firefox", ".var/app/org.mozilla.firefox/.mozilla/firefox")
MOZILLA_FILES = ("cookies.sqlite", "logins.json", "key4.db")


def wanted(homes):
    """[(path, permissions, key)] of the homes given, what exists of them."""
    rules = []
    for home in homes:
        for path in (".ssh", ".gnupg", ".local/share/keyrings", ".config/mentor/keys", ".claude/.credentials.json",
                     ".codex/auth.json", ".gemini/oauth_creds.json"):
            rules.append((os.path.join(home, path), "rwa", SECRETS))
        for folder in BROWSER_FOLDERS:
            for profile in glob.glob(os.path.join(glob.escape(home), folder, "*")):
                rules += [(os.path.join(profile, name), "rwa", BROWSER) for name in BROWSER_FILES]
        for folder in MOZILLA_FOLDERS:
            for profile in glob.glob(os.path.join(glob.escape(home), folder, "*")):
                rules += [(os.path.join(profile, name), "rwa", BROWSER) for name in MOZILLA_FILES]
        for path in (".config/autostart", ".config/systemd/user", ".bashrc", ".bash_profile", ".profile"):
            rules.append((os.path.join(home, path), "wa", STARTS))
    return [r for r in rules if os.path.exists(r[0])]


def refresh(homes):
    """Add the rules still missing. Quietly nothing when audit is not there or is off."""
    try:
        now = subprocess.run(["auditctl", "-l"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for path, permissions, key in wanted(homes):
        if f"-w {path} " in now:
            continue
        try:
            subprocess.run(["auditctl", "-w", path, "-p", permissions, "-k", key], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return


def _value(text):
    """A field as the audit log writes it: in quotes, or in hex when it holds anything unusual."""
    if text.startswith('"'):
        return text[1:-1]
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", text):
        try:
            return bytes.fromhex(text).decode("utf-8", "replace").replace("\0", " ")
        except ValueError:
            pass
    return text


def _events(lines):
    """Events of Mentor's rules from lines of the log: {key, exe, comm, pid, ppid, uid, time, paths, command}."""
    open_events, done = {}, []
    for line in lines:
        found = RECORD.match(line)
        if not found:
            continue
        kind, stamp, serial, rest = found.groups()
        fields = dict(FIELD.findall(rest))
        if kind == "SYSCALL":
            key = _value(fields.get("key", "")) if fields.get("key") != "(null)" else ""
            if key in KEYS:
                open_events[serial] = {"key": key, "exe": _value(fields.get("exe", "")), "comm": _value(fields.get("comm", "")),
                                       "pid": fields.get("pid", ""), "ppid": fields.get("ppid", ""),
                                       "uid": fields.get("uid", ""), "time": int(stamp), "paths": [], "command": ""}
                done.append(open_events[serial])
        elif serial in open_events:
            if kind == "PATH" and fields.get("nametype") != "PARENT" and fields.get("name"):
                open_events[serial]["paths"].append(_value(fields["name"]))
            elif kind == "PROCTITLE":
                open_events[serial]["command"] = _value(fields.get("proctitle", ""))[:400]
    return done


def since(position):
    """(events, new position) since `position`, {inode, offset} from the last call. None: from the end of the log
    (nothing old is news)."""
    try:
        with open(LOG, "rb") as f:
            stat = os.fstat(f.fileno())
            end = stat.st_size
            if position is None:
                return [], {"inode": stat.st_ino, "offset": end}
            start = position.get("offset", 0) if position.get("inode") == stat.st_ino else 0
            f.seek(0 if start > end else start)
            data = f.read(1 << 24)
            return _events(data.decode("utf-8", "replace").splitlines()), {"inode": stat.st_ino, "offset": f.tell()}
    except OSError:
        return [], position


def about(program, most=20):
    """The last events of a program, and of an interpreter running it as a script, newest last."""
    lines = []
    for path in (LOG + ".1", LOG):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines += f.readlines()
        except OSError:
            pass
    return [e for e in _events(lines) if e["exe"] == program or program in e["command"]][-most:]
