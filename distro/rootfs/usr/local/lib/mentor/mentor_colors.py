"""Window colors: matched sets of tones for GNOME's windows, chosen in Mentor Settings (DESKTOP.md,
"Window colors").

Each palette sets libadwaita's documented named colors (the CSS variables --window-bg-color and the
like) in the user's own stylesheet, ~/.config/gtk-4.0/gtk.css, which GTK reads on top of the theme for
every GTK 4 program, and the same names as @define-color in ~/.config/gtk-3.0/gtk.css for the older
ones. Only the block between BEGIN and END is Mentor's; anything else in those files is the user's and
stays. A light palette also sets GNOME's style to light (org.gnome.desktop.interface color-scheme), a
dark one to dark, so that text, icons and the shades libadwaita derives stay readable.

Two tones, as GNOME's own: the window and the content (view) are one, the sidebar and the title bar a
little lighter in dark sets and a little deeper in light ones. Text is chosen for a contrast of at least
7:1 against every background of its set.
"""
import os

BEGIN = "/* BEGIN Mentor window colors (Mentor Settings, Window colors; changed there, not here) */"
END = "/* END Mentor window colors */"

# name, light?, window, view, sidebar, headerbar, text
PALETTES = [
    ("GNOME dark", False, None, None, None, None, None),       # nothing set: GNOME's own
    ("Slate", False, "#1f2430", "#1b1f29", "#272e3b", "#2a3140", "#e6e9ef"),
    ("Navy", False, "#1a2233", "#161d2b", "#212b40", "#243046", "#e6eaf2"),
    ("Deep teal", False, "#1b2728", "#172122", "#233334", "#263738", "#e4eeee"),
    ("Forest", False, "#1e261f", "#19201a", "#273128", "#2a352b", "#e6ede6"),
    ("Olive", False, "#26271d", "#202118", "#303126", "#34362a", "#ececdf"),
    ("Espresso", False, "#2a2420", "#231e1a", "#342d28", "#393129", "#efe8e2"),
    ("Warm charcoal", False, "#262422", "#201e1c", "#302d2b", "#34312e", "#eeeae6"),
    ("Burgundy", False, "#2a1f22", "#241a1d", "#352629", "#3a2a2d", "#f0e6e8"),
    ("Plum", False, "#261f2b", "#201a25", "#302737", "#352a3c", "#eee8f1"),
    ("GNOME light", True, None, None, None, None, None),
    ("Cream", True, "#f7f3ea", "#fbf8f2", "#ece5d6", "#efe9dc", "#2e2a24"),
    ("Soft yellow", True, "#faf5e1", "#fdfaee", "#efe6c4", "#f3ebcf", "#2f2b1e"),
    ("Sand", True, "#f3ece2", "#f8f3ec", "#e6dccd", "#eae1d3", "#33291f"),
    ("Warm grey", True, "#f1f0ee", "#f7f6f4", "#e3e1de", "#e8e6e3", "#2b2a28"),
    ("Blue-grey", True, "#eef2f6", "#f5f8fb", "#dfe6ee", "#e5ebf1", "#1f2933"),
    ("Sage", True, "#eef2ec", "#f5f8f3", "#dfe7db", "#e5ece1", "#24301f"),
    ("Mint", True, "#ecf4f1", "#f4f9f7", "#dceae4", "#e2eee9", "#1f302a"),
    ("Blush", True, "#f6eeee", "#fbf6f6", "#ebdfdf", "#efe5e5", "#362828"),
    ("Lavender", True, "#f1eff5", "#f7f6fa", "#e4e0ec", "#e9e5f0", "#2a2633"),
]


# GNOME's own tones (libadwaita), for a window that has to change to them while it is open (Mentor Settings,
# live_css): the stylesheets are only read when a program starts.
GNOME_TONES = {False: ("#222226", "#1d1d20", "#2e2e32", "#2e2e32", "#ffffff"),
               True: ("#fafafb", "#ffffff", "#ebebed", "#ffffff", "#2e3436")}


