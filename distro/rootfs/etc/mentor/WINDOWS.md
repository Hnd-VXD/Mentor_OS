# Mentor.exe on Windows, and what of it reaches this system

Mentor runs as a virtual machine on Windows. The program that starts it there is **Mentor.exe** (the "launcher"; its source is `launcher/` in the project, not in this system). You cannot see or change Windows from here, but the user will ask you about what Mentor.exe does, and some of it has a part inside this system. This file says what the launcher does, what the user sees, which files here belong to it, and how to make those again.

Most of these features were made after Try Omarchy for Windows (github.com/omacom/try-omarchy-windows, MIT), which runs another Linux the same way.

Where the user finds things on Windows, in plain words:
- **The Mentor window** when Mentor.exe starts without anything else (wide and low since 2026-10-22, the shape of the loading window after it): the owl and "Mentor" at the top left (the line under the name shows news of a new Mentor.exe), two tabs at the top right. **Settings**: **Screen** (three switches side by side: Graphics card, Vulkan, Full screen; what each does is in its tooltip), **Speed** (Balanced, Maximum, Manual; Manual shows Memory and Processors sliders side by side), **Sound, USB and sign-in** (a "Change…" button). **More**: Restore points, Repair, Back up…, Restore a backup…, Move Mentor…, Start over… (one window that can also download the newest Mentor). **Start Mentor** across the bottom. Opened from the tray icon while Mentor runs, it has only the Settings page and Save.
- **The loading window** after "Start Mentor" (since 2026-10-22, made after Try Omarchy's): the Mentor window turns a page, in the same place and size, with the same top: a line saying what is happening ("Starting Mentor…", "Getting the desktop ready…", "Trying the change from last time…", "That change did not work. Going back…"), a bar that fills in about the time the last start took (`vm\start-seconds` on Windows), "Keys worth knowing" (Ctrl+Alt+F full screen, Ctrl+Alt+G mouse and keyboard back to Windows, Ctrl+Alt+Backspace help if Mentor gets stuck: the emergency console of FREEZES.md), and **Back** where Start was (stops the start at once and shows the settings again; the window's X stops it and closes). A stop from there is not counted as a failed start. Mentor's own window waits hidden meanwhile (off the taskbar too: the loading window has the owl there instead), already at the size it will have, and comes up when this system says the desktop is up (`{"boot": "ok"}`, BOOT.md): the firmware's logo, the start-up picture and the desktop changing size are no longer seen. For full screen the loading window covers the screen at that moment. If the desktop does not report within 2 minutes, the window comes up anyway, wherever the start is. Not hidden for Repair, a start from an ISO, or the start after two failed ones: there the user sees what happens. The start-up picture (BOOT.md) is still drawn, only no longer seen in a normal start.
- **The Mentor icon in the Windows notification area** (bottom right, by the clock) while Mentor runs. Right click: Open Mentor, Settings…, Make a diagnostics file, Shut down Mentor.

Everything chosen in the Mentor window is used from the next start of Mentor. When the user wants a choice there, tell them in one sentence where it is; you cannot change it for them.

## 1. Mentor.exe keeps itself up to date

At every start, Mentor.exe looks (at most twice a day) for a newer Mentor.exe in the GitHub release "updates" of Hnd-VXD/Mentor_OS. It takes one only if Mentor's maker signed it (with the same key as this system's updates, `/etc/mentor/update-signers`, namespace `mentor-launcher`) and the file is exactly the one signed. It downloads it while Mentor runs and puts it in place at the next start, without asking: the user sees nothing. If the new one does not start, or the system does not come up under it, the next start goes back to the one before by itself, and that version is not tried again.

The Mentor window says so in one line under the Start button, in blue: "A new version is ready for next time." once one is downloaded, and "Updated to the newest version." at the first open after it was put in place (`SelfUpdate.Note`). Nothing has to be clicked.

Nothing of this is inside this system. On Windows its record is `launcher-update\log.txt` beside Mentor.exe (it is in the diagnostics file, section 7). Updates of this system itself are another thing: UPDATES.md.

## 2. When Windows sleeps, wakes, or shuts down

