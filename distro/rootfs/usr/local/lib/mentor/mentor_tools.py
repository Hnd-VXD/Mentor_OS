"""User side of the Mentor agent layer: the tools an agent can call.

Runs as the logged-in user. Unprivileged work happens here directly; anything
that needs root goes through pkexec to the helpers in this directory, which
makes GNOME show the approval dialog.
"""
import json
import os
import re
import select
import shlex
import shutil
import subprocess
import tempfile
import time

import mentor_journal
import mentor_security

LIBDIR = "/usr/local/lib/mentor"
HELPER = f"{LIBDIR}/mentor-helper"
ROOT_SHELL = f"{LIBDIR}/mentor-root-shell"
SANDBOX = f"{LIBDIR}/mentor-sandbox"
REVIEW = f"{LIBDIR}/mentor-review"
CHANGES = "/var/lib/mentor/changes"
BOOT = f"{LIBDIR}/mentor-boot"
# virtio-serial channel to the launcher on the host, which owns the VM's window.
CONTROL_PORT = "/dev/virtio-ports/org.mentor.control"
WINDOW_MODES = {"fullscreen": True, "windowed": False, "toggle": "toggle"}
# The two desktop layouts differ by one shell extension.
TASKBAR_EXTENSION = "dash-to-panel@jderose9.github.com"
LAYOUTS = {"taskbar": "enable", "normal": "disable"}
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
HOME_BACKUPS = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mentor", "backups")
MAX_OUTPUT = 20000


NOTICES = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mentor", "notices")


def leave_notice(level, title, text="", prompt=None):
    """Tell the user something by itself: the assistant shows it in the chat as a card, yellow
    for a "warning", red for a "problem" (mentor-chat, NOTICES_DIR). `prompt` is what goes to
    the agent when the user asks it to look. Returns where it was left."""
    os.makedirs(NOTICES, exist_ok=True)
    path = os.path.join(NOTICES, f"{time.time():.3f}-{os.getpid()}.json")
    with open(path + ".new", "w") as f:
        json.dump({"level": "problem" if level == "problem" else "warning", "title": title, "text": text,
                   **({"prompt": prompt} if prompt else {})}, f)
    os.replace(path + ".new", path)  # whole when it is seen
    return path


def _clip(text):
    if len(text) <= MAX_OUTPUT:
        return text
    head, tail = MAX_OUTPUT // 5, MAX_OUTPUT - MAX_OUTPUT // 5
    return f"{text[:head]}\n[... {len(text) - MAX_OUTPUT} characters omitted ...]\n{text[-tail:]}"