# Accent sets (the user's wish, 2026-10-19: "Orange should be like selecting a theme, make the elements
# orange"): as Windows' "accent color on title bars and taskbar". The title bars, the taskbar and the
# shell's menus in the color, deepened until white text on it has a contrast of at least 4.6:1; the side
# panels a dark tint of it; the windows themselves GNOME's dark, so all text stays white and readable.
# Each also sets GNOME's own accent color (switches, selections) to the same: the key after the name.
ACCENT_SETS = [
    ("Blue", "blue", "#2e74c8", "#2b3a50"), ("Teal", "teal", "#1d7e90", "#273c44"),
    ("Green", "green", "#338241", "#2c3d32"), ("Yellow", "yellow", "#9b6a00", "#433824"),
    ("Orange", "orange", "#c74c00", "#4d3124"), ("Red", "red", "#dc2b3f", "#512a32"),
    ("Pink", "pink", "#b25180", "#483340"), ("Purple", "purple", "#9141ac", "#412f4a"),
    ("Slate", "slate", "#637587", "#373a42"),
]
# as palettes: name, light?, window, view, sidebar, headerbar, text
ACCENT_PALETTES = [(name, False, "#222226", "#1d1d20", side, header, "#ffffff")
                   for name, _key, header, side in ACCENT_SETS]
ACCENT_KEYS = {name: key for name, key, _header, _side in ACCENT_SETS}


def find(name):
    wanted = str(name).strip().lower()
    # "Slate" is a dark set and an accent: the accent one is called "Slate accent" where both could be meant
    if wanted.endswith(" accent"):
        return next((p for p in ACCENT_PALETTES if p[0].lower() == wanted[:-7]), None)
    return next((p for p in PALETTES + ACCENT_PALETTES if p[0].lower() == wanted), None)


def is_accent(palette):
    return palette is not None and any(palette is p for p in ACCENT_PALETTES)


def label(palette):
    """The name to show and to give `mentor colors`: the accent sets say so ("Orange accent")."""
    return palette[0] + " accent" if is_accent(palette) else palette[0]


def css(palette, gtk3=False):
    """The block for one palette: libadwaita's variables (GTK 4), or @define-color (GTK 3)."""
    name, _light, window, view, sidebar, header, text = palette
    if window is None:
        return ""
    name = label(palette)
    # an accent set keeps its color for title bars (and taskbar and menus): dialogs, popovers and cards take
    # GNOME's own dark grey, or every one of them would be orange (in the side panels' tint they looked muddy)
    panel = GNOME_TONES[False][2] if is_accent(palette) else header
    colors = {
        "window-bg-color": window, "window-fg-color": text,
        "view-bg-color": view, "view-fg-color": text,
        "headerbar-bg-color": header, "headerbar-fg-color": text, "headerbar-backdrop-color": window,
        "sidebar-bg-color": sidebar, "sidebar-fg-color": text, "sidebar-backdrop-color": sidebar,
        "secondary-sidebar-bg-color": sidebar, "secondary-sidebar-fg-color": text,
        "secondary-sidebar-backdrop-color": sidebar,
        "dialog-bg-color": panel, "dialog-fg-color": text,
        "popover-bg-color": panel, "popover-fg-color": text,
        "thumbnail-bg-color": panel, "thumbnail-fg-color": text,
        # Cards and boxed lists (Settings' rows) carry text too: set, so that a program open while the style
        # changes between light and dark never shows white text on a light card (2026-10-18).
        "card-bg-color": view if _light else panel, "card-fg-color": text,
    }
    if gtk3:
        lines = [f"@define-color {key.replace('-', '_')} {value};" for key, value in colors.items()]
        lines += [f"@define-color theme_bg_color {window};", f"@define-color theme_fg_color {text};",
                  f"@define-color theme_base_color {view};", f"@define-color theme_text_color {text};"]
    else:
        lines = [":root {"] + [f"  --{key}: {value};" for key, value in colors.items()] + ["}"]
        if is_accent(palette):
            # libadwaita draws title bars flat, the window's own color through them, so --headerbar-bg-color
            # alone never showed (tested 2026-10-19): an accent set paints them, in focus; behind another
            # window they take the window's color, as GNOME's do.
            lines += ["toolbarview > .top-bar, window > headerbar.titlebar {",
                      "  background-color: var(--headerbar-bg-color); color: var(--headerbar-fg-color); }",
                      "toolbarview > .top-bar:backdrop, window > headerbar.titlebar:backdrop {",
                      "  background-color: var(--headerbar-backdrop-color); }"]
    return "\n".join([BEGIN, f"/* {name} */", *lines, END])


