# Updates of Mentor itself

This is for the agent, written so that a small model can follow it. Mentor's own files (the assistant, its tools, these instructions, the shell extension, its services and settings) get fixes from Mentor's maker as small signed updates. Arch's packages are not part of this: they are upgraded as always (system_upgrade).

## What the user sees

- **A green card in the chat, "An update for Mentor"**, with one or two sentences of what is new or fixed, and two buttons: **Not now** and **Update**. Nothing is installed before the user presses Update. A card left alone comes again after three days.
- **Mentor Settings → Updates**: which Mentor this is ("Mentor of 15 October 2026"), an update that is waiting with the same Update button, and **Look** to look for one now.
- **Update**: Mentor works for a minute or two and restarts by itself. The start after it tries the new version: if the desktop comes up, it is kept and a card says "Mentor is up to date" with what changed. If not, the update is undone by itself before anything else runs ("Mentor went back to the way it last worked", BOOT.md), and that version is not offered again.
- Not while the assistant is working: the card and Settings say to press Update again when it is done (the restart would cut the work off).

## When the user asks about updates

"Any updates?" means both kinds: the system's packages (as always) and Mentor's own. Call `mentor_updates` too, and tell both in the same answer, Mentor's first and in one sentence: "Mentor itself is up to date", or "An update of Mentor is waiting: <what it brings>. Press Update on the green card, or in Mentor Settings, Updates." You cannot install it yourself, and an upgrade of the packages does not install it.

## How it works

The program is `/usr/local/lib/mentor/mentor_update.py`, run as root as `/usr/local/lib/mentor/mentor-update check|apply|status`. Its state is `/var/lib/mentor/updates/` (`state.json`, the waiting `update.json`, its signature and package); its log is `/var/log/mentor/updates.log`.

| Step | When | What it does |
|---|---|---|
| `check` | `mentor-update-check.timer`: 3 minutes after each start, then daily; "Look" in Settings | first settles the update before the last restart (kept or undone); then fetches `update.json` and `update.json.sig` from the GitHub release `updates` of Hnd-VXD/Mentor_OS, checks the signature, and when the version is newer than `/etc/mentor/version` (and did not fail before) downloads the package, checks its size and SHA-256, and leaves the card (`mentor notice idea … --update VERSION`) |
| `apply` | `mentor-update-apply.service`, started by the Update button | checks signature, version and package again; asks the launcher for a restore point; unpacks the package; puts every file that differs into a sandbox of its own (`mentor-update`), removes the files of Mentor's that the new version no longer has, installs packages the new version added to Mentor's list (`etc/mentor/source/build/packages.x86_64`), runs `/usr/local/lib/mentor/mentor-enable` there; applies the sandbox like any change (`/var/lib/mentor/changes/ID`, summary "Mentor update VERSION: …"), records it for the trial start (mentor_boot), restarts |
| `status` | `mentor update` (as the user) shows the same in words; the tool `mentor_updates` looks first, then shows it | version, waiting, being tried, last installed, failed versions, declined packages |

- **The signature**: `update.json` is signed with `ssh-keygen -Y sign` (namespace `mentor-update`) by a key only Mentor's maker has. The public key is `/etc/mentor/update-signers`. A package is only installed when update.json is signed by it and the package's SHA-256 is the one update.json names. Never install an update by hand from anywhere else, and never edit `update-signers`: it is what keeps anyone else from putting their code into every Mentor.
- **The package** (`mentor-update-VERSION.tar.zst`) holds all of Mentor's own files, as an image gets them (`build/build.sh update`, the same `stage_overlay` as the image): `/etc/mentor/source` and its `MANIFEST.sha256` come with it, so `mentor verify` stays clean after an update. `/etc/mentor/version` is the version: the time of the build, UTC, `YYYYMMDDHHMM`.
- **`mentor-enable`** is the setup an image build does around Mentor's files: Mentor's services enabled, `dconf update`, the icon cache. The image build (customize.sh) runs the same script. It runs inside the sandbox, so its changes are part of what an undo takes back.
- **Declined packages**: a package on Mentor's list that is not installed was removed by the user. It is kept in `state.json` (`declined_packages`) and no update installs it again.
- **What an update cannot change**: the kernel, the boot splash and initramfs, users and passwords, anything customize.sh does besides `mentor-enable`. Those come with a new image (the launcher's Reinstall).
- **Permission**: `/etc/polkit-1/rules.d/50-mentor-update.rules` lets the user's active session start `mentor-update-apply.service` and `mentor-update-check.service` without the password, and nothing else. The Update button is the consent.

## How to tell that it works

| Check | Good answer |
|---|---|
| `mentor update` | a version, and no "Being tried" long after a restart |
| `systemctl is-enabled mentor-update-check.timer` | `enabled` |
| `systemctl list-timers mentor-update-check.timer` | a next run within a day |
| `tail /var/log/mentor/updates.log` | `no update information: …` when offline or nothing is published (normal); never `not signed by Mentor's maker` (that one means someone else tried: tell the user, change nothing) |
| `change_list` | an installed update is listed as "Mentor update VERSION: …" |

## When something is wrong

- **"The update could not be installed"** (a red card): nothing was changed; the sandbox was thrown away. Read the last lines of the log and say in plain words why (offline, a package that could not be downloaded, the disk full). It is offered again tomorrow, or with Settings → Look.
- **The update was undone at the start after it**: BOOT.md's restore told the user. The version is in `failed` and is not offered again; a newer one is. Read `journalctl -b -1 -p err` for why that start failed and tell the user.
- **To take an installed update back** (it works but the user does not want it): it is an ordinary change. `change_undo` with its id from `change_list`, then a restart. `/etc/mentor/version` goes back with it, so the update is offered again: say so.
- Do not run `mentor-update apply` yourself, and do not start `mentor-update-apply.service` for the user: they press Update.
