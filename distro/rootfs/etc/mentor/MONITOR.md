# A quiet watch on the system: what it is, and how to set it up on this install

This is for the agent, written so that a small model can follow it. Mentor does not come with this switched on. It is set up for the user of this install when they ask for it ("keep an eye on the system", "tell me when something eats my memory", "watch for odd network traffic"), and set up again from this file if it is ever lost. The program is already written and kept at `/etc/mentor/extras/monitor/`; setting it up is copying three files and starting a service. Say what it will and will not do before you set it up, and only when they say so.

## What the user gets

- **Nothing to see while all is well.** A small program of the user's own looks at the system every half minute. No model is involved in the looking, so it costs no tokens. It is held to 3% of a processor and 64 MB of memory by its service, and uses far less.
- **A card in the assistant's chat when something is out of the ordinary**: light yellow for a warning, red for a problem (`pressure` and `oom`). One at a time, and not the same one again for three days. When the desktop is covered, a notification says that there is one:

| Kind | Raised when |
|---|---|
| `memory` | an application holds more than 40% of the memory for five minutes; or more than three times what is usual for it, and more than 1 GB |
| `growth` | an application's memory went up in four looks out of five for twenty minutes, by more than 500 MB in all |
| `pressure` | the system is short of memory (`some avg60` of `/proc/pressure/memory` above 20) for three minutes |
| `cpu` | an application used more than 90% of one processor for fifteen minutes |
| `oom` | the kernel stopped a program for lack of memory |
| `upload` | more than 200 MB sent in five minutes, and more than five times what is usual at that hour |
| `listener` | a port is being listened on, reachable from the network, that was not open on any earlier day |

- **A button on the card, "Let Mentor look"**, which hands the agent a request that already carries the figures. Only then is a model called.
- **An answer to "why is my system slow?"** from what was recorded.
- **A way to change what counts, to switch it off, and to remove it.**

Tell the user the limits plainly:

- It notices what is unusual for this computer. It is not a virus scanner and will not recognise something made to hide.
- It knows how much data went out in all, and which programs had connections open at the time. It does not know how much each program sent: that needs root, and is not part of this.
- "Usual" is learned over the first three days. Until then only the fixed figures above count.
- Nothing is raised in the first ten minutes after it starts, when a login starts everything at once.

## Setting it up

Nothing here needs root or the sandbox: everything lives in the user's own folders. Run these with run_command, one block at a time, and check each answer.

**1. Copy the program and its service.**

```
install -D -m 755 /etc/mentor/extras/monitor/monitor.py ~/.local/lib/mentor-monitor/monitor.py
install -D -m 644 /etc/mentor/extras/monitor/mentor-monitor.service ~/.config/systemd/user/mentor-monitor.service
```

**2. Look once, without raising anything.** This shows that it sees the applications.

```
python3 ~/.local/lib/mentor-monitor/monitor.py --once --print
```

Good answer: a line `Applications seen:` naming what is open, a line `Memory:`, and `Nothing would be raised.` If it prints a Python error instead, stop: read "When it does not work".

**3. Show that it would raise something**, with a program that takes 600 MB on purpose and the test settings (which ask for 5% of the memory and no waiting):

```
systemd-run --user --quiet --scope --unit=app-gnome-memtest-1 python3 -c "x = bytearray(600 << 20); import time; time.sleep(40)" &
sleep 6
python3 ~/.local/lib/mentor-monitor/monitor.py --once --print --settings /etc/mentor/extras/monitor/test-settings.json
```

Good answer: `Would be raised:` and a line `[memory] memtest is using a lot of memory`. (On a computer with more than 12 GB of memory 600 MB is under 5%: use `bytearray(2000 << 20)`.)

**4. Start it, now and at every login.**

```
systemctl --user daemon-reload
systemctl --user enable --now mentor-monitor.service
sleep 5; systemctl --user status mentor-monitor.service | head -6
```

Good answer: `active (running)`.

**5. Tell the user** it is running, what it watches, the limits above, and how to switch it off. Write in `~/.local/share/mentor/notes.md` the date and that the monitor was set up.

## Its files

| What | Where |
|---|---|
| The program, as kept by Mentor (you cannot change these) | `/etc/mentor/extras/monitor/monitor.py`, `mentor-monitor.service`, `test-settings.json` |
| The program as it runs | `~/.local/lib/mentor-monitor/monitor.py` |
| Its service | `~/.config/systemd/user/mentor-monitor.service` |
| Its settings (only what differs from the defaults) | `~/.config/mentor-monitor/settings.json` |
| What it recorded: one line per five minutes, kept two weeks | `~/.local/state/mentor-monitor/samples.jsonl` |
| What is usual, what was raised and when, the ports seen | `~/.local/state/mentor-monitor/usual.json`, `raised.json`, `listeners.json` |

