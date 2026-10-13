"""Trial changes: let the agent change a throwaway copy of the system first.

The sandbox is an overlay filesystem over the real root: everything is visible,
every write lands in a separate layer. Commands run in it as root inside a
container (systemd-nspawn), so installing, building and editing there cannot
touch the running system. The layer is then exactly the set of affected files:
it is shown to the user, applied to the real root on approval, with the replaced
files kept so that the change can be undone.

/boot is a separate filesystem that an overlay cannot sit on, so the sandbox gets
a copy of it instead (it is small): a kernel or initramfs built there is listed,
applied and undone like any other file. The files of the safe start-up mechanism
(mentor_boot) are not in the copy.

There can be several sandboxes at once, one per conversation with the agent, each
with its own layer. They do not outlive a reboot.

Runs as root, called from mentor_core.
"""
import difflib
import json
import os
import re
import shutil
import stat
import subprocess
import time

STATE = "/var/lib/mentor"
IMAGE = f"{STATE}/sandbox.img"
# The layers live on their own filesystem: overlayfs refuses an upper directory
# that sits inside the lower one, and "/" contains everything else.
MOUNT = f"{STATE}/sandbox"
# One helper process works on one sandbox; use() points these at it.
NAME = HOME = UPPER = WORK = MERGED = CREATED = BOOT_COPY = None
BOOT = "/boot"
# Never copied, listed or applied: what a failed start falls back on.
BOOT_KEPT_OUT = ("mentor", "loader/random-seed", "loader/entries/mentor.conf", "loader/entries/mentor-trial.conf")
CHANGES = f"{STATE}/changes"
IMAGE_SIZE = "24G"  # sparse; only what the sandbox writes takes space

# Written by almost any command and of no interest to the real system.
IGNORED = (
    "tmp/", "run/", "var/tmp/", "var/cache/", "var/log/", "var/lib/systemd/", "var/lib/pacman/sync/",
    "var/lib/mentor/", "root/.cache/", "root/.bash_history", "etc/.pwd.lock", "etc/.updated", "var/.updated",
)
MAX_DIFF_BYTES = 256 * 1024
MAX_DIFF_LINES = 400
MAX_DIFFS = 80
MAX_ENTRIES = 2000


class SandboxError(Exception):
    pass


def _sh(*argv):
    subprocess.run(argv, check=True, stdin=subprocess.DEVNULL)


def use(name):
    """Select the sandbox the rest of this module works on."""
    global NAME, HOME, UPPER, WORK, MERGED, CREATED, BOOT_COPY
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise SandboxError(f"invalid sandbox name: {name!r}")
    NAME, HOME = name, f"{MOUNT}/{name}"
    UPPER, WORK, MERGED, CREATED = (f"{HOME}/{part}" for part in ("upper", "work", "merged", "created"))
    BOOT_COPY = f"{HOME}/boot"


def exists():
    return os.path.ismount(MERGED)


def ensure():
    """Create and mount the sandbox if there is none."""
    if exists():
        return
    os.makedirs(MOUNT, exist_ok=True)
    if not os.path.ismount(MOUNT):
        if not os.path.exists(IMAGE):
            _sh("truncate", "-s", IMAGE_SIZE, IMAGE)
            _sh("mkfs.ext4", "-q", "-F", IMAGE)
        _sh("mount", "-o", "loop", IMAGE, MOUNT)
    for other in os.listdir(MOUNT):  # layers left behind by a reboot
        stale = f"{MOUNT}/{other}"
        if other in (NAME, "lost+found") or os.path.ismount(f"{stale}/merged"):
            continue
        if os.path.isdir(stale):
            shutil.rmtree(stale, ignore_errors=True)
        else:
            os.remove(stale)
    for directory in (UPPER, WORK, MERGED):
        os.makedirs(directory, exist_ok=True)
    _mount_overlay(HOME)
    if os.path.ismount(BOOT):
        shutil.rmtree(BOOT_COPY, ignore_errors=True)
        shutil.copytree(BOOT, BOOT_COPY, ignore=_boot_kept_out)
    with open(CREATED, "w") as f:
        f.write(str(time.time()))


def _boot_kept_out(directory, names):
    base = os.path.relpath(directory, BOOT)
    return [n for n in names if os.path.normpath(os.path.join(base, n)) in BOOT_KEPT_OUT]


