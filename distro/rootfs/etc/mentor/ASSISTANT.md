# The assistant on the desktop (mentor-chat)

This is for the agent, written so that a small model can follow it. The assistant is the program the user talks to you through. It is one Python file, `/usr/local/bin/mentor-chat`, about 2400 lines, which you can write (in the sandbox). This file says what the user is meant to have, where each thing is made in that file, what it leans on, how to tell that it works, and how to mend it. How the window is made to be the desktop is the shell extension's work: DESKTOP.md. Which model answers is ENGINES.md. The bell is SUGGESTIONS.md.

**The most important thing to know:** if mentor-chat does not start, the user has an empty wallpaper and no way to reach you except a terminal. Never apply a change to it that you have not started once and watched for an error. The check is in "How to test a change" below. A copy as built is always at `/etc/mentor/source/rootfs/usr/local/bin/mentor-chat`.

## What the user has

- **No window to open.** What the assistant says is written on the wallpaper, under every application. A click on the desktop, or Super+A, clears the windows away and puts the cursor in the text box; Escape or Super+A brings them back.
- **A text box at the bottom**, with a paperclip to its left and, to its right, the model button (ENGINES.md) and a send button that turns into a stop button while the agent works. It is 6 pixels from the taskbar below, as far as from the line above it (`bar`'s `margin_bottom` and `bottom`'s `margin_top` in `mentor-chat`; 28 left a wide gap, the user, 2026-10-19). The same row is the box over a program (ASKBAR.md), so it sits as close above the taskbar there too.
- **Conversations as tabs** at the top left, a "+" for a new one and a list of all of them. Each runs on its own, with its own sandbox, so several requests can be in progress at once. Each workspace has its own conversation in front.
- **What was said**: the user's words in a bubble on the right; the agent's as text in a dark card on the left, with light Markdown (bold, `code`, lists); a row for each tool call, with a spinner, then a tick, or a warning when it failed.
- **The steps card**: the tool calls of one answer share one card, with a turning gear and the time so far while the agent works, folded to "N steps · took M:SS · show them" when the answer comes (`add_step`, `show_steps`, `end_steps` in `mentor-chat`). The gear is turned by a timer, a sixteenth of a turn every 90 ms through the CSS classes `turn-0`…`turn-15` (`GEAR_STEPS`), not by a CSS animation: Mentor has GNOME's animations off (`enable-animations=false` in `/etc/dconf/db/local.d/00-mentor`), and GTK leaves CSS animations still then. The time is kept in the saved conversation as an item `{"took": seconds}` after the steps, so that the card says it again after a restart; conversations saved before that show no time. Text in an engine's "user" events (the tools' answers) is never drawn (`on_event`): Claude's CLI puts notes such as "[Image: original 3840x2160, displayed at …]" there after it reads a picture, and they showed as Mentor's words between one-step cards (2026-10-22).
- **No thumbs on answers.** For a few hours on 2026-10-14 the answers had thumbs that kept a way of doing it on this computer (`plays.jsonl`) and reminded the agent of it later. They were taken away again: matching requests by their words missed most of the same ones, simple requests gained nothing, and the real gains came from better tools. What the agent keeps doing by hand is turned into tools instead (TOOLS.md, "The tools made from what was done by hand"). A saved conversation item `{"thumbs": …}` is skipped when shown again; `~/.local/state/mentor/plays.jsonl` may be left from then and is not read.
- **App names while typing**: from the third letter of a word, the installed apps whose name has a word starting with it (the ones in the app grid, `Gio.AppInfo.should_show`) are listed just above the text box with their icons, at most 5. Nothing is changed in the text until Tab, which puts the highlighted name in place of the word; the arrows move the highlight, Escape hides the list, a click picks one. `installed_apps`, `apps_matching` and `Conversation.update_suggestions` in `mentor-chat`; the list is read again when an app is added or removed (`Gio.AppInfoMonitor`). A picked app is a real reference, not just words: its icon goes into the line, in front of its name in blue (the text box is `AskBox`, a `Gtk.TextView` made to behave like the entry it replaced, because a one-line `Gtk.Entry` holds text only; the icon is a child anchor). Taking out the icon, or editing the name, makes it plain words again (`AskBox.on_changed`). Enter sends, Shift+Enter starts a new line. Sent, the message shows each picked name with its icon inline, in the words (`words_with_apps`) (saved in the history item as `apps`: name -> desktop id), and the agent gets, after the user's words, which installed application each name means: its desktop file and command (`picked_note`).
- **Attachments**: by the paperclip, by dropping files on the desktop, or by Ctrl+V (a copied picture is saved under `~/.cache/mentor/attachments/` and attached). They show as chips above the text box and go to the agent as paths. A click on a chip, or on the 📎 note under a sent message (kept in the history as `{"note", "files"}`), opens the file: a picture at once in a preview over the chat (`preview_picture`, solid so the chat does not show through, in the user's window colors as all the chat's dialogs are (DESKTOP.md, "Window colors"); a click, Esc or × closes it), anything else in its usual program (`open_attachment`, in a `systemd-run --user --scope`). A right click on the name or the preview (`open_with_menu`) offers "Open with…" (GNOME's app chooser, `Gtk.FileLauncher` with `always_ask`). A drag on an empty part of the preview or any dialog of the chat (its title, a margin) does nothing (`keep_still`): libadwaita gives a dialog's sheet the drag of the window it is in, and that window is the desktop, which then jumped back and forth under the mouse (2026-10-18). A drag on the dimmed space around a dialog, which the chat never sees (the dialog is a window attached to the desktop, and the window manager moves the desktop with it), is held still by the shell: Mentor's extension shifts the desktop's picture back while it is dragged, so nothing moves on the screen (`_holdStill`, DESKTOP.md "The desktop cannot be moved, hidden or closed by mistake"; fixed 2026-10-19, `Status` `desktop_put_back` stays 0).
- **Asking about something**: "Ask Mentor…" on an app icon puts that application into the text box as a picked one (its icon and name, then a space, as when it is typed and picked with Tab; `set_subject`), in the conversation in front unless the agent is working in it; the agent is told which application it is (`picked_note`). It used to be a bar "About NAME" over the text box; on a file in Files it attaches the file; typing in the overview offers "Ask Mentor" with the typed words. Selecting words of the agent's and choosing to quote them makes the next message be about those words.
- **A timeline** at the left edge: a tick per message of the user's, which shows the message when pointed at and scrolls to it when clicked. The tick of the message the view is at is lit (`mark_tick`): the last one at or above a line a third of the way down the view. Over the first page of scrolling that line slides up to the top of the view, and over the last page down to the bottom, so that at the very top the first message is lit and at the end the last one (short messages near either end never cross a third), and each scroll on the way moves the mark about one message on. (A first version lit the last message only once the view was at the very end, and the mark jumped there from several messages back; the next one could not light the first marks at the top.)
- **History**, **Network…** and **Important warnings…** are at the end of the list button at the top left (beside +): Network… lists the programs that asked to go online, with what was answered, Allow / Block / Unblock and Ask Mentor; Important warnings… lists the red cards shown, newest first, each with Ask Mentor (SECURITY.md, "Programs going online"; `show_network`, `show_warnings`; the user's wish, 2026-10-23). **A right-click menu on the desktop**: Hide/Show chat, New conversation and Clear chat (while the chat shows; Clear chat when something was said and the agent is not answering in it, and it asks first), then Report a problem… (asks you, in that chat, for a problem report: UPDATES.md), then Themes (Mentor Settings on its Themes tab: `mentor-settings themes`; the desktop picture is in that tab too, the user's wish, 2026-10-24), Mentor Settings… (SETTINGS.md, with the bell's suggestions as a tab) and Settings (GNOME's; Display Settings is inside it).
- **A log out stands out**: in the agent's answers (the chat, and the bubble over the box of Super+Z) the words "log out" / "logout" / "log-out" are bold and blue (`LOG_OUT` in `_inline`, not inside `code`): it is the one step an answer asks the user to do themselves, and their windows close with it. The bubble is drawn with `to_markup` like the chat.
- **Links in answers, with icons** (the user's wish, 2026-10-22): the agent writes `[name](target)` for a file (`file:///full/path`), an installed app (`app:pinta.desktop`), a page of GNOME Settings (`settings:display`, from the page's own desktop file `gnome-display-panel.desktop`) or a web page (`https://…`); `SYSTEM_PROMPT` tells every engine so. The chat shows the name in blue with that thing's icon in front, as a picked app is shown in the text box, and a click opens it: a picture in the preview over the chat, another file in its usual program (`open_attachment`), an app with `gtk-launch`, a Settings page with `gnome-control-center PAGE`, a web page with `gio open`, each in a scope of its own (`launch`). Nothing else is ever opened: other kinds of target are not links (`LINK`), and a link to a file, app or page that is not there is shown as its plain name (`link_target`, `with_links`). A `Gtk.Label` cannot hold an icon, so an answer with links is an `AnswerView` (a read-only `Gtk.TextView` with the icons as child anchors) that answers to what the chat asks of an answer's label (`set_markup`, `get_text`, `get_selection_bounds`), so Quote, Show more and the question at the end work as before; it is made as wide as its longest line (`fit`), as a label is. Every other answer is still a label. In History and in the bubble over a program a link is its name only (`_inline`). When a link does not open: is the target there (`link_target`)? For a Settings page, does `/usr/share/applications/gnome-PAGE-panel.desktop` exist (a new GNOME may rename pages)?
- **Over a program**: Alt+Space or Super+Z lifts this text box out of the desktop and shows it over the program in front, with a picture of the screen attached; the answer also shows in a bubble above it (fully solid, so that the page behind does not show through: `window.ask-over` in the CSS of `mentor-chat`), and Esc in the box (or the same key again) puts it back; it stays on top while the user works in other windows (ASKBAR.md).
- **History**: everything ever said, searchable, also after a conversation was cleared. Each of Mentor's answers has, above it in grey after ↪, the user's words it answered, whole (`DesktopWindow.user_words` reads the user's lines of `history.jsonl` once when History opens; `history_card(..., asked)`); the tab's title, cut at 28 letters, names the conversation only where there are no such words. A suggestion taken to the chat starts with its own title ("New projects on GitHub…: what can we make of it?", `take_advice`), so conversations started from the bell are told apart.
- **Larger or smaller text**: Ctrl and the mouse wheel over the conversation (up: larger), or Ctrl + `+` / `-` / `0` (0 is back to 100%), shows the conversations from 70% to 200% in steps of 10; the column of cards widens and narrows with the text (720 pixels at 100%, `CHAT_WIDTH`), so a line holds as many words at any size. A pill at the top right, under the bell, says the new size for a moment (`zoom_shown`; at the middle of the top row it covered the tabs). It is the same for every tab and is kept in `~/.config/mentor/chat.json` as `"zoom": 120`. How: the conversation's scroller has the CSS class `chat-zoom`; a second `Gtk.CssProvider` (`DesktopWindow.zoom_css`, priority APPLICATION + 1) holds `.chat-zoom { font-size: N%; }` (`zoom_css()`), and `set_zoom` loads it again and sets each `Conversation.column` (`Adw.Clamp`) to `maximum_size = 720 * N / 100`. The wheel is an `Gtk.EventControllerScroll` in the capture phase on each conversation's scroller (`DesktopWindow.on_zoom_scroll`: without Ctrl it does nothing and the view scrolls; with Ctrl it returns True so the view does not scroll too; a touchpad's pixels are counted 40 to a step). Each view keeps showing the same messages: `set_zoom` notes the point at the middle of it (or that it was at the end) and puts it back 60 ms later, once the text has its new size; the keys are an `Gtk.EventControllerKey` in the capture phase on the window (`on_zoom_key`, only while the chat shows, not on the sign-in cards). The text box at the bottom and the box over a program (Super+Z) keep their size. On Wayland an app sees Ctrl with the wheel only while it has the keyboard; after a start nothing had it, and Ctrl and the wheel did nothing until the user clicked into the chat (2026-10-18). So the shell extension gives the assistant the keyboard whenever no other window has it (`_focusWhenAlone` in `DesktopLayer`, on `notify::focus-window` and when the assistant's window is taken over): at the start and when the last app window closes. When Ctrl and the wheel do not zoom: does Ctrl and `+` zoom? Then the chat did not have the keyboard: a click into it gives it; tell the user so and check that `_focusWhenAlone` is still in the extension. It was first made on 2026-10-17 by a user's own agent as a recipe; the recipes site refuses recipes that change Mentor's own files, so it became part of Mentor.
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
| `mentor-chat --uninstall chromium.desktop` | "Uninstall NAME" sent at once, in a new conversation (the icon menu's Uninstall; UNINSTALL.md) |
| `mentor-chat --file PATH…` | attaches the files |
| `mentor-chat --workspace N` | the shell says workspace N is in front |
| `mentor-chat` | goes to the desktop |

- It asks the shell extension to clear the windows away or bring them back over D-Bus: `org.gnome.Shell`, object `/org/mentor/Shell`, interface `org.mentor.Shell`, methods `Show` and `Restore` (`AssistantApp.shell`).
- The window is found by the extension by its application id `org.mentor.Chat`. Do not change that id.

## Where things are in the file

| Part | Where |
|---|---|
| Constants: paths, the prompt every engine gets (`SYSTEM_PROMPT`), models, engines | the top, to about line 200 |
| The look (`CSS`) | after the constants: transparent window, dark cards, the rounded text box; the green, yellow and red cards (`.notice`) nearly solid, a deep tone of their color with the color in the border and buttons (at a third of a color they could hardly be read over a light wallpaper, 2026-10-19) |
| Markdown to markup (`to_markup`) | a few regular expressions; if the result is not valid markup, the plain text is shown |
| `class Conversation(Gtk.Box)` | one tab: text box, attachments, quote, subject, messages, timeline; `send` runs the engine, `on_line` reads what it prints, `on_block` draws a text or a tool row, `finish` ends the turn |
| `class DesktopWindow(Adw.ApplicationWindow)` | the one window: tabs, the model menu, the bell, history, the right-click menu, the cards for connecting an engine; `spawn` starts every program |
| `class AssistantApp(Adw.Application)` | start-up, the command line, the call to the shell |

What it keeps, all in the user's folders:

| What | File |
|---|---|
| The chosen model and effort, the text size (`zoom`) | `~/.config/mentor/chat.json` |
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

written under another name and renamed, so that it is whole when it is seen. `"net": "/path/of/program"` makes it the card of a program waiting to go online, with Block and Allow; `"network": true` (several of them at once) gives it Open Network… (SECURITY.md). Every card shown is also kept, a line each, in `~/.local/state/mentor/cards.jsonl` (`log_card`; the older half goes past 1 MB), which Important warnings… reads. `prompt` is what goes to the agent when the user presses Let Mentor look; leave it out and the card gets **Talk about it**, which asks you, in a new conversation, what the card means and whether anything needs doing (an update card without notes gets What's new? instead): every card, green, yellow or red, can be taken into a conversation. `"quiet": true` (mentor notice --quiet) shows only the card, without GNOME's pop-up notification; the updater's cards are quiet. With `"auto": true` the assistant sends the prompt on by itself as soon as the card is shown, when an engine is chosen (only `mentor-firewall-watch` leaves such notices; SECURITY.md). The assistant watches the folder (`show_notices` in `DesktopWindow`), shows each file once as a card in the conversation in front (`Conversation.add_notice`; the colours are `.notice.warning` and `.notice.problem` in `CSS`), and removes the file. A notice left while the assistant is not running is shown when it starts.

From a command line or a script, this does it:

```
mentor notice warning "TITLE" "TEXT" --prompt "WHAT THE AGENT IS ASKED"
mentor notice problem "TITLE" "TEXT"
```

From Python: `mentor_tools.leave_notice(level, title, text, prompt)`. Who leaves notices now: mentor-watch (SUGGESTIONS.md), the monitor when it is set up (MONITOR.md), and the assistant itself after a start that was undone. Use a warning for what the user should know and can leave; a problem for what will not go away by itself or has already cost something. Suggestions (updates, news) are not notices: they wait behind the bell.

Check: `mentor notice warning "A test" "Nothing is wrong."`, then screen_capture: a yellow card at the end of the chat.

## What it leans on

- **Packages**: `python`, `python-gobject`, `gtk4`, `libadwaita`, `libnotify`; `gnome-console` (`kgx`) for the sign-in terminal.
- **GTK 4**: `Gtk.Box`, `Gtk.Label` (with `use_markup`), `Gtk.Entry`, `Gtk.MenuButton` with a `Gio.Menu` and a child placed in it by `add_child(widget, "usage")`, `Gtk.Popover`, `Gtk.FileDialog`, `Gtk.CssProvider.load_from_string`, `Gtk.GestureClick`, `Gtk.EventControllerScroll`, `Gtk.DropTarget`, `Gdk.Clipboard`, `Gdk.Texture.save_to_png`.
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

In the user's words: the desktop is empty; there is no chat; the chat does not open; the chat is gone; the assistant does not start; the assistant does not answer; a message gets no answer; the conversations are gone.

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

The owl on the big cards in the middle (the welcome, "Connect the agent", the keyring) is the simpler one, Mentor Settings' icon `org.mentor.Settings` (`CARD_ICON` in `mentor-chat`, the user's choice on 2026-10-17); the assistant's entry (`org.mentor.Chat.desktop`, and `org.mentor.Review.desktop`) uses that one too, `Icon=org.mentor.Settings`, so notifications and GNOME's log-out dialog show the simpler owl (the user's choice, 2026-10-19); the round emblem `org.mentor.Chat.png` stays installed but is no longer shown.

```
src=/etc/mentor/source/rootfs
cp -a $src/usr/local/bin/mentor-chat $src/usr/local/bin/mentor-agent /usr/local/bin/
cp -a $src/etc/xdg/autostart/mentor-desktop.desktop /etc/xdg/autostart/
cp -a $src/usr/share/applications/org.mentor.Chat.desktop /usr/share/applications/
install -D -m 644 $src/usr/share/icons/hicolor/256x256/apps/org.mentor.Chat.png /usr/share/icons/hicolor/256x256/apps/org.mentor.Chat.png
install -D -m 644 $src/usr/share/icons/hicolor/256x256/apps/org.mentor.Settings.png /usr/share/icons/hicolor/256x256/apps/org.mentor.Settings.png
gtk-update-icon-cache -q -f /usr/share/icons/hicolor
```

in the sandbox, then apply, then the checks above. It needs the tools (TOOLS.md), an engine (ENGINES.md) and the extension (DESKTOP.md) to be of any use.
