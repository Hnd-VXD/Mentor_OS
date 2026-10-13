"""Starting up safely after a change.

The agent may change anything a start depends on: the kernel, its parameters,
the initramfs, modules, the desktop. So a start is never trusted before it has
been seen to work:

- The default boot entry only ever points at a kernel and initramfs that have
  reached the desktop: a copy under /boot/mentor, with that kernel's modules kept
  aside. What pacman or the agent put at the usual place (/boot/vmlinuz-linux,
  /boot/initramfs-linux.img, /etc/kernel/cmdline) is the candidate. A candidate
  that differs is started once, through a one-shot boot entry; when it reaches
  the desktop it becomes the new copy, and when it does not the next start is
  the default again by itself.
- The changes applied through the sandbox since the last good start are on
  trial too. A start that tries something gets three minutes to show the
  desktop; when it fails, the next start undoes those changes before anything
  else runs, and restarts.

"Reached the desktop" is the mentor shell extension putting the assistant on it
(it creates DESKTOP_OK). The state lives in STATE; the launcher on the host is
told how each start went, for its own restore points (see launcher/Mentor.cs).

Runs as root: from the mentor-boot-* units, a pacman hook and mentor_core.
"""
import fcntl
import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

STATE_DIR = "/var/lib/mentor/boot"
STATE = f"{STATE_DIR}/state.json"
RESTORED = f"{STATE_DIR}/restored.json"  # what the last automatic restore did, for the assistant
FELL_BACK = f"{STATE_DIR}/fell-back"     # the next start is the one after a restore: it shows the other emblem
MODULES = f"{STATE_DIR}/modules"
AUDIT_PATH = "/var/log/mentor/audit.log"
ESP = "/boot"
GOOD_ROOT = f"{ESP}/mentor"
ENTRIES = f"{ESP}/loader/entries"
LOADER_CONF = f"{ESP}/loader/loader.conf"
DEFAULT_ENTRY, TRIAL_ENTRY = "mentor.conf", "mentor-trial.conf"
CMDLINE = "/etc/kernel/cmdline"
# Optional "kernel=/boot/..." and "initrd=/boot/..." lines, for a kernel other than the stock one.
CANDIDATE_CONF = "/etc/kernel/mentor-boot.conf"
CANDIDATE_DEFAULT = {"kernel": f"{ESP}/vmlinuz-linux", "initrd": f"{ESP}/initramfs-linux.img"}
# Only on the entry that tries something: a kernel that panics restarts by itself.
TRIAL_OPTIONS = "mentor.trial=1 panic=20"
DESKTOP_OK = "/run/mentor/desktop-ok"
DEADLINE = 180
EFIVARS = "/sys/firmware/efi/efivars"
LOADER_GUID = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
HOST_PORT = "org.mentor.control"
# How much the host's screen is scaled (2 on a 200% display), as the launcher passes it in;
# the desktop is scaled to match (`mentor scale`), so that it is drawn at the screen's own resolution.
HOST_SCALE_IN = "/sys/firmware/qemu_fw_cfg/by_name/opt/mentor/scale/raw"
HOST_SCALE = "/run/mentor/host-scale"
FRESH = {"phase": "ok", "attempts": 0, "changes": [], "kernel": False, "candidate": None,
         "failed": [], "reason": None, "good": None}


# --- state -------------------------------------------------------------------------

