# Repair drills: can a small model fix Mentor from its docs alone?

Run 2026-10-19 on a headless test VM. The aim was to find gaps in the instruction docs in `/etc/mentor` (source: `distro/rootfs/etc/mentor/`).

## How it was run

- **VM:** the release image 16.10.26.10 (`out\release\new\mentor.qcow2`) on a throwaway overlay in `out\drills\vm`. It ran headless (`-display none`), with the guest agent on port 47931. First it updated itself through the real channel to **18.10.26.08**. Then the tree's newer docs were pushed in, along with three unpublished files the docs already describe (`mentor-chat`, `mentor_colors.py`, `extension.js`, for the window buttons). Nothing showed on the screen, and neither `out\mentor.qcow2` nor the user's Mentor was touched.
- **The small model:** Claude Haiku as a subagent. It got only these things:
  - the user's symptom in plain words;
  - one command, `vm 'CMD'` (as the user), `vm --root 'CMD'` (as root, standing in for an approved sandbox_apply or run_root_command) or `vm --user-runs 'CMD'` (a command the docs say the user must type);
  - a mapping from the agent's tools to shell commands (desktop_check → `mentor doctor`, session_logout → `systemctl restart gdm`, and so on);
  - the rule to read `/etc/mentor/AGENT.md` first and follow the docs.

  It had no screen_capture and no app_open. It reported where the docs fell short, and every command it ran was logged.
- **Pass:** a hidden check confirmed the fault was gone (`mentor verify`, the service state, the binding, the `mentor doctor` line), and the model got there by following the docs: no guessing, no reading program code, nothing unsafe.

## Results

| # | Breakage | Symptom given | Before the fix | After |
|---|---|---|---|---|
| 1 | `/usr/local/lib/mentor/mentor-clipboard` deleted, helper stopped | Copy/paste with Windows stopped | **Gap.** Fixed, but it worked out the live restart itself (it found Xwayland's display and auth file by hand) | **Pass**, followed "Start it again" |
| 2 | `extension.js` search part damaged (`addProvider` → `addSearchProvider`) | "Ask Mentor" gone from search | **Fail.** It "ported" the damaged file to fit, ran `mentor verify --accept` on it, installed glib2-devel, and restarted the session without asking | **Pass**, put the built copy back |
| 3 | Window-buttons block removed from `~/.config/gtk-4.0/gtk.css` | Buttons grey and round again | Pass. The fix was only in the "after a new GNOME" paragraph | Clearer (not rerun) |
| 4 | `mentor-taskbar-quiet` switched off (global) | "Dash to Panel has been updated!" at every login | **Gap.** Guessed a user-level enable and restarted gdm unasked | **Pass** (run 4). Runs 2 and 3 picked the right commands, but this session's permission checker refused `systemctl --global enable` inside the VM ("Unauthorized Persistence") |
| 5 | Super+A section removed from `00-mentor` | Super+A does nothing | **Gap.** It read `extension.js` to find where the key is defined, and restarted the session for nothing | **Pass**, 9 commands, no logout |
| 6 | `org.gnome.Settings.service` (D-Bus) deleted | Settings freezes after Mouse & Touchpad | Pass, after a detour through the desktop-freeze log | Clearer (not rerun) |
| 7 | Clipboard autostart file deleted, helper stopped | Copy/paste both ways broken | Pass | — |
| 8 | User's own Alt+Space binding emptied | Alt+Space opens nothing | **Gap.** Fixed from its own knowledge: ASKBAR.md never checked the binding | **Pass**, `gsettings reset` as written |
| 9 | `mentor-chat` damaged (syntax error), assistant gone | Only the wallpaper, clicking does nothing | Pass | — |
| 10 | `mentor-crash-watch` switched off (global) and stopped; doctor clean | No crash card any more | Pass through the new Step 2b, after it found `daemon-reload` was needed | Doc fixed |
| 11 | Files extension `mentor.py` deleted | "Ask Mentor…" gone from Files | Pass | — |
| 12 | `/etc/chromium-flags.conf` deleted | Blank "Terms of Service" window | Pass | — |
| 13 | `mentor-update-check.timer` disabled | Yellow card about the daily update look | Pass, but it could not explain `list-timers` showing NEXT `-` | Doc fixed (tested) |
| 14 | `metadata.json` lost GNOME 51 (extension OUT OF DATE) | Desktop looks like plain GNOME | Pass through step 1b | — |

Every drill passes now. Drills 1, 2, 4, 5 and 8 were run again after their doc fix and passed. The rest passed on their first run, and their small doc fixes were tested by hand rather than in a full rerun.

## What was added, and where

- **DESKTOP.md**
  - "Mending one part", **step 1b** (new): run `mentor verify` before touching the code. A changed `extension.js` or `metadata.json` with no note means damage, so put the built copy back and never `--accept` it. Only a file that is still as built means GNOME changed. The step also gives the one-file restore command.
  - Step 1 sends the assistant, service and clipboard lines from `mentor doctor` to the right doc.
  - The OUT OF DATE pointer now says to do step 1b first.
  - Step 6: ask before a logout, because it closes every window.
  - Step 7: the "errors in the shell's log" line still shows the error from before the logout; how to tell an old error from a new one.
  - Step 3: `> /tmp/file; grep` in place of `| less`.
- **DESKTOP.md**, other sections
  - **"Mentor's keys, for mending them"** (new): every key's dconf name and command, a `gsettings` check, the order to try fixes (verify / the user's own value / run the command), and the fact that `dconf update` and `gsettings reset` work at once, with no logout.
  - "The shared clipboard": **"When copy and paste with Windows stopped"** and **"Start it again"**, which starts the helper with `systemd-run --user`, no logout (tested). The restore table no longer says "log out and in" for the clipboard rows.
  - "Window buttons": **"The lights are gone"**: `mentor colors` shows the set in use, `mentor colors "SET"` writes the block again, and how to check it.
  - "Settings": no logout is needed, and how to check the fix without opening a window.
  - The Chromium row now has a check that proves `--no-first-run` is in place.
  - The "Ask Mentor… in Files" row now says to warn that Files windows will close, and how to check.
  - The Dash to Panel bullet now points to Step 2b.
