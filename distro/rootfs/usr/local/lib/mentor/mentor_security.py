"""Looking after the user's safety: three things, none of which needs a model.

1. The checks (`checks`): the firewall, the password everybody knows, remote login, root
   without a password, a second root account, keys other users can read. mentor-watch runs
   them and what they find becomes a card in the chat; the agent runs them on request
   (tool security_check, `mentor security`).

2. What the agent read from outside during the request it is working on (`saw`, `reads`):
   web pages, and files anyone could have put on the disk. Text like that can be written
   to steer a model. Each engine's reading is noted here as it happens, by the tools
   themselves and by the assistant for the engines' own tools.

3. The words shown before the password is asked (`before_root`): what is about to happen,
   in plain language, with a warning when it follows such reading. mentor-explain is the
   window; a text console gets the same as text.

See /etc/mentor/SECURITY.md.
"""
import json
import os
import re
import subprocess
import tempfile

import mentor_journal

EXPLAIN = "/usr/local/lib/mentor/mentor-explain"
KEYS = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mentor", "keys")
FIRST_PASSWORD = "admin"  # what every copy of Mentor starts with (distro/config.env when it was built)
MAX_READS = 12

# A command that brings text in from the network.
FETCHES = re.compile(r"(?<![\w.-])(curl|wget|git\s+(clone|pull|fetch)|lynx|w3m|links|aria2c|pip3?\s+install|npm\s+(i|install)|"
                     r"npx|yay|paru)(?![\w-])|https?://")
# A path in a command that is somebody's own file: in the home folder and not a hidden one.
HOME_FILE = re.compile(r"(?:~|/home/[^/\s'\"]+)/(?!\.)[^\s'\";|&<>)]+|/tmp/[^\s'\";|&<>)]+|/run/media/[^\s'\";|&<>)]+")


def _mark(conversation, suffix):
    return mentor_journal._request_path(conversation)[:-4] + suffix


def outside_file(path):
    """The real path of a file whose text is not to be trusted as instructions, or None.
    Not trusted: what any program of the user's, a download or an attachment could have put
    there (the home folder outside its hidden folders, temporary folders, plugged-in disks).
    Trusted: what only root can write (/etc, /usr, …) and the hidden folders programs keep
    their own settings in."""
    try:
        real = os.path.realpath(os.path.expanduser(str(path)))
    except (OSError, ValueError):
        return None
    home = os.path.realpath(os.path.expanduser("~"))
    if real.startswith(home + os.sep):
        return None if real[len(home) + 1:].startswith(".") else real
    return real if real.startswith(("/home/", "/tmp/", "/var/tmp/", "/run/media/", "/mnt/", "/media/")) else None


def classify(name, arguments):
    """[(kind, what)] for one tool call of any engine: kind "web" or "file", `what` the address,
    the search or the path. Empty for a call that reads nothing from outside. Goes by what the
    tool is called and what it is given, so that a tool nobody listed here is still caught."""
    low = str(name).lower()
    if isinstance(arguments, dict):
        values = [str(v) for v in arguments.values() if isinstance(v, (str, int, float))]
    else:
        values = [str(arguments or "")]
    given = " ".join(values)
    if isinstance(arguments, dict) and "command" not in arguments:  # the address or the search itself, when named
        named = [str(arguments[k]) for k in ("url", "Url", "query", "Query") if arguments.get(k)]
        given = named[0] if named else given
    found = []
    if any(word in low for word in ("web", "fetch", "url", "browse", "search_web", "http")):
        found.append(("web", given[:200] or low))
    elif any(word in low for word in ("shell", "bash", "command", "terminal", "exec")):
        if FETCHES.search(given):
            found.append(("web", given[:200]))
        found += [("file", real) for real in (outside_file(p) for p in HOME_FILE.findall(given)) if real]
    elif any(word in low for word in ("read", "view", "open", "cat", "grep", "glob", "list")):
        found += [("file", real) for real in (outside_file(v) for v in values if v.startswith(("/", "~"))) if real]
    return found[:4]


def saw(conversation, name, arguments):
    """Note what a tool call read from outside, for the request this conversation is on."""
    if not conversation:
        return
    found = classify(name, arguments)
    if not found:
        return
    try:
        known = reads(conversation)
        with open(_mark(conversation, ".read"), "a", encoding="utf-8") as f:
            for kind, what in found:
                if (kind, what) not in known and len(known) < MAX_READS:
                    f.write(json.dumps([kind, what], ensure_ascii=False) + "\n")
                    known.append((kind, what))
    except OSError:
        pass


