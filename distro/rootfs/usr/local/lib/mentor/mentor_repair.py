"""Talking to the agent on a text console, to mend Mentor when its desktop does not come up.

    mentor repair

Needs nothing of GNOME: no window, no shell extension, no assistant. It is what the launcher's
"Repair" start runs (the system then starts without the desktop at all, see
mentor-repair.target), and it can be run in any terminal.

The user types, an engine answers. It is the same engines the assistant uses, run the same
way, once per message and kept to the Mentor tools: Claude Code, Codex, Google's Antigravity
CLI, or mentor-agent with a key (see /etc/mentor/ENGINES.md; the commands here and the ones
in mentor-chat have to be kept in step). Approvals are asked on the console.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time

try:  # line editing and history at the prompt (arrows), and a coloured prompt measured right
    import readline  # noqa: F401
except ImportError:
    pass

sys.path.insert(0, "/usr/local/lib/mentor")
import mentor_journal
import mentor_security

HOME =os.path.expanduser("~")
os.environ["PATH"] = f"{HOME}/.local/bin" + os.pathsep + os.environ.get("PATH", "")
GUIDE = "/etc/mentor/AGENT.md"
MCP_SERVER = "/usr/local/bin/mentor-mcp"
MCP_CONFIG = "/etc/mentor/mcp.json"
AGENT = "/usr/local/bin/mentor-agent"
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or f"{HOME}/.config", "mentor")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or f"{HOME}/.local/state", "mentor")
SANDBOX = "repair"
TOOL_PREFIX = "mcp__mentor__"
# The engines that run on a key (mentor-agent): the model when the assistant's own choice is not one of theirs.
KEY_MODELS = {"nvidia": "z-ai/glm-5.3", "groq": "openai/gpt-oss-120b"}
ALLOWED_TOOLS = "mcp__mentor,Read,Glob,Grep,WebSearch,WebFetch"
DISALLOWED_TOOLS = "Bash,Edit,Write,NotebookEdit"

PROMPT = (
    "You are the Mentor agent, started in repair mode. The user is at a text console: GNOME is not "
    "running, and neither is the assistant on the desktop. They started this because Mentor's desktop "
    "does not come up, or something of Mentor's own is broken, often after an upgrade.\n\n"
    "Everything of Mentor's is written down for this: start with /etc/mentor/REBUILD.md and "
    "/etc/mentor/REPAIR.md (file_read), and follow them step by step. First find out what is wrong, and "
    "tell the user in a few plain lines before you change anything: `mentor verify` (which of Mentor's "
    "files are missing or changed), `journalctl -b -1 -p err -o cat | tail -40` (what the last start "
    "complained of), `journalctl -b -1 -o cat _COMM=gnome-shell | tail -40` (the desktop itself), "
    "`tail -60 /var/log/pacman.log` (what was upgraded), `mentor boot` (what start-up thinks).\n\n"
    "What is different here: tools that need the desktop do not work (screen_capture, app_open, "
    "terminal_run, session_logout, window_mode, desktop_check's shell parts). An approval is a password "
    "asked on this console, and the preview of a sandbox change is text with a yes or no. You cannot see "
    "the desktop from here: after a repair the user has to restart to find out, by typing /restart. "
    "Say so when you are done, and say what to tell you if it still does not come up.\n\n"
    "Write plain text, no Markdown: this is a console. Keep it short."
)
OPENING = ("I started Mentor in repair mode. Find out what is wrong with it and tell me, before changing anything.")

# Opened by the emergency key (Ctrl+Alt+Backspace, mentor-emergency-key; /etc/mentor/FREEZES.md):
# the desktop froze, and it still runs on behind this console.
EMERGENCY = os.environ.get("MENTOR_EMERGENCY") == "1"
EMERGENCY_PROMPT = (
    "You are the Mentor agent, on the emergency console. The user pressed Ctrl+Alt+Backspace because the "
    "desktop froze or stopped responding. The desktop session is still running behind this text console, "
    "with their programs open: this is not a broken system, it is a stuck one, right now.\n\n"
    "Find out what is happening now, before changing anything, and tell them in a few plain lines: "
    "/var/log/mentor/freezes.jsonl (file_read: Mentor's watch writes each stall there, newest last; "
    "/etc/mentor/FREEZES.md says how to read it), `top -bn1 -o %CPU | head -15` and "
    "`ps -eo pid,rss,pcpu,comm --sort=-rss | head -12` (what uses the processor and memory now), `free -m`, "
    "`journalctl -b --since -10min -p warning -o cat | tail -40`. Then offer what would help and wait for "
    "their yes: close the program behind it (kill, or `systemctl --user stop` its app unit), or restart "
    "the desktop session (`systemctl restart gdm`: their open programs close). Say which you recommend.\n\n"
    "Tools that need the desktop do not work from here (screen_capture, app_open, terminal_run). An "
    "approval is a password asked on this console. When it is mended, tell them to type /desktop to go "
    "back to it.\n\nWrite plain text, no Markdown: this is a console. Keep it short."
)
EMERGENCY_OPENING = ("The desktop froze and I pressed the emergency key. Find out what is happening right now and "
                     "tell me, before changing anything.")
# Both: on 2026-10-15 Gemini, its sandbox approval refused, went reading Mentor's tool code instead.
STOP_RULE = ("\n\nIf an approval is refused, cancelled or fails (a wrong password), stop there: say so in one line and "
             "ask what they want. Do not try another way, and do not read Mentor's own code or tool files to find out why.")
PROMPT += STOP_RULE
EMERGENCY_PROMPT += STOP_RULE
if EMERGENCY:
    PROMPT = EMERGENCY_PROMPT


def busiest(count=8):
    """The processes using the processor most, without this console, its own helpers (the
    password agent it starts) and ps itself: (pid, %cpu, %mem, rss, running for, name) lines."""
    me = str(os.getpid())
    try:
        rows = subprocess.run(["ps", "-eo", "pid,ppid,pcpu,pmem,rss,etime,comm", "--sort=-pcpu", "--no-headers"],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return ["(no answer)"]
    kept = []
    for row in rows:
        fields = row.split()
        if len(fields) >= 7 and me not in fields[:2] and fields[6] != "ps":
            kept.append("  ".join([fields[0]] + fields[2:]))
    return kept[:count]


def snapshot():
    """What is going on right now, gathered here so that the agent can answer from it at once:
    whether GNOME Shell answers, the freezes Mentor's watch wrote down, the busiest processes, memory."""
    def run(*argv, timeout=10):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return "(no answer)"
    started = time.monotonic()
    bus = f"unix:path=/run/user/{os.getuid()}/bus"
    shell = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path",
                            "/org/mentor/Shell", "--method", "org.mentor.Shell.Status", "--timeout", "5"],
                           capture_output=True, text=True, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": bus})
    took = time.monotonic() - started
    answers = (f"answers ({took:.1f} s)" if shell.returncode == 0 else
               f"does NOT answer (no reply in {took:.0f} s): the desktop is stuck right now")
    try:
        with open("/var/log/mentor/freezes.jsonl") as f:
            stalls = f.read().strip().splitlines()[-5:]
    except OSError:
        stalls = []
    return "\n".join([
        f"GNOME Shell {answers}.",
        "Freezes Mentor's watch wrote down (newest last): " + ("\n" + "\n".join(stalls) if stalls else "none."),
        "Busiest processes now (pid, %cpu, %mem, rss KB, running for, name):\n"
        + "\n".join(busiest()),
        "Memory (MB):\n" + run("free", "-m"),
        "Load: " + run("cat", "/proc/loadavg"),
    ])
