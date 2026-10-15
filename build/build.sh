#!/usr/bin/env bash
# Builds Mentor. Run as root inside Arch Linux (WSL2 or a real install).
#   build.sh disk   -> out/mentor.qcow2   installed system for the QEMU launcher (default)
#   build.sh iso    -> out/mentor-*.iso   live ISO via archiso
set -euo pipefail

target=${1:-disk}
SRC=$(cd "$(dirname "$0")/.." && pwd)
# Work on a native Linux filesystem: the Windows mount has no Unix permissions and is slow.
WORK=${MENTOR_WORK:-/var/tmp/mentor-build}
OUT=${MENTOR_OUT:-$SRC/out}
RAW=$WORK/mentor.raw
MNT=$WORK/mnt
LOOPS=()

[[ $EUID -eq 0 ]] || { echo "build.sh must run as root" >&2; exit 1; }
[[ -f /etc/arch-release ]] || { echo "build.sh must run inside Arch Linux" >&2; exit 1; }

# shellcheck source=../distro/config.env
source <(tr -d '\r' < "$SRC/distro/config.env")
mapfile -t PACKAGES < <(tr -d '\r' < "$SRC/distro/packages.x86_64" | sed 's/#.*//; /^[[:space:]]*$/d')

cleanup() {
    mountpoint -q "$MNT" && { umount -R "$MNT" || umount -Rl "$MNT"; }
    for dev in "${LOOPS[@]}"; do losetup -d "$dev" || true; done
}
trap cleanup EXIT

# Copy distro/rootfs over a root tree, normalising what a Windows checkout loses:
# line endings, ownership and the executable bit.
stage_overlay() {
    local dest=$1 f
    cp -r --no-preserve=mode,ownership "$SRC/distro/rootfs/." "$dest/"
    while IFS= read -r -d '' f; do
        # Text files only (grep -I): the same edit would corrupt a picture.
        if grep -Iq . "$dest/$f"; then
            sed -i 's/\r$//' "$dest/$f"
        fi
        chown root:root "$dest/$f"
    done < <(cd "$SRC/distro/rootfs" && find . -type f -print0)
    chmod 755 "$dest"/usr/local/bin/mentor "$dest"/usr/local/bin/mentor-mcp "$dest"/usr/local/bin/mentor-chat \
        "$dest"/usr/local/bin/mentor-agent "$dest"/usr/local/bin/mentor-settings "$dest"/usr/local/bin/mentor-recipes \
        "$dest"/usr/local/lib/mentor/mentor-helper "$dest"/usr/local/lib/mentor/mentor-root-shell \
        "$dest"/usr/local/lib/mentor/mentor-clipboard "$dest"/usr/local/lib/mentor/mentor-sandbox \
        "$dest"/usr/local/lib/mentor/mentor-clipboard-files "$dest"/usr/local/lib/mentor/mentor-engine "$dest"/usr/local/lib/mentor/mentor-advisor "$dest"/usr/local/lib/mentor/mentor-usage \
        "$dest"/usr/local/lib/mentor/mentor-review "$dest"/usr/local/lib/mentor/mentor-watch \
        "$dest"/usr/local/lib/mentor/mentor-boot "$dest"/usr/local/lib/mentor/mentor-repair-console \
        "$dest"/usr/local/lib/mentor/mentor-explain "$dest"/usr/local/lib/mentor/mentor-write-file \
        "$dest"/usr/local/lib/mentor/mentor-apply "$dest"/usr/local/lib/mentor/mentor-undo \
        "$dest"/usr/local/lib/mentor/mentor-rootd "$dest"/usr/local/lib/mentor/mentor-firewall-watch \
        "$dest"/usr/local/lib/mentor/mentor-recipe-watch "$dest"/usr/local/lib/mentor/mentor-power-button \
        "$dest"/usr/local/lib/mentor/mentor-sentinel "$dest"/usr/local/lib/mentor/mentor-emergency-key \n        "$dest"/usr/local/lib/mentor/mentor-emergency-console

    # A copy of everything of ours as it was built, and what each file's contents should be:
    # what the agent checks the system against (mentor verify) and makes a lost part again
    # from (etc/mentor/REBUILD.md). It is in /etc/mentor, which the agent reads and cannot write.
    local ref=$dest/etc/mentor/source
    rm -rf "$ref"
    install -d "$ref/rootfs" "$ref/build/splash"
    (cd "$dest" && while IFS= read -r -d '' f; do cp -a --parents "$f" "$ref/rootfs/"; done) \
        < <(cd "$SRC/distro/rootfs" && find . -type f -print0)
    (cd "$dest" && xargs -0 sha256sum) < <(cd "$SRC/distro/rootfs" && find . -type f -print0 | sort -z) \
        | sed 's#  \./#  /#' > "$ref/MANIFEST.sha256"
    # How the rest of the system was set up when the image was built. Not the password.
    for f in customize.sh packages.x86_64 splash/mentor.plymouth splash/mentor.script splash/hint.svg; do
        tr -d '\r' < "$SRC/distro/$f" > "$ref/build/$f"
    done
    tr -d '\r' < "$SRC/distro/config.env" | grep -v '^MENTOR_PASSWORD=' > "$ref/build/config.env"
    cp "$SRC"/distro/splash/logo-1.png "$SRC"/distro/splash/logo-2.png "$ref/build/splash/"
    chown -R root:root "$ref"
}