def reads(conversation):
    """[(kind, what)] read from outside since the user's last message in this conversation."""
    found = []
    try:
        with open(_mark(conversation, ".read"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    kind, what = json.loads(line)
                    found.append((str(kind), str(what)))
                except (ValueError, TypeError):
                    pass
    except OSError:
        pass
    return found


def new_request(conversation):
    """The user said something new: what was read for the request before no longer counts,
    and what they were told then may be told again."""
    for suffix in (".read", ".asked"):
        try:
            os.remove(_mark(conversation, suffix))
        except OSError:
            pass


def said(found):
    """What was read, as a line or two for a person."""
    pages = [what for kind, what in found if kind == "web"]
    files = [what for kind, what in found if kind == "file"]
    parts = []
    if pages:
        parts.append("from the internet: " + "; ".join(p if len(p) <= 80 else p[:79] + "…" for p in pages[:3])
                     + (f" and {len(pages) - 3} more" if len(pages) > 3 else ""))
    if files:
        parts.append("files: " + ", ".join(files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else ""))
    return "; ".join(parts)


def _console(text, detail, warning):
    """The same on a text screen. Asks only when there is a warning: the password prompt that
    follows is itself the question."""
    try:
        with open("/dev/tty") as asked, open("/dev/tty", "w") as tty:
            tty.write(f"\n--- {text}\n")
            if detail:
                tty.write(f"    {detail}\n")
            if not warning:
                tty.write("    Next you are asked for your password. Type it only if this is what you wanted.\n")
                return 0
            tty.write(f"!!! {warning}\n")
            tty.write("Go on to the password? [y/N] ")
            tty.flush()
            return 0 if asked.readline().strip().lower() in ("y", "yes") else 1
    except OSError:
        return 0  # nowhere to say it: the password prompt still stands in the way


def before_root(conversation, door, text, detail=""):
    """Say in plain words what is about to be done as root, just before the password is asked.
    Returns (go on?, what was read from outside). `door` is which approval it is: "manage"
    and "sandbox" keep the password for a few minutes, so they are explained once for each
    request; "shell" asks every time and is explained every time. After reading from
    outside, every one is explained, with the warning.

    Nothing is shown for a tool called by hand (no conversation): whoever typed it knows."""
    if not conversation:
        return True, []
    # Work in the sandbox changes nothing real: its warning is in the preview of the change.
    found = [] if door == "sandbox" else reads(conversation)
    if door != "shell" and not found:
        try:
            with open(_mark(conversation, ".asked"), encoding="utf-8") as f:
                if door in f.read().split():
                    return True, found
        except OSError:
            pass
    warning = ""
    if found:
        warning = ("Just before this, Mentor read text that came from outside (" + said(found) + "). Such text "
                   "can be written to trick an assistant. Go on only if this is what you asked for.")
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="mentor-explain-", delete=False) as f:
            json.dump({"text": text, "detail": detail, "warning": warning}, f)
        try:
            code = subprocess.run([EXPLAIN, f.name], stdin=subprocess.DEVNULL, timeout=3600).returncode
        except subprocess.TimeoutExpired:
            code = 10  # nobody answered for an hour
        except OSError:
            code = 1
        finally:
            os.unlink(f.name)
        if code not in (0, 10):
            # The window could not be shown (10 is the user's no). The password prompt still
            # stands in the way; after outside reading that is not enough.
            code = 10 if warning else 0
    else:
        code = _console(text, detail, warning)
    if code == 0 and door != "shell":
        try:
            with open(_mark(conversation, ".asked"), "a", encoding="utf-8") as f:
                f.write(door + "\n")
        except OSError:
            pass
    return code == 0, found


# --- the checks -----------------------------------------------------------------

def _out(*argv, stdin=None, timeout=30):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                              **({"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}))
        return done.returncode, done.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def listening():
    """Ports that programs here wait on for connections from other computers: ["tcp 22 (sshd)", …]."""
    found = []
    for line in _out("ss", "-Htulnp")[1].splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        address, _, port = parts[4].rpartition(":")
        if address.strip("[]").startswith(("127.", "::1")) or "%lo" in address:
            continue
        program = re.search(r'\("([^"]+)"', line)
        found.append(f"{parts[0]} {port}" + (f" ({program.group(1)})" if program else ""))
    return sorted(set(found))


def firewall():
    """(on?, why not). On means: the service that loads the rules is running, and what comes
    in from other computers is refused unless a rule lets it in."""
    if _out("systemctl", "is-active", "--quiet", "nftables.service")[0] != 0:
        return False, "the service nftables is not running"
    try:
        with open("/etc/nftables.conf", errors="replace") as f:
            rules = f.read()
    except OSError as e:
        return False, f"/etc/nftables.conf cannot be read ({e.strerror})"
    if not re.search(r"hook\s+input[^;]*;\s*policy\s+drop", rules):
        return False, "/etc/nftables.conf no longer refuses what comes in (no `hook input … policy drop`)"
    return True, ""


def checks():
    """(key, level, title, text for the user, request for the agent), most urgent first."""
    user = os.environ.get("USER") or _out("id", "-un")[1].strip()
    on, why = firewall()
    if not on:
        ports = listening()
        yield ("firewall", "problem" if ports else "warning", "The firewall is off",
               f"Nothing stops other computers from reaching this one: {why}."
               + (f" Open to them now: {', '.join(ports[:6])}." if ports else ""),
               f"The firewall is off: {why}. Follow /etc/mentor/SECURITY.md, \"The firewall\": find out with the "
               "journal (journal_read) whether it was switched off on purpose, tell me, and switch it on again "
               "if I agree.")

    # The password every copy of Mentor starts with. unix_chkpwd is PAM's own helper for
    # letting a user check their own password; nothing is read that the user may not read.
    if _out("unix_chkpwd", user, "nullok", stdin=FIRST_PASSWORD + "\0")[0] == 0:
        remote = _out("systemctl", "is-active", "--quiet", "sshd.service")[0] == 0
        yield ("password", "problem" if remote or not on else "warning",
               "Your password is still the one every Mentor starts with",
               f"Anyone who knows Mentor knows it is “{FIRST_PASSWORD}”. Choose your own.",
               "My password is still the first one. Open a Console window on `passwd` for me (terminal_run), "
               "so that I can type a new one there. Never ask me for a password in the chat.")

    if _out("systemctl", "is-active", "--quiet", "sshd.service")[0] == 0:
        yield ("ssh", "warning", "Other computers can log in to this one",
               "The remote login service (sshd) is running.",
               "The remote login service sshd is running. Look in the journal (journal_read, search sshd) for "
               "who switched it on and why, tell me, and stop and disable it if I do not need it.")

    if _out("sudo", "-n", "true")[0] == 0:
        yield ("sudo", "problem", "Commands can run as root without your password",
               "sudo does not ask for a password at the moment. If you did not just type it in a terminal, a "
               "rule lets everything through.",
               "`sudo -n true` succeeds: sudo runs commands as root without asking for my password. Follow "
               "/etc/mentor/SECURITY.md, \"Root without a password\", and tell me what you find before changing "
               "anything.")

    roots = []
    try:
        with open("/etc/passwd") as f:
            roots = [line.split(":")[0] for line in f if line.split(":")[2:3] == ["0"] and not line.startswith("root:")]
    except OSError:
        pass
    if roots:
        yield ("uid0:" + ",".join(roots), "problem", "There is a second account with full power",
               f"{', '.join(roots)} has the same rights as root.",
               f"/etc/passwd has an account with user id 0 besides root: {', '.join(roots)}. Look in the journal "
               "(journal_read) and the audit log (`mentor log -n 100`) for where it came from, and tell me. Do "
               "not remove it before I agree.")

    loose = []
    try:
        for name in [""] + sorted(os.listdir(KEYS)):
            if os.stat(os.path.join(KEYS, name)).st_mode & 0o077:
                loose.append(os.path.join(KEYS, name).rstrip("/"))
    except OSError:
        pass
    if loose:
        yield ("keys", "warning", "Other users of this computer can read your keys",
               ", ".join(loose[:4]),
               f"These hold my API keys and can be read by other users: {', '.join(loose)}. Make the folder mode "
               "700 and the files 600 (run_command with chmod; say so in `changes`).")


def report():
    """The checks as text, for the agent and for `mentor security`."""
    found = list(checks())
    lines = [f"{level.upper():<8} {title}\n         {text}" for _key, level, title, text, _request in found]
    on, _why = firewall()
    lines.append("ok       the firewall refuses what comes in from other computers" if on else "")
    ports = listening()
    lines.append("Programs waiting for connections from other computers"
                 + (" (the firewall refuses them unless a rule lets them in): " if on else ": ")
                 + (", ".join(ports) or "none"))
    lines.append(f"\n{len(found)} thing(s) need attention. What each means and what to do: /etc/mentor/SECURITY.md"
                 if found else "\nNothing needs attention. What is looked at: /etc/mentor/SECURITY.md")
    return "\n".join(line for line in lines if line)
