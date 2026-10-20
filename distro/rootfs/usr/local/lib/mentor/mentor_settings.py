"""The user's choices about Mentor itself, kept in one file of their own.

    ~/.config/mentor/settings.json    {"watch_off": ["disk"], "auto_review": true, "exact": false}

Read by the parts the choices are about (mentor_security, mentor-watch) and changed by the
Mentor Settings window (/usr/local/bin/mentor-settings). A key that is not in the file has
the value in DEFAULTS. See /etc/mentor/SETTINGS.md.
"""
import json
import os

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mentor", "settings.json")
DEFAULTS = {
    # A menu where the pointer is when a picture comes from Windows' Print Screen (a smaller copy, save as JPG…;
    # mentor-clipboard, the extension's HostPictureMenu; DESKTOP.md, "Screenshots").
    "picture_menu": True,
    # Say in plain words what is about to happen before the password is asked. The warning
    # after outside reading is not part of this choice: it is always shown.
    "explain": True,
    # Groups of mentor-watch's checks that are not to become cards in the chat:
    # "self", "security", "refused", "disk", "failed".
    "watch_off": [],
    # When other computers try to get in, have the agent look by itself and say what it was
    # (mentor-firewall-watch). Off: an ordinary card, and nothing goes to a model unasked.
    "auto_review": True,
    # Show the exact command, file or program names in the password dialog, under the agent's
    # own sentence. For people who read commands; everyone else gets the sentence alone.
    "exact": False,
    # After something that took some doing has worked, offer (a green card) to write it down as
    # a recipe. Off: only when the user asks for one.
    "offer_recipes": True,
    # When the rules find something serious in a recipe that came from the recipes site, tell the
    # site so (a signed report, with nothing of this computer's in it). It looks for itself.
    "report_to_hub": True,
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