HELP = """  Type what you want and press Enter. The agent answers here.
  /desktop   go back to the desktop (only from the emergency console)
  /restart   restart the computer, to see whether the desktop comes up
  /engine    choose another engine to talk to
  /verify    list the files of Mentor's that are missing or changed
  /shell     leave this for a command line (type `mentor repair` to come back)
  /help      this
  Ctrl+V     paste what you copied, on Windows or in Mentor"""


# Colour on the console (the Linux console's 16 colours), not when the output goes elsewhere.
COLOR = sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
LOGO = [
    r" __  __            _",
    r"|  \/  | ___ _ __ | |_ ___  _ __",
    r"| |\/| |/ _ \ '_ \| __/ _ \| '__|",
    r"| |  | |  __/ | | | || (_) | |",
    r"|_|  |_|\___|_| |_|\__\___/|_|",
]
LOGO_COLORS = ("1;96", "1;96", "1;36", "1;94", "1;34")  # light cyan down to blue
COMMANDS = re.compile(r"(/(?:desktop|restart|engine|verify|shell|help)\b|Ctrl\+Alt\+(?:Backspace|F\d)|Ctrl\+V\b)")


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def chips(text):
    """The commands and keys in a line, in green: what can be typed or pressed stands out."""
    return COMMANDS.sub(lambda m: paint(m.group(0), "1;92"), text) if COLOR else text


