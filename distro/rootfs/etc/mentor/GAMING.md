# Games: Steam, Lutris and Heroic, and how to set them up on this install

This is for the agent, written so that a small model can follow it. Mentor does not come with anything for games. When the user asks for games ("I want to play games", "install Steam", "can I run my Epic games?"), it is set up from this file, with the script kept at `/etc/mentor/extras/gaming/setup-gaming.sh`. Say what it will do before you start, and only go on when they say yes. The order follows Omarchy's `bin/omarchy-install-steam` (github.com/omacom/omarchy, MIT).

## What the user gets

- **Steam** (Valve's store and library), and on request **Lutris** (games from many places, Windows games through Wine) and **Heroic** (the Epic Games and GOG stores).
- What they need underneath, which nobody sees: Arch's `multilib` repository switched on, and the 32-bit graphics drivers of Mentor's own graphics (virtio-gpu): `lib32-mesa`, `lib32-vulkan-virtio`, `lib32-vulkan-icd-loader`, and `lib32-pipewire` for sound. Steam itself and many games are 32-bit programs.
- **3D only with the graphics card switched on.** Mentor runs in a window on Windows. Games draw with Vulkan or OpenGL; that is fast only when the launcher lets Windows' graphics card do it. In the Mentor window on Windows that opens before Mentor starts (the one with "Start Mentor"), the switches **Graphics card** and **Vulkan** must be on. Without them games either do not start or run very slowly. Both say "Experimental": tell the user that simple and older games are the ones most likely to run well, and that a game made for a strong gaming PC may not.
- **Mouse-look in 3D games** is the game mouse (DESKTOP.md, "The game mouse"): Mentor switches it on by itself while a game is in front.

Tell the user, in one or two short sentences, before you start: what will be installed (Steam, and the others they named), that it downloads about 1 GB now and more when Steam first starts, that games themselves need a lot of free space, and that 3D needs the Graphics card and Vulkan switches. Then wait for their yes.

## Setting it up

**1. Look at how it stands.** With run_command:

```
bash /etc/mentor/extras/gaming/setup-gaming.sh --check
```

It prints `multilib: on|off`, one line `installed:` or `not installed:` for each package, `free space: N GiB`, and `vulkan: NAME`.

- `vulkan: Virtio-GPU Venus (...)`: the graphics card and Vulkan are on. Good.
- `vulkan: none`, or `llvmpipe` or `lavapipe`: they are off. Setting up still works; tell the user to switch on **Graphics card** and **Vulkan** in the Mentor window on Windows the next time Mentor starts (for that: shut Mentor down, switch them on, Start Mentor).
- `free space` under 10 GiB: say that games will not fit, and offer to make room first.

**2. Install, in the sandbox.** With sandbox_run, `timeout_seconds` 1800, name what the user wants (`steam`, `lutris`, or both):

```
bash /etc/mentor/extras/gaming/setup-gaming.sh steam
```

It takes a few minutes (about 260 MB to download for Steam and the drivers; Lutris with Wine adds more). In its output, `error: command failed to execute correctly` after `36-systemd-modules-load.hook` is normal in the sandbox (that hook needs a running system) and is not a failure. Read the **last line** of what it prints:

| Last line | What it means | What you do |
|---|---|---|
| `DONE` | multilib is on, the drivers and the programs are installed in the sandbox | step 3 |
| `UPGRADE_FIRST` | the system has updates waiting. Arch is never upgraded in part, so they come first | sandbox_discard. Tell the user in one sentence that the system needs its updates first, then system_upgrade (with their yes, as always). When it is done, step 2 again |
| `NO_SPACE` | under 4 GiB free | sandbox_discard. Tell the user; offer to make room |
| `FAILED` | the line before it says what | sandbox_discard. Tell the user in one plain sentence; when it is a download that failed, try once more later |

**3. Apply.** sandbox_changes to look (it lists `/etc/pacman.conf` and many files under `/usr/lib32/`, `/usr/bin/steam`…), then sandbox_apply with the summary "Games: Steam and the 32-bit graphics drivers" (name Lutris too when it was in). The user sees the preview and accepts it. The package lists the sandbox downloaded are not carried over (they never are), so until the next system_upgrade pacman warns `database file for 'multilib' does not exist` and package_search finds no `lib32-` package. That is harmless; system_upgrade fetches the list. Never fix it with `pacman -Sy` alone.

**4. Heroic**, when asked for: it is on Flathub, not in Arch's repositories, and needs no root:

```
flatpak_install com.heroicgameslauncher.hgl
```

**5. Check.** With run_command:

```
bash /etc/mentor/extras/gaming/setup-gaming.sh --check
ls /usr/lib/libvulkan_virtio.so /usr/lib32/libvulkan_virtio.so
```

Good answer: `multilib: on`, `installed: steam` (and the others), and both files listed: the 64-bit and the 32-bit Vulkan driver. (One description, `/usr/share/vulkan/icd.d/virtio_icd.json`, serves both.)

**6. Tell the user** in one or two sentences that Steam is in their apps, that the first start downloads Steam's own update (about 500 MB, a few minutes) and then asks them to sign in, which is theirs to do. Write in `~/.local/share/mentor/notes.md` the date and what was set up.

## When a game does not work

In the user's words: a game does not start; a game is slow; Steam says a library is missing; a Windows game in Steam does not run.

1. The game does not start, or is very slow: `bash /etc/mentor/extras/gaming/setup-gaming.sh --check`. `vulkan:` not Venus means the switches are off (step 1). Otherwise read the game's own log: Steam keeps one per game, `~/.local/share/Steam/logs/`; and `journalctl --user -n 50 -o cat`.
2. A Windows game in Steam: in Steam, the game's Properties, Compatibility, "Force the use of a specific Steam Play compatibility tool" (Proton). Tell the user where to click; that is theirs.
3. The view does not turn with the mouse: DESKTOP.md, "The game mouse". Never change the game's settings for it.
4. Steam says a 32-bit library is missing: run step 2 again (it installs only what is missing). If that does not help, `package_search lib32-NAME` for the library it names (nothing found and the multilib warning: system_upgrade first), and install it with the user's yes.
5. Do not install other makers' drivers (`lib32-nvidia-utils`, `lib32-vulkan-radeon`, `lib32-vulkan-intel`, `amdvlk`): Mentor's graphics is virtio-gpu, whatever card Windows has.

## Taking it away

- The programs: package_remove `steam` (and `lutris`, `wine`), flatpak_remove `com.heroicgameslauncher.hgl`. Their games and settings stay in the home folder (`~/.local/share/Steam`, `~/Games`); ask before removing those, they can be very large.
- The 32-bit drivers: package_remove `lib32-mesa lib32-vulkan-virtio lib32-vulkan-icd-loader lib32-pipewire` (pacman refuses while something still needs one: remove that first).
- multilib can stay on; it costs nothing but a slightly longer package list.

## Its files

| What | Where |
|---|---|
| The script, as kept by Mentor (you cannot change it) | `/etc/mentor/extras/gaming/setup-gaming.sh` |
| What it changes | `/etc/pacman.conf` (the `[multilib]` lines), and the packages above |

The script, step by step, for when it is lost: as root, (1) in `/etc/pacman.conf`, take the `#` off the two lines `#[multilib]` and `#Include = /etc/pacman.d/mirrorlist` below it (or add them at the end); (2) `pacman -Sy`, and stop if `pacman -Qu` lists anything (UPGRADE_FIRST); (3) `pacman -S --needed --noconfirm lib32-mesa lib32-vulkan-virtio lib32-vulkan-icd-loader lib32-pipewire`; (4) `pacman -S --needed --noconfirm steam` (Lutris: `lutris wine`). The drivers go first, on their own, so that Steam's need for "a 32-bit Vulkan driver" is met by Mentor's and pacman does not pick another maker's.
