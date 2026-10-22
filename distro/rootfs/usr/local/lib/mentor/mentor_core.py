"""Privileged side of the Mentor agent layer.

Runs as root, only through pkexec, so every call has been approved by the user
in the polkit dialog. Validates the request against /etc/mentor/policy.toml,
executes it and appends a record to the audit log.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib

import mentor_apps
import mentor_boot
import mentor_sandbox

POLICY_PATH = "/etc/mentor/policy.toml"
AUDIT_PATH = "/var/log/mentor/audit.log"
BACKUP_ROOT = "/var/lib/mentor/backups"
MAX_FILE_BYTES = 1 << 20
# Never writable through the agent, whatever policy.toml says: the layer that
# keeps the agent in check, and the files that decide who is root.
ALWAYS_PROTECTED = (
    "/etc/mentor", "/usr/local/lib/mentor", "/usr/local/bin/mentor", "/usr/local/bin/mentor-mcp",
    "/usr/share/polkit-1", "/etc/polkit-1", "/etc/sudoers", "/etc/sudoers.d",
    "/etc/shadow", "/etc/gshadow", "/etc/passwd", "/etc/group", "/var/log/mentor", "/var/lib/mentor",
    # What a failed start falls back on (mentor_boot): the working kernel and the units that check.
    "/boot/mentor", "/boot/loader/entries/mentor.conf", "/boot/loader/entries/mentor-trial.conf",
    *(f"/usr/local/lib/systemd/system/mentor-boot-{unit}" for unit in
      ("check.service", "deadline.service", "confirm.path", "confirm.service", "arm.service")),
    *(f"/etc/systemd/system/{target}.wants/mentor-boot-{unit}" for target, unit in
      (("sysinit.target", "check.service"), ("sysinit.target", "deadline.service"),
       ("multi-user.target", "confirm.path"), ("multi-user.target", "arm.service"))),
    "/etc/pacman.d/hooks/zz-mentor-boot.hook", "/etc/tmpfiles.d/mentor.conf",
    # The way back in when the desktop is gone (mentor repair).
    "/usr/local/lib/systemd/system/mentor-repair.target", "/usr/local/lib/systemd/system/mentor-repair-console.service",
    "/etc/profile.d/mentor-repair.sh",
    # Who asks for the password, and with which words (mentor-rootd).
    "/usr/local/lib/systemd/system/mentor-root.socket", "/usr/local/lib/systemd/system/mentor-root@.service",
    "/etc/systemd/system/sockets.target.wants/mentor-root.socket",
    # Updates of Mentor itself: what installs them and what checks who signed them (UPDATES.md).
    "/usr/local/lib/systemd/system/mentor-update-check.service", "/usr/local/lib/systemd/system/mentor-update-check.timer",
    "/usr/local/lib/systemd/system/mentor-update-apply.service", "/etc/systemd/system/timers.target.wants/mentor-update-check.timer",
)

# Changes under these (relative to /) only show at the next restart.
STARTUP_PATHS = ("boot/", "etc/kernel/", "etc/mkinitcpio", "etc/modprobe.d/", "etc/modules-load.d/",
                 "usr/lib/modules/", "etc/fstab")

PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9@._+-]*$")
UNIT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9@._:\\-]*$")
SERVICE_OPS = {"start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask"}
DISRUPTIVE_OPS = {"stop", "disable", "mask"}


class Denied(Exception):
    pass


def load_policy():
    try:
        with open(POLICY_PATH, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def audit(action, args, outcome, exit_code=None, seconds=None):
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "uid": os.environ.get("PKEXEC_UID"),
        "action": action,
        "args": args,
        "outcome": outcome,
        "exit_code": exit_code,
        "seconds": seconds,
    }
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def packages(args):
    names = args.get("packages")
    if not isinstance(names, list) or not names:
        raise Denied("'packages' must be a non-empty list")
    for name in names:
        if not isinstance(name, str) or not PKG_RE.match(name):
            raise Denied(f"invalid package name: {name!r}")
    return names


def pkg_install(args, policy):
    return ["pacman", "-S", "--noconfirm", "--needed", "--", *packages(args)]


# Said whenever something of Mentor's would go: the agent passes it on, and does not look for another way.
PART_OF_MENTOR = ("{} came with Mentor and cannot be uninstalled: Mentor needs it (etc/mentor/UNINSTALL.md). "
                  "Tell the user so in one plain sentence; do not try another way.")


def pkg_remove(args, policy):
    names = packages(args)
    protected = set(policy.get("packages", {}).get("protected", []))
    blocked = sorted(protected.intersection(names))
    if blocked:
        raise Denied(f"protected packages cannot be removed: {', '.join(blocked)}")
    # Everything pacman would take with them (-s), checked against Mentor's packages and all they need.
    went = subprocess.run(["pacman", "-Rnsp", "--print-format", "%n", "--", *names], capture_output=True, text=True,
                          env={**os.environ, "LC_ALL": "C"})
    blocked = sorted(mentor_apps.protected_packages().intersection(went.stdout.split() if went.returncode == 0 else names))
    if blocked:
        raise Denied(PART_OF_MENTOR.format(", ".join(blocked)))
    return ["pacman", "-Rns", "--noconfirm", "--", *names]


# The last line system_upgrade prints when the initramfs was not made (mentor_tools reads it).
INITCPIO_FAILED = "[mentor: the initramfs was not made]"


def _initcpio_made(lines):
    text = "".join(lines)
    return bool(re.search(r"(?i)image generation successful", text)) and not re.search(r"==> ERROR|command failed", text)


def _pacman_watched(argv):
    """Run pacman with its output passed on as it comes. Returns (exit code, whether mkinitcpio's
    hook ran, whether every image it made says it was made)."""
    ran = made = False
    section = None
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          cwd="/", text=True, errors="replace", env={**os.environ, "LC_ALL": "C"}) as p:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if "Updating linux initcpios" in line:
                ran, section = True, []
            elif section is not None and re.match(r"^\(\s*\d+/\d+\) ", line):  # the next hook
                made, section = made or _initcpio_made(section), None
            elif section is not None:
                section.append(line)
    if section is not None:  # it was the last hook
        made = made or _initcpio_made(section)
    return p.returncode, ran, made


def system_upgrade(args, policy):
    # The signing keys first (as Omarchy's omarchy-update-keyring): a Mentor that sat unused for
    # months otherwise stops at "invalid or corrupted package (PGP signature)". The full -Su
    # follows in the same run, so the refreshed databases never leave a partial upgrade.
    print("Refreshing the signing keys (archlinux-keyring)...", flush=True)
    code = subprocess.run(["pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring"],
                          stdin=subprocess.DEVNULL, cwd="/").returncode
    if code != 0:
        print("mentor: the signing keys (archlinux-keyring) could not be refreshed. Nothing was upgraded.", flush=True)
        return code
    code, ran, made = _pacman_watched(["pacman", "-Su", "--noconfirm"])
    # As Omarchy's omarchy-update-analyze-logs: an initramfs that was not made does not start.
    if ran and not made:
        print(INITCPIO_FAILED, flush=True)
    return code


def service(args, policy):
    unit, op = args.get("unit"), args.get("operation")
    if not isinstance(unit, str) or not UNIT_RE.match(unit):
        raise Denied(f"invalid unit name: {unit!r}")
    if op not in SERVICE_OPS:
        raise Denied(f"operation must be one of: {', '.join(sorted(SERVICE_OPS))}")
    if "." not in unit:
        unit += ".service"
    protected = policy.get("services", {}).get("protected", [])
    if op in DISRUPTIVE_OPS and unit in protected:
        raise Denied(f"{unit} is protected against '{op}'")
    return ["systemctl", op, "--", unit]


def run_root(args, policy):
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise Denied("'command' must be a non-empty string")
    shell = policy.get("root_shell", {})
    if not shell.get("enabled", True):
        raise Denied("root shell is disabled in /etc/mentor/policy.toml")
    for pattern in shell.get("deny_patterns", []):
        if re.search(pattern, command):
            raise Denied(f"command matches deny pattern {pattern!r}")
    # A package of Mentor's taken away by hand (pacman -R, -Rdd...): a net, as the patterns are; the
    # sandbox's check (sandbox_apply) is the one that holds.
    removals = [m.group(1) for m in re.finditer(r"\bpacman\b([^;&|\n]*)", command)
                if re.search(r"\s(-R\w*|--remove)\b", m.group(1))]
    if removals:
        words = {w for part in removals for w in part.split() if not w.startswith("-")}
        blocked = sorted(mentor_apps.protected_packages().intersection(words))
        if blocked:
            raise Denied(PART_OF_MENTOR.format(", ".join(blocked)))
    return ["bash", "-c", command]


def system_path(args, policy):
    """The validated absolute path a file action may touch."""
    path = args.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise Denied("'path' must be an absolute path")
    path = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    if os.path.islink(path):
        path = os.path.realpath(path)
    for prefix in protected_paths(policy):
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            raise Denied(f"{path} is protected and cannot be changed by the agent")
    if os.path.isdir(path):
        raise Denied(f"{path} is a directory")
    return path


def backups_of(path):
    """Backup copies of a file, oldest first."""
    if not os.path.isdir(BACKUP_ROOT):
        return []
    copies = [os.path.join(BACKUP_ROOT, stamp, path.lstrip("/")) for stamp in sorted(os.listdir(BACKUP_ROOT))]
    return [c for c in copies if os.path.isfile(c)]


def replace_file(path, data, like=None):
    """Write atomically, keeping the owner and mode of the file being replaced."""
    like = like or (path if os.path.exists(path) else None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.mentor-new"
    with open(temporary, "wb") as f:
        f.write(data)
    if like:
        st = os.stat(like)
        os.chown(temporary, st.st_uid, st.st_gid)
        os.chmod(temporary, st.st_mode & 0o7777)
    else:
        os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def write_file(args, policy):
    path = system_path(args, policy)
    data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise Denied(f"content is larger than {MAX_FILE_BYTES} bytes")
    if os.path.exists(path):
        backup = os.path.join(BACKUP_ROOT, time.strftime("%Y%m%d-%H%M%S"), path.lstrip("/"))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(path, backup)
        print(f"previous version saved; file_restore brings it back")
    replace_file(path, data)
    print(f"wrote {len(data)} bytes to {path}")
    return 0


def restore_file(args, policy):
    path = system_path(args, policy)
    copies = backups_of(path)
    if not copies:
        raise Denied(f"there is no backup of {path}")
    with open(copies[-1], "rb") as f:
        replace_file(path, f.read(), like=copies[-1])
    os.remove(copies[-1])  # so that a second restore goes one step further back
    print(f"restored {path} from the backup of {copies[-1].split('/')[5]}")
    return 0


def protected_paths(policy):
    return (*ALWAYS_PROTECTED, *policy.get("files", {}).get("protected", []))


def sandbox_run(args, policy):
    mentor_sandbox.use(args.get("sandbox", "default"))
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise Denied("'command' must be a non-empty string")
    timeout = min(max(int(args.get("timeout", 600)), 10), 7200)
    return mentor_sandbox.command(command, timeout)


def sandbox_changes(args, policy):
    mentor_sandbox.use(args.get("sandbox", "default"))
    print(json.dumps(mentor_sandbox.report()))
    return 0


def sandbox_discard(args, policy):
    mentor_sandbox.use(args.get("sandbox", "default"))
    mentor_sandbox.discard()
    print("sandbox discarded")
    return 0


def _takes_mentor_away():
    """What of Mentor's the sandbox's changes would remove: its packages (their pacman database folders
    deleted) and its own files (MANIFEST.sha256). Mentor's updates apply their own sandbox, not this way."""
    gone = [rel for rel, kind in mentor_sandbox.scan() if kind in ("deleted", "replaced")]
    if not gone:
        return []
    keep, files = mentor_apps.protected_packages(), mentor_apps.mentor_files()
    found = set()
    for rel in gone:
        package = mentor_apps.package_of_dir(rel)
        if package in keep:
            found.add(package)
        path = "/" + rel.rstrip("/")
        if rel.endswith("/") or os.path.isdir(path):
            # a directory deleted or swapped for another: the files of Mentor's in it went with it, or may have
            changed = [f for f in files if f.startswith(path + "/") and
                       not os.path.lexists(os.path.join(mentor_sandbox.MERGED, f.lstrip("/")))]
            found.update(changed)
        elif path in files:
            found.add(path)
    return sorted(found)


