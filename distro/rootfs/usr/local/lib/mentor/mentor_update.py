"""Mentor's updates: small packages of Mentor's own files, signed by its maker (UPDATES.md).

check   daily as root (mentor-update-check.timer): first `settle`; then fetch update.json and its
        signature from the release "updates" on GitHub, check the signature against the key built
        into the system (/etc/mentor/update-signers), download the package when it is newer than
        /etc/mentor/version, and leave the user a card that asks whether to install it.
apply   started from that card (mentor-update-apply.service; polkit lets the user start it): a
        restore point on the host, the package's files put into a sandbox of their own, Mentor's
        services and settings set up there (mentor-enable), and the whole applied like any change
        the assistant makes: recorded, undoable, and on trial at the next start. Then a restart.
settle  after that restart: whether the update was kept (a card says what is new) or undone by the
        trial start (mentor_boot tells of that itself); a version that failed is not offered again.
status  prints the state as JSON.

Runs as root.
"""
import hashlib
import http.client
import json
import os
import pwd
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import mentor_boot
import mentor_sandbox

# Where updates are published. MENTOR_UPDATES points a test at another address.
BASE = (os.environ.get("MENTOR_UPDATES") or "https://github.com/Hnd-VXD/Mentor_OS/releases/download/updates").rstrip("/")
SIGNERS = "/etc/mentor/update-signers"
NAMESPACE = "mentor-update"
VERSION_PATH = "/etc/mentor/version"
VERSION_NAME_PATH = "/etc/mentor/version-name"  # what people read: 15.10.26.00
MANIFEST = "/etc/mentor/source/MANIFEST.sha256"
PACKAGES = "/etc/mentor/source/build/packages.x86_64"
STATE_DIR = "/var/lib/mentor/updates"
STATE_PATH = f"{STATE_DIR}/state.json"
LOG = "/var/log/mentor/updates.log"
CONTROL_PORT = "/dev/virtio-ports/org.mentor.control"
SANDBOX = "mentor-update"
REOFFER = 3 * 86400  # a card not acted on comes again after this long
MAX_PACKAGE = 200 << 20
MAX_NOTES = 256 << 10
NOTES_DIR = "/etc/mentor/update-notes"  # each installed update's notes, kept (UPDATES.md)


class UpdateError(Exception):
    pass


def log(text):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    print(text, flush=True)


def apply_stage(version):
    """"installing" while the update `version` is being installed, "failed" when the last try of an install
    ended in an error, else None. From the log, which `apply` writes to as it starts: so that the update card
    in the chat and Mentor Settings both show "Updating…" whichever of their Update buttons was pressed."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.read()[-8000:].splitlines()
        with open("/proc/stat") as f:  # an install ends in a restart: what was written before this start is over
            booted = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(
                int(next(line for line in f if line.startswith("btime")).split()[1])))
    except (OSError, StopIteration, ValueError):
        return None
    for line in reversed(lines):
        if line[:19] < booted:
            return None
        if "apply failed:" in line:
            return "failed"
        if f"installing update {version} " in line:
            return "installing"
    return None


def load():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    os.chmod(STATE_DIR, 0o755)
    with open(STATE_PATH + ".new", "w") as f:
        json.dump(state, f, indent=1)
    os.chmod(STATE_PATH + ".new", 0o644)  # `mentor update` reads it as the user
    os.replace(STATE_PATH + ".new", STATE_PATH)


def display_name(version, given=None):
    """What people read for a version: 15.10.26.00 (day.month.year and the build that day), as the
    build named it; from the number alone (15.10.26) when it has no name."""
    if isinstance(given, str) and 0 < len(given) <= 20 and all(c.isdigit() or c == "." for c in given):
        return given
    text = str(version)
    return f"{text[6:8]}.{text[4:6]}.{text[2:4]}" if len(text) >= 8 and text.isdigit() else text


def installed_version():
    try:
        with open(VERSION_PATH) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


# --- what is offered ---------------------------------------------------------------

def installed_name():
    try:
        with open(VERSION_NAME_PATH) as f:
            return display_name(installed_version(), f.read().strip())
    except OSError:
        return display_name(installed_version())


def _fetch(name, most, timeout=60):
    request = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": "mentor-update"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        data = answer.read(most + 1)
    if len(data) > most:
        raise UpdateError(f"{name} is larger than expected")
    return data


def verify(data, signature):
    """True when `signature` is the maker's signature of `data`."""
    with tempfile.NamedTemporaryFile(suffix=".sig") as sig:
        sig.write(signature)
        sig.flush()
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", SIGNERS, "-I", NAMESPACE, "-n", NAMESPACE,
                                 "-s", sig.name], input=data, capture_output=True)
    return result.returncode == 0