stage_setup() {
    local dest=$1 f
    install -d "$dest/splash"
    for f in customize.sh config.env splash/mentor.plymouth splash/mentor.script splash/hint.svg; do
        tr -d '\r' < "$SRC/distro/$f" > "$dest/$f"
    done
    cp "$SRC"/distro/splash/logo-1.png "$SRC"/distro/splash/logo-2.png "$dest/splash/"
}

# Attach one partition of the raw image as a loop device. Offsets instead of
# partition scanning, so it also works where /dev is not managed by udev.
attach() {
    local start sectors
    read -r start sectors < <(partx --show --noheadings --output START,SECTORS --nr "$1:$1" "$RAW")
    losetup --find --show --offset $((start * 512)) --sizelimit $((sectors * 512)) "$RAW"
}

build_disk() {
    pacman -Syu --needed --noconfirm arch-install-scripts dosfstools e2fsprogs qemu-img

    rm -f "$RAW"
    mkdir -p "$MNT"
    truncate -s "${MENTOR_DISK_GB}G" "$RAW"
    printf 'label: gpt\n,1G,U\n,,L\n' | sfdisk --quiet "$RAW"

    local esp root
    esp=$(attach 1); LOOPS+=("$esp")
    root=$(attach 2); LOOPS+=("$root")
    mkfs.fat -F 32 -n MENTOR_EFI "$esp" > /dev/null
    mkfs.ext4 -q -L mentor-root "$root"
    mount "$root" "$MNT"
    mount --mkdir "$esp" "$MNT/boot"

    # In place before the kernel is installed, so the first initramfs is already right.
    mkdir -p "$MNT/etc/mkinitcpio.conf.d"
    cat > "$MNT/etc/mkinitcpio.conf.d/mentor.conf" <<'EOF'
# The image is built outside the machine it boots on, so no autodetect hook:
# the storage drivers of the VM are listed explicitly. virtio_gpu is there so
# the boot splash has a display to draw on from the start.
MODULES=(virtio_pci virtio_blk virtio_scsi virtio_net virtio_gpu virtio_console ahci sd_mod nvme)
HOOKS=(base systemd plymouth modconf keyboard block filesystems fsck)
EOF

    # -c downloads into this machine's package cache, so a retry (mirrors do stall)
    # or the next build does not fetch everything again.
    local attempt
    for attempt in 1 2 3; do
        pacstrap -c -K "$MNT" base linux mkinitcpio "${PACKAGES[@]}" && break
        [[ $attempt -lt 3 ]] || { echo "packages could not be installed" >&2; exit 1; }
        echo "package installation failed, trying again ($attempt)" >&2
        sleep 10
    done
    # genfstab also lists the build host's active swap, which the VM would wait 90s for.
    # /boot is made private because systemd keeps its random seed there.
    genfstab -U "$MNT" | awk '$3 != "swap"' | sed 's/fmask=0022,dmask=0022/fmask=0077,dmask=0077/' >> "$MNT/etc/fstab"

    stage_overlay "$MNT"
    stage_setup "$MNT/root/mentor-setup"
    arch-chroot "$MNT" bash /root/mentor-setup/customize.sh
    rm -rf "$MNT/root/mentor-setup"
    # Again, now that the splash theme exists, so the initramfs carries it.
    arch-chroot "$MNT" mkinitcpio -P

    # systemd-boot, copied by hand: bootctl refuses an ESP it cannot trace to a GPT partition.
    # \EFI\BOOT\BOOTX64.EFI is what firmware with empty NVRAM starts.
    local efi=$MNT/usr/lib/systemd/boot/efi/systemd-bootx64.efi
    mkdir -p "$MNT/boot/EFI/BOOT" "$MNT/boot/EFI/systemd" "$MNT/boot/loader/entries"
    cp "$efi" "$MNT/boot/EFI/BOOT/BOOTX64.EFI"
    cp "$efi" "$MNT/boot/EFI/systemd/systemd-bootx64.efi"
    printf 'default mentor.conf\ntimeout 0\n' > "$MNT/boot/loader/loader.conf"
    # The kernel parameters have one home; the boot entries are written from it. The
    # entry that is started by default points at a copy of this kernel, which only a
    # start that reached the desktop replaces (rootfs/usr/local/lib/mentor/mentor_boot.py).
    mkdir -p "$MNT/etc/kernel"
    echo "root=UUID=$(blkid -s UUID -o value "$root") rw quiet splash loglevel=3 systemd.show_status=auto rd.udev.log_level=3 vt.global_cursor_default=0" > "$MNT/etc/kernel/cmdline"
    arch-chroot "$MNT" /usr/local/lib/mentor/mentor-boot init

    # pacman-key leaves a gpg-agent behind that would keep the image mounted.
    arch-chroot "$MNT" gpgconf --homedir /etc/pacman.d/gnupg --kill all || true
    sync
    cleanup
    LOOPS=()

    mkdir -p "$OUT"
    qemu-img convert -f raw -O qcow2 "$RAW" "$OUT/mentor.qcow2.tmp"
    mv -f "$OUT/mentor.qcow2.tmp" "$OUT/mentor.qcow2"
    rm -f "$RAW"
    echo "Built $OUT/mentor.qcow2"
}

