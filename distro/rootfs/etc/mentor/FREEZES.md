# When the desktop freezes

This is for the agent. It says what Mentor does about a desktop that stops answering, how to read what it wrote down, and how to make each part again.

Everything of Mentor's that runs inside the desktop session (the assistant, the warnings, `mentor doctor`) freezes together with the desktop. So the watch on freezes runs outside it, as a system service, and is planned in stages:

1. **Prevent** (built): the desktop gets a larger share of the processor than apps.
2. **Notice and explain** (built): a stall is noticed from outside, written down with what was behind it, and told to the user afterwards in one sentence.
3. **Act, step by step** (built): a busy app is given less of the processor after 15 seconds; when memory has run out, the largest app is closed after 10. A GNOME Shell dead for a minute is only reported, never restarted: the user chose so (2026-10-15).
4. **An emergency key** (built): Ctrl+Alt+Backspace, read by a root service straight from the keyboards, opens the agent on a text console (tty3) beside the frozen desktop.

## What the user sees

After a stall of 5 seconds or more, a yellow card in the chat (at most one every 10 minutes): "The desktop froze for 20 seconds", with one sentence on what was behind it and what was done about it ("I gave Settings less of the processor", "I closed Chromium (2826 MB) to free memory"), and "Let Mentor look", which sends you the record. After a minute or more it also says that Ctrl+Alt+Backspace brings them to Mentor while the desktop is frozen.

**Ctrl+Alt+Backspace**, at any time: the screen switches to a text console, the user logged in, with the agent told that the desktop froze ("Mentor, emergency console"). The desktop goes on running behind it with their programs open. There you look at what is going on now and offer what would help (close the program behind it, or `systemctl restart gdm`, which closes their programs), and do it only after their yes. `/desktop` (or Ctrl+Alt+F2) goes back to the desktop. Ctrl+V there pastes the text last copied, on Windows or in Mentor (mentor-clipboard keeps it in `~/.cache/mentor/clipboard-text`, mode 600; `bind_paste` in mentor_repair.py binds it to the key before each prompt). A stray Ctrl+C or Ctrl+D at the prompt does not leave; after `/shell`, `desktop` (a shell function the profile hook defines) goes back. Answer in two or three short sentences, in simple words: what most likely happened, and whether they need to do anything.

## The parts

