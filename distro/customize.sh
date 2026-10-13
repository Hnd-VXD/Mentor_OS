#!/usr/bin/env bash
# Runs inside the target root (arch-chroot) for both the disk image and the ISO.
# Expects config.env next to it.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=config.env
source "$here/config.env"

# Identity
rm -f /etc/os-release
cat > /etc/os-release <<EOF
NAME="Mentor"
PRETTY_NAME="Mentor (Agentic Linux)"
ID=mentor
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;23;147;209"
HOME_URL="https://archlinux.org/"
LOGO=archlinux-logo
EOF
echo "$MENTOR_HOSTNAME" > /etc/hostname

# Locale and time
ln -sf "/usr/share/zoneinfo/$MENTOR_TIMEZONE" /etc/localtime
sed -i "s/^#\(${MENTOR_LOCALE} \)/\1/; s/^#\(el_GR.UTF-8 \)/\1/" /etc/locale.gen
locale-gen
echo "LANG=$MENTOR_LOCALE" > /etc/locale.conf

# With automatic login there is no password to unlock a keyring with, and apps
# that save secrets (browsers) would ask the user to invent one. New users get a
# default keyring without a password instead.
# It is the one called "login": a login with the password (after logging out) makes a
# keyring of that name if there is none, locked by the password, and programs that look
# for "login" first (the Antigravity CLI among them) then find it locked at the next
# automatic login and lose what they kept. With ours in that place there is only ever one.
keyrings=/etc/skel/.local/share/keyrings
install -d -m 700 /etc/skel/.local /etc/skel/.local/share "$keyrings"
echo -n login > "$keyrings/default"
cat > "$keyrings/login.keyring" <<EOF
[keyring]
display-name=Login
ctime=0
mtime=0
lock-on-idle=false
lock-after=false
EOF
chmod 600 "$keyrings"/*

# User
if ! id "$MENTOR_USER" &>/dev/null; then
    useradd -m -G wheel -s /bin/bash "$MENTOR_USER"
fi
echo "$MENTOR_USER:$MENTOR_PASSWORD" | chpasswd
echo '%wheel ALL=(ALL:ALL) ALL' > /etc/sudoers.d/10-wheel
chmod 440 /etc/sudoers.d/10-wheel

# Desktop
mkdir -p /etc/gdm
cat > /etc/gdm/custom.conf <<EOF
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=$MENTOR_USER
EOF
dconf update
systemctl set-default graphical.target
systemctl --global enable mentor-watch.timer mentor-firewall-watch.service mentor-recipe-watch.service
systemctl enable gdm.service NetworkManager.service systemd-timesyncd.service qemu-guest-agent.service
# Safe start-up: see usr/local/lib/mentor/mentor_boot.py.
systemctl enable mentor-boot-check.service mentor-boot-deadline.service mentor-boot-confirm.path mentor-boot-arm.service
systemctl enable mentor-advisor.timer
# The firewall: what comes in from other computers is refused (etc/nftables.conf, etc/mentor/SECURITY.md).
systemctl enable nftables.service
# Where the agent's tools ask for root, with a password dialog that says exactly what for (mentor-rootd).
systemctl enable mentor-root.socket

# Boot splash: our own theme (distro/splash). It shows the emblem (a second one while
# the system goes back after a failed start), the hint drawn here from hint.svg, and
# the stock spinner's frames.
theme=/usr/share/plymouth/themes/mentor
rm -rf "$theme"
install -d "$theme"
cp "$here"/splash/mentor.plymouth "$here"/splash/mentor.script "$here"/splash/logo-1.png "$here"/splash/logo-2.png "$theme/"
rsvg-convert "$here/splash/hint.svg" -o "$theme/hint.png"
frames=0
for frame in /usr/share/plymouth/themes/spinner/throbber-*.png; do
    cp "$frame" "$theme/throbber-$frames.png"
    frames=$((frames + 1))
done
sed -i "s/@FRAMES@/$frames/g" "$theme/mentor.script"

# Agent layer
install -d -m 755 /var/log/mentor
gtk-update-icon-cache -q -f /usr/share/icons/hicolor

# Claude Code, Codex and Google's Antigravity CLI, the engines for those who run the assistant on their
# Claude, ChatGPT or Google account, are not installed here: an image that is given to others should not
# carry them. Each user gets them on first sign-in (rootfs/usr/local/lib/mentor/mentor-engine).