def _boot_copied():
    return BOOT_COPY is not None and os.path.isdir(BOOT_COPY)


def _source(rel):
    """Where the sandbox keeps its version of a path."""
    if _boot_copied() and rel.startswith("boot/"):
        return os.path.join(BOOT_COPY, rel[5:])
    return os.path.join(UPPER, rel)


def _unmount(mountpoint):
    if os.path.ismount(mountpoint) and subprocess.run(["umount", "-R", mountpoint]).returncode != 0:
        _sh("umount", "-Rl", mountpoint)  # something inside is still running


def discard():
    _unmount(MERGED)
    shutil.rmtree(HOME, ignore_errors=True)
    # With the last sandbox gone, give the disk space back.
    if os.path.ismount(MOUNT) and not [d for d in os.listdir(MOUNT) if d != "lost+found"]:
        _unmount(MOUNT)
    if not os.path.ismount(MOUNT) and os.path.exists(IMAGE):
        os.remove(IMAGE)


def _mount_overlay(home):
    _sh("mount", "-t", "overlay", "overlay", "-o",
        f"lowerdir=/,upperdir={home}/upper,workdir={home}/work", f"{home}/merged")


def refresh_others():
    """Let the other sandboxes see that the real system changed underneath them.

    An overlay remembers what it looked up in its lower layer, so each one is
    mounted afresh. One that is busy running a command is left as it is.
    """
    if not os.path.ismount(MOUNT):
        return
    for other in os.listdir(MOUNT):
        home = f"{MOUNT}/{other}"
        if home == HOME or not os.path.ismount(f"{home}/merged"):
            continue
        if subprocess.run(["umount", f"{home}/merged"], stderr=subprocess.DEVNULL).returncode == 0:
            _mount_overlay(home)


def command(shell_command, timeout):
    """The argv that runs a shell command as root inside the sandbox."""
    ensure()
    return [
        "timeout", "--kill-after=10", str(timeout),
        "systemd-nspawn", "--quiet", "--register=no", "--keep-unit", "--as-pid2", "--console=pipe",
        f"--machine=mentor-{NAME}",
        "--link-journal=no", "--timezone=off", "--setenv=HOME=/root",
        *([f"--bind={BOOT_COPY}:{BOOT}"] if _boot_copied() else []),
        "-D", MERGED, "bash", "-lc", shell_command,
    ]


# --- what changed ----------------------------------------------------------------

def _ignored(rel):
    return any(rel.startswith(prefix) for prefix in IGNORED) or "/__pycache__/" in f"/{rel}"


def _is_whiteout(st):
    return stat.S_ISCHR(st.st_mode) and st.st_rdev == 0


def _opaque(directory):
    """True for a directory the sandbox deleted and created again."""
    try:
        return os.getxattr(directory, "trusted.overlay.opaque") == b"y"
    except OSError:
        return False


def _same(a, b):
    """True when two existing paths are the same kind of thing with the same content and mode."""
    sa, sb = os.lstat(a), os.lstat(b)
    if stat.S_IFMT(sa.st_mode) != stat.S_IFMT(sb.st_mode) or sa.st_mode != sb.st_mode:
        return False
    if (sa.st_uid, sa.st_gid) != (sb.st_uid, sb.st_gid):
        return False
    if stat.S_ISLNK(sa.st_mode):
        return os.readlink(a) == os.readlink(b)
    if not stat.S_ISREG(sa.st_mode) or sa.st_size != sb.st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            chunk = fa.read(1 << 20)
            if chunk != fb.read(1 << 20):
                return False
            if not chunk:
                return True


