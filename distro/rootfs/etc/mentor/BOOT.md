# Starting safely after a change, and the start-up picture

This is for the agent, written so that a small model can follow it. The agent may change anything a start depends on: the kernel, its parameters, the initramfs, modules, GNOME itself. This part makes sure the user is never left with a system that does not start. Its files are ones you cannot write (they are what a failed start falls back on); when one is lost the user puts it back with `sudo mentor restore PATH` (REBUILD.md). What you do here is read the state, explain it, and adapt the things around it.

## What the user has

- **A new kernel, initramfs or kernel parameter is tried once.** If the desktop comes up, it is kept. If not, the next start is the old one again, by itself.
- **A change applied through the sandbox is on trial at the next start** in the same way: no desktop within three minutes, and the change is undone before anything else runs, and the system restarts as it was.
- **The assistant says so afterwards**: "Mentor went back to the way it last worked", with what was undone.
- **A start-up picture**: Mentor's emblem with a spinner under it; a second emblem while the system is going back after a failed start.
- **Restore points on Windows**: the launcher keeps snapshots of the whole disk and offers one when two starts in a row failed. That half is outside this system.

## How it works

The program is `/usr/local/lib/mentor/mentor_boot.py`, run as `/usr/local/lib/mentor/mentor-boot STEP` by systemd units and by pacman. Its state is `/var/lib/mentor/boot/state.json`.

**Two boot entries** (systemd-boot, in `/boot/loader/entries/`):

- `mentor.conf` is the default (`default mentor.conf` in `/boot/loader/loader.conf`). It never points at `/boot/vmlinuz-linux`. It points at a copy under `/boot/mentor/good-N/` (`vmlinuz`, `initramfs.img`) of a kernel that has reached the desktop. That kernel's modules are kept aside in `/var/lib/mentor/boot/modules/VERSION` (hard links), and given back if a change removes them.
- `mentor-trial.conf` is written when there is something to try. It points at the usual places, `/boot/vmlinuz-linux` and `/boot/initramfs-linux.img`, with the parameters of `/etc/kernel/cmdline` plus `mentor.trial=1 panic=20`. It is started once: the EFI variable `LoaderEntryOneShot` names it for one start only.

**The candidate** is what is at the usual places now: kernel, initramfs and `/etc/kernel/cmdline`. Its fingerprint (a hash of the three) is compared with the one known to work. A kernel other than the stock one is named in `/etc/kernel/mentor-boot.conf` with lines `kernel=/boot/…` and `initrd=/boot/…`.

**The steps**, and when each runs:

| Step | When | What it does |
|---|---|---|
| `arm` | at shutdown (`mentor-boot-arm.service`, its ExecStop), after every pacman transaction (`/etc/pacman.d/hooks/zz-mentor-boot.hook`), and after a sandbox change is applied or undone | compares the candidate with the working one; if it differs, writes the trial entry and sets it for one start; sets the phase to `pending` when a kernel or a change is to be tried |
| `check` | very early in every start (`mentor-boot-check.service`, before modules are loaded and file systems mounted) | gives the running kernel its modules back if needed; passes on the scale of the host's screen; if the last start was a trial that did not finish, undoes the changes (`restore`) and restarts; if a trial is due, marks it `running` |
| `deadline` | during a start that tries something (`mentor-boot-deadline.service`) | waits up to 180 seconds for `/run/mentor/desktop-ok`; if it does not appear, notes the reason `deadline` and restarts |
| `confirm` | when `/run/mentor/desktop-ok` appears (`mentor-boot-confirm.path` starts `mentor-boot-confirm.service`) | the start worked: the candidate becomes the new copy (`promote`), the default entry points at it, the changes on trial are kept, phase `ok` |
| `init` | once, when the image is built | the kernel the image ships with is the first one known to work |
| `status` | `mentor boot`, tool boot_status | prints the state |

