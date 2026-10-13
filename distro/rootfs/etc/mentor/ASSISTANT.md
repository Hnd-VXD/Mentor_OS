# The assistant on the desktop (mentor-chat)

This is for the agent, written so that a small model can follow it. The assistant is the program the user talks to you through. It is one Python file, `/usr/local/bin/mentor-chat`, about 2400 lines, which you can write (in the sandbox). This file says what the user is meant to have, where each thing is made in that file, what it leans on, how to tell that it works, and how to mend it. How the window is made to be the desktop is the shell extension's work: DESKTOP.md. Which model answers is ENGINES.md. The bell is SUGGESTIONS.md.

**The most important thing to know:** if mentor-chat does not start, the user has an empty wallpaper and no way to reach you except a terminal. Never apply a change to it that you have not started once and watched for an error. The check is in "How to test a change" below. A copy as built is always at `/etc/mentor/source/rootfs/usr/local/bin/mentor-chat`.

## What the user has

- **No window to open.** What the assistant says is written on the wallpaper, under every application. A click on the desktop, or Super+A, clears the windows away and puts the cursor in the text box; Escape or Super+A brings them back.
- **A text box at the bottom**, with a paperclip to its left and, to its right, the model button (ENGINES.md) and a send button that turns into a stop button while the agent works.
- **Conversations as tabs** at the top left, a "+" for a new one and a list of all of them. Each runs on its own, with its own sandbox, so several requests can be in progress at once. Each workspace has its own conversation in front.
- **What was said**: the user's words in a bubble on the right; the agent's as text in a dark card on the left, with light Markdown (bold, `code`, lists); a row for each tool call, with a spinner, then a tick, or a warning when it failed.
- **Attachments**: by the paperclip, by dropping files on the desktop, or by Ctrl+V (a copied picture is saved under `~/.cache/mentor/attachments/` and attached). They show as chips above the text box and go to the agent as paths.
- **Asking about something**: "Ask Mentor…" on an app icon makes the next message be about that application (a bar "About NAME" over the text box); on a file in Files it attaches the file; typing in the overview offers "Ask Mentor" with the typed words. Selecting words of the agent's and choosing to quote them makes the next message be about those words.
- **A timeline** at the right edge: a tick per message of the user's, which shows the message when pointed at and scrolls to it when clicked.
- **A right-click menu on the desktop**: Hide/Show chat, Clear chat…, New conversation, History…, Suggestions…, and Change Background…, Display Settings, Settings.
- **History**: everything ever said, searchable, also after a conversation was cleared.
- **Nothing is lost at logout**: the conversations come back at the next login.
- **A notification "Mentor has finished"** when an answer arrives while an application covers the desktop.
- **Warnings and problems of the system, in the chat**: a card with a light yellow ground for a warning (an application eating memory, a service that failed), a red one for a problem (the disk almost full, a part of Mentor broken, a start that was undone). Each has **Let Mentor look**, which hands it to the agent, and **Dismiss**. When the desktop is covered, a notification says that there is one.
- **On the very first start**: a card "Welcome to Mentor" with a button "Set up my system", and before that the card that asks which engine to use.
- **After a start that failed and was undone**: a message saying what was put back (BOOT.md).

## How it is started, and how others talk to it

- At login: `/etc/xdg/autostart/mentor-desktop.desktop` runs `/usr/local/bin/mentor-chat`.
- It is one instance (`Adw.Application` with the id `org.mentor.Chat`, `HANDLES_COMMAND_LINE`). Starting it again hands the request to the one that runs (`AssistantApp.do_command_line`):

| Command | What happens |
|---|---|
| `mentor-chat "a request"` | sent in the open conversation if nothing was asked in it yet, otherwise in a new one |
| `mentor-chat --app chromium.desktop` | the next message is about that application |
| `mentor-chat --file PATH…` | attaches the files |
| `mentor-chat --workspace N` | the shell says workspace N is in front |
| `mentor-chat` | goes to the desktop |

- It asks the shell extension to clear the windows away or bring them back over D-Bus: `org.gnome.Shell`, object `/org/mentor/Shell`, interface `org.mentor.Shell`, methods `Show` and `Restore` (`AssistantApp.shell`).
- The window is found by the extension by its application id `org.mentor.Chat`. Do not change that id.

## Where things are in the file

