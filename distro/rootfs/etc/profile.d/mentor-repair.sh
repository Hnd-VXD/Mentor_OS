# In a repair start (the launcher's "Repair", see /etc/mentor/REPAIR.md) the first console
# opens on the agent. Leaving it (/shell) gives the command line; `mentor repair` comes back.
if [ "$(tty 2>/dev/null)" = /dev/tty1 ] && [ -z "$MENTOR_REPAIR_SHOWN" ] && grep -qw 'mentor.repair=1' /proc/cmdline 2>/dev/null; then
    export MENTOR_REPAIR_SHOWN=1
    /usr/local/bin/mentor repair || cat <<'EOF'

  The repair console could not be started, or has nobody to talk to. By hand:
    sha256sum --quiet -c /etc/mentor/source/MANIFEST.sha256      which of Mentor's files are missing or changed
    sudo cp -a /etc/mentor/source/rootfs/PATH /PATH              put one back as it was built
    less /etc/mentor/REBUILD.md                                  everything else
    systemctl reboot                                             restart
EOF
fi

# The emergency console (Ctrl+Alt+Backspace, mentor-emergency-key; /etc/mentor/FREEZES.md): the
# third console, opened by the key in the last two minutes, while the desktop runs on behind it.
# Drawn by kmscon (the login runs on a pseudo-terminal under it), or the kernel's tty3 without it.
mentor_under_kmscon() {
    [ "$(ps -o comm= -p "$(ps -o ppid= -p "$PPID" 2>/dev/null | tr -d ' ')" 2>/dev/null)" = kmscon ]
}
if { [ "$(tty 2>/dev/null)" = /dev/tty3 ] || mentor_under_kmscon; } && [ -z "$MENTOR_REPAIR_SHOWN" ] && [ -n "$(find /run/mentor/emergency -mmin -2 2>/dev/null)" ]; then
    export MENTOR_REPAIR_SHOWN=1 MENTOR_EMERGENCY=1
    setfont 2>/dev/null  # the console's own letter size: the welcome and its logo fit on one screen
    # On the command line left behind, `desktop` goes back (`/desktop` there is a path, not a command).
    desktop() {
        for session in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
            case "$(loginctl show-session "$session" -p Type --value)" in
                wayland|x11) loginctl activate "$session"; return ;;
            esac
        done
        echo "No desktop to go back to: systemctl reboot restarts."
    }
    /usr/local/bin/mentor repair || echo "  The agent could not be started here."
    echo "  A command line.  desktop  goes back to the desktop (or Ctrl+Alt+F2);  mentor repair  talks to the agent again."
fi