def banner(subtitle, color):
    print()
    for line, code in zip(LOGO, LOGO_COLORS):
        print("    " + paint(line, code))
    print("    " + paint(subtitle, color))
    print()


INLINE = re.compile(r"(\*\*|`)")


def styled(line, state):
    """One wrapped line of an answer with its **bold** and `code` drawn as such (the marks taken
    out); `state` carries a span that goes on into the next line. Returns (text, state)."""
    out, bold, code = [], state.get("bold", False), state.get("code", False)

    def opened():
        return ("\033[1m" if bold else "") + ("\033[36m" if code else "") if COLOR else ""

    out.append(opened())
    for piece in INLINE.split(line):
        if piece == "**" and not code:
            bold = not bold
        elif piece == "`":
            code = not code
        else:
            out.append(piece if code else chips(piece))
            continue
        out.append(("\033[0m" + opened()) if COLOR else "")
    out.append("\033[0m" if COLOR and (bold or code) else "")
    return "".join(out), {"bold": bold, "code": code}


def render(text, indent="  "):
    """An answer as the engines write it (Markdown, whatever they are told) made readable on a
    console: no fence or star marks; code blocks indented, in cyan and not wrapped; headings and
    **bold** bright; bullets as dots."""
    width = min(shutil.get_terminal_size((100, 30)).columns, 110) - len(indent) - 2
    fenced, state = False, {}
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            print(indent + "    " + paint(line, "36"))
            continue
        heading = re.match(r"\s*#{1,6}\s+(.*)", line)
        if heading:
            print(indent + paint(heading.group(1).replace("**", ""), "1"))
            continue
        bullet = re.match(r"(\s*)[-*+]\s+(.*)", line)
        lead, body = (bullet.group(1) + "\u2022 ", bullet.group(2)) if bullet else ("", line)
        parts = textwrap.wrap(body, max(20, width - len(lead)), replace_whitespace=False) or [""]
        for number, part in enumerate(parts):
            shown, state = styled(part, state)
            print(indent + (lead if number == 0 else " " * len(lead)) + shown)
        state = {}  # a span not closed in its paragraph ends with it
    sys.stdout.flush()


def say(text="", indent="  "):
    width = min(shutil.get_terminal_size((100, 30)).columns, 110) - len(indent)
    for line in str(text).splitlines() or [""]:
        for part in textwrap.wrap(line, width, replace_whitespace=False) or [""]:
            print(indent + chips(part))  # coloured after wrapping: the colour codes take no room
    sys.stdout.flush()


def guide():
    try:
        with open(GUIDE) as f:
            return f.read()
    except OSError:
        return ""


def settings():
    try:
        with open(os.path.join(CONFIG, "chat.json")) as f:
            found = json.load(f)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_key(provider):
    try:
        with open(os.path.join(CONFIG, "keys", provider)) as f:
            return f.read().strip()
    except OSError:
        return ""