def live_css(name):
    """The colors of a palette for a window that is open (GNOME's own tones for the GNOME sets), to put on
    top of what it read at its start."""
    palette = find(name)
    if palette is None:
        return ""
    if palette[2] is None:
        palette = (palette[0], palette[1], *GNOME_TONES[palette[1]])
    return css(palette)


def _write(path, block, begin=BEGIN, end=END):
    """Put Mentor's block in a stylesheet, or take it out (block empty); the rest of the file stays."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    if begin in text and end in text:
        text = text[:text.index(begin)] + text[text.index(end) + len(end):]
    text = text.strip("\n")
    text = (text + "\n\n" + block if text and block else text or block).strip("\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    elif os.path.exists(path):
        os.remove(path)


def apply(name):
    """Use a palette: the two stylesheets, and GNOME's light or dark style. Programs that are open take
    the new colors when they are opened again. Returns the palette, or None when there is no such one."""
    palette = find(name)
    if palette is None:
        return None
    home = os.path.expanduser("~/.config")
    _write(os.path.join(home, "gtk-4.0", "gtk.css"), css(palette))
    _write(os.path.join(home, "gtk-3.0", "gtk.css"), css(palette, gtk3=True))
    buttons()
    import subprocess
    # The taskbar (Dash to Panel, its own setting for a background color) in the set's title bar tone, so
    # that it belongs to the set (the user's wish); the GNOME sets give it back its own.
    # Mentor's extension (part "taskbar color") keeps it so: it uses this tone only while GNOME's style is the
    # set's (light or dark), and gives the taskbar back its own colors when the style is switched by hand
    # (the "Dark Style" switch), so that its text is never light on light (2026-10-18).
    note = os.path.join(home, "mentor", "taskbar-color")
    taskbar = "org.gnome.shell.extensions.dash-to-panel"
    if palette[5]:
        os.makedirs(os.path.dirname(note), exist_ok=True)
        with open(note, "w") as f:
            # the title bar tone, light or dark, then the window and content tones (the shell's menus use them);
            # an accent set adds the menus' own tone, GNOME's dark grey (the extension's part "menu colors")
            menus = f" {GNOME_TONES[False][2]}" if is_accent(palette) else ""
            f.write(f"{palette[5]} {'light' if palette[1] else 'dark'} {palette[2]} {palette[3]}{menus}\n")
        subprocess.run(["gsettings", "set", taskbar, "trans-bg-color", palette[5]], check=False)
        subprocess.run(["gsettings", "set", taskbar, "trans-use-custom-bg", "true"], check=False)
    else:
        if os.path.exists(note):
            os.remove(note)
        subprocess.run(["gsettings", "reset", taskbar, "trans-use-custom-bg"], check=False)
        subprocess.run(["gsettings", "reset", taskbar, "trans-bg-color"], check=False)
    if is_accent(palette):  # GNOME's own accent the same color: switches, selections, today in the calendar
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "accent-color",
                        ACCENT_KEYS[palette[0]]], check=False)
    # The style last, after the note: the extension's part "keep style" puts back any style that is not the
    # one the note names, and would otherwise undo this change (2026-10-19).
    subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme",
                    "prefer-light" if palette[1] else "prefer-dark"], check=False)
    return palette


# The window buttons as round lights, as on a Mac but at the right and in GNOME's order: minimize
# yellow, maximize green, close red at the far right (the user's wish, 2026-10-18). Their sign shows
# when the pointer is over them. In every set of colors, GNOME's own included: a block of its own.
BUTTONS_BEGIN = "/* BEGIN Mentor window buttons (DESKTOP.md, Window buttons; changed there, not here) */"
BUTTONS_END = "/* END Mentor window buttons */"
LIGHTS = (("minimize", "#febc2e"), ("maximize", "#28c840"), ("close", "#ff5f57"))

def light(color, size=18, corner=5):
    """One light: a square of SIZE pixels (18: 14 was small, the user, 2026-10-18) with rounded corners (the user's choice over circles,
    2026-10-18), whatever the size of the button. Drawn as layers of a fixed size in the middle of the
    button, not as the button's own rounded background, because Chromium (GTK 4) and Electron programs
    (GTK 3) paint the button as large as their own title bar is high: rounded backgrounds came out twice
    the size. The layers: a band across, a band down, and a quarter circle in each corner, whose edges
    fade over one pixel into the color made clear, so they are smooth at any scale. Returns the
    declarations."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    clear = f"rgba({r}, {g}, {b}, 0)"
    near, far = corner, size - corner
    layers = [f"linear-gradient(to bottom, {clear} {near}px, {color} {near}px, {color} {far}px, {clear} {far}px)",
              f"linear-gradient(to right, {clear} {near}px, {color} {near}px, {color} {far}px, {clear} {far}px)"]
    layers += [f"radial-gradient(circle at {x}px {y}px, {color} {corner - 0.5}px, {clear} {corner + 0.5}px)"
               for x in (near, far) for y in (near, far)]
    n = len(layers)
    return (f"background-image: {', '.join(layers)}; background-size: {', '.join([f'{size}px {size}px'] * n)};"
            f" background-position: {', '.join(['center'] * n)}; background-repeat: {', '.join(['no-repeat'] * n)};")