build_iso() {
    pacman -Syu --needed --noconfirm archiso

    local profile=$WORK/profile
    rm -rf "$profile" "$WORK/iso-work"
    cp -r /usr/share/archiso/configs/releng "$profile"
    printf '%s\n' "${PACKAGES[@]}" >> "$profile/packages.x86_64"

    stage_overlay "$profile/airootfs"
    stage_setup "$profile/airootfs/root/mentor-setup"
    cat > "$profile/airootfs/root/customize_airootfs.sh" <<'EOF'
#!/usr/bin/env bash
set -e
bash /root/mentor-setup/customize.sh
rm -rf /root/mentor-setup
EOF

    sed -i 's/^iso_name=.*/iso_name="mentor"/; s/^iso_label=.*/iso_label="MENTOR"/' "$profile/profiledef.sh"
    cat >> "$profile/profiledef.sh" <<'EOF'
file_permissions+=(
  ["/root/customize_airootfs.sh"]="0:0:755"
  ["/usr/local/bin/mentor"]="0:0:755"
  ["/usr/local/bin/mentor-mcp"]="0:0:755"
  ["/usr/local/bin/mentor-chat"]="0:0:755"
  ["/usr/local/bin/mentor-agent"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-helper"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-root-shell"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-clipboard"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-clipboard-files"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-engine"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-advisor"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-usage"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-sandbox"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-review"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-watch"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-boot"]="0:0:755"
  ["/usr/local/lib/mentor/mentor-repair-console"]="0:0:755"
)
EOF

    mkdir -p "$OUT"
    mkarchiso -v -w "$WORK/iso-work" -o "$OUT" "$profile"
    rm -rf "$WORK/iso-work"
}

mkdir -p "$WORK"
case $target in
    disk) build_disk ;;
    iso) build_iso ;;
    *) echo "usage: build.sh [disk|iso]" >&2; exit 1 ;;
esac