def offered(update):
    """The parts of update.json that are used, checked."""
    try:
        version, summary, name = int(update["version"]), str(update["summary"]).strip(), str(update["file"])
        size, digest = int(update["size"]), str(update["sha256"]).lower()
    except (KeyError, TypeError, ValueError) as e:
        raise UpdateError(f"update.json is not as expected: {e}")
    if not name.startswith("mentor-update-") or "/" in name or not 0 < size <= MAX_PACKAGE or len(digest) != 64:
        raise UpdateError("update.json is not as expected")
    found = {"version": version, "summary": summary, "file": name, "size": size, "sha256": digest,
             "name": display_name(version, update.get("name"))}
    # The problem reports this update fixes (their numbers): the Mentor that sent one says so.
    fixes = update.get("fixes")
    if isinstance(fixes, list):
        found["fixes"] = [int(n) for n in fixes[:200] if isinstance(n, int) and 0 < n < 10 ** 9]
    # The maker's notes for the assistant (NOTES.md): what changed and why, and steps for what files
    # cannot do. Optional; signed through update.json like the package.
    if update.get("notes"):
        try:
            notes, notes_size, notes_digest = str(update["notes"]), int(update["notes_size"]), str(update["notes_sha256"]).lower()
        except (KeyError, TypeError, ValueError) as e:
            raise UpdateError(f"update.json is not as expected: {e}")
        if not notes.startswith("mentor-update-") or not notes.endswith(".md") or "/" in notes \
                or not 0 < notes_size <= MAX_NOTES or len(notes_digest) != 64:
            raise UpdateError("update.json is not as expected")
        found.update(notes=notes, notes_size=notes_size, notes_sha256=notes_digest)
    return found


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _package_ok(update):
    path = f"{STATE_DIR}/{update['file']}"
    return os.path.isfile(path) and os.path.getsize(path) == update["size"] and _sha256(path) == update["sha256"]


def notes_path(update):
    """Where the waiting update's notes are, or None."""
    return f"{STATE_DIR}/{update['notes']}" if update.get("notes") else None


def _notes_ok(update):
    path = notes_path(update)
    return path is None or (os.path.isfile(path) and os.path.getsize(path) == update["notes_size"]
                            and _sha256(path) == update["notes_sha256"])