## Changing what counts

The figures are the dictionary `DEFAULTS` at the top of `monitor.py`, each with a comment. To change one, write only that one into the settings file and restart the service. For example, to be told at 30% instead of 40%, and never about new listeners:

```
mkdir -p ~/.config/mentor-monitor
echo '{"memory_share": 0.30, "never": ["listener"]}' > ~/.config/mentor-monitor/settings.json
systemctl --user restart mentor-monitor.service
```

`"never"` lists the kinds the user does not want to hear of. `"remind_after_days"` is how long the same finding stays quiet.

## Answering from what was recorded

When the user asks why the system is slow, what used the memory, or what happened earlier:

```
python3 ~/.local/lib/mentor-monitor/monitor.py --report 24
```

(the number is hours). It prints at most forty lines: the applications that held the most memory and used the most processor time, how often the system was short of memory, the data sent and received, and what was raised. Answer from that. Do not read `samples.jsonl` itself: it is long, and reading it is what would cost tokens.

## How it works, for mending it

- **Applications** are the control groups GNOME starts them in: `/sys/fs/cgroup/user.slice/user-UID.slice/user@UID.service/app.slice/`, named `app-gnome-NAME-PID.scope`, `app-flatpak-NAME-PID.scope`, or `app-dbus\x2d:1.N\x2dNAME.slice` (`\x2d` stands for `-`). In each, `memory.current` is the memory in bytes and the first line of `cpu.stat` (`usage_usec`) the processor time so far, which only grows: the share of a processor is the difference between two looks over the time between them. (`applications`, `app_name`)
- **The whole system**: `/proc/meminfo` (`MemTotal`, `MemAvailable`), `/proc/pressure/memory` (the first line's `avg60`), `/proc/net/dev` (bytes received are the first number after the interface's name, bytes sent the ninth; `lo` is left out). (`system`)
- **Killed for lack of memory**: `journalctl -k -o cat --since=@TIME`, lines with `Out of memory`, `oom-kill` or `Killed process`. (`killed_since`)
- **Listening**: `ss -H -tunl`, leaving out what only this computer can reach. **Who is talking**: `ss -H -tunp`. (`listening`, `talking`)
- **The rules** are `Watch.findings`; each returns a kind, what it is about, a title, the notification's text, and the request for the assistant.
- **Speaking** is `notify`: it leaves a notice, a file `{"level", "title", "text", "prompt"}` in `~/.local/state/mentor/notices/`, which the assistant shows as a card (ASSISTANT.md, "Notices"). `PROBLEMS` near the top names the kinds shown in red. Only when the assistant is not running does it use `notify-send`.
- It needs nothing but Python's own library, `ss` (package `iproute2`) and `notify-send` (package `libnotify`).

## When it does not work

| What you see | What it is | What to do |
|---|---|---|
| `Applications seen:` is empty | the folder of control groups is elsewhere on this system | `ls /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/` and look for where the `app-…` groups are; set `APPS` in your copy of the program to that folder |
| a Python error naming a line | something the program reads has changed shape | read that line and the file it reads (`cat` it); mend your copy in `~/.local/lib/mentor-monitor/`; run step 2 again |
| the service is `failed` | it stopped with an error | `journalctl --user -u mentor-monitor -n 30 -o cat` |
| cards never come though step 3 passes | waiting ten minutes after a start, or the finding was raised in the last three days | `cat ~/.local/state/mentor-monitor/raised.json`; delete that file to start afresh |
| too many cards of one kind | the figure is too low for this computer | raise it in the settings, or put the kind in `"never"`, as the user prefers |
| a finding is raised (`raised.json` has it) and no card shows | the assistant is not running, or does not read the folder | `ls ~/.local/state/mentor/notices/` (a file left there was not taken); `mentor notice warning "A test"` by hand; ASSISTANT.md |

After mending your copy, write what you changed in `~/.local/share/mentor/notes.md`: the copy in `/etc/mentor/extras/monitor/` stays as it was, and that note is how the change is carried into the next image.

## Switching off, removing, setting up again

- Off: `systemctl --user disable --now mentor-monitor.service`. On again: `enable --now`.
- Remove: that, then

```
rm -rf ~/.local/lib/mentor-monitor ~/.config/mentor-monitor ~/.local/state/mentor-monitor ~/.config/systemd/user/mentor-monitor.service
systemctl --user daemon-reload
```

- Set up again: "Setting it up", from step 1. What was recorded is not needed for that; what is usual is learned again in three days.