**"The desktop is up"** means the file `/run/mentor/desktop-ok` exists. The shell extension writes it when the assistant's window has drawn itself and the taskbar's panels exist (DESKTOP.md). `/run/mentor` is made by `/etc/tmpfiles.d/mentor.conf` (`d /run/mentor 1777 root root -`). On a system without automatic login, the login screen counts after 30 seconds.

**What is told to the launcher on Windows**: one JSON line on the virtio port named `org.mentor.control`: `{"boot": "starting"}`, `"trial"`, `"restoring"`, `"ok"`. On a real computer there is no such port and nothing is sent.

**After a restore**, `/var/lib/mentor/boot/restored.json` says when, why, what was undone, what could not be, and whether a kernel is being held back. The assistant reads it and tells the user once (`tell_restore` in mentor-chat).

## How to tell that it works

| Check | Good answer |
|---|---|
| `mentor boot` | `"phase": "ok"`, a `"good"` entry with a version and a time, `"running_kernel"` |
| `cat /boot/loader/loader.conf` (as root) | a line `default mentor.conf` |
| `ls /boot/mentor` (as root) | one folder `good-N` with `vmlinuz` and `initramfs.img` |
| `systemctl is-enabled mentor-boot-check.service mentor-boot-deadline.service mentor-boot-confirm.path mentor-boot-arm.service` | `enabled` four times |
| `systemctl status mentor-boot-confirm.service` | active (exited), from this start |
| `ls /run/mentor/desktop-ok` | the file is there |
| `plymouth-set-default-theme` | `mentor` |

## A new kernel, step by step

1. Before upgrading, run boot_status and say to the user what will happen: the new kernel is tried once; if the desktop does not come up in three minutes, the old one starts again by itself and nothing is lost.
2. Upgrade (system_upgrade). The pacman hook runs `arm`: the trial entry is written.
3. Ask for a restart (system_restart). Do not restart twice in a hurry: the first start is the trial.
4. After the restart, run boot_status. `"phase": "ok"` and a `"good"` entry with the new version means it was kept. A `"last_restore"` entry means it failed and the old one is running: read its `"why"`, then `journalctl -b -1 -p err` for what went wrong in the failed start. A kernel that failed is remembered (`"failed"`) and not tried again until it changes.
5. If the desktop itself is what failed (the extension does not load on the new GNOME), the fault is in DESKTOP.md's territory, not here. This part did its work by going back.

**Do not get around the checks.** Do not write `/run/mentor/desktop-ok` by hand, do not edit the boot entries, do not clear the state file. They are what lets the user try a change without risk. If the check is wrong (a working start is undone), find why the file is not written: `mentor doctor` says whether the extension and the taskbar are up.

## The start-up picture