def has_steps(path):
    """True when notes hold steps for the assistant: a "## Steps" heading with something under it."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    part = text.split("\n## Steps", 1)
    return len(part) == 2 and bool(part[1].split("\n## ", 1)[0].strip(" \n:-").strip())


def download(update):
    if update.get("notes") and not _notes_ok(update):
        data = _fetch(update["notes"], update["notes_size"])
        with open(notes_path(update) + ".part", "wb") as f:
            f.write(data)
        os.chmod(notes_path(update) + ".part", 0o644)
        os.replace(notes_path(update) + ".part", notes_path(update))
        if not _notes_ok(update):
            os.remove(notes_path(update))
            raise UpdateError("the notes that arrived are not the ones update.json describes")
    path = f"{STATE_DIR}/{update['file']}"
    if _package_ok(update):
        return path
    for old in os.listdir(STATE_DIR):  # one package at a time
        if old.startswith("mentor-update-") and old != update.get("notes"):
            os.remove(f"{STATE_DIR}/{old}")
    with open(path + ".part", "wb") as f:
        f.write(_fetch(update["file"], update["size"], timeout=600))
    os.replace(path + ".part", path)
    if not _package_ok(update):
        os.remove(path)
        raise UpdateError("the package that arrived is not the one update.json describes")
    return path


# --- telling the user ----------------------------------------------------------------

def _session_user():
    """(uid, gid, name) of the user with a desktop session, or None."""
    out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].isdigit():
            kind = subprocess.run(["loginctl", "show-session", fields[0], "-p", "Type", "--value"],
                                  capture_output=True, text=True).stdout.strip()
            if kind in ("wayland", "x11"):
                user = pwd.getpwnam(fields[2])
                return user.pw_uid, user.pw_gid, user.pw_name
    return None


def notice(level, title, text, *extra):
    """A card in the user's chat (mentor notice). False when nobody is logged in to see it."""
    user = _session_user()
    if not user:
        return False
    uid, gid, name = user
    argv = ["setpriv", f"--reuid={uid}", f"--regid={gid}", "--init-groups", "env", f"HOME={pwd.getpwuid(uid).pw_dir}",
            f"USER={name}", f"XDG_RUNTIME_DIR=/run/user/{uid}", "PATH=/usr/local/bin:/usr/bin",
            # Quiet: the card waits in the chat; GNOME's pop-up is not wanted for updates (the user's wish).
            "/usr/local/bin/mentor", "notice", "--quiet", level, title, text, *extra]
    return subprocess.run(argv, capture_output=True, timeout=30).returncode == 0


# --- after the restart -----------------------------------------------------------------

def reports_fixed(update):
    """The user's own problem reports that this update fixes: [(number, title, date sent)]."""
    fixes = set(update.get("fixes") or [])
    user = _session_user()
    if not fixes or not user:
        return []
    path = os.path.join(pwd.getpwuid(user[0]).pw_dir, ".local/state/mentor/reports.json")
    try:
        with open(path, encoding="utf-8") as f:
            mine = json.load(f)
        return [(r["id"], str(r.get("title", "")), str(r.get("time", ""))[:10]) for r in mine
                if isinstance(r, dict) and r.get("id") in fixes]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def fixed_sentence(update):
    found = reports_fixed(update)
    if not found:
        return ""
    if len(found) == 1:
        return f" It fixes the problem you reported on {found[0][2]} ({found[0][1]})."
    return f" It fixes {len(found)} of the problems you reported."


def remember(state, update, outcome):
    """One line of the history of updates on this Mentor (Mentor Settings, Updates; newest last)."""
    state.setdefault("history", []).append({
        "version": update["version"], "name": update.get("name") or display_name(update["version"]),
        "summary": update.get("summary", ""), "change": update.get("change"), "outcome": outcome,
        "notes": f"{NOTES_DIR}/{update['version']}.md" if update.get("notes") and outcome == "installed" else None,
        "fixes": update.get("fixes") or [],
        "time": time.strftime("%Y-%m-%d %H:%M")})
    state["history"] = state["history"][-100:]