| Part | Where |
|---|---|
| Constants: paths, the prompt every engine gets (`SYSTEM_PROMPT`), models, engines | the top, to about line 200 |
| The look (`CSS`) | after the constants: transparent window, dark cards, the rounded text box |
| Markdown to markup (`to_markup`) | a few regular expressions; if the result is not valid markup, the plain text is shown |
| `class Conversation(Gtk.Box)` | one tab: text box, attachments, quote, subject, messages, timeline; `send` runs the engine, `on_line` reads what it prints, `on_block` draws a text or a tool row, `finish` ends the turn |
| `class DesktopWindow(Adw.ApplicationWindow)` | the one window: tabs, the model menu, the bell, history, the right-click menu, the cards for connecting an engine; `spawn` starts every program |
| `class AssistantApp(Adw.Application)` | start-up, the command line, the call to the shell |

What it keeps, all in the user's folders:

| What | File |
|---|---|
| The chosen model and effort | `~/.config/mentor/chat.json` |
| Keys of the hosted models | `~/.config/mentor/keys/` (mode 600) |
| That the first-start card was used | `~/.config/mentor/welcomed` |
| Suggestions turned away | `~/.config/mentor/advice.json` |
| The open conversations | `~/.local/state/mentor/conversations.json` |
| Everything ever said, a line each | `~/.local/state/mentor/history.jsonl` |
| The request each conversation is on, for the journal of changes (`note_request`; JOURNAL.md) | `~/.local/state/mentor/requests/` |
| Pasted pictures | `~/.cache/mentor/attachments/` |
| Models and usage last told | `~/.cache/mentor/` |

## Notices: how something gets into the chat as a yellow or red card

Anything that has something to tell the user leaves a file in `~/.local/state/mentor/notices/`:

```
NAME.json   {"level": "warning" or "problem", "title": "…", "text": "…", "prompt": "…"}
```

written under another name and renamed, so that it is whole when it is seen. `prompt` is what goes to the agent when the user presses Let Mentor look; leave it out and the card has only Dismiss. The assistant watches the folder (`show_notices` in `DesktopWindow`), shows each file once as a card in the conversation in front (`Conversation.add_notice`; the colours are `.notice.warning` and `.notice.problem` in `CSS`), and removes the file. A notice left while the assistant is not running is shown when it starts.

From a command line or a script, this does it:

```
mentor notice warning "TITLE" "TEXT" --prompt "WHAT THE AGENT IS ASKED"
mentor notice problem "TITLE" "TEXT"
```

From Python: `mentor_tools.leave_notice(level, title, text, prompt)`. Who leaves notices now: mentor-watch (SUGGESTIONS.md), the monitor when it is set up (MONITOR.md), and the assistant itself after a start that was undone. Use a warning for what the user should know and can leave; a problem for what will not go away by itself or has already cost something. Suggestions (updates, news) are not notices: they wait behind the bell.

Check: `mentor notice warning "A test" "Nothing is wrong."`, then screen_capture: a yellow card at the end of the chat.

## What it leans on

- **Packages**: `python`, `python-gobject`, `gtk4`, `libadwaita`, `libnotify`; `gnome-console` (`kgx`) for the sign-in terminal.
- **GTK 4**: `Gtk.Box`, `Gtk.Label` (with `use_markup`), `Gtk.Entry`, `Gtk.MenuButton` with a `Gio.Menu` and a child placed in it by `add_child(widget, "usage")`, `Gtk.Popover`, `Gtk.FileDialog`, `Gtk.CssProvider.load_from_string`, `Gtk.GestureClick`, `Gtk.DropTarget`, `Gdk.Clipboard`, `Gdk.Texture.save_to_png`.
- **libadwaita**: `Adw.Application`, `Adw.ApplicationWindow`, `Adw.TabView`, `Adw.TabBar`, `Adw.AlertDialog`, `Adw.Dialog`, `Adw.SwitchRow`, `Adw.WrapBox`, `Adw.Clamp`.
- **GLib/Gio**: `Gio.Subprocess` and `Gio.SubprocessLauncher`, `Gio.DataInputStream.read_line_async`, `Gio.Notification`, `Gio.File.monitor_file`, `Gio.DesktopAppInfo`.
- **The shell extension**, for being the desktop at all, and for `Show` / `Restore`.

A new GNOME brings new versions of GTK and libadwaita. A class or method that has gone shows as a Python traceback when the assistant starts, naming the line.

## How to tell that it works

