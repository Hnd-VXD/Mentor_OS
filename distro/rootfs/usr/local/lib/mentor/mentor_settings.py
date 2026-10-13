"""The user's choices about Mentor itself, kept in one file of their own.

    ~/.config/mentor/settings.json    {"explain": true, "watch_off": ["disk"]}

Read by the parts the choices are about (mentor_security, mentor-watch) and changed by the
Mentor Settings window (/usr/local/bin/mentor-settings). A key that is not in the file has
the value in DEFAULTS. See /etc/mentor/SETTINGS.md.
"""
import json
import os

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mentor", "settings.json")
DEFAULTS = {
    # Say in plain words what is about to happen before the password is asked. The warning
    # after outside reading is not part of this choice: it is always shown.
    "explain": True,
    # Groups of mentor-watch's checks that are not to become cards in the chat:
    # "self", "security", "refused", "disk", "failed".
    "watch_off": [],
}


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULTS, **(saved if isinstance(saved, dict) else {})}


def get(key):
    return load().get(key, DEFAULTS.get(key))


def put(key, value):
    settings = load()
    settings[key] = value
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH + ".new", "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)
    os.replace(PATH + ".new", PATH)