A Mentor.exe from 2026-10-18 on pauses the system just before Windows sleeps and lets it go on when Windows wakes (QEMU's `stop` and `cont`), and when Windows shuts down or signs out it shuts this system down properly first (the power button, up to ten seconds). Before that, Windows froze the machine wherever it was. Either way the time that passed shows up here as a gap; BOOT.md, "When Windows sleeps", says how to recognise it (`mentor-sentinel: stall of N s, paused`) and why no service here has a watchdog. The clock here stays right across a pause; nothing has to correct it.

**Left paused after a wake.** Until 2026-10-22, when QEMU answered the pause late (Windows already going down), Mentor.exe took it as not paused, and at the wake left the system paused: the window says "Mentor [Stopped]" and takes no clicks, and `vm\launcher.log` has "could not pause it: QEMU did not answer" at the sleep. Nobody inside can see or fix that (the system is stopped); closing Mentor and starting it again does. A newer Mentor.exe checks the real state at the wake and goes on.

**A start Mentor.exe could not reach.** Mentor.exe talks to QEMU over local ports (control, clipboard, the host link, QMP). It waits up to 5 minutes for QEMU to open them; one it could not reach is a line in `vm\launcher.log` ("could not connect to QEMU's port …"). Until 2026-10-18 it waited only 20 seconds: on a slow or just-started Windows nothing got connected, so no clipboard, no time zone, the game mouse could stay in use (the pointer caught in the window), and the word that the start worked never arrived, so after 8 minutes Mentor.exe stopped a working Mentor and started it again ("exit -1, no reason given" in `vm\qemu.log`). It now stops a start only when it could have heard from it. If the user reports a Mentor that "crashed" after about 8 minutes, or a pointer caught with no game open: look for those lines, and tell them a newer Mentor.exe fixes it.

## 3. The link to Mentor.exe: mentor-host-link

A Mentor.exe from 2026-10-18 on gives this system a third channel, the virtio port `org.mentor.host` (`/dev/virtio-ports/org.mentor.host`), readable by root only (the other two, `org.mentor.clipboard` and `org.mentor.control`, are the user's). `mentor-host-link`, a root service, is at its other end. It carries, one JSON object a line:
- Windows' time zone (section 4),
- Windows Hello for passwords (section 8),
- cards for the chat that Mentor.exe wants the user to see (a USB device it could not give, section 9),
- the system's logs for the diagnostics file (section 7).

The service is started by udev when the port is there, so with an older Mentor.exe it simply does not run.

Its files:

| File | What it is |
|---|---|
| `/usr/local/lib/mentor/mentor-host-link` | the service (Python), also `mentor-host-link status` and `mentor-host-link follow` |
| `/usr/local/lib/systemd/system/mentor-host-link.service` | runs it, again after 5 s if it stops |
| `/etc/udev/rules.d/70-mentor-host.rules` | starts the service when the port appears |

Check that it works:
1. `ls /dev/virtio-ports/` — good: `org.mentor.host` is listed. Not listed: Mentor.exe is older than 2026-10-18; nothing here can be done about it, the user gets the newer one by itself (section 1).
2. `systemctl is-active mentor-host-link` — good: `active`.
3. `journalctl -u mentor-host-link -b -o cat | tail` — good: `link to Mentor.exe open`, and no `Traceback`.

Make it again (as root, in the sandbox first; these files are in `/usr/local/lib/mentor`, which only the user can write: give them the lines):
1. `mentor verify` — see which of the three files is missing or changed.
2. `sudo mentor restore /usr/local/lib/mentor/mentor-host-link /usr/local/lib/systemd/system/mentor-host-link.service /etc/udev/rules.d/70-mentor-host.rules`
3. `sudo chmod 755 /usr/local/lib/mentor/mentor-host-link`
4. `sudo systemctl daemon-reload`
5. `sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=virtio-ports`
6. Do the three checks above again.

When it fails after a Python update: `journalctl -u mentor-host-link -b` shows the error; it uses only Python's own modules (json, os, select, socket, subprocess, threading, tarfile, zoneinfo) and the commands `timedatectl`, `loginctl`, `setpriv`, `journalctl`, `systemctl`.

## 4. The time zone follows Windows'

Mentor.exe sends Windows' time zone by the name Linux knows it by (Windows' "GTB Standard Time" is `Europe/Bucharest` or `Europe/Athens`, depending on the country in Windows' region settings), when the link opens and whenever it changes on Windows. mentor-host-link sets it with `timedatectl set-timezone`. A zone that shows exactly the same time as the one already set is left as it is (Athens stays Athens when Windows says Bucharest).

**A zone chosen inside Mentor wins.** When the zone here is not the one mentor-host-link last set (the user chose another in GNOME Settings, or asked you to), Windows' is no longer followed. Its record is `/var/lib/mentor/host-timezone.json`: `following`, `applied` (what it last set), `windows` (what Windows says), `chosen` (the user's).

- What it does now: `mentor-host-link status` (good: `"following": true` and `now` the same as `windows`, or a zone with the same time).
- The user wants Windows' zone followed again: they run (you cannot write `/var/lib/mentor`) `sudo /usr/local/lib/mentor/mentor-host-link follow`. It answers "Following Windows' time zone again: ZONE." and sets it.
- The user wants a fixed zone: set it as usual (`timedatectl set-timezone Zone/City`, or GNOME Settings, Date & Time); following stops by itself.

## 5. Sound, the microphone, and the camera

With Mentor's own QEMU (every Mentor installed by MentorSetup.exe), sound goes through SDL and the system always has a microphone input, also when Windows has none plugged in (it then hears silence until one is plugged in). In the Mentor window, **Sound, USB and sign-in** chooses:
- **Sound**: "Same as Windows" or one of Windows' speakers or headphones.
- **Microphone**: "Same as Windows", one of Windows' microphones, or **Off**: then this system has no microphone at all (no app here can listen).
A chosen device that is unplugged falls back to Windows' own until it is back.

What you see here: one card `HDA Intel` (`cat /proc/asound/cards`). With PipeWire: `pactl list sinks short` and `pactl list sources short`; the microphone is the source that is not a `.monitor`. With the microphone Off there is no such source. When the user says the microphone does not work: 1) ask whether Mentor's microphone is Off in the Mentor window (Sound, USB and sign-in); 2) whether Windows lets apps use the microphone (Windows Settings, Privacy & security, Microphone: "Let desktop apps access your microphone" on); 3) `pactl list sources short` here, and the input volume in GNOME Settings, Sound.

