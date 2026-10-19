# The assistant's engines: what they are made of, and how to make them again

This is for the agent. The assistant (mentor-chat) does not answer by itself: each message is handed to an engine, a program that talks to a model and calls the Mentor tools. This file says what the user is meant to have with each engine, where it is done, what of the other makers' programs it leans on, and how to tell that it works. Use it when an engine has stopped answering, when its maker has changed or replaced its program, or when the picker, the sign-in or the usage display no longer do what is written here.

The programs of other makers change on their own schedule and without notice. In June 2026 Google stopped serving personal accounts through the Gemini CLI and moved them to the Antigravity CLI, a different program with different options; Gemini in Mentor had to be made again around it. Expect that kind of change, and make the same thing for the user the new way.

## What the user has

- **A picker** beside the text box: a menu with one submenu per engine (NVIDIA, Claude, ChatGPT, Gemini), the models of each, "Sign in again…" or "Change key…", and Effort. At its top: the chosen model and, for the engines with an account, how much of the account's allowance is used (a session limit and a weekly limit, each with a bar and the time it resets).
- **A first start that asks**: someone who has not picked an engine yet sees a card, "Connect the agent", with the four of them and what each needs. None is picked for them.
- **A card that connects the chosen engine** when it is not ready: a field for the key (NVIDIA), or a button "Sign in to …" that opens a terminal on the maker's own sign-in (the others). The maker's program is downloaded first if it is not there. Under it, "Or use" and the other engines.
- **The key comes back by itself** (since 2026-10-19; the user: the card hid behind NVIDIA's page): "Open NVIDIA's page" also asks the shell to watch the clipboard (`AwaitCopy` of the extension, with `KEY_SHAPES["nvidia"]`, `nvapi-` and at least 20 letters, digits, `-` or `_`; for 15 minutes, until such a key is copied). When the user copies the key on the page, the desktop comes to the front as with Super+A, and the card, in front again, puts the key in its box from the clipboard (`take_copied_key` in `mentor-chat`, on `notify::is-active`) and gives Save the focus. Nothing is saved before Save. Other copied text is only compared in the shell, never kept. Not working: `gdbus introspect --session --dest org.gnome.Shell --object-path /org/mentor/Shell | grep AwaitCopy` must show it (an older extension until the next login); a key of another shape (NVIDIA changed it) is still pasted by hand, and `KEY_SHAPES` is changed to fit.
- **The same conversation whichever engine answers**: text, a row for each tool call with a tick or a warning, and the conversation can be gone on with in a later message.
- **Changes only through the Mentor tools**: no engine may use a shell or write files by its own means, so that every change passes the approval dialog and the sandbox.

## How it hangs together

- `mentor repair` (`/usr/local/lib/mentor/mentor_repair.py`, REPAIR.md) talks to the same engines on a text screen, with the same commands and its own readers of their events (`Engine.command`, `Engine.read`). When an engine's command or events change, both have to follow.
- `/usr/local/bin/mentor-chat` runs the engine once per message (`Conversation.send`), reads what it prints line by line (`on_line`) and draws it. Each engine tells the story in its own words, so there is one reader per engine: `on_event` (Claude Code, and mentor-agent, which prints the same shape), `on_codex_event`, `on_agy_event`. All of them end in `on_block`.
- The models are the list `MODELS`; the submenus `MENUS`; the engines with an account `ACCOUNTS` (name, program, how to tell whether one is signed in, how to sign in); the ones with a key `PROVIDERS`.
- `/usr/local/lib/mentor/mentor-engine claude|codex|gemini` is what the "Sign in" button runs in a terminal: it downloads the maker's program into `~/.local` if it is missing, then starts its sign-in. The programs are not in the image: each user gets their own copy.
- `/usr/local/lib/mentor/mentor-usage codex|gemini` asks an account how much of its allowance is used and prints `{"windows": [{"minutes", "used", "resets"}]}`. Claude Code needs no asking (see its row).
- What the engines are told is `/etc/mentor/AGENT.md` followed by `SYSTEM_PROMPT` in mentor-chat. The tools reach them through `/usr/local/bin/mentor-mcp` (an MCP server on standard input and output), except mentor-agent, which calls `mentor_tools` directly.
- Kept per user: the choice and the effort in `~/.config/mentor/chat.json`; keys in `~/.config/mentor/keys/` (mode 600); the models an account listed in `~/.cache/mentor/{codex,gemini}-models.json`; the last usage figures in `~/.cache/mentor/usage.json`; the conversations in `~/.local/state/mentor/conversations.json`.

## The engines

| Engine (name in the code) | Runs through | How one run is started | How it is kept to the Mentor tools | Going on with a conversation |
|---|---|---|---|---|
| NVIDIA (`nvidia`) | `/usr/local/bin/mentor-agent`, ours: the chat-completions protocol against `https://integrate.api.nvidia.com/v1` with the user's key (in the environment, `MENTOR_API_KEY`) | `mentor-agent -p … --provider nvidia --model …` | It has no other tools | `--resume ID`; the history is in `~/.local/state/mentor/sessions/` |
| Claude (`claude`) | Claude Code (`claude`, npm `@anthropic-ai/claude-code`) | `claude -p … --output-format stream-json --verbose --mcp-config /etc/mentor/mcp.json --strict-mcp-config` | `--allowedTools` / `--disallowedTools` (its Bash, Edit and Write are off) | `--resume ID` from the `session_id` of its events |
| ChatGPT (`codex`) | Codex (`codex`, npm `@openai/codex`) | `codex exec --json --skip-git-repo-check -c …` | `sandbox_mode=read-only`, `approval_policy=never`, and the Mentor server given with `-c mcp_servers.mentor.…` | `codex exec resume … ID` from `thread.started` |
| Gemini (`gemini`) | Google's Antigravity CLI (`agy`, from `https://antigravity.google/cli/install.sh`) | `agy -p … --output-format stream-json --disable-slash-commands`, run in a folder of the conversation's own | See below | `--conversation ID` from the `conversation_id` of its events |

| Engine | Signed in? | Its models | Its allowance |
|---|---|---|---|
| NVIDIA | a key is saved | written in `MODELS` | none shown |
| Claude | `claude auth status` prints JSON with `loggedIn` | its aliases, written in `MODELS` | told unasked, in the `rate_limit_event` of every answer (`claude_usage`) |
| ChatGPT | `codex login status` exits 0 | `codex debug models` | `codex app-server`, request `account/rateLimits/read` (mentor-usage) |
| Gemini | `agy models` exits 0 (it lists them only to someone signed in) | the same command: lines of `id<TAB>name`, of which the `gemini…` ones are kept | `agy -p /usage --output-format json`: `command.data.groups[].buckets[]` with `id` (`gemini-5h`, `gemini-weekly`), `window`, `remaining_fraction`, `reset_time` (mentor-usage) |

### Gemini through the Antigravity CLI, in full

This one leans on the most that is not ours, so it is written out.

- **A folder per conversation**, `~/.local/state/mentor/agy/<sandbox>/` (`agy_folder`). The CLI has no option for instructions or for a list of tool servers; it takes both from the folder it is run in. So the folder holds `AGENTS.md` (AGENT.md, `SYSTEM_PROMPT` and `AGY_PROMPT`) and `.agents/mcp_config.json`, which names the server `mentor` with `MENTOR_SANDBOX` set to this conversation's. The user's own rules and servers for `agy` are not touched.
- **One rule in the user's settings**, `~/.gemini/antigravity-cli/settings.json`: `permissions.allow` gets `mcp(mentor/*)` (`agy_allow`, before every run). Without it every call of a Mentor tool is refused. A settings file in the folder is not read; this has to be the user's.
- **Attached files are put into the folder** (`agy_attach`): as `attached/NAME`, a second name for the same file (a hard link) where that can be had, a copy otherwise, and the message names them by that place. Its own file tool, `view_file`, is the one that can look at a picture, and it opens nothing outside the folder it works in: a picture left where it was ends the turn with "reached for a tool of its own (ViewFile)". An attached folder is given with `--add-dir`.
- **Mentor's instruction files are put into the folder too** (`mentor-docs/NAME.md`, copied from `/etc/mentor` each time by `agy_folder`), and `--add-dir /etc/mentor` is given, because the instructions name them as `/etc/mentor/NAME.md` and its own `view_file` opens nothing outside the folder it works in: a refusal ends its turn with "Gemini reached for a tool of its own (ViewFile)". `AGY_PROMPT` tells it to open them as `mentor-docs/NAME.md` and to use the Mentor tool `file_read` for everything else. If that message still appears, read what it tried to open (the row above it in the chat): a path outside the folder that is not `/etc/mentor` is the model going its own way, and the answer is to add to `AGY_PROMPT`, not to widen what it may open.
- **Nothing else needs a rule.** Run with `-p` it cannot ask, so whatever would need approval is refused: its own `run_command`, and writing outside the folder. A refusal ends its turn with an empty answer and `denied_actions` in the result; mentor-chat then says so. `AGY_PROMPT` tells it not to try.
- **Its events** (`on_agy_event`): `init`; `step_update` with `step_type` `agent_response` (text in `text_delta`, piece by piece, until `state` is no longer `ACTIVE`) or `tool` (`tool_info.name`, `.parameters`, `.output`, `.error`; `state` `ACTIVE`, then `DONE` or `ERROR`); `result` with `status` (`SUCCESS` or not), `error`, `response`, `denied_actions`.
- **How it calls a Mentor tool**: through one tool of its own, `call_mcp_tool` with `ServerName`, `ToolName`, `Arguments`. Before that it reads how the tool is called, with `view_file` on a file under `~/.gemini/antigravity-cli/mcp/`; that step is not shown.
- **Signing in** (`mentor-engine gemini`): it has no command for it. Started without an account it asks, in a screen that fills the terminal, and stays open afterwards. So a loop beside it asks `agy models` every few seconds and closes it once that succeeds; the assistant then sees the sign-in when it gets the focus back. The token is kept in the session's keyring.
- **Effort** is part of its models' names (`gemini-3.8-flash-high`), so the Effort menu does not apply.
- Not signed in, a run waits about a minute and ends with `status: ERROR`, "authentication failed or timed out".
- The CLI carries its own documentation in `~/.gemini/antigravity-cli/builtin/skills/`; `agy --help` lists its options. Google's pages: `https://antigravity.google/docs/cli/headless/`, `/docs/permissions/`, `/docs/mcp/`.

## Cancel on the connect card

Choosing a model that is not ready yet (no key, not signed in) shows the connect card. It has **Cancel** when a working model was in use before: `choose_model` keeps it in `came_from` (only when leaving the chat, not when going from one connect card to another), and Cancel chooses it again. On a first start, with nothing working yet, there is no Cancel.

The card that "Set a key for …" in the model menu opens (`show_connect(change=…)`) has its own **Cancel**: it keeps the key the model has and goes back to the chat (`check_sign_in`).

## Changing the model in the middle of a conversation

The model is one for all tabs: choosing it in one changes them all, from their next question on.

- **A question already being answered** goes on with the model it started with. Its tab's model button goes on showing that model until the answer is done (`finish`), then shows the one chosen now (`choose_model` leaves busy tabs alone).
- **Within one engine** (Claude Opus to Sonnet, one ChatGPT model to another, NVIDIA's models among themselves) the engine's own session goes on, and the new model knows everything said.
- **To another engine** (Gemini to an NVIDIA model, say), the new engine has its own memory of the conversation, or none: `handover()` puts what it has not seen in front of the question ("You are taking over this conversation from another model…", the last 14000 characters). It goes by turns: each question starts one (`self.turn`, kept with every message), and `engine_seen` holds the last turn each engine took part in, so an engine coming back gets only what was said while it was away. A conversation taken up again from History is not handed over twice (`reopened` brings it).
- A small note marks each change above the question the new model answers: "GLM 5.3 handed over to Gemini" (`last_model`).

## How to tell that it works

| What | How |
|---|---|
| The maker's program is there | `command -v claude codex agy` (they live in `~/.local/bin`) |
| Signed in | the commands in the table above |
| A run by hand | the command in the table above, with a short message; it should end in a result that says success |
| The tools reach it | ask it for something only a tool can tell, such as whether a package exists; a row `package_search` should show |
| Usage | `/usr/local/lib/mentor/mentor-usage gemini` (or `codex`): windows, or `{}` when it cannot be told |
| The assistant itself | `journalctl -b --user | grep -A12 Traceback`; `mentor doctor` says whether it is running |
| What the engine really said | mentor-chat shows the engine's own words when a run fails. Do not replace them with a guess: "not signed in" once hid that the maker had retired its program. |

## When an engine stops working

An engine that is broken cannot mend itself: you are only reading this because some engine answers. If the user says one of the others has stopped, they have already switched to you; do the work below for the broken one, and tell them when to switch back and try it. If there is no engine left that answers, the free NVIDIA models need only a key.

1. **Run it by hand** with the command from the table and read what it prints. Tell apart: not signed in; the maker refusing the account or the program ("no longer supported", "not eligible"); an option that no longer exists; the tools refused; an answer in a shape the reader does not know.
2. **Read the maker's own word** on what changed: `--help` of the program, its release notes, its documentation. If the program has been replaced, find what replaces it for the same account and work through the rows of the tables above for the new one: how to run it without a terminal and get events, how to give it instructions, how to give it the Mentor server, how to keep its own shell and file writing off, how to go on with a conversation, how to tell whether one is signed in, how to sign in, how to read the allowance.
3. **Change it in the sandbox**: in mentor-chat, the run in `Conversation.send`, the reader (`on_…_event`) and `ACCOUNTS`. Keep the other engines as they are. `mentor-engine` and `mentor-usage` are in `/usr/local/lib/mentor`, which you cannot write: it holds the layer that keeps the agent in check, and that is not to be got around. When one of the two has to change, put the new one in `/usr/local/libexec/mentor/` under the same name and point mentor-chat at it (`ENGINE`, `USAGE`, near its top); the old one stays where it is, unused.
4. **Try it with the user's account**, not only with made-up answers: what a maker's server says to a real account is what decides. Ask the user to sign in, then run one message that needs a tool, one that tempts it to use a shell of its own, and a second message in the same conversation.
5. **Tell the user** what is the same and what differs (models, effort, what the allowance shows).
6. **Write down what you changed.** You cannot change this file (nothing in `/etc/mentor` is yours to write). Put what now differs from it in `~/.local/share/mentor/notes.md`, and tell the user, so that it can be carried into the image.

A change to mentor-chat takes effect when it is started again (at login, or `pkill -f bin/mentor-chat` and starting `/usr/local/bin/mentor-chat`); the others at the next message.

## Adding an engine

Add its models to `MODELS` and its submenu to `MENUS`; for an account, a row in `ACCOUNTS`, a case in `mentor-engine`, and what tells of its allowance (`USAGE_ASKED` and `mentor-usage`, or its own events); for a key, a row in `PROVIDERS` and its address in mentor-agent's `PROVIDERS`. Then the run in `Conversation.send`, a reader if it speaks in words of its own, a line in `ATTACHED` for how it gets at attached files, and a row in each table here. The first-start card (`show_choice`) takes its options from `MENUS` and needs a line saying what the engine needs.

## When the keyring is locked

The Antigravity CLI keeps the Google sign-in in the login keyring. A keyring that has a password (it gets one at a password login on systems built before that was turned off) is not opened by the automatic login. Asked while it was locked, the CLI took the user for signed out: at the start of the chat the usage check (`agy -p /usage`) opened a new Google sign-in in Chromium, and the sign-in check (`agy models`) made the chat show "Connect the agent" to someone who was signed in. Now `keyring_locked()` in `mentor-chat` is asked first (the `Locked` property of `/org/freedesktop/secrets/collection/login`): when it is locked the CLI is not run at all, and `show_keyring` shows a card instead, "Your saved sign-ins are locked", with **Unlock** (`unlock_keyring`: the Secret Service's `Unlock` and its prompt, GNOME's own password box; the sign-in is looked at again when it is answered) and **Open by itself from now on** (`keyring_for_good`: a password box of Mentor's own; `keyring_without_password` takes the password off the keyring with `ChangeWithMasterPassword` and opens it at once with `UnlockWithMasterPassword`, as `mentor keyring` does on a terminal; a wrong password says so and asks again). Never ask for the password in the chat. A keyring with no password is "locked" too until something first opens it (the automatic login does not): `keyring_locked()` opens such a one silently with the empty password (`UnlockWithMasterPassword`), and calls locked only one that has a password; without that, the card came up at every start of a system whose keyring opens by itself.

## When Gemini reaches for a tool of its own

The Antigravity CLI has tools of its own (RunCommand, its file editing). They are not allowed here, so that every change goes through Mentor's tools, and run headless a refused one ends its turn with no answer (`denied_actions` in its `result`). The first time in a request, `on_agy_event` sets it going again by itself: a note in the chat ("Gemini reached for a tool of its own; Mentor used its own, which ask you first and keep a record": the reason in a few words, for a user who does not know what a tool is) and `send(…, carry_on=True)` with a word to use the Mentor tools instead (`carry_prompt`), in the same conversation, with no bubble and nothing of the text box touched; the turn's steps and thumbs go on. A second refusal in the same request is shown as before: "Gemini reached for a tool of its own … Ask again."
