"""What came with Mentor, and what the user added: the packages and apps that are never uninstalled.

Mentor's packages are the ones on its list (/etc/mentor/source/build/packages.x86_64, which every
update brings up to date), what pacstrap puts in besides (base, linux, mkinitcpio), the names
policy.toml protects, and everything those depend on. Mentor's own files are those in
/etc/mentor/source/MANIFEST.sha256. An app came with Mentor when its .desktop file belongs to one
of those packages or to no package at all (Mentor's own, in the overlay).

Read by the root side (mentor_core: pkg_remove, sandbox_apply, run_root refuse to take them away),
by the tools (package_remove says so before any password), and written out for the shell as
/usr/share/mentor/bundled-apps, one desktop id a line: the app grid's "Uninstall" is not shown
on those. That list is made by `mentor-apps refresh`, from mentor-enable (image build, every
update) and from a pacman hook (etc/pacman.d/hooks/mentor-apps.hook). etc/mentor/UNINSTALL.md.
"""
import glob
import os
import re
import tomllib

SOURCE = "/etc/mentor/source"
PACKAGE_LIST = f"{SOURCE}/build/packages.x86_64"
MANIFEST = f"{SOURCE}/MANIFEST.sha256"
POLICY = "/etc/mentor/policy.toml"
LOCAL_DB = "/var/lib/pacman/local"
BUNDLED_APPS = "/usr/share/mentor/bundled-apps"
APP_FOLDERS = ("/usr/share/applications", "/usr/local/share/applications")
# Installed by build.sh's pacstrap before the list.
PACSTRAP = ("base", "linux", "mkinitcpio")
_NAME = re.compile(r"^[^<>=:]+")


def _db():
    """{name: {"depends": [...], "provides": [...], "groups": [...], "dir": path}} from pacman's local database."""
    packages = {}
    for desc in glob.glob(f"{LOCAL_DB}/*/desc"):
        fields, key = {}, None
        try:
            with open(desc, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("%") and line.endswith("%"):
                        key = line.strip("%")
                        fields[key] = []
                    elif line and key:
                        fields[key].append(line)
        except OSError:
            continue
        name = (fields.get("NAME") or [None])[0]
        if name:
            packages[name] = {"depends": [_NAME.match(d).group(0) for d in fields.get("DEPENDS", []) if _NAME.match(d)],
                              "provides": [_NAME.match(p).group(0) for p in fields.get("PROVIDES", []) if _NAME.match(p)],
                              "groups": fields.get("GROUPS", []), "dir": os.path.dirname(desc)}
    return packages


def listed():
    """The names Mentor installs on purpose: its list, pacstrap's, and what policy.toml protects."""
    names = set(PACSTRAP)
    try:
        with open(PACKAGE_LIST, encoding="utf-8") as f:
            names.update(line.split("#")[0].strip() for line in f)
    except OSError:
        pass
    try:
        with open(POLICY, "rb") as f:
            names.update(tomllib.load(f).get("packages", {}).get("protected", []))
    except (OSError, tomllib.TOMLDecodeError):
        pass
    names.discard("")
    return names


def protected_packages(db=None):
    """The installed packages that are part of Mentor: the listed ones (a group stands for its members)
    and, all the way down, what they depend on."""
    db = _db() if db is None else db
    provider = {}
    for name, p in db.items():
        provider.setdefault(name, name)
        for alias in p["provides"]:
            provider.setdefault(alias, name)
    wanted = listed()
    todo = [name for name, p in db.items() if name in wanted or wanted.intersection(p["groups"])]
    todo += [provider[n] for n in wanted if n in provider]
    seen = set()
    while todo:
        name = todo.pop()
        if name in seen or name not in db:
            continue
        seen.add(name)
        todo += [provider[d] for d in db[name]["depends"] if d in provider]
    return seen


def mentor_files():
    """Mentor's own files, as absolute paths (the overlay, as built or as the last update left it)."""
    files = set()
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            for line in f:
                _, sep, path = line.rstrip("\n").partition("  ")
                if sep and path.startswith("/"):
                    files.add(path)
    except OSError:
        pass
    return files


def _owners(db):
    """{absolute path: package} for the .desktop files of the app folders."""
    owners = {}
    folders = tuple(f.lstrip("/") + "/" for f in APP_FOLDERS)
    for name, p in db.items():
        try:
            with open(os.path.join(p["dir"], "files"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.endswith(".desktop") and line.startswith(folders):
                        owners["/" + line] = name
        except OSError:
            continue
    return owners


def bundled_apps():
    """The desktop ids of the apps that came with Mentor, sorted."""
    db = _db()
    keep = protected_packages(db)
    owners = _owners(db)
    ids = set()
    for folder in APP_FOLDERS:
        for path in glob.glob(f"{folder}/*.desktop"):
            owner = owners.get(path)
            if owner is None or owner in keep:
                ids.add(os.path.basename(path))
    return sorted(ids)


def refresh():
    """Write BUNDLED_APPS, only when it changed (so that a sandbox where only the user's apps came or went
    does not show it as a change)."""
    text = "".join(f"{i}\n" for i in bundled_apps())
    try:
        with open(BUNDLED_APPS, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(BUNDLED_APPS), exist_ok=True)
    with open(BUNDLED_APPS + ".new", "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(BUNDLED_APPS + ".new", 0o644)
    os.replace(BUNDLED_APPS + ".new", BUNDLED_APPS)
    return True


def package_of_dir(rel):
    """The package whose pacman database folder `rel` is (var/lib/pacman/local/NAME-VER-REL), or None."""
    m = re.fullmatch(r"var/lib/pacman/local/([^/]+)/?", rel)
    if not m:
        return None
    try:
        with open(f"/{rel.rstrip('/')}/desc", encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
        return lines[lines.index("%NAME%") + 1].strip()
    except (OSError, ValueError, IndexError):
        return m.group(1).rsplit("-", 2)[0]