def _write(path, text):
    """Replace a file so that a power cut leaves the old or the new one, never half."""
    temporary = path + ".new"
    with open(temporary, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def load():
    try:
        with open(STATE) as f:
            return {**FRESH, **json.load(f)}
    except (OSError, ValueError):
        return dict(FRESH)


def save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    _write(STATE, json.dumps(state, indent=1))
    os.chmod(STATE, 0o644)


def _locked():
    os.makedirs(STATE_DIR, exist_ok=True)
    lock = open(f"{STATE_DIR}/lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def _audit(action, details):
    record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "uid": None, "action": action, "args": details,
              "outcome": "executed", "exit_code": 0, "seconds": None}
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        with open(AUDIT_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _trial_boot():
    with open("/proc/cmdline") as f:
        return "mentor.trial=1" in f.read().split()


def _live():
    """False in a container or a chroot: the sandbox and the image build are not a start-up."""
    return os.path.isdir("/run/systemd/system") and "container" not in os.environ and \
        subprocess.run(["systemd-detect-virt", "--container", "--quiet"]).returncode != 0


# --- the boot partition --------------------------------------------------------------

def _efivar(name):
    path = f"{EFIVARS}/{name}-{LOADER_GUID}"
    try:
        with open(path, "rb") as f:
            return f.read()[4:].decode("utf-16-le").rstrip("\0")
    except OSError:
        return None


def _set_efivar(name, value):
    """Set (or with None, delete) one of the boot loader's variables. False where there is no UEFI."""
    path = f"{EFIVARS}/{name}-{LOADER_GUID}"
    try:
        if os.path.exists(path):
            subprocess.run(["chattr", "-i", path], stderr=subprocess.DEVNULL)
            os.remove(path)
        if value is not None:
            # Non-volatile, visible to the loader and to us; efivarfs wants it in one write.
            with open(path, "wb", buffering=0) as f:
                f.write(struct.pack("<I", 7) + (value + "\0").encode("utf-16-le"))
        return True
    except OSError:
        return False


def mount_esp():
    """Make sure /boot is the boot partition. Needed when this runs before the system mounts it."""
    if os.path.ismount(ESP):
        return True
    device = None
    part = _efivar("LoaderDevicePartUUID")
    if part:
        device = subprocess.run(["blkid", "-t", f"PARTUUID={part.lower()}", "-o", "device"],
                                capture_output=True, text=True).stdout.strip()
    if device:
        return subprocess.run(["mount", device.splitlines()[0], ESP]).returncode == 0
    return subprocess.run(["mount", ESP], stderr=subprocess.DEVNULL).returncode == 0  # as fstab has it


def cmdline():
    try:
        with open(CMDLINE) as f:
            return " ".join(f.read().split())
    except OSError:  # an installation from before this file existed: what we were started with
        with open("/proc/cmdline") as f:
            words = [w for w in f.read().split() if not w.startswith("initrd=") and w not in TRIAL_OPTIONS.split()]
        return " ".join(words)


def candidate():
    """The kernel, initramfs and parameters that the next start should use if they work."""
    found = dict(CANDIDATE_DEFAULT)
    try:
        with open(CANDIDATE_CONF) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key in found and os.path.realpath(value).startswith(ESP + "/"):
                    found[key] = os.path.realpath(value)
    except OSError:
        pass
    found["cmdline"] = cmdline()
    return found


def fingerprint(found):
    """Identifies a candidate by content. None when it is not complete."""
    digest = hashlib.sha256(found["cmdline"].encode())
    try:
        for key in ("kernel", "initrd"):
            with open(found[key], "rb") as f:
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def kernel_version(path):
    """The release a kernel image reports (what its modules directory is called)."""
    try:
        with open(path, "rb") as f:
            f.seek(0x20E)
            offset = struct.unpack("<H", f.read(2))[0]
            f.seek(0x200 + offset)
            return f.read(256).split(b"\0")[0].decode().split()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return None


def _entry(name, title, kernel, initrd, options):
    os.makedirs(ENTRIES, exist_ok=True)
    _write(f"{ENTRIES}/{name}", f"title   {title}\nlinux   {kernel}\ninitrd  {initrd}\noptions {options}\n")


def _on_esp(path):
    return path[len(ESP):]


def _keep_modules(version):
    """Keep the modules of the kernel that works, whatever happens to /usr/lib/modules.

    Hard links: no space, and a package that is upgraded or removed leaves them alone.
    """
    source = f"/usr/lib/modules/{version}"
    os.makedirs(MODULES, exist_ok=True)
    if version and os.path.isdir(source):
        shutil.rmtree(f"{MODULES}/{version}", ignore_errors=True)
        subprocess.run(["cp", "-al", source, f"{MODULES}/{version}"], check=True)
    for other in os.listdir(MODULES):
        if other != version:
            shutil.rmtree(f"{MODULES}/{other}", ignore_errors=True)


def ensure_modules():
    """Give the running kernel its modules back if a change took them away."""
    version = os.uname().release
    if not os.path.isdir(f"/usr/lib/modules/{version}") and os.path.isdir(f"{MODULES}/{version}"):
        subprocess.run(["cp", "-al", f"{MODULES}/{version}", f"/usr/lib/modules/{version}"])


def promote(state, found, mark):
    """Make a candidate the one the default entry starts."""
    numbers = [int(d[5:]) for d in os.listdir(GOOD_ROOT) if d.startswith("good-") and d[5:].isdigit()] \
        if os.path.isdir(GOOD_ROOT) else []
    name = f"good-{max(numbers, default=0) + 1}"
    os.makedirs(f"{GOOD_ROOT}/{name}")
    for key, target in (("kernel", "vmlinuz"), ("initrd", "initramfs.img")):
        shutil.copyfile(found[key], f"{GOOD_ROOT}/{name}/{target}")
    os.sync()
    # Only now does the default entry change, and only after that does the old copy go.
    _entry(DEFAULT_ENTRY, "Mentor", f"/mentor/{name}/vmlinuz", f"/mentor/{name}/initramfs.img", found["cmdline"])
    version = kernel_version(found["kernel"])
    _keep_modules(version)
    for other in os.listdir(GOOD_ROOT):
        if other != name:
            shutil.rmtree(f"{GOOD_ROOT}/{other}", ignore_errors=True)
    state["good"] = {"dir": name, "hash": mark, "version": version, "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def _default_is_ours():
    """The loader must keep starting the entry that is known to work."""
    try:
        with open(LOADER_CONF) as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    wanted = f"default {DEFAULT_ENTRY}"
    if wanted not in [" ".join(line.split()) for line in lines]:
        kept = [line for line in lines if not line.split() or line.split()[0] != "default"]
        _write(LOADER_CONF, "\n".join([wanted, *kept]) + "\n")


# --- talking to the launcher on the host ---------------------------------------------

def tell_host(message, tries=1):
    """Best effort; there is no launcher on a real machine."""
    line = (json.dumps(message) + "\n").encode()
    subprocess.run(["modprobe", "-q", "virtio_console"], stderr=subprocess.DEVNULL)
    for attempt in range(tries * 10):
        if not os.path.isdir("/sys/class/virtio-ports"):
            return False
        for port in glob.glob("/sys/class/virtio-ports/*"):
            try:
                with open(f"{port}/name") as f:
                    if f.read().strip() != HOST_PORT:
                        continue
                fd = os.open("/dev/" + os.path.basename(port), os.O_WRONLY | os.O_NONBLOCK)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
                return True
            except OSError:  # not there yet, or someone else has it open right now
                pass
        time.sleep(0.2)
    return False


def _fallback_emblem():
    """Have the boot screen show its second emblem: this start is putting things back."""
    subprocess.run(["plymouth", "display-message", "--text=mentor-fallback"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _host_scale():
    """Pass on the scale of the host's screen, if the launcher gave one."""
    subprocess.run(["modprobe", "-q", "qemu_fw_cfg"], stderr=subprocess.DEVNULL)
    try:
        with open(HOST_SCALE_IN) as f:
            scale = float(f.read().strip().strip("\0"))
        os.makedirs(os.path.dirname(HOST_SCALE), exist_ok=True)
        os.chmod(os.path.dirname(HOST_SCALE), 0o1777)
        with open(HOST_SCALE, "w") as f:
            f.write(f"{scale:g}\n")
        os.chmod(HOST_SCALE, 0o644)
    except (OSError, ValueError):
        pass


def _restart():
    os.sync()
    subprocess.run(["systemctl", "reboot", "--force", "--force"])
    time.sleep(30)


# --- the steps -----------------------------------------------------------------------

def arm(state=None):
    """Work out what the next start has to prove, and point the loader at it."""
    if not _live():
        return 0
    lock = _locked()
    state = state or load()
    if state["phase"] == "running" or not state["good"] or not mount_esp():
        return 0  # a trial is under way, or there is nothing to fall back to yet
    found = candidate()
    mark = fingerprint(found)
    kernel = bool(mark) and mark != state["good"]["hash"] and mark not in state["failed"]
    if kernel:
        _entry(TRIAL_ENTRY, "Mentor (trying a change)", _on_esp(found["kernel"]), _on_esp(found["initrd"]),
               f"{found['cmdline']} {TRIAL_OPTIONS}")
        kernel = _set_efivar("LoaderEntryOneShot", TRIAL_ENTRY)
    elif state["kernel"]:
        _set_efivar("LoaderEntryOneShot", None)
    state.update(kernel=kernel, candidate=mark, attempts=0, reason=None,
                 phase="pending" if kernel or state["changes"] else "ok")
    save(state)
    lock.close()
    return 0


def record_change(change_id):
    """A change was applied through the sandbox: the next start is its trial."""
    state = load()
    state["changes"] = [c for c in state["changes"] if c != change_id] + [change_id]
    save(state)
    arm()


def forget_change(change_id):
    state = load()
    state["changes"] = [c for c in state["changes"] if c != change_id]
    save(state)
    arm()


def restore(state, why):
    """The start that tried something failed: put the system back as it last worked."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mentor_sandbox
    _fallback_emblem()
    open(FELL_BACK, "w").close()  # and so does the start that follows
    mount_esp()
    undone, kept = [], []
    for change_id in reversed(state["changes"]):
        try:
            manifest = mentor_sandbox.undo(change_id)
            undone.append({"id": change_id, "summary": manifest["summary"]})
        except Exception as e:  # one change that cannot be undone must not stop the others
            kept.append({"id": change_id, "error": str(e)})
    # A kernel that is still there after the undo came from outside the sandbox
    # (an upgrade): it stays installed but is not started again.
    held = False
    if state["kernel"]:
        mark = fingerprint(candidate())
        if mark and state["good"] and mark != state["good"]["hash"]:
            state["failed"] = (state["failed"] + [mark])[-10:]
            held = True
    _set_efivar("LoaderEntryOneShot", None)
    state.update(phase="ok", attempts=0, changes=[], kernel=False, reason=None)
    save(state)
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, "undone": undone, "not_undone": kept,
              "kernel_held": held}
    _write(RESTORED, json.dumps(report, indent=1))
    os.chmod(RESTORED, 0o644)
    _audit("boot_restore", report)
    if undone:
        # The files under the starting system changed: begin again from a clean slate.
        tell_host({"boot": "restoring"})
        _restart()


def check():
    """Early in every start: did the previous one, if it was a trial, make it?"""
    ensure_modules()
    _host_scale()
    # The launcher gives its window the size it is to have at this point, so that the
    # desktop, which comes later, starts in it.
    tell_host({"boot": "starting"})
    if os.path.exists(FELL_BACK):
        os.remove(FELL_BACK)
        _fallback_emblem()
    state = load()
    trial = _trial_boot()
    if state["phase"] == "running":
        if state["kernel"] and not trial:
            restore(state, "the new kernel or its start-up files did not reach the desktop")
        elif state["reason"] == "deadline" or state["attempts"] >= 2:
            restore(state, "the desktop did not come up after the last change")
        else:  # it may have been a power cut: once more
            state["attempts"] += 1
            save(state)
            tell_host({"boot": "trial"})
    elif state["phase"] == "pending":
        if state["kernel"] and not trial:
            restore(state, "the new kernel or its start-up files did not start")
        else:
            state.update(phase="running", attempts=1, reason=None)
            save(state)
            tell_host({"boot": "trial"})
    return 0


def _autologin():
    try:
        with open("/etc/gdm/custom.conf") as f:
            return any(line.replace(" ", "").lower() == "automaticloginenable=true" for line in f.read().splitlines())
    except OSError:
        return False


def deadline():
    """During a start that tries something: no desktop in time means it failed."""
    if load()["phase"] != "running":
        return 0
    started, greeter = time.monotonic(), None
    while time.monotonic() - started < DEADLINE:
        time.sleep(3)
        if os.path.exists(DESKTOP_OK) or load()["phase"] != "running":
            return 0
        # Without automatic login the login screen is as far as a start gets by itself.
        if not _autologin() and subprocess.run(["pgrep", "-x", "gnome-shell"], stdout=subprocess.DEVNULL).returncode == 0:
            greeter = greeter or time.monotonic()
            if time.monotonic() - greeter > 30:
                os.makedirs(os.path.dirname(DESKTOP_OK), exist_ok=True)
                open(DESKTOP_OK, "w").close()
                return 0
    state = load()
    if state["phase"] != "running":
        return 0
    state["reason"] = "deadline"
    save(state)
    _restart()
    return 1


def confirm():
    """The desktop is up: what this start tried has worked."""
    lock = _locked()
    state = load()
    if mount_esp():
        found = candidate()
        mark = fingerprint(found)
        tried = _trial_boot() and mark and mark == (state["candidate"] or mark)
        if mark and (tried or not state["good"]):
            promote(state, found, mark)
        _default_is_ours()
    if state["phase"] == "running":
        state.update(phase="ok", attempts=0, changes=[], kernel=False, reason=None)
    save(state)
    lock.close()
    arm()  # whatever changed in the meantime is for the start after this one
    tell_host({"boot": "ok"}, tries=5)
    return 0


def init():
    """When the image is built: the kernel it ships is the first one known to work."""
    state = dict(FRESH)
    found = candidate()
    promote(state, found, fingerprint(found))
    _default_is_ours()
    save(state)
    return 0


def status():
    state = load()
    report = {"state": state, "running_kernel": os.uname().release, "trial_start": _trial_boot()}
    try:
        with open(RESTORED) as f:
            report["last_restore"] = json.load(f)
    except (OSError, ValueError):
        pass
    print(json.dumps(report, indent=1))
    return 0


STEPS = {"check": check, "deadline": deadline, "confirm": confirm, "arm": arm, "init": init, "status": status}


def main(argv):
    if len(argv) != 1 or argv[0] not in STEPS:
        print(f"usage: mentor-boot {'|'.join(STEPS)}", file=sys.stderr)
        return 2
    if argv[0] != "status" and os.geteuid() != 0:
        print("mentor-boot: must run as root", file=sys.stderr)
        return 2
    return STEPS[argv[0]]()
