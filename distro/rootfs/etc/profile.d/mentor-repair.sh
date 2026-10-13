# In a repair start (the launcher's "Repair", see /etc/mentor/REPAIR.md) the first console
# opens on the agent. Leaving it (/shell) gives the command line; `mentor repair` comes back.
if [ "$(tty 2>/dev/null)" = /dev/tty1 ] && [ -z "$MENTOR_REPAIR_SHOWN" ] && grep -qw 'mentor.repair=1' /proc/cmdline 2>/dev/null; then
    export MENTOR_REPAIR_SHOWN=1
    setfont -d 2>/dev/null  # letters twice the size: the window is a whole screen
    /usr/local/bin/mentor repair || cat <<'EOF'

  The repair console could not be started, or has nobody to talk to. By hand:
    sha256sum --quiet -c /etc/mentor/source/MANIFEST.sha256      which of Mentor's files are missing or changed
    sudo cp -a /etc/mentor/source/rootfs/PATH /PATH              put one back as it was built
    less /etc/mentor/REBUILD.md                                  everything else
    systemctl reboot                                             restart
EOF
fi