- **REBUILD.md**
  - **"Step 2b: a service of Mentor's that is switched off"** (new):
    - the user services (global) and system services, taken from `mentor-enable`;
    - how to check each kind, and how to read the user-level state;
    - the fix: global enable, then `daemon-reload` and start, with no logout;
    - a timer that was off needs its service run once;
    - an empty journal means switch it on;
    - the `explain` sentence, and what to do when the password is refused.
  - Step 1: what the "(1 file(s) only root may read were not checked)" line means, and when to go to Step 2b because doctor does not look at every service.
- **ASKBAR.md:** "the key does nothing" now checks and resets the binding itself, and the D-Bus call for `Ask` now has its full address.
- **FREEZES.md:**
  - When one program hangs while the desktop still answers, it now points to DESKTOP.md "Settings" or that program's log.
  - The crash test was fixed: `sleep 300 & sleep 1; kill -SEGV $!`. Killed at once, the crash showed as "bash".
  - It now says how to check the crash card without a screen.
- **UPDATES.md:** the `list-timers` check explains NEXT `-` and its fix (tested: NEXT then showed +24 h).

## Found on the way, not doc gaps (follow-ups)

1. **`mentor doctor`'s "errors of Mentor's in the shell's log"** reads the whole boot. After a successful fix and a new login it still says BROKEN until the next reboot. The docs now explain this, but doctor should only count errors since the current gnome-shell started. Code: `/usr/local/bin/mentor`, around line 335.
2. **`mentor doctor` does not check every service of Mentor's.** The crash watch, recipe watch and firewall watch can be off while doctor says "Everything … is in place". Its WARN lines also all point to DESKTOP.md, even where the fix is in REBUILD.md Step 2b or UPDATES.md.
3. **Kept copies with mode 644 after hot-updates.** The scratch `hot_update.sh` used for hot-updates writes the kept copy in `/etc/mentor/source/rootfs` with `-m 644`. A program hot-updated this way (here `mentor-chat`) would come back non-executable from `cp -a` or `mentor restore`, so drill 9's model had to `chmod 755` it by hand. The user's own Mentor got many hot-updates this way, so its kept copies are worth checking (`stat -c '%a %n' /etc/mentor/source/rootfs/usr/local/bin/*`).
4. `mentor journal -n 20` exits 1 when the journal is empty, and small models read that as a failure.
5. The permission checker of the session running these drills refused `systemctl --global enable` inside the throwaway VM twice, then allowed the same command later. Anyone repeating the drills may hit this.

## Repeating it

The scratch tools are in the session scratchpad:

- `boot.ps1`, `qga.py`, `push.py`: start and drive the VM;
- `vm`: the small model's only command;
- `drill break|check N` with `drill-guest.sh`: the 14 breakages and their hidden checks;
- `syncdocs.sh`: put the tree's docs into the VM with the kept copy and MANIFEST;
- `drills/prompt.md`, `drills/dN.md`: the prompts;
- `drills/*.log`: every command each run used.

To keep any of them, they need copying into the project.
