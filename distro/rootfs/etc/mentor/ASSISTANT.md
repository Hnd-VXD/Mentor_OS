# The assistant on the desktop (mentor-chat)

This is for the agent, written so that a small model can follow it. The assistant is the program the user talks to you through. It is one Python file, `/usr/local/bin/mentor-chat`, about 2400 lines, which you can write (in the sandbox). This file says what the user is meant to have, where each thing is made in that file, what it leans on, how to tell that it works, and how to mend it. How the window is made to be the desktop is the shell extension's work: DESKTOP.md. Which model answers is ENGINES.md. The bell is SUGGESTIONS.md.

**The most important thing to know:** if mentor-chat does not start, the user has an empty wallpaper and no way to reach you except a terminal. Never apply a change to it that you have not started once and watched for an error. The check is in "How to test a change" below. A copy as built is always at `/etc/mentor/source/rootfs/usr/local/bin/mentor-chat`.

## What the user has

- **No window to open.** What the assistant says is written on the wallpaper, under every application. A click on the desktop, or Super+A, clears the windows away and puts the cursor in the text box; Escape or Super+A brings them back.
- **A text box at the bottom**, with a paperclip to its left and, to its right, the model button (ENGINES.md) and a send button that turns into a stop button while the agent works.
- **Conversations as tabs** at the top left, a "+" for a new one and a list of all of them. Each runs on its own, with its own sandbox, so several requests can be in progress at once. Each workspace has its own conversation in front.
- **What was said**: the user's words in a bubble on the right; the agent's as text in a dark card on the left, with light Markdown (bold, `code`, lists); a row for each tool call, with a spinner, then a tick, or a warning when it failed.
- **The steps card**: the tool calls of one answer share one card, with a turning gear and the time so far while the agent works, folded to "N steps · took M:SS · show them" when the answer comes (`add_step`, `show_steps`, `end_steps` in `mentor-chat`). The time is kept in the saved conversation as an item `{"took": seconds}` after the steps, so that the card says it again after a restart; conversations saved before that show no time.
- **No thumbs on answers.** For a few hours on 2026-10-14 the answers had thumbs that kept a way of doing it on this computer (`plays.jsonl`) and reminded the agent of it later. They were taken away again: matching requests by their words missed most of the same ones, simple requests gained nothing, and the real gains came from better tools. What the agent keeps doing by hand is turned into tools instead (TOOLS.md, "The tools made from what was done by hand"). A saved conversation item `{"thumbs": …}` is skipped when shown again; `~/.local/state/mentor/plays.jsonl` may be left from then and is not read.
- **App names while typing**: from the third letter of a word, the installed apps whose name has a word starting with it (the ones in the app grid, `Gio.AppInfo.should_show`) are listed just above the text box with their icons, at most 5. Nothing is changed in the text until Tab, which puts the highlighted name in place of the word; the arrows move the highlight, Escape hides the list, a click picks one. `installed_apps`, `apps_matching` and `Conversation.update_suggestions` in `mentor-chat`; the list is read again when an app is added or removed (`Gio.AppInfoMonitor`). A picked app is a real reference, not just words: its icon goes into the line, in front of its name in blue (the text box is `AskBox`, a `Gtk.TextView` made to behave like the entry it replaced, because a one-line `Gtk.Entry` holds text only; the icon is a child anchor). Taking out the icon, or editing the name, makes it plain words again (`AskBox.on_changed`). Enter sends, Shift+Enter starts a new line. Sent, the message shows each picked name with its icon inline, in the words (`words_with_apps`) (saved in the history item as `apps`: name -> desktop id), and the agent gets, after the user's words, which installed application each name means: its desktop file and command (`picked_note`).
- **Attachments**: by the paperclip, by dropping files on the desktop, or by Ctrl+V (a copied picture is saved under `~/.cache/mentor/attachments/` and attached). They show as chips above the text box and go to the agent as paths. A click on a chip, or on the 📎 note under a sent message (kept in the history as `{"note", "files"}`), opens the file: a picture at once in a preview over the chat (`preview_picture`; a click, Esc or × closes it), anything else in its usual program (`open_attachment`, in a `systemd-run --user --scope`). A right click on the name or the preview (`open_with_menu`) offers "Open with…" (GNOME's app chooser, `Gtk.FileLauncher` with `always_ask`).
- **Asking about something**: "Ask Mentor…" on an app icon puts that application into the text box as a picked one (its icon and name, then a space, as when it is typed and picked with Tab; `set_subject`), in the conversation in front unless the agent is working in it; the agent is told which application it is (`picked_note`). It used to be a bar "About NAME" over the text box; on a file in Files it attaches the file; typing in the overview offers "Ask Mentor" with the typed words. Selecting words of the agent's and choosing to quote them makes the next message be about those words.
- **A timeline** at the left edge: a tick per message of the user's, which shows the message when pointed at and scrolls to it when clicked. The tick of the message the view is at is lit (`mark_tick`): the last one at or above a line a third of the way down the view. Over the first page of scrolling that line slides up to the top of the view, and over the last page down to the bottom, so that at the very top the first message is lit and at the end the last one (short messages near either end never cross a third), and each scroll on the way moves the mark about one message on. (A first version lit the last message only once the view was at the very end, and the mark jumped there from several messages back; the next one could not light the first marks at the top.)
- **History** is at the end of the list button at the top left (beside +). **A right-click menu on the desktop**: Hide/Show chat, New conversation and Clear chat (while the chat shows; Clear chat when something was said and the agent is not answering in it, and it asks first), Report a problem… (asks you, in that chat, for a problem report: UPDATES.md), Suggestions…, Mentor Settings… (SETTINGS.md), and Change Background…, Display Settings, Settings.
- **A log out stands out**: in the agent's answers (the chat, and the bubble over the box of Super+Z) the words "log out" / "logout" / "log-out" are bold and blue (`LOG_OUT` in `_inline`, not inside `code`): it is the one step an answer asks the user to do themselves, and their windows close with it. The bubble is drawn with `to_markup` like the chat.
- **Over a program**: Alt+Space or Super+Z lifts this text box out of the desktop and shows it over the program in front, with a picture of the screen attached; the answer also shows in a bubble above it, and Esc in the box (or the same key again) puts it back; it stays on top while the user works in other windows (ASKBAR.md).
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
NAME.json   {"level": "warning", "problem" or "idea", "title": "…", "text": "…", "prompt": "…", "auto": true}
```

written under another name and renamed, so that it is whole when it is seen. `prompt` is what goes to the agent when the user presses Let Mentor look; leave it out and the card has only Dismiss. With `"auto": true` the assistant sends the prompt on by itself as soon as the card is shown, when an engine is chosen (only `mentor-firewall-watch` leaves such notices; SECURITY.md). The assistant watches the folder (`show_notices` in `DesktopWindow`), shows each file once as a card in the conversation in front (`Conversation.add_notice`; the colours are `.notice.warning` and `.notice.problem` in `CSS`), and removes the file. A notice left while the assistant is not running is shown when it starts.

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