def succeeds(*argv, wanted=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=40, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if wanted:
        try:
            return bool(json.loads(done.stdout).get(wanted))
        except (ValueError, AttributeError):
            return False
    return done.returncode == 0


# What each engine is called, and how to tell that it is ready to answer.
ENGINES = {
    "claude": ("Claude", lambda: succeeds("claude", "auth", "status", wanted="loggedIn")),
    "codex": ("ChatGPT", lambda: succeeds("codex", "login", "status")),
    "gemini": ("Gemini", lambda: succeeds("agy", "models")),
    "nvidia": ("NVIDIA (free models)", lambda: bool(saved_key("nvidia"))),
    "groq": ("Groq (free, fast models)", lambda: bool(saved_key("groq"))),
}


class Engine:
    """One engine, run once per message; what it calls the conversation is kept for the next."""

    def __init__(self, provider, model=None):
        self.provider, self.model, self.session = provider, model, None
        self.text = ""  # of a piece of text that comes in parts

    def command(self, message):
        """(argv, folder to run in, environment to add)."""
        system = f"{guide()}\n\n{PROMPT}"
        # The message is put so that one beginning with a dash is not taken as an option, nor one
        # beginning with a slash as a command (as in mentor-chat).
        if self.provider == "claude":
            argv = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                    "--mcp-config", MCP_CONFIG, "--strict-mcp-config", "--allowedTools", ALLOWED_TOOLS,
                    "--disallowedTools", DISALLOWED_TOOLS, "--append-system-prompt", PROMPT]
            if self.session:
                argv += ["--resume", self.session]
            return argv + ["--", " " + message if message.startswith("/") else message], HOME, {}
        if self.provider == "codex":
            options = ["--json", "--skip-git-repo-check"]
            for name, value in {"sandbox_mode": "read-only", "approval_policy": "never",
                                "mcp_servers.mentor.command": MCP_SERVER,
                                "mcp_servers.mentor.default_tools_approval_mode": "approve",
                                "developer_instructions": system}.items():
                options += ["-c", f"{name}={json.dumps(value)}"]
            options += ["-c", f"mcp_servers.mentor.env={{MENTOR_SANDBOX={json.dumps(SANDBOX)}}}"]
            argv = ["codex", "exec", *(["resume"] if self.session else []), *options, "--"]
            return argv + ([self.session] if self.session else []) + [message], HOME, {}
        if self.provider == "gemini":
            # It takes its instructions and its tool servers from the folder it is run in, and
            # must be allowed the Mentor tools in its own settings (as mentor-chat does).
            folder = os.path.join(STATE, "agy", SANDBOX)
            os.makedirs(os.path.join(folder, ".agents"), exist_ok=True)
            docs = os.path.join(folder, "mentor-docs")  # where its own file viewer may open them
            os.makedirs(docs, exist_ok=True)
            for name in os.listdir("/etc/mentor"):
                if name.endswith(".md"):
                    shutil.copyfile(os.path.join("/etc/mentor", name), os.path.join(docs, name))
            with open(os.path.join(folder, "AGENTS.md"), "w") as f:
                f.write(system + "\n\nNever use your own run_command or file-writing tools: nobody can approve "
                                 "them here, and the attempt ends your turn. Everything goes through the tools "
                                 "of the mentor server (call_mcp_tool with ServerName mentor).\n\n"
                                 "Your own file viewer (view_file) may open only what is inside this folder: "
                                 "Mentor's instruction files are there as mentor-docs/NAME.md (the same as "
                                 "/etc/mentor/NAME.md in what you were told). For every other file use the "
                                 "Mentor tool file_read. A file your viewer may not open ends your turn.")
            with open(os.path.join(folder, ".agents", "mcp_config.json"), "w") as f:
                json.dump({"mcpServers": {"mentor": {"command": MCP_SERVER, "env": {"MENTOR_SANDBOX": SANDBOX}}}}, f)
            allow_mentor_tools()
            argv = ["agy", "-p=" + message, "--output-format", "stream-json", "--disable-slash-commands",
                    "--add-dir", "/etc/mentor"]
            if self.session:
                argv += ["--conversation", self.session]
            return argv, folder, {}
        argv = [AGENT, "--prompt=" + message, "--provider", self.provider,
                "--model", self.model or KEY_MODELS[self.provider], "--system", PROMPT]
        if self.session:
            argv += ["--resume", self.session]
        return argv, HOME, {"MENTOR_API_KEY": saved_key(self.provider)}

    def ask(self, message, carried=False):
        """Send one message and print what comes back as it comes. True if it answered."""
        self.refused = None
        argv, folder, extra = self.command(message)
        mentor_journal.note_request(SANDBOX, message)  # the journal of changes names the request
        mentor_security.new_request(SANDBOX)
        self.text, answered, trouble, stray = "", False, None, []
        try:
            process = subprocess.Popen(argv, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, errors="replace",
                                       env={**os.environ, "MENTOR_SANDBOX": SANDBOX, "ENABLE_TOOL_SEARCH": "false", **extra})
        except OSError as e:
            say(f"Could not start {argv[0]}: {e.strerror}.")
            return False
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    event = None
                if not isinstance(event, dict):
                    if line.strip():
                        stray.append(line.rstrip())
                    continue
                done, problem = self.read(event)
                answered, trouble = answered or done, problem or trouble
        except KeyboardInterrupt:
            process.terminate()
            say("\nStopped.")
        process.wait()
        self.flush()
        if self.refused and not carried:
            # Gemini may not use its own tools here (a refusal ends its turn): told so once and set
            # going again on the same request, without the user having to ask again (as in the chat).
            print(paint("    (Gemini reached for a tool of its own; Mentor used its own, which ask you first and keep a record)", "90"),
                  flush=True)
            return self.ask(
                f"You reached for {self.refused}, a tool of your own, which is not allowed here, and your turn "
                "ended. Do it through the Mentor tools instead, with call_mcp_tool and ServerName mentor: "
                "run_command for a shell command, file_read for a file, log_read for logs, service_status for a "
                "service. Carry on with my request from where you were.", carried=True)
        if trouble:
            say(f"The engine says: {trouble}")
        elif not answered and stray and self.provider != "codex":
            say("The engine stopped without an answer. Its last words:")
            say("\n".join(stray[-8:]), indent="    ")
        return answered and not trouble

    def flush(self):
        if self.text.strip():
            print()
            render(self.text.strip())
        self.text = ""

    @staticmethod
    def tool(name, given):
        if name.startswith(TOOL_PREFIX):
            name = name[len(TOOL_PREFIX):]
        else:  # a tool of the engine's own: what it read from outside is noted for the warning
            mentor_security.saw(SANDBOX, name, given)
        detail = ""
        if isinstance(given, dict):
            detail = str(given.get("command") or given.get("path") or given.get("packages") or given.get("unit")
                         or given.get("query") or given.get("summary") or "")
        line = f"  > {name}" + (f"  {' '.join(detail.split())[:90]}" if detail else "")
        print(paint(line, "90"), flush=True)  # the agent's steps in grey, its words in white

    def read(self, event):
        """Print what one event of the engine's tells. Returns (it has answered, what went wrong)."""
        if self.provider in ("claude", *KEY_MODELS):
            if event.get("session_id"):
                self.session = event["session_id"]
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "status":
                print(f"  ({event.get('text')})", flush=True)
            elif kind in ("assistant", "user"):
                content = event.get("message", {}).get("content")
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "text":
                        self.text = block.get("text", "")
                        self.flush()
                    elif block.get("type") == "tool_use":
                        self.tool(block.get("name", "?"), block.get("input"))
                    elif block.get("type") == "tool_result" and block.get("is_error"):
                        print("    (that did not work)", flush=True)
            elif kind == "result":
                if event.get("is_error"):
                    return False, str(event.get("result") or event.get("subtype") or "it stopped")
                return True, None
        elif self.provider == "codex":
            kind, item = event.get("type"), event.get("item") or {}
            if kind == "thread.started" and event.get("thread_id"):
                self.session = event["thread_id"]
            elif kind == "item.started" and item.get("type") == "mcp_tool_call":
                self.tool(item.get("tool", "?"), item.get("arguments"))
            elif kind == "item.completed" and item.get("type") == "mcp_tool_call":
                if item.get("status") == "failed" or item.get("error"):
                    print("    (that did not work)", flush=True)
            elif kind == "item.completed" and item.get("type") == "agent_message":
                self.text = item.get("text", "")
                self.flush()
            elif kind == "turn.completed":
                return True, None
            elif kind in ("error", "turn.failed"):
                return False, str(event.get("message") or (event.get("error") or {}).get("message") or "Codex stopped.")
        else:  # the Antigravity CLI
            if event.get("conversation_id"):
                self.session = event["conversation_id"]
            if event.get("event") == "step_update":
                step = event.get("step_update") or {}
                info = step.get("tool_info") or {}
                if step.get("step_type") == "agent_response":
                    self.text += str(step.get("text_delta") or "")
                    if step.get("state") != "ACTIVE":
                        self.flush()
                elif step.get("step_type") == "tool":
                    self.flush()
                    name, given = str(info.get("name") or step.get("tool_name") or "?"), info.get("parameters") or {}
                    if "/antigravity-cli/mcp/" in str(given.get("AbsolutePath", "")):
                        return False, None  # it reading how one of our tools is called
                    if name == "call_mcp_tool" and given.get("ServerName") == "mentor":
                        name, given = str(given.get("ToolName") or "?"), given.get("Arguments")
                    if step.get("state") == "ACTIVE":
                        self.tool(name, given)
                    elif step.get("state") == "ERROR" or info.get("error"):
                        print("    (that did not work)", flush=True)
            elif event.get("event") == "result":
                result = event.get("result") or {}
                if result.get("status") != "SUCCESS":
                    return False, str(result.get("error") or result.get("status") or "it stopped")
                if result.get("denied_actions") and not str(result.get("response") or "").strip():
                    self.refused = ", ".join(str(action.get("display_name") or action.get("action"))
                                             for action in result["denied_actions"] if isinstance(action, dict))
                    return False, ("it reached for a tool of its own in place of Mentor's, which is not allowed "
                                   "here, and stopped. Ask again.")
                return True, None
        return False, None