def _run(argv, timeout=120, stdin=None):
    """Run a command, returning (exit_code, combined output). `stdin` is text to feed it."""
    try:
        p = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout,
            **({"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}),
        )
        return p.returncode, _clip(p.stdout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return 124, _clip(out) + f"\n[timed out after {timeout}s]"
    except FileNotFoundError:
        return 127, f"command not found: {argv[0]}"


# What the call in progress has to say to the journal beyond its arguments and its output.
_noted = {}

STOPPED = ("[The user was told in plain words what this would do and chose not to go on. Do not retry and do not "
           "try another way; ask what they want instead.]")


def _explained(door, a, plain, detail=""):
    """Tell the user, just before their password is asked, what is about to happen: the
    agent's own `explain` if it gave one, otherwise `plain`. With a warning when the agent
    has just read text from outside (mentor_security). False when they then say no."""
    go, read = mentor_security.before_root(os.environ.get("MENTOR_SANDBOX"), door,
                                           " ".join(str(a.get("explain") or plain).split())[:600], detail)
    if read:
        _noted["read"] = mentor_security.said(read)
    if not go:
        _noted["declined"] = True
    return go


def _privileged(helper, action, args, timeout=1800, stdin=None):
    code, out = _run(["pkexec", helper, action, json.dumps(args)], timeout, stdin)
    if code in (126, 127) or (code == 3 and "denied by policy" in out):
        _noted["declined"] = True  # nothing was done: not a line for the journal
    if code == 126:
        out += "\n[The user dismissed the approval dialog or is not allowed to approve. Do not retry; ask the user.]"
    elif code == 127:
        out += "\n[Authorization failed.]"
    return code, out


def system_info(a):
    parts = []
    for title, argv in (
        ("OS", ["cat", "/etc/os-release"]),
        ("Kernel", ["uname", "-srm"]),
        ("Memory", ["free", "-h"]),
        ("Disk", ["df", "-h", "/"]),
    ):
        parts.append(f"## {title}\n{_run(argv)[1].strip()}")
    session = {k: os.environ.get(k, "") for k in ("USER", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "LANG")}
    parts.append("## Session\n" + "\n".join(f"{k}={v}" for k, v in session.items()))
    return 0, "\n\n".join(parts)


def package_search(a):
    return _run(["pacman", "-Ss", "--", a["query"]])


def package_info(a):
    code, out = _run(["pacman", "-Qi", "--", a["package"]])
    if code != 0:
        code, out = _run(["pacman", "-Si", "--", a["package"]])
        out = "[not installed]\n" + out
    return code, out


def package_list(a):
    return _run(["pacman", "-Q" if a.get("include_dependencies") else "-Qe"])


def package_install(a):
    if not _explained("manage", a, f"Mentor wants to add these programs to your system: {', '.join(a['packages'])}."):
        return 1, STOPPED
    return _privileged(HELPER, "pkg_install", {"packages": a["packages"]})


def package_remove(a):
    if not _explained("manage", a, f"Mentor wants to take these programs off your system: {', '.join(a['packages'])}."):
        return 1, STOPPED
    return _privileged(HELPER, "pkg_remove", {"packages": a["packages"]})


MENTOR_EXTENSION = "/usr/share/gnome-shell/extensions/mentor@mentor.local/metadata.json"


def _gnome_major(version):
    """52 from 1:52.1-2."""
    return version.split(":")[-1].split(".")[0].split("-")[0]


def _gnome_jump():
    """(installed, coming, whether Mentor's desktop supports it) when a full upgrade would bring
    a new major GNOME, otherwise None. Looks at fresh package lists in a copy of its own, as
    the user, so that nothing of the system's is touched before the user has agreed."""
    db = os.path.expanduser("~/.cache/mentor/pacman-db")
    os.makedirs(db, exist_ok=True)
    if not os.path.islink(os.path.join(db, "local")):
        os.symlink("/var/lib/pacman/local", os.path.join(db, "local"))
    # Without its download sandbox: pacman cannot set that up when it is not really root.
    if _run(["fakeroot", "--", "pacman", "-Sy", "--disable-sandbox", "--dbpath", db, "--logfile", "/dev/null"],
            timeout=300)[0]:
        return None  # no network, or no fakeroot: the upgrade itself will say what is wrong
    parts = _run(["pacman", "-Qu", "--dbpath", db, "gnome-shell"])[1].split()
    if len(parts) < 4 or parts[0] != "gnome-shell":
        return None
    installed, coming = _gnome_major(parts[1]), _gnome_major(parts[3])
    if installed == coming:
        return None
    try:
        with open(MENTOR_EXTENSION) as f:
            supported = coming in json.load(f).get("shell-version", [])
    except (OSError, ValueError):
        supported = False
    return installed, coming, supported


def desktop_check(a):
    code, out = _run(["/usr/local/bin/mentor", "doctor"], timeout=90)
    return 0, out  # things that need attention are a finding, not a failure of the tool


def system_upgrade(a):
    jump = None if a.get("gnome_major_ok") else _gnome_jump()
    if jump:
        installed, coming, supported = jump
        if supported:
            what = (f"Mentor's desktop is made for GNOME {coming} too, so it should come up as before; other "
                    "extensions, the taskbar among them, and things you changed in the desktop may still need "
                    "attention afterwards. A restore point of the whole disk is taken first. Packages that were "
                    "upgraded are not put back by the system itself: if the desktop does not come up, the ways "
                    "back are the launcher's Repair start (the agent on a text screen, mending it) and that "
                    "restore point.")
            advice = "Going ahead is reasonable; say what may differ."
        else:
            what = (f"Mentor's desktop (the assistant on the desktop, its switches in the system menu) is not yet "
                    f"made for GNOME {coming}: the shell would switch it off, and the user would be left with a "
                    "desktop without the assistant. Upgraded packages are not put back by the system itself; the "
                    "ways back would be the launcher's Repair start and the restore point taken before the "
                    f"upgrade. So this should wait until Mentor's desktop is made for GNOME {coming}.")
            advice = ("Say that nothing has been changed, and give the two ways on: to wait for a Mentor that "
                      f"supports GNOME {coming}, or to have you adapt Mentor's desktop to it first, which you can try "
                      "by following /etc/mentor/DESKTOP.md (read it before you offer, and be plain that it may not "
                      "all carry over).")
        return 1, (f"Nothing was upgraded. This upgrade would take GNOME from {installed} to {coming}, a new major "
                   f"version. {what}\n\nTell the user this in plain words before anything else. {advice} Only if "
                   "they then say to go ahead, call system_upgrade again with gnome_major_ok set to true.")
    if not _explained("manage", a, "Mentor wants to bring every program on your system up to date. It can take "
                      "a few minutes. A copy of the whole disk is kept first, to go back to."):
        return 1, STOPPED
    note = _restore_point("Before a full system upgrade")
    code, out = _privileged(HELPER, "system_upgrade", {}, timeout=3600)
    return code, f"{note}\n{out}"


def settings_list(a):
    if a.get("schema"):
        return _run(["gsettings", "list-recursively", a["schema"]])
    return _run(["gsettings", "list-schemas"])


def settings_get(a):
    code, value = _run(["gsettings", "get", a["schema"], a["key"]])
    if code != 0:
        return code, value
    return 0, f"value: {value.strip()}\nrange: {_run(['gsettings', 'range', a['schema'], a['key']])[1].strip()}"


def settings_set(a):
    code, before = _run(["gsettings", "get", a["schema"], a["key"]])
    _noted["before"] = before.strip() if code == 0 else None
    code, out = _run(["gsettings", "set", a["schema"], a["key"], a["value"]])
    if code != 0:
        return code, out
    return settings_get(a)


def service_status(a):
    argv = ["systemctl", "--no-pager"]
    if a.get("user"):
        argv.append("--user")
    code, out = _run([*argv, "status", "--", a["unit"]])
    # systemctl status exits 3 for an inactive unit, which is an answer, not a failure.
    return (0 if code == 3 else code), out


def service_control(a):
    if a.get("user"):
        return _run(["systemctl", "--user", a["operation"], "--", a["unit"]])
    if not _explained("manage", a, f"Mentor wants to {a['operation']} {a['unit']}, a program that works in the "
                      "background."):
        return 1, STOPPED
    return _privileged(HELPER, "service", {"unit": a["unit"], "operation": a["operation"]}, timeout=300)


def _in_home(path):
    """The real path of a file if it lives in the user's home directory, else None."""
    home = os.path.realpath(os.path.expanduser("~"))
    real = os.path.realpath(os.path.expanduser(path))
    return real if real == home or real.startswith(home + os.sep) else None


def _home_backups(real):
    if not os.path.isdir(HOME_BACKUPS):
        return []
    copies = [os.path.join(HOME_BACKUPS, stamp, real.lstrip("/")) for stamp in sorted(os.listdir(HOME_BACKUPS))]
    return [c for c in copies if os.path.isfile(c)]


def file_read(a):
    path = os.path.expanduser(a["path"])
    mentor_security.saw(os.environ.get("MENTOR_SANDBOX"), "read", {"path": path})
    try:
        with open(path, errors="replace") as f:
            return 0, _clip(f.read())
    except PermissionError:
        return 1, f"{path} is not readable by the user; read it with run_root_command if it is really needed"
    except OSError as e:
        return 1, str(e)


def file_write(a):
    path, content = os.path.expanduser(a["path"]), a["content"]
    real = _in_home(path)
    if real is None:  # a system file: root writes it, after the user approves
        if not _explained("shell", a, "Mentor wants to change a file that belongs to the system. The file as it "
                          "is now is kept, so this can be undone.", os.path.abspath(path)):
            return 1, STOPPED
        return _privileged(ROOT_SHELL, "write_file", {"path": os.path.abspath(path)}, timeout=300, stdin=content)
    try:
        note = ""
        if os.path.isfile(real):
            backup = os.path.join(HOME_BACKUPS, time.strftime("%Y%m%d-%H%M%S"), real.lstrip("/"))
            os.makedirs(os.path.dirname(backup), exist_ok=True)
            shutil.copy2(real, backup)
            note = "previous version saved; file_restore brings it back\n"
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w") as f:
            f.write(content)
        return 0, f"{note}wrote {len(content)} characters to {real}"
    except OSError as e:
        return 1, str(e)


def file_restore(a):
    path = os.path.expanduser(a["path"])
    real = _in_home(path)
    if real is None:
        if not _explained("shell", a, "Mentor wants to put a file of the system back the way it was before.",
                          os.path.abspath(path)):
            return 1, STOPPED
        return _privileged(ROOT_SHELL, "restore_file", {"path": os.path.abspath(path)}, timeout=300)
    copies = _home_backups(real)
    if not copies:
        return 1, f"there is no backup of {real}"
    shutil.copy2(copies[-1], real)
    os.remove(copies[-1])  # so that a second restore goes one step further back
    return 0, f"restored {real}"


def _flathub():
    return _run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB], timeout=120)