def _same_content(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            chunk = fa.read(1 << 20)
            if chunk != fb.read(1 << 20):
                return False
            if not chunk:
                return True


def _scan_boot():
    """The same list for the copy of /boot. A FAT filesystem: only names and content count."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(BOOT_COPY):
        base = os.path.relpath(dirpath, BOOT_COPY)
        base = "" if base == "." else base + "/"
        for name in dirnames:
            if not os.path.isdir(os.path.join(BOOT, base + name)):
                entries.append((f"boot/{base}{name}/", "added"))
        for name in filenames:
            real = os.path.join(BOOT, base + name)
            if not os.path.isfile(real):
                entries.append((f"boot/{base}{name}", "added"))
            elif not _same_content(os.path.join(dirpath, name), real):
                entries.append((f"boot/{base}{name}", "modified"))
    for dirpath, dirnames, filenames in os.walk(BOOT):
        base = os.path.relpath(dirpath, BOOT)
        base = "" if base == "." else base + "/"
        for name in _boot_kept_out(dirpath, dirnames):
            dirnames.remove(name)
        for name in list(dirnames):
            if not os.path.isdir(os.path.join(BOOT_COPY, base + name)):
                entries.append((f"boot/{base}{name}/", "deleted"))
                dirnames.remove(name)
        for name in filenames:
            if not _boot_kept_out(dirpath, [name]) and not os.path.isfile(os.path.join(BOOT_COPY, base + name)):
                entries.append((f"boot/{base}{name}", "deleted"))
    return entries


def scan():
    """The affected paths as (relative path, kind), parents before children.

    kind: added | modified | deleted | replaced (a directory swapped for a new one).
    Directories carry a trailing slash.
    """
    if not exists():
        return []
    entries = []
    for dirpath, dirnames, filenames in os.walk(UPPER):
        base = os.path.relpath(dirpath, UPPER)
        base = "" if base == "." else base + "/"
        for name in sorted(dirnames):
            rel, full, real = base + name, os.path.join(dirpath, name), "/" + base + name
            if os.path.islink(full):
                filenames.append(name)  # a link to a directory is a file to us
                dirnames.remove(name)
            elif _ignored(rel + "/") or (rel == "boot" and _boot_copied()):
                dirnames.remove(name)
            elif not os.path.lexists(real):
                entries.append((rel + "/", "added"))
            elif _opaque(full) or os.path.islink(real) or not os.path.isdir(real):
                entries.append((rel + "/", "replaced"))
                dirnames.remove(name)  # applied and undone as one tree
        for name in sorted(filenames):
            rel, full = base + name, os.path.join(dirpath, name)
            if _ignored(rel):
                continue
            real = "/" + rel
            if _is_whiteout(os.lstat(full)):
                if os.path.lexists(real):
                    entries.append((rel, "deleted"))
            elif not os.path.lexists(real):
                entries.append((rel, "added"))
            elif not _same(full, real):
                entries.append((rel, "modified"))
    if _boot_copied():
        entries += _scan_boot()
    return sorted(entries)


def _text(path):
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_DIFF_BYTES:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _diff(rel, kind):
    if rel.endswith("/"):
        return None
    old = _text("/" + rel) if kind != "added" else []
    new = _text(_source(rel)) if kind != "deleted" else []
    if old is None or new is None:
        return None
    lines = list(difflib.unified_diff(old, new, "before", "after", lineterm="", n=2))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... {len(lines) - MAX_DIFF_LINES} more lines"]
    return "\n".join(lines)


def report():
    """Everything the user and the agent need to judge the change, as a dict."""
    entries = scan()
    counts = {}
    for _, kind in entries:
        counts[kind] = counts.get(kind, 0) + 1
    listed, diffs = [], 0
    for rel, kind in entries[:MAX_ENTRIES]:
        item = {"path": "/" + rel, "kind": kind}
        if diffs < MAX_DIFFS:
            diff = _diff(rel, kind)
            if diff:
                item["diff"] = diff
                diffs += 1
        listed.append(item)
    return {"exists": exists(), "counts": counts, "entries": listed, "omitted": len(entries) - len(listed)}


# --- applying and undoing --------------------------------------------------------

def _own(path, st, follow=True):
    """Give a copy the owner and mode of its original; /boot (FAT) has neither."""
    try:
        os.chown(path, st.st_uid, st.st_gid, follow_symlinks=follow)
        if follow:
            os.chmod(path, stat.S_IMODE(st.st_mode))
    except PermissionError:
        if not path.startswith(BOOT + "/"):
            raise


def _copy(src, dst):
    """Copy one file, link or directory (not its content) with owner, mode and capabilities."""
    st = os.lstat(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(dst) and not os.path.islink(dst) and not stat.S_ISDIR(st.st_mode):
        shutil.rmtree(dst)
    if stat.S_ISLNK(st.st_mode):
        if os.path.lexists(dst):
            os.remove(dst)
        os.symlink(os.readlink(src), dst)
        _own(dst, st, follow=False)
    elif stat.S_ISDIR(st.st_mode):
        if os.path.lexists(dst) and (os.path.islink(dst) or not os.path.isdir(dst)):
            os.remove(dst)
        os.makedirs(dst, exist_ok=True)
        _own(dst, st)
    elif stat.S_ISREG(st.st_mode):
        temporary = dst + ".mentor-new"  # replaced in one step, so running programs keep the old file
        shutil.copyfile(src, temporary)
        _own(temporary, st)
        for name in os.listxattr(src):
            if name.startswith("security.") and not dst.startswith(BOOT + "/"):
                os.setxattr(temporary, name, os.getxattr(src, name))
        os.utime(temporary, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(temporary, dst)


def _copy_tree(src, dst):
    _copy(src, dst)
    if os.path.isdir(src) and not os.path.islink(src):
        for name in os.listdir(src):
            _copy_tree(os.path.join(src, name), os.path.join(dst, name))


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _protected(rel, protected):
    path = "/" + rel.rstrip("/")
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in protected)


def apply(summary, protected):
    """Copy the sandbox's changes onto the real system and record how to undo them."""
    entries = scan()
    skipped = [rel for rel, _ in entries if _protected(rel, protected)]
    entries = [(rel, kind) for rel, kind in entries if not _protected(rel, protected)]
    if not entries:
        raise SandboxError("the sandbox has no changes to apply")

    with open(CREATED) as f:
        created = float(f.read())
    stale = [rel for rel, kind in entries
             if kind != "added" and not rel.endswith("/") and os.path.lexists("/" + rel)
             and os.lstat("/" + rel).st_mtime > created]
    if stale:
        raise SandboxError("these files changed on the real system after the sandbox was made; "
                           "discard it and redo the work: " + ", ".join("/" + s for s in stale[:20]))

    change_id = time.strftime("%Y%m%d-%H%M%S")
    record = os.path.join(CHANGES, change_id)
    before = os.path.join(record, "before")
    os.makedirs(before, mode=0o700)
    os.chmod(CHANGES, 0o755)
    os.chmod(record, 0o755)

    for rel, kind in entries:
        real, new = "/" + rel.rstrip("/"), _source(rel.rstrip("/"))
        if kind != "added" and os.path.lexists(real):
            _copy_tree(real, os.path.join(before, rel.rstrip("/")))
        if kind in ("deleted", "replaced"):
            _remove(real)
        if kind == "replaced":
            _copy_tree(new, real)
        elif kind in ("added", "modified"):
            _copy(new, real)

    manifest = {"id": change_id, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary,
                "state": "applied", "entries": entries, "skipped": skipped}
    with open(os.path.join(record, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    discard()
    refresh_others()
    return manifest


def changes():
    """Recorded changes, newest first."""
    found = []
    if os.path.isdir(CHANGES):
        for change_id in sorted(os.listdir(CHANGES), reverse=True):
            try:
                with open(os.path.join(CHANGES, change_id, "manifest.json")) as f:
                    found.append(json.load(f))
            except (OSError, ValueError):
                pass
    return found


def undo(change_id):
    record = os.path.join(CHANGES, os.path.basename(change_id))
    path = os.path.join(record, "manifest.json")
    if not os.path.isfile(path):
        raise SandboxError(f"there is no recorded change {change_id!r}")
    with open(path) as f:
        manifest = json.load(f)
    if manifest["state"] != "applied":
        raise SandboxError(f"change {change_id} was already undone")
    # Take away what the change put there, children first, then put the old files back.
    for rel, kind in sorted(manifest["entries"], reverse=True):
        real = "/" + rel.rstrip("/")
        if kind == "added" and rel.endswith("/"):
            if os.path.isdir(real) and not os.listdir(real):
                os.rmdir(real)
        elif kind != "deleted":
            _remove(real)
    before = os.path.join(record, "before")
    for rel, kind in sorted(manifest["entries"]):
        saved = os.path.join(before, rel.rstrip("/"))
        if kind != "added" and os.path.lexists(saved):
            _copy_tree(saved, "/" + rel.rstrip("/"))
    manifest["state"] = "undone"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=1)
    refresh_others()
    return manifest