def allow_mentor_tools():
    """Have the Antigravity CLI's settings let the Mentor tools through without asking."""
    path = f"{HOME}/.gemini/antigravity-cli/settings.json"
    try:
        with open(path) as f:
            kept = json.load(f)
    except (OSError, ValueError):
        kept = {}
    try:
        allowed = kept.setdefault("permissions", {}).setdefault("allow", [])
        if "mcp(mentor/*)" not in allowed:
            allowed.append("mcp(mentor/*)")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(kept, f, indent=2)
    except (OSError, AttributeError, TypeError):
        pass


# Who asks for the password when a tool needs root. On the desktop that is GNOME Shell. On a
# bare console pkexec would ask by itself, and with the polkit of 2026 is then refused ("No
# session for cookie": it asks as root, being setuid, and the answer is expected from the
# user). So the console gets an agent of the user's own for the time of the repair.
APPROVALS = """
import os, gi
gi.require_version("Polkit", "1.0")
gi.require_version("PolkitAgent", "1.0")
from gi.repository import GLib, Polkit, PolkitAgent
subject = Polkit.UnixSession.new_for_process_sync(os.getpid(), None)
listener = PolkitAgent.TextListener.new(None)
kept = listener.register(PolkitAgent.RegisterFlags.NONE, subject, "/org/mentor/RepairAgent", None)
GLib.MainLoop().run()
"""