| Check | Good answer |
|---|---|
| `pgrep -af bin/mentor-chat` | one line |
| `journalctl -b --user -o cat \| grep -B2 -A14 Traceback` | nothing |
| `python3 -c "import ast,sys; ast.parse(open('/usr/local/bin/mentor-chat').read()); print('ok')"` | `ok` (the file is at least valid Python) |
| `mentor verify \| grep mentor-chat` | nothing, or the notes say why it was changed |
| screen_capture | the text box at the bottom of the wallpaper, the "+" at the top left |
| `mentor-chat "Say hello in one word."` then screen_capture | the request on the right, an answer on the left |

## How to test a change (always, before applying it)

1. Work on a copy, never on the installed file:

   ```
   cp /usr/local/bin/mentor-chat ~/mentor-chat.new
   ```

2. Make the change in the copy (file_read, then file_write with the whole new text).
3. Check that it is valid Python:

   ```
   python3 -c "import ast; ast.parse(open('$HOME/mentor-chat.new').read()); print('ok')"
   ```

4. Start the copy in place of the running one and watch for an error, for twenty seconds:

   ```
   pkill -f bin/mentor-chat; sleep 2
   systemd-run --user --unit=mentor-chat-try python3 ~/mentor-chat.new
   sleep 20; systemctl --user status mentor-chat-try | head -5; journalctl --user -u mentor-chat-try -o cat | grep -A14 Traceback
   ```

   "active (running)" and no traceback is a pass. Then screen_capture, and try the thing you changed.
5. **If it fails**, start the installed one again at once, so the user has their desktop: `systemctl --user stop mentor-chat-try; systemd-run --user /usr/local/bin/mentor-chat`. Then mend the copy and go back to step 3.
6. **If it passes**, apply it through the sandbox (`install -m 755 /home/USER/mentor-chat.new /usr/local/bin/mentor-chat` in sandbox_run, then sandbox_apply), stop the trial and start the installed file: `systemctl --user stop mentor-chat-try; systemd-run --user /usr/local/bin/mentor-chat`. Write what you changed in `~/.local/share/mentor/notes.md`.

Lines about `Vulkan`, `MESA` or `ZINK` in the log are the graphics driver talking and are not errors of the assistant's.

## When it is broken

1. **The desktop is empty** (no text box). Is it running: `pgrep -af bin/mentor-chat`. If not, start it and read why it stopped:

   ```
   systemd-run --user --unit=mentor-chat-look /usr/local/bin/mentor-chat; sleep 8
   journalctl --user -u mentor-chat-look -o cat | tail -30
   ```

   - A traceback ending in `SyntaxError` or naming a line of mentor-chat with something that was changed: the file is damaged. Put it back: `cp -a /etc/mentor/source/rootfs/usr/local/bin/mentor-chat /usr/local/bin/mentor-chat` (sandbox_run, sandbox_apply), start it again.
   - A traceback naming a GTK or libadwaita class or method (`AttributeError: 'gi.repository.Adw' object has no attribute …`, `TypeError` in a constructor): the library moved on. Read the library's own notes for that name (GTK 4 and libadwaita publish what is deprecated and removed with each version, and what to use instead), make that one replacement in a copy, and test as above. Do the same for each name until it starts.
   - `ValueError: Namespace Adw not available` or `No module named gi`: a package is missing: `libadwaita`, `python-gobject`.
   - It runs, and the desktop is still empty: the fault is the extension's, which makes the window the desktop. DESKTOP.md, and `mentor doctor`.
2. **It starts, and a message gets no answer.** That is the engine: ENGINES.md. The assistant shows the engine's own words in red; read them.
3. **The conversations are gone after a login.** `~/.local/state/mentor/conversations.json`: a file that is not valid JSON is ignored. Everything said is still in `history.jsonl` beside it (History…).
4. **One part misbehaves** (the bell, the timeline, attachments): find its functions by name in the table above, read them, and test a change as above.

## Making it again from nothing

```
src=/etc/mentor/source/rootfs
cp -a $src/usr/local/bin/mentor-chat $src/usr/local/bin/mentor-agent /usr/local/bin/
cp -a $src/etc/xdg/autostart/mentor-desktop.desktop /etc/xdg/autostart/
cp -a $src/usr/share/applications/org.mentor.Chat.desktop /usr/share/applications/
install -D -m 644 $src/usr/share/icons/hicolor/256x256/apps/org.mentor.Chat.png /usr/share/icons/hicolor/256x256/apps/org.mentor.Chat.png
gtk-update-icon-cache -q -f /usr/share/icons/hicolor
```

in the sandbox, then apply, then the checks above. It needs the tools (TOOLS.md), an engine (ENGINES.md) and the extension (DESKTOP.md) to be of any use.