def flatpak_search(a):
    code, out = _flathub()
    return (code, out) if code else _run(["flatpak", "search", "--columns=application,name,description", a["query"]], timeout=300)


def flatpak_install(a):
    code, out = _flathub()
    if code:
        return code, out
    return _run(["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", a["app_id"]], timeout=3600)


def flatpak_remove(a):
    return _run(["flatpak", "uninstall", "--user", "--noninteractive", "-y", a["app_id"]], timeout=600)


def extension_list(a):
    return _run(["gnome-extensions", "list", "--details"])


def extension_set(a):
    return _run(["gnome-extensions", "enable" if a["enabled"] else "disable", a["uuid"]])


def _sandbox():
    """Which sandbox this agent works in: its conversation's own, named by whoever started it."""
    return os.environ.get("MENTOR_SANDBOX") or "default"


def sandbox_run(a):
    timeout = int(a.get("timeout_seconds", 600))
    mentor_security.saw(os.environ.get("MENTOR_SANDBOX"), "command", a.get("command"))
    if not _explained("sandbox", a, "Mentor wants to try something out in its sandbox: a copy of your system "
                      "for practising. Nothing on the real system changes until you have seen it and said yes.",
                      a["command"]):
        return 1, STOPPED
    return _privileged(SANDBOX, "sandbox_run", {"sandbox": _sandbox(), "command": a["command"], "timeout": timeout},
                       timeout=timeout + 60)


def _sandbox_report():
    code, out = _privileged(SANDBOX, "sandbox_changes", {"sandbox": _sandbox()}, timeout=600)
    if code:
        return None, out
    try:
        return json.loads(out[out.index("{"):]), ""
    except ValueError:
        return None, out


def _describe(report, with_diffs):
    if not report["entries"]:
        return "The sandbox has no changes." if report["exists"] else "There is no sandbox yet."
    counts = ", ".join(f"{n} {kind}" for kind, n in report["counts"].items())
    lines = [f"Affected paths: {counts}"]
    lines += [f"  {e['kind']:<8} {e['path']}" for e in report["entries"][:200]]
    hidden = len(report["entries"]) - 200 + report["omitted"]
    if hidden > 0:
        lines.append(f"  ... and {hidden} more")
    if with_diffs:
        for e in report["entries"]:
            if "diff" in e:
                lines.append(f"\n# {e['path']}\n{e['diff']}")
    return _clip("\n".join(lines))


def sandbox_changes(a):
    report, error = _sandbox_report()
    return (1, error) if report is None else (0, _describe(report, True))


def _review_on_console(report):
    """The preview of a change for a user at a text console: what would change, then yes or no.
    Returns what mentor-review does: 0 to apply, 1 not to."""
    try:
        with open("/dev/tty") as asked, open("/dev/tty", "w") as tty:  # a terminal cannot be opened for both at once
            tty.write(f"\n--- The agent wants to apply this change: {report['summary']}\n")
            if report.get("warning"):
                tty.write(f"!!! {report['warning']}\n")
            tty.write(_describe(report, False) + "\n")
            tty.write("Type d to see what changes inside the files, y to apply, anything else not to.\n")
            while True:
                tty.write("Apply? [y/N/d] ")
                tty.flush()
                answer = asked.readline().strip().lower()
                if answer != "d":
                    return (0 if answer in ("y", "yes") else 1), ""
                tty.write(_describe(report, True) + "\n")
    except OSError as e:
        return 2, f"there is no desktop to show the preview on, and no console to ask on ({e})"


def sandbox_apply(a):
    report, error = _sandbox_report()
    if report is None:
        return 1, error
    if not report["entries"]:
        return 1, _describe(report, False)
    report["summary"] = a["summary"]
    read = mentor_security.reads(os.environ.get("MENTOR_SANDBOX")) if os.environ.get("MENTOR_SANDBOX") else []
    if read:  # shown in the preview, above the files
        _noted["read"] = mentor_security.said(read)
        report["warning"] = ("While working on this, Mentor read text that came from outside (" + _noted["read"]
                             + "). Such text can be written to trick an assistant. Apply only if the files below "
                             "are what you asked for.")
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        # No desktop to show a window on (the repair console): the same preview as text.
        code, out = _review_on_console(report)
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="mentor-review-", delete=False) as f:
            json.dump(report, f)
        try:
            # The user reads the preview and decides; only then does root get asked to apply.
            code, out = _run([REVIEW, f.name], timeout=3600)
        finally:
            os.unlink(f.name)
    if code == 1:
        return 1, ("The user looked at the preview and chose not to apply it. The sandbox is kept: "
                   "ask what they want changed, or discard it with sandbox_discard.")
    if code:
        return code, f"the preview window could not be shown: {out}"
    note = _restore_point(a["summary"])
    code, out = _privileged(ROOT_SHELL, "sandbox_apply", {"sandbox": _sandbox(), "summary": a["summary"]}, timeout=1800)
    return code, f"{note}\n{out}"


def sandbox_discard(a):
    return _privileged(SANDBOX, "sandbox_discard", {"sandbox": _sandbox()}, timeout=300)