def sandbox_apply(args, policy):
    mentor_sandbox.use(args.get("sandbox", "default"))
    gone = _takes_mentor_away()
    if gone:
        more = f" and {len(gone) - 8} more" if len(gone) > 8 else ""
        raise Denied(PART_OF_MENTOR.format(", ".join(gone[:8]) + more) +
                     " Put them back in the sandbox (or sandbox_discard) and apply only the rest.")
    manifest = mentor_sandbox.apply(str(args.get("summary", "")), protected_paths(policy))
    print(f"applied change {manifest['id']}: {len(manifest['entries'])} paths")
    if manifest["skipped"]:
        print("not applied, protected: " + ", ".join("/" + s for s in manifest["skipped"][:20]))
    mentor_boot.record_change(manifest["id"])
    if any(rel.startswith(STARTUP_PATHS) for rel, _ in manifest["entries"]):
        print("This change is part of how the system starts, so it takes effect at the next restart "
              "(system_restart). That start is a trial: if the desktop is not up within three minutes, "
              "the change is undone by itself and the system starts as before.")
    return 0


def change_undo(args, policy):
    manifest = mentor_sandbox.undo(str(args.get("id", "")))
    mentor_boot.forget_change(manifest["id"])
    print(f"undid change {manifest['id']}: {len(manifest['entries'])} paths put back")
    return 0