**One volume.** Windows' volume and Mentor's are one: the laptop's volume keys, Windows' volume and Mentor's volume slider all move the same volume, and mute is shared too. (Before, they multiplied: 22% on Windows and 70% here sounded like 15%.) How:
1. Mentor.exe (`WindowsVolume.cs`) reads Windows' master volume and mute five times a second and sends changes over the link as `{"volume": 0.22, "mute": false}`; what comes back the same way, it sets on Windows.
2. `mentor-host-link` (root) starts `/usr/local/lib/mentor/mentor-volume` as the desktop's user when the first volume arrives, and passes the volume to it and its changes back.
3. `mentor-volume` makes a virtual output, **Speakers** (`mentor_speakers`, a PipeWire null sink with `monitor.channel-volumes=false`: its volume is only a number and does not lower the sound), makes it the default, and passes its sound with `pw-loopback` (`mentor-volume-loop`) to the real output (`alsa_output…`), kept at 100% and unmuted. The virtual output's volume and mute are Windows'; Windows does the lowering and the muting.
4. The laptop's volume keys reach Windows and, through QEMU, this system as well: one press moved the volume twice. So while joined, GNOME's own volume keys (`org.gnome.settings-daemon.plugins.media-keys` `volume-*-static`) are emptied and Windows' keys are the ones; the user's values are kept in `~/.local/state/mentor/volume-keys.json` and put back afterwards. GNOME's media-keys service reads them only when it starts, so `mentor-volume` starts it again (`pkill gsd-media-keys`, then `systemctl --user start org.gnome.SettingsDaemon.MediaKeys.target`). If the volume keys inside Mentor stay dead after Mentor.exe is gone: that file is still there; `gsettings reset` the `volume-*-static` keys and start the target the same way.
5. When Mentor.exe goes away (an older Mentor.exe, or none), `mentor-volume` puts it back: the real output is the default again, at the volume the virtual one had, and the virtual one is removed. Without a Mentor.exe that sends the volume, Mentor's own volume works as it always did.