- The theme is `/usr/share/plymouth/themes/mentor/`: `mentor.plymouth`, `mentor.script`, `logo-1.png` (the emblem), `logo-2.png` (shown while going back), `hint.png`, and `throbber-0.png` … (the stock spinner's frames). `/etc/plymouth/plymouthd.conf` selects it (`Theme=mentor`, `ShowDelay=0`). The kernel parameters `quiet splash` show it; the initramfs has the `plymouth` hook (`/etc/mkinitcpio.conf.d/mentor.conf`: `HOOKS=(base systemd plymouth modconf keyboard block filesystems fsck)`).
- The second emblem is shown when the script is sent the message `mentor-fallback` (`plymouth display-message --text=mentor-fallback`, from `mentor_boot.py`).
- To make it again, in the sandbox, from the parts kept in `/etc/mentor/source/build/splash/`:

```
theme=/usr/share/plymouth/themes/mentor
src=/etc/mentor/source/build/splash
rm -rf "$theme"; install -d "$theme"
cp "$src"/mentor.plymouth "$src"/mentor.script "$src"/logo-1.png "$src"/logo-2.png "$theme/"
rsvg-convert "$src/hint.svg" -o "$theme/hint.png"
frames=0
for frame in /usr/share/plymouth/themes/spinner/throbber-*.png; do
    cp "$frame" "$theme/throbber-$frames.png"; frames=$((frames + 1))
done
sed -i "s/@FRAMES@/$frames/g" "$theme/mentor.script"
mkinitcpio -P
```

  `mentor.script` has `@FRAMES@` where the number of spinner frames goes; the `sed` line fills it in. `mkinitcpio -P` puts the theme into the initramfs, which makes this a change to how the system starts: the next start is a trial. Needs the packages `plymouth` and `librsvg`.
- If a new plymouth no longer has `/usr/share/plymouth/themes/spinner/throbber-*.png`, the loop copies nothing and `@FRAMES@` becomes 0, which breaks the script (a division by zero in `refresh`). Check `ls /usr/share/plymouth/themes/spinner/` first; if the frames are gone or renamed, use what is there, or remove the spinner lines from the script.

## When Windows sleeps, and the launcher's shut down

**Windows pauses the VM while the PC sleeps** (Modern Standby). On 2026-10-14 a sleep of 88 minutes (Windows' System log: Kernel-Power 506 "entering Modern Standby", 507 "exiting") left the kernel saying `rcu: ... kthread starved for 5280247 jiffies`, and every service with a systemd watchdog (journald, logind, udevd, hostnamed: 3 minutes) was killed as hung on waking. logind restarting broke the desktop: the login screen started over the running session, which lost its screen and keyboard (`Device already taken`), and the VM's window looked frozen. A pause is not a hang, so **no service is watched that way here**: `/etc/systemd/system/service.d/10-mentor-no-watchdog.conf` and `/etc/systemd/user/service.d/…` set `WatchdogSec=0` for every service (`systemctl show -p WatchdogUSec systemd-logind` says 0). Tested by stopping the VM 4 minutes (QMP `stop`, `cont`): before, `systemd-hostnamed.service: Watchdog timeout`; after, nothing, and the session goes on.

**The launcher's "shut it down properly"** presses the VM's power button (QMP `system_powerdown`). GNOME takes that button from logind while someone is logged in and does what `power-button-action` says; it was `suspend`, which a VM cannot do, so nothing happened and the launcher then said Mentor was still running. Now `mentor-power-button.service` (`/usr/local/lib/mentor/mentor-power-button`) reads every input device named "Power Button" itself and runs `systemctl poweroff` on a press, at the login screen, in a session, or in a stuck one; GNOME's `power-button-action` is `'nothing'` (dconf `00-mentor`) so the two do not both act. Off in about 2 seconds. If it does not: `systemctl status mentor-power-button` (it says "no power button found" when `/proc/bus/input/devices` has none).

## Making the safe start again from nothing

For the user to run as root; you cannot write these.

```
src=/etc/mentor/source/rootfs
cp -a $src/usr/local/lib/mentor/mentor_boot.py $src/usr/local/lib/mentor/mentor-boot /usr/local/lib/mentor/
cp -a $src/usr/local/lib/systemd/system/mentor-boot-* /usr/local/lib/systemd/system/
cp -a $src/etc/pacman.d/hooks/zz-mentor-boot.hook /etc/pacman.d/hooks/
cp -a $src/etc/tmpfiles.d/mentor.conf /etc/tmpfiles.d/
systemd-tmpfiles --create /etc/tmpfiles.d/mentor.conf
systemctl daemon-reload
systemctl enable mentor-boot-check.service mentor-boot-deadline.service mentor-boot-confirm.path mentor-boot-arm.service
/usr/local/lib/mentor/mentor-boot init
```

`init` makes the kernel that is installed now the one known to work and writes the default entry. Run it only on a system that is running well: it trusts what is there. `/etc/kernel/cmdline` must hold the kernel parameters (`root=UUID=… rw quiet splash loglevel=3 systemd.show_status=auto rd.udev.log_level=3 vt.global_cursor_default=0`).