| What | Where | How to tell it works |
|---|---|---|
| The desktop's processor share | `/etc/systemd/user/session.slice.d/50-mentor-desktop-first.conf`: `CPUWeight=1000` for `session.slice` (GNOME Shell), against the default 100 of `app.slice` (apps). Mentor's assistant, the desktop window, raises its own share among the apps at start (`desktop_first` in mentor-chat: `systemctl --user set-property --runtime <its unit> CPUWeight=1000`) | `cat /sys/fs/cgroup/user.slice/user-$UID.slice/user@$UID.service/session.slice/cpu.weight` says 1000; the same `cpu.weight` of the assistant's unit (from `/proc/$(pgrep -f bin/mentor-chat)/cgroup`) says 1000 |
| The watch | `/usr/local/lib/mentor/mentor-sentinel`, `/etc/systemd/system/mentor-sentinel.service` (root, `Nice=-5`, enabled in customize.sh) | `systemctl is-active mentor-sentinel`; `journalctl -u mentor-sentinel` prints one line for each stall |
| What it wrote down | `/var/log/mentor/freezes.jsonl`, one JSON object per stall, the last 500; made empty when the watch starts, so an empty file means no freeze yet | readable by everyone: file_read |
| What it does during a stall (stage 3) | in `mentor-sentinel`: `act()`. After `LOWER_AFTER` (15) seconds, the app that used the processor most in the stall (at least half the time) is niced to 15 and its unit gets `CPUWeight=10` (`systemctl --user set-property --runtime`, or `cpu.weight` written straight); for as long as it runs. After `MEMORY_AFTER` (10) seconds with less than 3% of memory available, or all tasks waiting on memory 30% of the time (`/proc/pressure/memory`, "full"), the app using the most memory (`memory.current` of its cgroup) is closed, all of it (`cgroup.kill`). Only the user's apps (`user@UID.service/app.slice/`), never GNOME Shell, the session's services, Mentor's assistant or the system. Each is done once per stall and named in `actions` | `journalctl -u mentor-sentinel` says `lowered …` / `closed …` |
| The emergency key (stage 4) | `/usr/local/lib/mentor/mentor-emergency-key`, `/etc/systemd/system/mentor-emergency-key.service` (root, enabled in customize.sh): reads every `/dev/input/event*` with a Backspace key, without grabbing it; on Ctrl+Alt+Backspace it writes `/run/mentor/emergency`, restarts `mentor-emergency-console.service` and `chvt 3` | `journalctl -u mentor-emergency-key` says "the emergency key was pressed"; `fgconsole` says 3 |
| The emergency console | `/usr/local/lib/systemd/system/mentor-emergency-console.service` runs `/usr/local/lib/mentor/mentor-emergency-console`: **kmscon** (package `kmscon`) on VT 3, `--font-size` 16 pixels times the host's screen scale (`/run/mentor/host-scale`), `--login -- /bin/login -f USER`. kmscon draws at the size the display has when it starts (the launcher's window, or the whole screen), where the kernel's console keeps its boot size (1280x800, before the launcher sized the window); it does not follow a resize while it is open. If kmscon is missing or cannot take the screen within 5 seconds, the kernel's console on tty3 is used (`mentor-repair-console tty3`, the repair console's login, REPAIR.md); `/etc/profile.d/mentor-repair.sh` starts `mentor repair` with `MENTOR_EMERGENCY=1` there (tty3, or a login whose parent is kmscon: `mentor_under_kmscon`) when `/run/mentor/emergency` is less than two minutes old; `mentor_repair.py` then uses `EMERGENCY_PROMPT` and `EMERGENCY_OPENING`, and `/desktop` (`back_to_desktop`: `loginctl activate` of the graphical session). The first message to the agent carries `snapshot()`: whether GNOME Shell answers right now, the last five freezes, the busiest processes (`busiest()`, without the console and its helpers), memory and load, so that it can answer at once without tools | the key in a test VM: tty3 shows "Mentor, emergency console"; `/desktop` brings the desktop back |

How the watch works: root may not talk on the user's session bus, so it starts a small child as the logged-in user (`setpriv`), which asks GNOME Shell for `org.mentor.Shell.Status` every 2 seconds. That is answered by the shell's own main loop, the thing that stops when the desktop freezes. An answer later than 1 second is a stall. Meanwhile the root side reads how much processor time each process used (`/proc/*/stat`: every 2 seconds, every half second during a stall; it costs well under 1% of a processor) and the kernel's stall counters (`/proc/pressure/cpu`, `memory`, `io`), and when the stall ends it decides what it was.

## Reading a record

```
{"at": "2026-10-15T08:24:08", "seconds": 6.4, "kind": "processor", "culprit": "Settings",
 "processor_seconds": {"Settings": 17.5, ...}, "stalled_seconds": {"cpu": 0.0, "memory": 0.0, "io": 0.0},
 "paused_seconds": 0.0}
```

- `actions`: what the watch did (lowered or closed an app), in the words of the card; `shell_dead`: GNOME Shell did not answer for a minute or more (reported, not restarted).
- `kind`:
  - `processor`: a program used the processor for at least half the stall (`culprit`, named from its app; `processor_seconds` adds up over all processors, so 17.5 in 6.4 seconds is almost three processors).
  - `memory`: the kernel says programs waited for memory a quarter of the time or more. The system was short of memory; the largest program is the likely cause (`ps -eo rss,comm --sort=-rss | head`).
  - `disk`: programs waited for the disk half the time or more.
  - `graphics`: GNOME Shell did not answer while the processor, memory and disk were calm. In Mentor that is almost always drawing: with the graphics card on (the launcher's GPU and Vulkan), a program pushing many large pictures to it (Settings making previews of all the wallpapers the first time its Background page opens, on 2026-10-15) holds up the shell's own drawing. `culprit` is the program that was working at the time, if one used the processor noticeably.
  - `paused`: the whole computer was stopped (Windows asleep, the VM paused): the watch's own sleep took as long as the stall. Written down, never shown to the user, and nobody's fault.
- A stall in the middle of a restart of the assistant or the shell (an update, a log out) is not a freeze; the journal (journal_read) says when those happened.

What to tell the user: what was behind it in their words ("Settings was making previews of the wallpapers"), whether it will happen again (the previews are kept: the second time is fast), and only if it keeps happening, what would help (a program closed, the graphics card turned off in the launcher for a test, more memory in the launcher).

## Making it again

1. Files: copy the files above back from `/etc/mentor/source/rootfs/` (`sudo mentor restore PATH`), `chmod 755` the watch and the key.
2. `systemctl daemon-reload && systemctl enable --now mentor-sentinel mentor-emergency-key`; `systemctl --user daemon-reload` for the slice.
3. Check with the table above. To test without waiting for a real freeze: `kill -STOP $(pgrep -x gnome-shell); sleep 8; kill -CONT $(pgrep -x gnome-shell)` as root gives a `graphics` record and a card (the screen stands still for those 8 seconds: only with the user's agreement). The key: Ctrl+Alt+Backspace (in a test VM, QMP `send-key` ctrl, alt, backspace).
