#!/bin/bash
# Games on Mentor (/etc/mentor/GAMING.md): Steam and Lutris, and the 32-bit graphics drivers they need,
# from Arch's multilib repository. Nothing of this is in the image: the agent runs it when the user asks
# for games, as root inside the sandbox (sandbox_run), and the user accepts it with sandbox_apply.
# The order follows Omarchy's bin/omarchy-install-steam (MIT, github.com/omacom/omarchy): multilib on,
# the 32-bit drivers first (so that pacman does not pick another maker's driver for Steam), then Steam.
#
#   setup-gaming.sh --check            how it stands (needs no root)
#   setup-gaming.sh steam [lutris]     set up what is named
#
# The last line says how it went: DONE, UPGRADE_FIRST (the system has updates waiting: system_upgrade
# first, then run this again), NO_SPACE, or FAILED.
set -uo pipefail

# Mentor's graphics: virtio-gpu, with Venus for Vulkan when the launcher's graphics card option is on.
DRIVERS=(lib32-mesa lib32-vulkan-virtio lib32-vulkan-icd-loader lib32-pipewire)
declare -A APPS=([steam]="steam" [lutris]="lutris wine")
NEED_GIB=4

multilib_on() { grep -q '^\[multilib\]' /etc/pacman.conf; }

if [ "${1:-}" = "--check" ]; then
    multilib_on && echo "multilib: on" || echo "multilib: off"
    for name in "${DRIVERS[@]}" steam lutris wine; do
        pacman -Q "$name" >/dev/null 2>&1 && echo "installed: $name" || echo "not installed: $name"
    done
    free=$(( $(stat -f --format='%a*%S' / ) / 1024 / 1024 / 1024 ))
    echo "free space: ${free} GiB"
    # The Vulkan device games will see: "Virtio-GPU Venus" when the graphics card option is on.
    device=$(vulkaninfo --summary 2>/dev/null | sed -n 's/^\s*deviceName\s*=\s*//p' | head -n 3 | paste -sd ',')
    echo "vulkan: ${device:-none}"
    exit 0
fi

if [ "$(id -u)" != 0 ]; then
    echo "Run this as root, in the sandbox (sandbox_run)."; echo FAILED; exit 1
fi
if [ $# = 0 ]; then
    echo "Name what to set up: steam, lutris."; echo FAILED; exit 2
fi
wanted=()
for name in "$@"; do
    [ -n "${APPS[$name]:-}" ] || { echo "Unknown: $name (steam, lutris)"; echo FAILED; exit 2; }
    wanted+=(${APPS[$name]})
done

free=$(( $(stat -f --format='%a*%S' / ) / 1024 / 1024 / 1024 ))
if [ "$free" -lt "$NEED_GIB" ]; then
    echo "Only ${free} GiB free; ${NEED_GIB} GiB are needed for these programs (games need more)."; echo NO_SPACE; exit 4
fi

# 1. The multilib repository, as Arch's own pacman.conf has it (commented out).
if ! multilib_on; then
    if grep -q '^#\[multilib\]' /etc/pacman.conf; then
        sed -i '/^#\[multilib\]$/{s/^#//;n;s/^#\s*Include/Include/}' /etc/pacman.conf
    else
        printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >> /etc/pacman.conf
    fi
fi
multilib_on || { echo "multilib could not be switched on in /etc/pacman.conf"; echo FAILED; exit 1; }
echo "multilib: on"

# 2. Fresh package lists. Arch is never upgraded in part: with updates waiting, they come first.
pacman -Sy --noconfirm || { echo "The package lists could not be fetched."; echo FAILED; exit 1; }
waiting=$(pacman -Qu 2>/dev/null | wc -l)
if [ "$waiting" -gt 0 ]; then
    echo "$waiting updates are waiting: the system must be upgraded first."; echo UPGRADE_FIRST; exit 3
fi

# 3. The 32-bit drivers, on their own, so that Steam's "a 32-bit Vulkan driver" is this one.
pacman -S --needed --noconfirm "${DRIVERS[@]}" || { echo "The 32-bit drivers could not be installed."; echo FAILED; exit 1; }

# 4. The programs.
pacman -S --needed --noconfirm "${wanted[@]}" || { echo "Could not install: ${wanted[*]}"; echo FAILED; exit 1; }

# Mesa describes both drivers in one file (virtio_icd.json, "libvulkan_virtio.so"); the 32-bit one is in /usr/lib32.
[ -e /usr/lib32/libvulkan_virtio.so ] && echo "32-bit Vulkan driver: in place"
echo "installed: ${DRIVERS[*]} ${wanted[*]}"
echo DONE