BUTTONS_GTK4 = "\n".join([
    # libadwaita and Chromium: the light is drawn on the button's image
    "windowcontrols > button { min-width: 26px; min-height: 26px; padding: 0; margin: 0 1px;"
    " background: none; box-shadow: none; }",
    "windowcontrols > button > image { -gtk-icon-size: 12px; padding: 3px; border-radius: 0;"
    " background-color: transparent; color: transparent; box-shadow: none; }",
    *[f"windowcontrols > button.{name} > image, windowcontrols > button.{name}:hover > image,"
      f" windowcontrols > button.{name}:active > image {{ {light(color)} }}"
      for name, color in LIGHTS],
    "windowcontrols > button:hover > image { color: rgba(0, 0, 0, 0.6); }",
    "windowcontrols > button:active > image { filter: brightness(0.85); }",
])

BUTTONS_GTK3 = "\n".join([
    # GTK 3 (Electron programs, Bitwarden among them, draw their title bar from it): the button itself
    # is the light, a plain rounded square. GTK 3 draws layered gradients wrongly (broken shapes, tested
    # in Bitwarden 2026-10-18), and Electron keeps the button's own size.
    "button.titlebutton { min-width: 18px; min-height: 18px; padding: 0; margin: 0 3px; border: none;"
    " border-radius: 5px; background-image: none; box-shadow: none; color: transparent;"
    " -gtk-icon-shadow: none; }",
    "button.titlebutton image { -gtk-icon-transform: scale(0.6); }",
    *[f"button.titlebutton.{name}, button.titlebutton.{name}:hover, button.titlebutton.{name}:active,"
      f" button.titlebutton.{name}:backdrop {{ background-color: {color}; }}" for name, color in LIGHTS],
    "button.titlebutton:hover { color: rgba(0, 0, 0, 0.6); }",
])


def buttons():
    """Put the round window buttons into the user's two stylesheets when they are not there as now (at
    every login, by the assistant; and with each set of colors). Programs show them when opened again."""
    home = os.path.expanduser("~/.config")
    for folder, rules in (("gtk-4.0", BUTTONS_GTK4), ("gtk-3.0", BUTTONS_GTK3)):
        path = os.path.join(home, folder, "gtk.css")
        block = "\n".join([BUTTONS_BEGIN, rules, BUTTONS_END])
        try:
            with open(path, encoding="utf-8") as f:
                if block in f.read():
                    continue
        except OSError:
            pass
        _write(path, block, BUTTONS_BEGIN, BUTTONS_END)


def current():
    """The name of the palette in use, from Mentor's block (GNOME's own when there is none)."""
    try:
        with open(os.path.expanduser("~/.config/gtk-4.0/gtk.css"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    if BEGIN in text:
        line = text[text.index(BEGIN):].split("\n")[1]
        return line.strip("/* ").strip()
    import subprocess  # none of Mentor's: GNOME's own, light or dark as GNOME's style is
    scheme = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                            capture_output=True, text=True).stdout.strip()
    return "GNOME light" if "light" in scheme else "GNOME dark"
