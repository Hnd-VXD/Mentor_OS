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
import shutil
import subprocess
import sys
import textwrap

sys.path.insert(0, "/usr/local/lib/mentor")
import mentor_journal

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
NVIDIA_MODEL = "z-ai/glm-5.3"  # when the assistant's own choice is not one of NVIDIA's
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
HELP = """  Type what you want and press Enter. The agent answers here.
  /restart   restart the computer, to see whether the desktop comes up
  /engine    choose another engine to talk to
  /verify    list the files of Mentor's that are missing or changed
  /shell     leave this for a command line (type `mentor repair` to come back)
  /help      this"""


def say(text="", indent="  "):
    width = min(shutil.get_terminal_size((100, 30)).columns, 110) - len(indent)
    for line in str(text).splitlines() or [""]:
        for part in textwrap.wrap(line, width, replace_whitespace=False) or [""]:
            print(indent + part)
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


def nvidia_key():
    try:
        with open(os.path.join(CONFIG, "keys", "nvidia")) as f:
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
    "nvidia": ("NVIDIA (free models)", lambda: bool(nvidia_key())),
}


class Engine:
    """One engine, run once per message; what it calls the conversation is kept for the next."""

    def __init__(self, provider, model=None):
        self.provider, self.model, self.session = provider, model, None
        self.text = ""  # of a piece of text that comes in parts

    def command(self, message):
        """(argv, folder to run in, environment to add)."""
        system = f"{guide()}\n\n{PROMPT}"
        if self.provider == "claude":
            argv = ["claude", "-p", message, "--output-format", "stream-json", "--verbose",
                    "--mcp-config", MCP_CONFIG, "--strict-mcp-config", "--allowedTools", ALLOWED_TOOLS,
                    "--disallowedTools", DISALLOWED_TOOLS, "--append-system-prompt", PROMPT]
            if self.session:
                argv += ["--resume", self.session]
            return argv, HOME, {}
        if self.provider == "codex":
            options = ["--json", "--skip-git-repo-check"]
            for name, value in {"sandbox_mode": "read-only", "approval_policy": "never",
                                "mcp_servers.mentor.command": MCP_SERVER,
                                "mcp_servers.mentor.default_tools_approval_mode": "approve",
                                "developer_instructions": system}.items():
                options += ["-c", f"{name}={json.dumps(value)}"]
            options += ["-c", f"mcp_servers.mentor.env={{MENTOR_SANDBOX={json.dumps(SANDBOX)}}}"]
            argv = ["codex", "exec", *(["resume"] if self.session else []), *options]
            return argv + ([self.session] if self.session else []) + [message], HOME, {}
        if self.provider == "gemini":
            # It takes its instructions and its tool servers from the folder it is run in, and
            # must be allowed the Mentor tools in its own settings (as mentor-chat does).
            folder = os.path.join(STATE, "agy", SANDBOX)
            os.makedirs(os.path.join(folder, ".agents"), exist_ok=True)
            with open(os.path.join(folder, "AGENTS.md"), "w") as f:
                f.write(system + "\n\nNever use your own run_command or file-writing tools: nobody can approve "
                                 "them here, and the attempt ends your turn. Everything goes through the tools "
                                 "of the mentor server (call_mcp_tool with ServerName mentor).")
            with open(os.path.join(folder, ".agents", "mcp_config.json"), "w") as f:
                json.dump({"mcpServers": {"mentor": {"command": MCP_SERVER, "env": {"MENTOR_SANDBOX": SANDBOX}}}}, f)
            allow_mentor_tools()
            argv = ["agy", "-p", message, "--output-format", "stream-json", "--disable-slash-commands"]
            if self.session:
                argv += ["--conversation", self.session]
            return argv, folder, {}
        argv = [AGENT, "-p", message, "--provider", "nvidia", "--model", self.model or NVIDIA_MODEL, "--system", PROMPT]
        if self.session:
            argv += ["--resume", self.session]
        return argv, HOME, {"MENTOR_API_KEY": nvidia_key()}

    def ask(self, message):
        """Send one message and print what comes back as it comes. True if it answered."""
        argv, folder, extra = self.command(message)
        mentor_journal.note_request(SANDBOX, message)  # the journal of changes names the request
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
        if trouble:
            say(f"The engine says: {trouble}")
        elif not answered and stray and self.provider != "codex":
            say("The engine stopped without an answer. Its last words:")
            say("\n".join(stray[-8:]), indent="    ")
        return answered and not trouble

    def flush(self):
        if self.text.strip():
            print()
            say(self.text.strip())
        self.text = ""

    @staticmethod
    def tool(name, given):
        if name.startswith(TOOL_PREFIX):
            name = name[len(TOOL_PREFIX):]
        detail = ""
        if isinstance(given, dict):
            detail = str(given.get("command") or given.get("path") or given.get("packages") or given.get("unit")
                         or given.get("query") or given.get("summary") or "")
        print(f"  > {name}" + (f"  {' '.join(detail.split())[:90]}" if detail else ""), flush=True)

    def read(self, event):
        """Print what one event of the engine's tells. Returns (it has answered, what went wrong)."""
        if self.provider in ("claude", "nvidia"):
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
    say("Claude:   /usr/local/lib/mentor/mentor-engine claude", indent="    ")
    say("ChatGPT:  /usr/local/lib/mentor/mentor-engine codex", indent="    ")
    say("Then: mentor repair")
    print()
    say("Without one, by hand:")
    say("mentor verify                which of Mentor's files are missing or changed", indent="    ")
    say("sudo mentor restore --all    put them back as they were built", indent="    ")
    say("less /etc/mentor/REPAIR.md   the rest", indent="    ")


def main():
    approvals = ask_approvals_here()
    try:
        return talk()
    finally:
        if approvals:
            approvals.terminate()


def talk():
    print()
    say("Mentor, repair mode.")
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
    while True:
        if message:
            engine.ask(message)
        print()
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if message == "/help":
            print(HELP)
        elif message == "/verify":
            say(verify())
        elif message == "/shell":
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