def settle(state):
    """What became of the update installed before the last restart. True when that is known."""
    installing = state.get("installing")
    if not installing:
        return True
    try:
        with open(f"{mentor_sandbox.CHANGES}/{installing['change']}/manifest.json") as f:
            kept = json.load(f)["state"] == "applied"
    except (OSError, ValueError, KeyError):
        kept = False
    if kept and mentor_boot.load().get("phase") != "ok":
        return False  # the start that tries it is not over yet
    if not kept:
        log(f"update {installing['version']} ({installing.get('name', '')}) was undone by the start that tried it")
        state.setdefault("failed", []).append(installing["version"])
        remember(state, installing, "undone")
        state.pop("installing")
        save(state)
        return True  # mentor-chat has already said "Mentor went back to the way it last worked"
    kept = f"{NOTES_DIR}/{installing['version']}.md"
    extra = []
    if installing.get("notes") and has_steps(kept):
        extra = ["--action", "Let Mentor finish", "--prompt",
                 f"Mentor was just updated. Its maker's notes are in {kept}. Follow its section \"Steps\" exactly as "
                 "/etc/mentor/UPDATES.md says (\"Steps after an update\"): first tell me in plain words what you are "
                 "going to do and wait for my yes; then one step at a time, checking each as the notes say, through the "
                 "sandbox where a step changes the system. If anything is not as the notes expect, stop and tell me."]
    elif installing.get("notes"):
        extra = ["--action", "What's new?", "--prompt",
                 f"Mentor was just updated. Its maker's notes are in {kept}. Tell me as simply as you can, in two or three "
                 "short sentences, what was fixed or is new and what that means for me: no technical words, as to "
                 "someone who has never looked inside a computer."]
    if not notice("idea", f"Mentor is up to date: {installing.get('name') or installed_name()}",
                  installing["summary"] + fixed_sentence(installing), *extra):
        return False  # told when somebody is logged in
    log(f"update {installing['version']} ({installing.get('name', '')}) is installed")
    state["installed"] = {"version": installing["version"], "name": installing.get("name"),
                          "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    remember(state, installing, "installed")
    state.pop("installing")
    state.pop("offered", None)
    save(state)
    return True


# --- the steps ---------------------------------------------------------------------------

def check():
    state = load()
    if not settle(state):
        log("looked: the last update is still being tried, or nobody is logged in to be told")
        return 0
    try:
        data, signature = _fetch("update.json", 64 << 10), _fetch("update.json.sig", 16 << 10)
    except (OSError, UpdateError, http.client.HTTPException) as e:
        log(f"no update information: {e}")
        return 0  # offline, or nothing published yet: tried again tomorrow
    if not verify(data, signature):
        log("update.json is not signed by Mentor's maker: ignored")
        return 1
    update = offered(json.loads(data))
    if update["version"] <= installed_version() or update["version"] in state.get("failed", []):
        log(f"looked: nothing newer than {installed_name()}")  # mentor doctor reads that it looks
        return 0
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        download(update)
    except (OSError, UpdateError, http.client.HTTPException) as e:
        # A connection that broke, or bytes that are not the signed ones: nothing is offered, and the
        # next look tries again. Not a failed service (mentor-watch would show a card for that).
        log(f"looked: {update['name']} could not be downloaded ({e}); tried again at the next look")
        return 0
    with open(f"{STATE_DIR}/update.json", "wb") as f:
        f.write(data)
    with open(f"{STATE_DIR}/update.json.sig", "wb") as f:
        f.write(signature)
    last = state.get("offered") or {}
    if last.get("version") == update["version"] and time.time() - last.get("time", 0) < REOFFER:
        log(f"looked: {update['name']} is still waiting for the user")
        return 0
    extra = []
    if update.get("notes"):
        extra = ["--action", "What's new?", "--prompt",
                 f"An update of Mentor is waiting. Its maker's notes are in {notes_path(update)}. Read them and tell "
                 "me as simply as you can, in two or three short sentences, what it fixes or brings and what that means "
                 "for me: no technical words, as to someone who has never looked inside a computer. Do not install it "
                 "and do not carry out any steps in the notes: I decide with the Update button. /etc/mentor/UPDATES.md "
                 "says how."]
    if notice("idea", f"An update for Mentor: {update['name']}", update["summary"] + fixed_sentence(update),
              "--update", str(update["version"]), *extra):
        state["offered"] = {"version": update["version"], "time": time.time()}
        save(state)
        log(f"update {update['version']} ({update['name']}) offered")
    else:
        log(f"looked: {update['name']} is waiting, but the card could not be left (nobody logged in?); tried again later")
    return 0


def _restore_point(reason):
    """A snapshot of the whole disk by the launcher on the host (mentor_tools._restore_point)."""
    os.sync()
    try:
        fd = os.open(CONTROL_PORT, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return "no restore point: there is no launcher"
    try:
        try:
            while os.read(fd, 65536):
                pass
        except BlockingIOError:
            pass
        for tries_left in range(30, -1, -1):  # the launcher may be connecting again (WINDOWS.md)
            try:
                os.write(fd, (json.dumps({"restore-point": reason[:200]}) + "\n").encode())
                break
            except BlockingIOError:
                if not tries_left:
                    raise
                time.sleep(0.5)
        answer, end = b"", time.monotonic() + 60
        while b"\n" not in answer:
            left = end - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return "no restore point: the launcher did not answer"
            chunk = os.read(fd, 65536)
            if not chunk:
                return "no restore point: the link to the launcher dropped"
            answer += chunk
        reply = json.loads(answer.split(b"\n")[0])
        return f"restore point {reply.get('name')}" if reply.get("ok") else f"no restore point: {reply.get('error')}"
    except (OSError, ValueError) as e:
        return f"no restore point: {e}"
    finally:
        os.close(fd)


def _manifest(path):
    found = {}
    try:
        with open(path) as f:
            for line in f:
                digest, _, name = line.rstrip("\n").partition("  ")
                if name.startswith("/"):
                    found[name] = digest
    except OSError:
        pass
    return found


def _package_list(path):
    try:
        with open(path) as f:
            return {line.split("#")[0].strip() for line in f} - {""}
    except OSError:
        return set()


def _same(a, b):
    try:
        sa, sb = os.lstat(a), os.lstat(b)
    except OSError:
        return False
    if (sa.st_mode, sa.st_size) != (sb.st_mode, sb.st_size):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def _in_sandbox(command, timeout=3600):
    result = subprocess.run(mentor_sandbox.command(command, timeout), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise UpdateError(f"{command.split()[0]} failed in the sandbox: {(result.stdout + result.stderr)[-600:]}")


def declined_packages(state):
    """Packages on Mentor's list that are not installed: the user removed them, so no update puts them
    back, not even one that drops a package from the list and adds it again later. Kept in the state."""
    names = _package_list(PACKAGES)
    if names:
        # pacman -T prints the names that nothing installed provides; a group's name (none on the list
        # today) is among them, so it counts only when no package of the group is installed either.
        result = subprocess.run(["pacman", "-T", *sorted(names)], capture_output=True, text=True)
        missing = {name for name in result.stdout.split() if name in names
                   and subprocess.run(["pacman", "-Qg", name], capture_output=True).returncode != 0}
        state["declined_packages"] = sorted(set(state.get("declined_packages", [])) | missing)
    return set(state.get("declined_packages", []))


def stage(tree, declined=frozenset()):
    """The update's files, and what they need, into the update's own sandbox. Returns what changed."""
    mentor_sandbox.use(SANDBOX)
    mentor_sandbox.discard()
    mentor_sandbox.ensure()
    merged = mentor_sandbox.MERGED
    written = 0
    for folder, dirs, files in os.walk(tree):
        rel_dir = os.path.relpath(folder, tree)
        for name in files:
            rel = os.path.normpath(os.path.join(rel_dir, name))
            if _same(os.path.join(folder, name), "/" + rel):
                continue
            target = os.path.join(merged, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.lexists(target):
                os.remove(target)
            shutil.copy2(os.path.join(folder, name), target, follow_symlinks=False)
            os.lchown(target, 0, 0)
            written += 1
    # Files of Mentor's that the new version no longer has.
    new = _manifest(os.path.join(tree, MANIFEST.lstrip("/")))
    gone = [path for path in _manifest(MANIFEST) if new and path not in new and os.path.lexists(merged + path)]
    for path in gone:
        os.remove(merged + path)
    # Packages the new version added to Mentor's list. One the user removed stays removed.
    added = sorted(_package_list(os.path.join(tree, PACKAGES.lstrip("/"))) - _package_list(PACKAGES) - set(declined))
    if added:  # only those that are not installed already (an older list may not name what is there)
        missing = subprocess.run(["pacman", "-T", *added], capture_output=True, text=True).stdout.split()
        added = [name for name in added if name in missing]
    if added:
        names = " ".join(added)
        try:
            _in_sandbox(f"pacman -S --needed --noconfirm -- {names}")
        except UpdateError:
            _in_sandbox(f"pacman -Syu --needed --noconfirm -- {names}")  # the package lists were out of date
    # Mentor's services, settings database and icons, as the image build sets them up.
    _in_sandbox("/usr/local/lib/mentor/mentor-enable", timeout=600)
    return written, gone, added


def apply():
    state = load()
    try:
        with open(f"{STATE_DIR}/update.json", "rb") as f:
            data = f.read()
        with open(f"{STATE_DIR}/update.json.sig", "rb") as f:
            signature = f.read()
    except OSError:
        raise UpdateError("there is no update waiting")
    if not verify(data, signature):  # again: the files could have changed since the check
        raise UpdateError("the waiting update is not signed by Mentor's maker")
    update = offered(json.loads(data))
    if update["version"] <= installed_version():
        raise UpdateError("Mentor is already this version or newer")
    if not _package_ok(update):
        raise UpdateError("the waiting package is not the one update.json describes")
    log(f"installing update {update['version']} ({update['name']})")
    with tempfile.TemporaryDirectory(prefix="mentor-update-") as tree:
        subprocess.run(["tar", "--zstd", "-xf", f"{STATE_DIR}/{update['file']}", "-C", tree,
                        "--no-same-owner", "--no-overwrite-dir"], check=True, capture_output=True)
        try:
            with open(os.path.join(tree, VERSION_PATH.lstrip("/"))) as f:
                inside = int(f.read().strip())
        except (OSError, ValueError):
            inside = None
        if inside != update["version"]:
            raise UpdateError("the package does not hold the version update.json names")
        point = _restore_point(f"Before Mentor update {update['version']}")
        log(point)
        if update.get("notes"):
            if not _notes_ok(update):
                raise UpdateError("the waiting notes are not the ones update.json describes")
            os.makedirs(os.path.join(tree, NOTES_DIR.lstrip("/")), exist_ok=True)
            shutil.copy(notes_path(update), os.path.join(tree, NOTES_DIR.lstrip("/"), f"{update['version']}.md"))
            os.chmod(os.path.join(tree, NOTES_DIR.lstrip("/"), f"{update['version']}.md"), 0o644)
        declined = declined_packages(state)
        written, gone, added = stage(tree, declined)
    log(f"{written} files, {len(gone)} removed, packages added: {', '.join(added) or 'none'}")
    manifest = mentor_sandbox.apply(f"Mentor update {update['name']}: {update['summary']}", ())
    mentor_boot.record_change(manifest["id"])
    state["installing"] = {**update, "change": manifest["id"], "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    state.pop("offered", None)  # no longer waiting for the user
    save(state)
    log(f"applied as change {manifest['id']}; restarting to try it")
    subprocess.run(["sync"])
    subprocess.Popen(["systemctl", "reboot"])
    return 0


def status():
    state = load()
    print(json.dumps({"version": installed_version(), "name": installed_name(), "source": BASE, **state}, indent=1))
    return 0


def main(argv):
    if os.geteuid() != 0:
        print("mentor-update runs as root", file=sys.stderr)
        return 2
    step = argv[1] if len(argv) > 1 else "status"
    steps = {"check": check, "apply": apply, "status": status}
    if step not in steps:
        print("usage: mentor-update check|apply|status", file=sys.stderr)
        return 2
    try:
        return steps[step]()
    except (OSError, UpdateError, mentor_sandbox.SandboxError, subprocess.CalledProcessError) as e:
        log(f"{step} failed: {e}")
        if step == "apply":
            try:
                mentor_sandbox.use(SANDBOX)
                mentor_sandbox.discard()
            except Exception:
                pass
            notice("problem", "The update could not be installed", f"Nothing was changed. {e}",
                   "--prompt", f"Mentor's update failed with this ({LOG} has the details): {e}\n\nExplain in plain "
                   "words what went wrong, using /etc/mentor/UPDATES.md. Do not change anything before I agree.")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