ACTIONS = {
    "manage": {
        "pkg_install": pkg_install,
        "pkg_remove": pkg_remove,
        "system_upgrade": system_upgrade,
        "service": service,
    },
    # Each of these asks for the password every time: editing a system file is as powerful as a
    # root shell. They are separate doors so that the password dialog can say which it is.
    "shell": {"run_root": run_root},
    "write": {"write_file": write_file, "restore_file": restore_file},
    "apply": {"sandbox_apply": sandbox_apply},
    "undo": {"change_undo": change_undo},
    # Work inside the sandbox cannot reach the real system.
    "sandbox": {"sandbox_run": sandbox_run, "sandbox_changes": sandbox_changes, "sandbox_discard": sandbox_discard},
}


def main(mode):
    # PKEXEC_UID is set by pkexec, and by Mentor's own root service (mentor-rootd), which asks
    # the user the same way: either way the user has approved this request.
    if os.geteuid() != 0 or "PKEXEC_UID" not in os.environ:
        print("mentor: this helper only runs through pkexec", file=sys.stderr)
        return 2
    if len(sys.argv) != 3:
        print("usage: <action> <json-args>", file=sys.stderr)
        return 2
    action = sys.argv[1]
    try:
        args = json.loads(sys.argv[2])
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError as e:
        print(f"mentor: bad arguments: {e}", file=sys.stderr)
        return 2

    try:
        build = ACTIONS[mode].get(action)
        if build is None:
            raise Denied(f"unknown action {action!r}")
        started = time.monotonic()
        todo = build(args, load_policy())  # a command to run, or the exit code of work already done
    except Denied as e:
        audit(action, args, f"denied: {e}")
        print(f"mentor: denied by policy: {e}", file=sys.stderr)
        return 3
    except (OSError, subprocess.CalledProcessError, mentor_sandbox.SandboxError, shutil.Error) as e:
        audit(action, args, f"failed: {e}")
        print(f"mentor: {e}", file=sys.stderr)
        return 1

    code = todo if isinstance(todo, int) else subprocess.run(todo, stdin=subprocess.DEVNULL, cwd="/").returncode
    audit(action, args, "executed", code, round(time.monotonic() - started, 1))
    return code