def change_list(a):
    lines = []
    try:
        for change_id in sorted(os.listdir(CHANGES), reverse=True)[:30]:
            with open(os.path.join(CHANGES, change_id, "manifest.json")) as f:
                m = json.load(f)
            lines.append(f"{m['id']}  {m['state']:<8} {len(m['entries'])} paths  {m['summary']}")
    except OSError:
        pass
    return 0, "\n".join(lines) or "No changes have been applied through the sandbox yet."


def change_undo(a):
    if not _explained("shell", a, "Mentor wants to undo a change it made to the system earlier: the files go "
                      "back to how they were before it.", f"change {a['id']}"):
        return 1, STOPPED
    return _privileged(ROOT_SHELL, "change_undo", {"id": a["id"]}, timeout=1800)


def wallpaper_set(a):
    path = os.path.abspath(os.path.expanduser(a["path"]))
    if not os.path.isfile(path):
        return 1, f"no such file: {path}"
    uri = "file://" + path
    for key in ("picture-uri", "picture-uri-dark"):  # the light and the dark variant
        code, out = _run(["gsettings", "set", "org.gnome.desktop.background", key, uri])
        if code:
            return code, out
    return 0, f"wallpaper is now {path}"


def app_open(a):
    name = a["app"].removesuffix(".desktop")
    try:
        subprocess.Popen(["gtk-launch", name, *a.get("arguments", [])], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return 1, str(e)
    return 0, f"opened {name}"


def terminal_run(a):
    """Run a command in a Console window the user can watch, and report what it printed."""
    timeout = int(a.get("timeout_seconds", 120))
    mentor_security.saw(os.environ.get("MENTOR_SANDBOX"), "command", a.get("command"))
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    with tempfile.NamedTemporaryFile(prefix="mentor-terminal-", suffix=".log", dir=runtime, delete=False) as f:
        log = f.name
    done = log + ".done"
    # The command keeps the terminal for its input; its output is copied to a file
    # for us; the window stays open on a shell afterwards.
    script = (f"({a['command']}) 2>&1 | tee {shlex.quote(log)}; "
              f"echo ${{PIPESTATUS[0]}} > {shlex.quote(done)}; echo; exec bash")
    try:
        subprocess.Popen(["kgx", "-e", f"bash -c {shlex.quote(script)}"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        waited = 0.0
        while not os.path.exists(done) and waited < timeout:
            time.sleep(0.5)
            waited += 0.5
        with open(log, errors="replace") as f:
            output = _clip(f.read())
        if not os.path.exists(done):
            return 0, f"{output}\n[still running in the Console window after {timeout}s; the user can see it there]"
        with open(done) as f:
            return int(f.read().strip() or 0), output
    except OSError as e:
        return 1, str(e)
    finally:
        for path in (log, done):
            if os.path.exists(path) and os.path.exists(done):
                os.unlink(path)


def screen_capture(a):
    """What is on the screen right now, as a JPEG small enough to hand to a model."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mentor-screen.png")
    # The shell itself takes the picture (see the mentor extension); nothing else may on Wayland.
    code, out = _run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path",
                      "/org/mentor/Shell", "--method", "org.mentor.Shell.Screenshot", path], timeout=30)
    if code or "true" not in out:
        return 1, f"could not capture the screen: {out.strip()}"
    small = path[:-4] + ".jpg"
    try:
        # ffmpeg does the shrinking and the JPEG: GdkPixbuf's own JPEG writer loses the colours.
        code, out = _run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-vf",
                          "scale=w='min(1568,iw)':h='min(1568,ih)':force_original_aspect_ratio=decrease",
                          "-q:v", "4", small], timeout=30)
        if code:
            return 1, f"could not prepare the picture: {out.strip()}"
        with open(small, "rb") as f:
            data = f.read()
    finally:
        for leftover in (path, small):
            if os.path.exists(leftover):
                os.unlink(leftover)
    return 0, "The screen as it is now.", data


def extension_status(a):
    uuid = a["uuid"]
    code, info = _run(["gnome-extensions", "info", uuid])
    if code:
        return code, info + ("\nA new extension is only found by the shell at the next login."
                             if "not exist" in info or "doesn" in info else "")
    _, log = _run(["journalctl", "-b", "--no-pager", "-n", "3000", "_COMM=gnome-shell"])
    lines = [line for line in log.splitlines() if uuid in line or uuid.split("@")[0] in line or "JS ERROR" in line]
    return 0, info + "\nShell log:\n" + ("\n".join(lines[-25:]) or "(nothing about this extension)")


def session_logout(a):
    # GNOME asks the user to confirm, with a countdown; the agent's own session ends with it.
    return _run(["gnome-session-quit", "--logout"], timeout=90)


def _ask_host(message, timeout=20):
    """Send the launcher on the host a request and wait for its one-line answer."""
    fd = os.open(CONTROL_PORT, os.O_RDWR | os.O_NONBLOCK)
    try:
        try:
            while os.read(fd, 65536):  # an old answer nobody waited for
                pass
        except BlockingIOError:
            pass
        os.write(fd, (json.dumps(message) + "\n").encode())
        answer, end = b"", time.monotonic() + timeout
        while b"\n" not in answer:
            left = end - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise OSError("the launcher did not answer")
            chunk = os.read(fd, 65536)
            if not chunk:
                raise OSError("there is no launcher on the other side")
            answer += chunk
        return json.loads(answer.split(b"\n")[0])
    finally:
        os.close(fd)


def _restore_point(reason):
    """A snapshot of the whole disk, kept by the launcher on the host. Returns what to tell about it."""
    os.sync()  # what the snapshot holds is what has reached the disk
    try:
        answer = _ask_host({"restore-point": " ".join(reason.split())[:200]})
    except (OSError, ValueError) as e:
        return f"[No restore point on the host: {e}]"
    if not answer.get("ok"):
        return f"[No restore point on the host: {answer.get('error', 'refused')}]"
    return (f"[Restore point {answer.get('name')} made on the host: the whole disk as it is now. If Mentor "
            "ever stops starting, the launcher offers to go back to it.]")


def restore_point_create(a):
    note = _restore_point(a["reason"])
    return (1 if note.startswith("[No") else 0), note


def boot_status(a):
    code, out = _run([BOOT, "status"])
    if code:
        return code, out
    report = json.loads(out)
    state, good = report["state"], report["state"].get("good") or {}
    lines = [f"Running kernel: {report['running_kernel']}" + (" (a start that tries a change)" if report["trial_start"] else ""),
             f"Kernel known to work: {good.get('version', 'none yet')}, since {good.get('time', '-')}"]
    if state["phase"] == "ok":
        lines.append("Nothing is waiting to be tried: the next start is the one that works.")
    else:
        what = [f"{len(state['changes'])} applied change(s): {', '.join(state['changes'])}"] if state["changes"] else []
        if state["kernel"]:
            what.append("a new kernel, initramfs or kernel command line")
        lines.append(f"On trial ({state['phase']}): " + " and ".join(what) + ". If the desktop does not come up "
                     "within three minutes of the next start, this is undone automatically.")
    if state["failed"]:
        lines.append(f"{len(state['failed'])} kernel/initramfs version(s) failed to start and are not tried again "
                     "until they change.")
    last = report.get("last_restore")
    if last:
        lines.append(f"Last automatic restore: {last['time']}, because {last['why']}.")
        lines += [f"  undone: {u['id']}  {u['summary']}" for u in last["undone"]]
        lines += [f"  could not be undone: {u['id']}  {u['error']}" for u in last["not_undone"]]
        if last["kernel_held"]:
            lines.append("  the kernel that failed is still installed but is not started")
    return 0, "\n".join(lines)


def system_restart(a):
    # GNOME asks the user to confirm, with a countdown; the agent's own session ends with it.
    return _run(["gnome-session-quit", "--reboot"], timeout=90)


def window_mode(a):
    mode = a["mode"]
    if mode not in WINDOW_MODES:
        return 2, f"mode must be one of: {', '.join(WINDOW_MODES)}"
    try:
        with open(CONTROL_PORT, "w") as port:
            port.write(json.dumps({"fullscreen": WINDOW_MODES[mode]}) + "\n")
    except OSError as e:
        return 1, f"cannot reach the Mentor launcher on the host: {e}"
    return 0, f"asked the launcher for: {mode}"


def desktop_layout(a):
    layout = a["layout"]
    if layout not in LAYOUTS:
        return 2, f"layout must be one of: {', '.join(LAYOUTS)}"
    code, out = _run(["gnome-extensions", LAYOUTS[layout], TASKBAR_EXTENSION])
    return code, out or f"desktop layout is now: {layout}"


def run_command(a):
    mentor_security.saw(os.environ.get("MENTOR_SANDBOX"), "command", a.get("command"))
    return _run(["bash", "-c", a["command"]], timeout=int(a.get("timeout_seconds", 120)))


def run_root_command(a):
    if not _explained("shell", a, "Mentor wants to run a command with full power over your system.", a["command"]):
        return 1, STOPPED
    return _privileged(ROOT_SHELL, "run_root", {"command": a["command"]})


def security_check(a):
    return 0, mentor_security.report()


def journal_read(a):
    limit = 40 if a.get("limit") is None else int(a["limit"])  # 0 is all of it
    found, left_out = mentor_journal.entries(str(a.get("search") or ""), limit, bool(a.get("all")), a.get("since"))
    return 0, _clip(mentor_journal.readable(found, left_out))


def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required)}


_STR = {"type": "string"}
_PACKAGES = {"type": "array", "items": _STR, "minItems": 1, "description": "Exact pacman package names."}
_USER_UNIT = {"type": "boolean", "description": "Act on the user's own systemd instance instead of the system one."}
_OPERATION = {"type": "string", "enum": ["start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask"]}
_EXPLAIN = {"type": "string", "description":
            "One or two short sentences for the user, shown in a window just before their password is asked: "
            "what this does and why they would want it. In their language, in words a child would understand: "
            "no names of commands, packages or files, no technical terms."}
_CHANGES = {"type": "string", "description":
            "When the command changes something (a file, a setting, a program): what it changes, in a few "
            "words, for the journal. Leave it out for a command that only reads."}

# name -> (description, input schema, handler)
# --- suggestions -------------------------------------------------------------
# mentor-advisor writes down what it finds; the assistant shows it behind the bell and
# keeps what the user said about hearing of it (see mentor-chat).

ADVICE = "/var/lib/mentor/advice/suggestions.json"
ADVICE_STATE = os.path.expanduser("~/.config/mentor/advice.json")
ADVICE_KINDS = {"updates": "waiting updates", "disk": "a disk that is filling", "failed": "services that failed",
                "news": "Arch Linux news", "gnome": "GNOME news", "apps": "new applications",
                "github": "new projects on GitHub"}


def _advice_state():
    try:
        with open(ADVICE_STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("off", False)
    state.setdefault("never", [])
    state.setdefault("until", {})
    return state


def suggestions_status(a):
    state = _advice_state()
    try:
        with open(ADVICE) as f:
            found = [s for s in json.load(f) if isinstance(s, dict) and s.get("id")]
    except (OSError, ValueError):
        found = []
    now = time.time()
    put_off = {key: when for key, when in state["until"].items() if when > now}
    showing = [s for s in found if s.get("kind") not in state["never"] and s["id"] not in put_off]
    lines = ["Suggestions are turned off altogether." if state["off"] else "Suggestions are on."]
    lines.append("Behind the bell now: " + ("; ".join(s.get("title", s["id"]) for s in showing) or "nothing")
                 + (" (not shown while suggestions are off)" if state["off"] and showing else ""))
    if state["never"]:
        lines.append("The user chose never to be told about: "
                     + ", ".join(f"{ADVICE_KINDS.get(kind, kind)} [{kind}]" for kind in state["never"]))
    else:
        lines.append("No kind of suggestion has been turned away for good.")
    for key, when in sorted(put_off.items(), key=lambda item: item[1]):
        title = next((s.get("title") for s in found if s["id"] == key), None)
        lines.append(f"Put off until {time.strftime('%d %B %H:%M', time.localtime(when))}: {title or key} [{key}]"
                     + ("" if title else " (no longer found on the system)"))
    lines.append(f"Kinds there are: {', '.join(ADVICE_KINDS)}.")
    return 0, "\n".join(lines)


def suggestions_restore(a):
    what = a["what"].strip()
    state = _advice_state()
    done = []
    if what == "all":
        if state["never"] or state["until"] or state["off"]:
            done.append("everything that was turned away or put off is back, and suggestions are on")
        state.update(never=[], until={}, off=False)
    elif what == "on":
        state["off"] = False
        done.append("suggestions are on")
    elif what in state["never"]:
        state["never"].remove(what)
        done.append(f"{ADVICE_KINDS.get(what, what)} will be suggested again")
    elif what in state["until"]:
        del state["until"][what]
        done.append(f"{what} is no longer put off")
    else:
        kind_ids = [key for key in state["until"] if key == what or key.startswith(what + "-")]
        for key in kind_ids:
            del state["until"][key]
        if kind_ids:
            done.append(f"no longer put off: {', '.join(kind_ids)}")
    if not done:
        return 1, f"Nothing to bring back under '{what}'. suggestions_status says what was turned away."
    os.makedirs(os.path.dirname(ADVICE_STATE), exist_ok=True)
    with open(ADVICE_STATE, "w") as f:
        json.dump(state, f)
    return 0, "Done: " + "; ".join(done) + ". It shows behind the bell on the desktop when there is something to say."


TOOLS = {
    "system_info": (
        "OS release, kernel, memory, disk usage and desktop session of this machine.",
        _schema(), system_info),
    "package_search": (
        "Search the pacman repositories by name or description. Installed packages are marked [installed].",
        _schema({"query": _STR}, ["query"]), package_search),
    "package_info": (
        "Details of one package: version, description, dependencies, whether it is installed.",
        _schema({"package": _STR}, ["package"]), package_info),
    "package_list": (
        "List installed packages. By default only the explicitly installed ones.",
        _schema({"include_dependencies": {"type": "boolean"}}), package_list),
    "package_install": (
        "Install packages with pacman. Asks the user for approval.",
        _schema({"packages": _PACKAGES, "explain": _EXPLAIN}, ["packages"]), package_install),
    "package_remove": (
        "Remove packages and their unneeded dependencies with pacman. Asks the user for approval.",
        _schema({"packages": _PACKAGES, "explain": _EXPLAIN}, ["packages"]), package_remove),
    "system_upgrade": (
        "Upgrade every package on the system (pacman -Syu). Asks the user for approval. Can take several minutes. "
        "When the upgrade would bring a new major version of GNOME it stops first and tells you what that means "
        "for this system: pass that on, and call again with gnome_major_ok only after the user has said to go ahead.",
        _schema({"gnome_major_ok": {"type": "boolean", "description":
                 "The user was told a new major GNOME is coming and said to go ahead."},
                 "explain": _EXPLAIN}), system_upgrade),
    "settings_list": (
        "Without a schema: list all GSettings schemas. With one: list its keys and current values "
        "(e.g. org.gnome.desktop.interface).",
        _schema({"schema": _STR}), settings_list),
    "settings_get": (
        "Read one GSettings key, with the range of values it accepts.",
        _schema({"schema": _STR, "key": _STR}, ["schema", "key"]), settings_get),
    "settings_set": (
        "Change one GSettings key for the current user. The value uses GVariant text syntax: "
        "strings need quotes ('prefer-dark'), booleans are true/false, e.g. \"uint32 300\" for typed numbers.",
        _schema({"schema": _STR, "key": _STR, "value": _STR}, ["schema", "key", "value"]), settings_set),
    "service_status": (
        "Status and recent log lines of a systemd unit.",
        _schema({"unit": _STR, "user": _USER_UNIT}, ["unit"]), service_status),
    "service_control": (
        "Start, stop, restart, reload, enable, disable, mask or unmask a systemd unit. "
        "System units ask the user for approval.",
        _schema({"unit": _STR, "operation": _OPERATION, "user": _USER_UNIT, "explain": _EXPLAIN},
                ["unit", "operation"]), service_control),
    "window_mode": (
        "Switch the Mentor window on the host between full screen and a normal window. "
        "This is the whole VM's window, not an app inside it; the screen resolution follows it.",
        _schema({"mode": {"type": "string", "enum": list(WINDOW_MODES)}}, ["mode"]), window_mode),
    "sandbox_run": (
        "Run a bash command as root inside the sandbox: a private copy-on-write view of this system. "
        "Install packages, build software, edit files there freely; the real system is not touched until "
        "sandbox_apply. The sandbox belongs to this conversation, is created on first use and keeps its "
        "state between calls. /boot is included: a kernel, initramfs or boot loader file changed there is "
        "part of the change. No graphical session inside, and the kernel is the running one.",
        _schema({"command": _STR, "timeout_seconds": {"type": "integer", "default": 600}, "explain": _EXPLAIN},
                ["command"]), sandbox_run),
    "sandbox_changes": (
        "List every file the sandbox added, modified or deleted relative to the real system, with text diffs. "
        "Check this before proposing the change.",
        _schema(), sandbox_changes),
    "sandbox_apply": (
        "Propose the sandbox's changes to the user. They see a preview window with the affected files and "
        "diffs and choose whether to apply; if they do, the files are copied to the real system and the "
        "change is recorded so it can be undone. `summary` is the one or two sentences the user reads at "
        "the top of the preview: what the change does and why, in their language.",
        _schema({"summary": _STR}, ["summary"]), sandbox_apply),
    "sandbox_discard": (
        "Throw the sandbox and everything in it away.",
        _schema(), sandbox_discard),
    "change_list": (
        "List the changes applied through the sandbox, newest first, with their ids and state.",
        _schema(), change_list),
    "change_undo": (
        "Undo one applied change by id: the files it replaced or deleted come back, the files it added go away. "
        "Asks the user for approval.",
        _schema({"id": _STR, "explain": _EXPLAIN}, ["id"]), change_undo),
    "file_read": (
        "Read a text file. Works for anything the logged-in user can read.",
        _schema({"path": _STR}, ["path"]), file_read),
    "file_write": (
        "Create a file or replace its whole content (read it first and send back the full new text). "
        "Files in the home directory are written directly; system files such as /etc/... ask the user for "
        "approval. The previous version is kept and file_restore undoes the change. This is the way to "
        "edit configuration files; do not write them with shell redirection.",
        _schema({"path": _STR, "content": _STR, "explain": _EXPLAIN}, ["path", "content"]), file_write),
    "file_restore": (
        "Undo the last file_write to a file by restoring its previous version. Call again to go further back.",
        _schema({"path": _STR}, ["path"]), file_restore),
    "flatpak_search": (
        "Search Flathub for an application. Use it when pacman does not have the app.",
        _schema({"query": _STR}, ["query"]), flatpak_search),
    "flatpak_install": (
        "Install an application from Flathub for the current user, by application ID "
        "(e.g. org.videolan.VLC). No approval needed. Large downloads can take several minutes.",
        _schema({"app_id": _STR}, ["app_id"]), flatpak_install),
    "flatpak_remove": (
        "Remove an application that was installed from Flathub.",
        _schema({"app_id": _STR}, ["app_id"]), flatpak_remove),
    "extension_list": (
        "List the installed GNOME Shell extensions with their state.",
        _schema(), extension_list),
    "wallpaper_set": (
        "Set the desktop wallpaper to an image file. Wallpapers that come with the system are under "
        "/usr/share/backgrounds; one the user gave you or that you downloaded should be kept in ~/Pictures.",
        _schema({"path": _STR}, ["path"]), wallpaper_set),
    "app_open": (
        "Open an installed application for the user, by desktop file name (chromium.desktop). `arguments` are "
        "the files or URLs to open in it. Use this when the user wants something opened or shown in an app.",
        _schema({"app": _STR, "arguments": {"type": "array", "items": _STR}}, ["app"]), app_open),
    "terminal_run": (
        "Run a bash command in a new Console window on the user's screen, so they watch it happen; returns "
        "its output and exit code. Use this instead of run_command when the user asked for something to be "
        "run in the terminal, or when watching it is the point (a speed test, a download, a long build). "
        "The window stays open afterwards.",
        _schema({"command": _STR, "timeout_seconds": {"type": "integer", "default": 120}, "changes": _CHANGES},
                ["command"]), terminal_run),
    "extension_status": (
        "State of one GNOME Shell extension, any error it failed with, and what the shell logged about it. "
        "Use it after writing or enabling an extension to see whether it actually loaded.",
        _schema({"uuid": _STR}, ["uuid"]), extension_status),
    "screen_capture": (
        "Look at the screen: returns a picture of the whole desktop as it is right now. Use it to check the "
        "result of a visual change, or to see what the user is describing.",
        _schema(), screen_capture),
    "system_restart": (
        "Ask the user to restart the computer, which is how a change to the kernel, its parameters, the "
        "initramfs, modules or early services takes effect. GNOME shows its own confirmation. Your "
        "conversation ends when they accept, so finish explaining first: what will be different, and that "
        "a start which does not reach the desktop undoes the change by itself.",
        _schema(), system_restart),
    "boot_status": (
        "How start-up stands: the running kernel, the one known to work, what is waiting to be tried at the "
        "next restart, and what the last automatic restore undid and why. Read it after a restart that was "
        "meant to try a change, to see whether the change survived.",
        _schema(), boot_status),
    "suggestions_status": (
        "The suggestions the system makes by itself (behind the bell on the desktop: waiting updates, a full "
        "disk, failed services, news from Arch and GNOME, new applications): which are there now, which kinds the user chose never to hear of "
        "again, and which they put off and until when. Read it when the user asks what they dismissed or hid.",
        _schema(), suggestions_status),
    "suggestions_restore": (
        "Bring back suggestions the user turned away: a kind they chose never to hear of (updates, disk, "
        "failed, news, gnome, apps, github), one they put off (its id from suggestions_status), 'on' to turn suggestions on, or "
        "'all' for everything. Only when the user asks for it.",
        _schema({"what": {"type": "string", "description": "A kind, an id from suggestions_status, 'on' or 'all'."}},
                ["what"]), suggestions_restore),
    "desktop_check": (
        "Which parts of Mentor's own desktop work right now: the extension and each of its parts, the taskbar, "
        "the assistant, the shared clipboard, and errors of Mentor's in the logs. Use it when something of "
        "Mentor's looks wrong, and after any upgrade of GNOME. What each part is and how to make it again is "
        "in /etc/mentor/DESKTOP.md.",
        _schema(), desktop_check),
    "restore_point_create": (
        "Have the launcher on the host take a snapshot of the whole disk now, to go back to if Mentor ever "
        "stops starting. sandbox_apply and system_upgrade make one by themselves; call this before any other "
        "risky change (run_root_command, file_write to a system file). The three newest are kept.",
        _schema({"reason": {"type": "string", "description": "What is about to change, for the user to recognise it by."}},
                ["reason"]), restore_point_create),
    "session_logout": (
        "Ask the user to log out, which is how the shell picks up a new extension or a rebuilt GNOME "
        "component. GNOME shows its own confirmation. Your conversation ends when they accept, so finish "
        "explaining first and tell them what to check after logging back in.",
        _schema(), session_logout),
    "extension_set": (
        "Enable or disable a GNOME Shell extension by UUID.",
        _schema({"uuid": _STR, "enabled": {"type": "boolean"}}, ["uuid", "enabled"]), extension_set),
    "desktop_layout": (
        "Choose the desktop layout: 'taskbar' is a permanent bar at the bottom with the running apps "
        "(the Mentor default), 'normal' is stock GNOME with a top bar and a dock in the overview.",
        _schema({"layout": {"type": "string", "enum": list(LAYOUTS)}}, ["layout"]), desktop_layout),
    "run_command": (
        "Run a bash command as the logged-in user, without root. For reading state and for changes "
        "inside the home directory.",
        _schema({"command": _STR, "timeout_seconds": {"type": "integer", "default": 120}, "changes": _CHANGES},
                ["command"]), run_command),
    "run_root_command": (
        "Run a bash command as root. The user sees the exact command and must enter their password every time. "
        "Only for changes no other tool covers.",
        _schema({"command": _STR, "explain": _EXPLAIN}, ["command"]), run_root_command),
    "security_check": (
        "Look at how safe this system is right now, without changing anything: whether the firewall refuses "
        "what comes in from other computers, whether the password is still the one every Mentor starts with, "
        "remote login, root without a password, a second root account, keys others can read, and which "
        "programs wait for connections. Use it when the user asks whether their system is safe, and after any "
        "change to the network, to accounts or to services. /etc/mentor/SECURITY.md says what each finding "
        "means and what to do about it.",
        _schema(), security_check),
    "journal_read": (
        "The journal of what was changed on this system through these tools, by you and by every model before "
        "you: under each request of the user's, the changes made for it, when, and the way back where there is "
        "one. Read it when the user asks what was changed, when or why; before looking for the cause of "
        "something that stopped working (what changed last is the first suspect); before undoing something; "
        "and when asked to set another system up the same way. `search` is words to look for (a package, a "
        "file, a setting, part of a request), `since` the start of a date (2026-10 or 2026-10-13), `all` adds "
        "the plain commands that were run. Newest last.",
        _schema({"search": _STR, "since": _STR,
                 "limit": {"type": "integer", "default": 40, "description": "How many of the newest; 0 for all."},
                 "all": {"type": "boolean"}}), journal_read),
}


# --- the journal ---------------------------------------------------------------
# What each tool that changes something writes down (mentor_journal, /etc/mentor/JOURNAL.md):
# name -> function(arguments, output) giving the line, or (line, the way back), or
# (line, the way back, kind), or None when the call changed nothing. A tool that is not
# here only reads, or only shows something.

_OPPOSITE = {"start": "stop", "stop": "start", "enable": "disable", "disable": "enable", "mask": "unmask", "unmask": "mask"}


def _applied(a, out):
    done = re.search(r"applied change (\S+): (\d+) paths", out)
    if not done:
        return None  # the user looked at the preview and said no
    return (f"applied a change to the system: {a['summary']} (change {done.group(1)}, {done.group(2)} paths; "
            f"change_list shows it)", f"change_undo {done.group(1)}")


def _commanded(where=""):
    def line(a, out):
        said = " ".join(str(a.get("changes") or "").split())
        return (f"{said}: {where}{a['command']}", None, "change") if said else (f"{where}{a['command']}", None, "command")
    return line


JOURNAL = {
    "package_install": lambda a, out: (f"installed packages: {', '.join(a['packages'])}", "package_remove, the same names"),
    "package_remove": lambda a, out: (f"removed packages, and what only they needed: {', '.join(a['packages'])}",
                                      "package_install, the same names"),
    "system_upgrade": lambda a, out: None if "Nothing was upgraded" in out else (
        "upgraded every package (pacman -Syu); /var/log/pacman.log has the versions",
        "the restore point made just before it (Restore points in the launcher)"),
    "settings_set": lambda a, out: (
        f"setting {a['schema']} {a['key']}: {_noted.get('before') or 'unknown'} -> {a['value']}",
        f"settings_set {a['schema']} {a['key']} {_noted['before']}" if _noted.get("before") else None),
    "service_control": lambda a, out: (
        f"{a['operation']} {a['unit']}" + (" (of the user's own services)" if a.get("user") else ""),
        f"service_control {_OPPOSITE[a['operation']]} {a['unit']}" if a["operation"] in _OPPOSITE else None),
    "file_write": lambda a, out: (
        f"wrote the file {os.path.abspath(os.path.expanduser(a['path']))}",
        f"file_restore {a['path']}" if "previous version saved" in out else "the file was new: remove it"),
    "file_restore": lambda a, out: f"put back the version before of {os.path.abspath(os.path.expanduser(a['path']))}",
    "flatpak_install": lambda a, out: (f"installed the application {a['app_id']} from Flathub", f"flatpak_remove {a['app_id']}"),
    "flatpak_remove": lambda a, out: (f"removed the application {a['app_id']} (Flathub)", f"flatpak_install {a['app_id']}"),
    "extension_set": lambda a, out: (
        f"{'enabled' if a['enabled'] else 'disabled'} the shell extension {a['uuid']}",
        f"extension_set {a['uuid']}, enabled {'false' if a['enabled'] else 'true'}"),
    "sandbox_apply": _applied,
    "change_undo": lambda a, out: f"undid the applied change {a['id']}",
    "wallpaper_set": lambda a, out: f"wallpaper: {os.path.abspath(os.path.expanduser(a['path']))}",
    "desktop_layout": lambda a, out: (f"desktop layout: {a['layout']}",
                                      f"desktop_layout {'normal' if a['layout'] == 'taskbar' else 'taskbar'}"),
    "suggestions_restore": lambda a, out: f"brought back suggestions that were turned away: {a['what']}",
    "run_root_command": lambda a, out: f"as root: {a['command']}",
    "run_command": _commanded(),
    "terminal_run": _commanded("in a Console window: "),
    "sandbox_run": lambda a, out: (f"in the sandbox (real only once applied): {a['command']}", None, "command"),
}


def _journal(name, a, code, out):
    """Write down what a call changed. Never in the way of the call itself."""
    try:
        describe = JOURNAL.get(name)
        line = None if not describe or _noted.get("declined") else describe(a, out)
        if line is None:
            return
        what, undo, kind = (line, None, "change") if isinstance(line, str) else (*line, "change")[:3]
        mentor_journal.record(name, what, kind, code == 0, os.environ.get("MENTOR_SANDBOX"), undo=undo,
                              after_reading=_noted.get("read") if kind == "change" else None)
    except Exception:
        pass


def call(name, arguments):
    """Run a tool. Returns (ok, text)."""
    if name not in TOOLS:
        return False, f"unknown tool: {name}"
    return call_with_image(name, arguments)[:2]


def call_with_image(name, arguments):
    """Run a tool. Returns (ok, text, JPEG bytes or None)."""
    if name not in TOOLS:
        return False, f"unknown tool: {name}", None
    _noted.clear()
    try:
        code, out, *image = TOOLS[name][2](arguments or {})
    except KeyError as e:
        return False, f"missing argument: {e.args[0]}", None
    _journal(name, arguments or {}, code, out)
    out = out.strip() or "(no output)"
    return code == 0, out if code == 0 else f"{out}\n[exit code {code}]", image[0] if image else None