Check: `pactl get-default-sink` says `mentor_speakers` while Mentor.exe is connected; `pactl get-sink-volume mentor_speakers` shows Windows' volume; `pactl get-sink-volume @DEFAULT_SINK@` after Mentor.exe is gone shows the last one; `journalctl -u mentor-host-link -b -o cat | grep "one volume"` says when it started and stopped. When the volume does not follow: 1) `systemctl status mentor-host-link` (active?); 2) `pgrep -af mentor-volume` (running as the user?); 3) its errors are in the same journal. When there is sound only in Windows' volume mixer but nothing heard: `pactl list short sinks` must show the real output RUNNING at 100%; set it so with `pactl set-sink-volume alsa_output… 100%`. Never remove `mentor_speakers` by hand while Mentor.exe is connected: `mentor-volume` makes it again at the next volume.

**There is no camera.** Mentor's QEMU cannot pass a camera to this system: it has no virtual camera, and giving it the camera as a USB device (section 9) works only when the camera's Windows driver is WinUSB, which a camera's is not. Tell the user so in one sentence when they ask; video calls work with the microphone, without a picture of them.

## 6. Speed: how much of the computer Mentor gets

In the Mentor window, **Speed**:
- **Balanced** (the default): half of the processors, 4 to 8, and a third of the memory, 4 to 8 GB, leaving Windows at least 2 GB of what is free when Mentor starts.
- **Maximum**: what Windows is not using when Mentor starts, less room for Windows (two processors, or an eighth on larger computers; 4 GB of memory, or an eighth on larger computers). Never less than Balanced.
- **Manual**: the two sliders, as before.
It is worked out again at every start. Here, `nproc` and `free -g` show what this start got. When the user says Mentor is slow and Windows has plenty free, Maximum is the one to suggest; when Windows is slow while Mentor runs, Balanced. The change counts from the next start.

## 7. The diagnostics file

The tray icon's **Make a diagnostics file** puts `Mentor diagnostics DATE TIME.zip` on the user's Windows Desktop. It holds Mentor.exe's records (launcher.log, qemu.log, the self-update's log, the restore points' list, the settings, a description of the computer) and, asked over the link, this system's: `system-inside.tar.gz` with this start's journal and the one before, the failed services, `/var/log/mentor/*` and the versions. Nothing is sent anywhere: the user decides whether to share it. When the user asks how to send their problem to Mentor's maker, the problem report (`problem_report`, UPDATES.md) is the way; the diagnostics file is for when someone asks them for it.

## 8. Windows Hello for passwords

Opt-in, in the Mentor window: **Sound, USB and sign-in**, switch **Windows Hello** (only when Windows Hello is set up on Windows). Then when this system asks for the user's password (the password dialog for the agent's changes, `sudo`), Windows shows its own Windows Hello prompt (face, finger or PIN) with the words "Mentor wants to …", and a yes there is enough. Cancelled, refused, or Hello not answering: the password is asked as always. The password never stops working.

How it works:
1. `/etc/pam.d/polkit-1` and `/etc/pam.d/sudo` have one line first: `auth sufficient pam_exec.so quiet quiet_log /usr/local/lib/mentor/mentor-hello`. (`quiet_log`: without it every password prompt with Windows Hello off wrote "mentor-hello failed: exit code 1" to the log as an error, and problem reports and the agent took that for a fault.)
2. `mentor-hello` (run as root by PAM) gives up at once (exit 1, the password follows) unless `/run/mentor-hello/on` exists. mentor-host-link makes that file when Mentor.exe says Hello is switched on, and removes it when the link closes. `/run/mentor-hello` is root's alone (0700); `mentor-hello` trusts nothing there that is not root's. (`/run/mentor` is not used for this: anyone may write there.)
3. It asks mentor-host-link on `/run/mentor-hello/socket`, with what for: for `sudo`, the command; for the password dialog, the agent's sentence, which `mentor-rootd` leaves in `/run/mentor-hello/why`.
4. mentor-host-link passes it to Mentor.exe, which shows the prompt, and passes back yes or no. One prompt at a time; after a no, none for 3 seconds.

