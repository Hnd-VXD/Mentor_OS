"""The mouse pointer: its color (black, white, or the accent color) and its size, chosen in Mentor Settings
(DESKTOP.md, "Pointer"). The user's wish, 2026-10-19.

Black is GNOME's own pointer, Adwaita. White and accent are Adwaita's pointer recolored: its images are a
black fill, a white outline and a faint black shadow (adwaita-cursors, Xcursor files); each pixel's lightness
says how much of fill and how much of outline it is, and it is drawn again in the new fill and outline, the
shadow left as it is. Made once into the user's own icons (~/.local/share/icons/Mentor-pointer-*), named as a
pointer theme, which GNOME's `cursor-theme` setting then uses at once. Made again when Adwaita changes (a
GNOME update) or the accent color does (mentor-chat follows `accent-color`).
"""
import array
import os
import shutil
import struct
import subprocess

SOURCE = "/usr/share/icons/Adwaita/cursors"
ICONS = os.path.expanduser("~/.local/share/icons")
PREFIX = "Mentor-pointer-"
SIZES = (24, 30, 36, 48, 72, 96)  # the sizes Adwaita's pointer is drawn in
COLORS = ("black", "white", "accent")
# libadwaita's accent tones, the ones GNOME's accent-color names
ACCENTS = {"blue": "#3584e4", "teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800", "orange": "#ed5b00",
           "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac", "slate": "#6f8396"}
IMAGE = 0xfffd0002


def _gsettings(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True).stdout.strip().strip("'")


def accent():
    key = _gsettings("get", "org.gnome.desktop.interface", "accent-color")
    return key if key in ACCENTS else "blue"


# The size the user chose. In a virtual machine the extension (part "pointer fits") may use a smaller one while
# the screen's scale would make the chosen one too large for the graphics card's pointer (DESKTOP.md, "Pointer").
CHOSEN = os.path.expanduser("~/.config/mentor/pointer-size")


def current():
    """(color, size) as the user chose them: the size from CHOSEN when it is there, else GNOME's."""
    theme = _gsettings("get", "org.gnome.desktop.interface", "cursor-theme")
    color = "white" if theme == PREFIX + "white" else "accent" if theme.startswith(PREFIX + "accent") else "black"
    try:
        with open(CHOSEN) as f:
            return color, int(f.read().strip())
    except (OSError, ValueError):
        pass
    try:
        size = int(_gsettings("get", "org.gnome.desktop.interface", "cursor-size"))
    except ValueError:
        size = 24
    return color, size


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _recolor(data, fill, outline):
    """One Xcursor file with its images drawn again: fill for Adwaita's black, outline for its white."""
    out = bytearray(data)
    _magic, _header, _version, count = struct.unpack_from("<4sIII", data, 0)
    memo = {}
    for i in range(count):
        kind, _size, position = struct.unpack_from("<III", data, 16 + 12 * i)
        if kind != IMAGE:
            continue
        width, height = struct.unpack_from("<II", data, position + 16)
        start = position + 36
        pixels = array.array("I")
        pixels.frombytes(data[start:start + 4 * width * height])
        for k, p in enumerate(pixels):
            new = memo.get(p)
            if new is None:
                a = p >> 24
                new = p
                if a:
                    r, g, b = (min(255, ((p >> s) & 255) * 255 // a) for s in (16, 8, 0))
                    light = (r * 299 + g * 587 + b * 114) / 255000
                    if not (light < 0.25 and a < 128):  # the faint shadow stays
                        c = [round((f * (1 - light) + o * light) * a / 255) for f, o in zip(fill, outline)]
                        new = (a << 24) | (c[0] << 16) | (c[1] << 8) | c[2]
                memo[p] = new
            pixels[k] = new
        out[start:start + 4 * width * height] = pixels.tobytes()
    return bytes(out)


def make(name, fill, outline):
    """The pointer theme NAME in the user's icons, unless it is there and Adwaita has not changed since."""
    folder = os.path.join(ICONS, name)
    stamp = os.path.join(folder, "made-from")
    source = str(os.stat(os.path.join(SOURCE, "default")).st_mtime) + f" {fill} {outline}"
    try:
        with open(stamp) as f:
            if f.read() == source:
                return name
    except OSError:
        pass
    work = folder + ".new"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, "cursors"))
    for entry in os.scandir(SOURCE):
        target = os.path.join(work, "cursors", entry.name)
        if entry.is_symlink():
            os.symlink(os.readlink(entry.path), target)
        elif entry.is_file():
            with open(entry.path, "rb") as f:
                data = f.read()
            with open(target, "wb") as f:
                f.write(_recolor(data, _rgb(fill), _rgb(outline)) if data[:4] == b"Xcur" else data)
    with open(os.path.join(work, "index.theme"), "w") as f:
        f.write(f"[Icon Theme]\nName={name}\nComment=Adwaita's pointer in other colors, made by Mentor\n"
                "Inherits=Adwaita\n")
    with open(os.path.join(work, "made-from"), "w") as f:
        f.write(source)
    shutil.rmtree(folder, ignore_errors=True)
    os.rename(work, folder)
    return name


def theme_for(color):
    """The name of the pointer theme for a color, made first when it has to be (a few seconds)."""
    if color == "white":
        return make(PREFIX + "white", "#ffffff", "#000000")
    if color == "accent":
        key = accent()
        for entry in os.scandir(ICONS) if os.path.isdir(ICONS) else ():  # the accent pointers of before
            if entry.name.startswith(PREFIX + "accent-") and entry.name != PREFIX + "accent-" + key:
                shutil.rmtree(entry.path, ignore_errors=True)
        return make(PREFIX + "accent-" + key, ACCENTS[key], "#ffffff")
    return "Adwaita"


def apply(color=None, size=None):
    """Use a color and/or a size. Returns (color, size) as they are then."""
    if color is not None:
        if color not in COLORS:
            raise ValueError(f"no pointer color {color!r}: black, white or accent")
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme_for(color)],
                       check=False)
    if size is not None:
        size = min(SIZES, key=lambda s: abs(s - int(size)))
        os.makedirs(os.path.dirname(CHOSEN), exist_ok=True)
        with open(CHOSEN, "w") as f:
            f.write(f"{size}\n")
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(size)], check=False)
    return current()


def follow_accent():
    """The accent color changed (an Accent set, or Settings, Appearance): an accent pointer takes it too."""
    color, _size = current()
    if color == "accent":
        apply("accent")