def ask_approvals_here():
    """Start the console's approval agent. Where there is one already (a terminal on the
    desktop), it finds that out and ends by itself."""
    try:
        return subprocess.Popen([sys.executable, "-c", APPROVALS], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def choose(ask_user):
    """The engine to talk to: the one the assistant was set to if it is ready, otherwise the
    first that is; or the user's pick. None when none is ready."""
    kept = settings()
    print("  Looking for an engine that is ready to answer...", flush=True)
    ready = [provider for provider, (_name, test) in ENGINES.items() if test()]
    if not ready:
        return None
    wanted = kept.get("engine")
    if ask_user and len(ready) > 1:
        for number, provider in enumerate(ready, 1):
            say(f"{number}. {ENGINES[provider][0]}")
        answer = input("  Which one? ").strip()
        wanted = ready[int(answer) - 1] if answer.isdigit() and 0 < int(answer) <= len(ready) else wanted
    provider = wanted if wanted in ready else ready[0]
    return Engine(provider, kept.get("engine_model") if provider == kept.get("engine") else None)


def verify():
    try:
        done = subprocess.run(["/usr/local/bin/mentor", "verify"], capture_output=True, text=True, timeout=120)
        return done.stdout.strip() or done.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"mentor verify could not be run: {e}"


def no_engine():
    say("No engine is ready to answer, so there is nobody to talk to yet. To make one ready:")
    say("NVIDIA, with a free key (build.nvidia.com, any model, Get API Key):", indent="    ")
    say("mkdir -p ~/.config/mentor/keys; nano ~/.config/mentor/keys/nvidia", indent="      ")
    say("Groq, the same with a key from console.groq.com/keys, in ~/.config/mentor/keys/groq", indent="    ")
    say("Claude:   /usr/local/lib/mentor/mentor-engine claude", indent="    ")
    say("ChatGPT:  /usr/local/lib/mentor/mentor-engine codex", indent="    ")
    say("Then: mentor repair")
    print()
    say("Without one, by hand:")
    say("mentor verify                which of Mentor's files are missing or changed", indent="    ")
    say("sudo mentor restore --all    put them back as they were built", indent="    ")
    say("less /etc/mentor/REPAIR.md   the rest", indent="    ")
    if EMERGENCY:
        say("top                          what uses the processor now (q to leave)", indent="    ")
        print()
        say("Ctrl+Alt+F2 goes back to the desktop.")


def main():
    approvals = ask_approvals_here()
    try:
        return talk()
    finally:
        if approvals:
            approvals.terminate()


def back_to_desktop():
    """Switch the screen back to the user's graphical session (loginctl activate)."""
    out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        session = line.split()[0] if line.split() else ""
        kind = subprocess.run(["loginctl", "show-session", session, "-p", "Type", "--value"],
                              capture_output=True, text=True).stdout.strip()
        if kind in ("wayland", "x11"):
            return subprocess.run(["loginctl", "activate", session]).returncode == 0
    return False


CLIP_TEXT = os.path.join(os.environ.get("XDG_CACHE_HOME") or f"{HOME}/.cache", "mentor", "clipboard-text")


def bind_paste():
    """Ctrl+V types what was copied last, on Windows or in Mentor (mentor-clipboard keeps it in
    CLIP_TEXT): a text console has no clipboard of its own. Bound again before each prompt, so it
    is always the latest. Ctrl+Shift+V arrives as the same key on a console."""
    if "readline" not in sys.modules:
        return
    try:
        with open(CLIP_TEXT, encoding="utf-8", errors="replace") as f:
            text = f.read(4000)
    except OSError:
        text = ""
    text = " ".join(text.split())  # one line: Enter is what sends
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    sys.modules["readline"].parse_and_bind(f'"\\C-v": "{text}"')


# The prompt in bold green; \001 and \002 tell readline that the colour codes take no room.
PROMPT_MARK = "\001\033[1;92m\002you>\001\033[0m\002 " if COLOR else "you> "


def talk():
    print()
    if EMERGENCY:
        banner("emergency console  -  you are not stuck", "1;93")
        say("You pressed Ctrl+Alt+Backspace. Your desktop is still running behind this screen, with your "
            "programs open. Tell the agent what happened; it looks at what is going on and says what would help "
            "before it changes anything.")
        print()
        say("/desktop  back to the desktop      /help  what else you can type      Ctrl+V  paste")
    else:
        banner("repair mode", "1;93")
        say("This is a text console: the desktop is not running. You talk to the agent here, and it works from "
            "the instructions kept in /etc/mentor to find what is broken and mend it. Nothing is changed without "
            "your say: an approval is asked for with your password, here.")
        print()
        say(verify())
    print()
    engine = choose(ask_user=False)
    if engine is None:
        no_engine()
        return 0
    say(f"Talking to {ENGINES[engine.provider][0]}. /help lists what else you can type.")
    message = OPENING
    if EMERGENCY:
        message = (EMERGENCY_OPENING + "\n\nWhat the console found when it opened (answer from this first; "
                   "use tools only for what it does not say):\n\n" + snapshot())
    while True:
        if message:
            engine.ask(message)
        print()
        try:
            bind_paste()
            message = input(PROMPT_MARK).strip()
        except (EOFError, KeyboardInterrupt):
            # A stray Ctrl+C or Ctrl+D (or what a console sends for Ctrl+Shift+V) does not leave:
            # on 2026-10-15 it dropped the user on a command line where /desktop means nothing.
            print()
            if not sys.stdin.isatty():
                return 0
            say("(Still here. /desktop goes back to the desktop, /shell leaves for a command line.)")
            message = ""
            continue
        if message == "/help":
            print("\n".join(chips(line) for line in HELP.splitlines()))
        elif message == "/verify":
            say(verify())
        elif message == "/desktop":
            if not EMERGENCY:
                say("There is no desktop running to go back to: /restart starts it.")
            elif not back_to_desktop():
                say("That did not work. Ctrl+Alt+F2 goes back to the desktop.")
        elif message == "/shell":
            if not EMERGENCY:  # the emergency console's own line says it (/etc/profile.d/mentor-repair.sh)
                say("A command line. `mentor repair` comes back here; `systemctl reboot` restarts.")
            return 0
        elif message == "/restart":
            say("Restarting.")
            subprocess.run(["systemctl", "reboot"])
            return 0
        elif message == "/engine":
            engine = choose(ask_user=True) or engine
            say(f"Talking to {ENGINES[engine.provider][0]}.")
        elif message.startswith("/"):
            say("That is not one of the commands. /help lists them.")
        else:
            continue
        message = ""