What it does not protect against: the prompt cannot prove which request it is for. A program running as the user could start its own `sudo` just before the user's. Tell the user, when they switch it on or ask: answer a Windows Hello prompt from Mentor only right after asking for something in Mentor; cancel one that comes by itself.

Check it (with Windows Hello switched on in the Mentor window):
1. `sudo ls -ld /run/mentor-hello` — good: `drwx------ ... root root`.
2. `sudo ls /run/mentor-hello` — good: `on` and `socket`. No `on`: Hello is off in the Mentor window, or Mentor.exe is older.
3. `journalctl -u mentor-host-link -b -o cat | grep "Windows Hello"` — one line for each prompt and its answer.

Its files: `/usr/local/lib/mentor/mentor-hello`, `/etc/pam.d/polkit-1`, `/etc/pam.d/sudo`, and the hint in `/usr/local/lib/mentor/mentor-rootd` (`hello_hint`). Make them again (the user runs these; you cannot write them):
1. `sudo mentor restore /usr/local/lib/mentor/mentor-hello /etc/pam.d/polkit-1 /etc/pam.d/sudo`
2. `sudo chmod 755 /usr/local/lib/mentor/mentor-hello`
3. Check with `sudo -k; sudo true`: with Hello on, a prompt on Windows; cancel it, and the password is asked.

If passwords stop working at all after a change to these files (they should not: every failure falls through to the password), the user can still use repair mode (REPAIR.md) or the emergency console, and put the files back with step 1. Never remove `include system-auth` from either file.

## 9. USB devices (experimental)

In the Mentor window, **Sound, USB and sign-in**, **USB device**: one of the USB devices plugged into Windows, given to this system when Mentor starts; Windows cannot use it meanwhile. It is remembered by the USB port it is in: plugged in elsewhere, it is not given. Whether it works depends on its Windows driver: only a device whose driver is WinUSB (or libusbK) can be given. Most devices (cameras, Bluetooth, most phones and printers) have their own drivers, and Mentor installs none.

When it could not be given, Mentor.exe says so in a yellow card here ("… could not be given to Mentor"), with the exact reason for you behind "Let Mentor look": "not plugged in at the same USB port" (plug it into the port where it was chosen, or choose it again), or anything else (its Windows driver keeps it: it stays usable in Windows). Explain that in one or two plain sentences.

A device that was given: `lsusb` lists it here. To give it back to Windows, choose "None" in the Mentor window and restart Mentor.

## 10. Back up, restore, move

In the Mentor window, **More options** (Mentor must be shut down; the buttons say so otherwise):
- **Back up…**: everything of Mentor in one .zip where the user chooses: the disk with everything done inside Mentor and its restore points, the system image it is made on, the firmware's settings. About the size of Mentor's disk plus 2 to 3 GB. It is not locked with a password: it holds the user's files and sign-ins, so it must be kept somewhere private.
- **Restore a backup…**: puts Mentor back as it is in such a file. Every file in it is checked first; a damaged backup changes nothing. What is in Mentor now is replaced.
- **Move Mentor…**: the whole installation to another folder or drive (a folder "Mentor" is made there). Copied, checked, then used from there; the shortcuts follow, and the old copy is removed.

Restore points (inside the disk) go along with a backup and a move; going back to one is still "Restore points". None of this can be done from inside Mentor. When the user asks how to keep everything safe before a big change, a backup is the answer for "everything, to a file", a restore point for "go back to this morning".

## 11. When the user asks "what version is Mentor?"

This system's version: `cat /etc/mentor/version-name` (and UPDATES.md). Mentor.exe's version is not visible from here; it is in the diagnostics file (`about.txt`), and it keeps itself up to date (section 1).
