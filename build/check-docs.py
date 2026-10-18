#!/usr/bin/env python3
"""Finds gaps between Mentor's files and its instruction docs (distro/rootfs/etc/mentor).

The agent in Mentor mends and rebuilds Mentor's parts from those docs alone, so a file,
part, command or tool that no doc names is one it cannot put back. build.sh runs this
before it packs an image or an update and stops on a gap.

    python3 build/check-docs.py        one line for each gap; exit 1 if there is any

Checks:
 1. every file under distro/rootfs (each is in MANIFEST.sha256) has a row in REBUILD.md
 2. every part of the shell extension (this._part('NAME') has a row in DESKTOP.md
 3. every subcommand of /usr/local/bin/mentor and every tool of mentor_tools.py is in TOOLS.md
    (or in the doc REBUILD.md points to for it)
 4. every doc REBUILD.md names exists; every DOC.md "Section" points to a heading
 5. every Mentor path in backticks (/usr, /etc, /var) exists in rootfs, is made by the
    build, or is a known runtime path
"""
import ast
import fnmatch
import os
import re
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTFS = os.path.join(SRC, "distro", "rootfs")
DOCS = os.path.join(ROOTFS, "etc", "mentor")

# Made by build.sh or customize.sh, or only while Mentor runs: not in distro/rootfs.
RUNTIME = [
    "/etc/mentor/source", "/etc/mentor/version", "/etc/mentor/version-name",
    "/etc/mentor/update-notes", "/etc/mentor/updates-included.json",
    "/var/lib/mentor", "/var/log/mentor", "/var/cache/mentor", "/var/tmp/mentor",
    "/run", "/proc", "/sys", "/tmp", "/home", "/root",
    "/etc/kernel/mentor-boot.conf",   # written only for a kernel other than the stock one (BOOT.md)
    "/usr/local/libexec/mentor",      # where the agent puts a changed engine program (ENGINES.md)
    "/etc/mentor-test",               # the file a check in TOOLS.md makes in the sandbox
]
# Words that stand for a name in a path (/etc/mentor/source/rootfs/PATH, mentor-webapp-NAME.desktop).
PLACEHOLDER = re.compile(r"\b(PATH|NAME|USER|ID|N|VERSION|DOC|FILE|PART)\b")

gaps = []


def gap(text):
    gaps.append(text)
    print(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def shipped():
    """Every file Mentor ships, as its path on the system (what MANIFEST.sha256 lists)."""
    files = []
    for top, dirs, names in os.walk(ROOTFS):
        # Python's caches from running a file in the checkout: not Mentor's, nothing to document.
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            rel = os.path.relpath(os.path.join(top, name), ROOTFS).replace(os.sep, "/")
            files.append("/" + rel)
    return sorted(files)


def docs():
    return {name: read(os.path.join(DOCS, name)) for name in sorted(os.listdir(DOCS)) if name.endswith(".md")}


def table_rows(text):
    """The rows of every table in a markdown text, as lists of cells (header and rule left out)."""
    rows, in_table = [], False
    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            in_table = True       # the rule under the header; the rows follow
            continue
        if in_table:
            rows.append(cells)
    return rows


def headings(text):
    """What a "Section" reference can point to: a heading, a paragraph or list item that starts with
    a bold name (**Who asks for the password.**), or the first cell of a table row (Key bindings: ...)."""
    found = [re.sub(r"^#+\s*", "", line).strip() for line in text.splitlines() if re.match(r"#+\s", line)]
    found += re.findall(r"^(?:[-*]\s+|\d+\.\s+)?\*\*([^*\n]+)\*\*", text, re.M)
    found += [cells[0] for cells in table_rows(text) if cells]
    return found


def ticks(text):
    return re.findall(r"`([^`\n]+)`", text)


def row_patterns(cell):
    """The files a REBUILD.md cell names. A name without a folder is in the folder of the path
    before it (`/usr/local/lib/mentor/mentor-helper`, `mentor-sandbox`); one that starts with a
    dot is the name before it with another ending (`mentor-advisor.service`, `.timer`)."""
    patterns, folder, stem = [], None, None
    for tok in ticks(cell):
        if " " in tok:
            continue
        if tok.startswith("/"):
            path = tok
        elif tok.startswith("~"):
            folder = None
            continue
        elif tok.startswith(".") and stem is not None:
            path = folder + "/" + stem + tok
        elif folder is not None and re.fullmatch(r"[\w.*@+-]+", tok):
            path = folder + "/" + tok
        else:
            continue
        folder, base = path.rsplit("/", 1)
        stem = base.split(".", 1)[0] if base and not base.startswith(".") else stem
        patterns.append(path)
    return patterns


def check_rebuild_rows(rebuild):
    """1. Every shipped file has a row in REBUILD.md."""
    patterns = []
    for cells in table_rows(rebuild):
        if cells:
            patterns += row_patterns(cells[0])
    # A path named anywhere in a row counts too (`/usr/local/lib/mentor/...` in another column).
    for cells in table_rows(rebuild):
        for cell in cells[1:]:
            patterns += [t for t in ticks(cell) if t.startswith("/") and " " not in t]
    for f in shipped():
        if not any(f == p or fnmatch.fnmatchcase(f, p) or f.startswith(p.rstrip("/") + "/") for p in patterns):
            gap(f"REBUILD.md: no row for {f}")


def check_extension_parts(desktop):
    """2. Every part of the extension has a row in DESKTOP.md "The parts of the extension"."""
    js = read(os.path.join(ROOTFS, "usr/share/gnome-shell/extensions/mentor@mentor.local/extension.js"))
    parts = re.findall(r"this\._part\(\s*['\"]([^'\"]+)['\"]", js)
    section = re.search(r"^## The parts of the extension\n(.*?)(?=^## )", desktop, re.M | re.S)
    if not section:
        gap('DESKTOP.md: no section "The parts of the extension"')
        return
    named = set()
    for cells in table_rows(section.group(1)):
        m = re.match(r"`([^`]+)`", cells[0])
        if m:
            named.add(m.group(1))
    for part in parts:
        if part not in named:
            gap(f'DESKTOP.md "The parts of the extension": no row for the part `{part}` (extension.js)')
    for name in sorted(named - set(parts)):
        gap(f'DESKTOP.md "The parts of the extension": the row `{name}` names no part of extension.js')


def docs_for(rebuild, all_docs, file):
    """TOOLS.md and the docs REBUILD.md's row for this file points to (its column "Read")."""
    names = {"TOOLS.md"}
    for cells in table_rows(rebuild):
        if len(cells) >= 5 and file in row_patterns(cells[0]):
            names |= set(re.findall(r"[A-Z]+\.md", cells[4]))
    return "\n".join(all_docs.get(n, "") for n in sorted(names)), " or ".join(sorted(names))


def check_commands_and_tools(rebuild, all_docs):
    """3. Every subcommand of `mentor` and every tool is named in the docs for them."""
    text, where = docs_for(rebuild, all_docs, "/usr/local/bin/mentor")
    script = read(os.path.join(ROOTFS, "usr/local/bin/mentor"))
    for cmd in re.findall(r"add_parser\(\s*['\"]([\w-]+)['\"]", script):
        if not re.search(r"(?<![\w/-])mentor " + re.escape(cmd) + r"(?![\w-])", text):
            gap(f"{where}: the command `mentor {cmd}` is not described (usr/local/bin/mentor)")
    text, where = docs_for(rebuild, all_docs, "/usr/local/lib/mentor/mentor_tools.py")
    tree = ast.parse(read(os.path.join(ROOTFS, "usr/local/lib/mentor/mentor_tools.py")))
    tools = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in node.targets):
            tools += [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    if not tools:
        gap("mentor_tools.py: no TOOLS dictionary found; check-docs.py needs a look")
    for tool in tools:
        # A one-word name (sound, windows, dbus) is also a plain word: only `name` counts for it.
        word = r"(?<![\w-])" + re.escape(tool) + r"(?![\w-])"
        if not re.search(word if "_" in tool else "`" + re.escape(tool) + "`", text):
            gap(f"{where}: the tool `{tool}` is not described (mentor_tools.py)")


def norm(s):
    return re.sub(r"[^\w]+", " ", s.lower()).strip()


def check_references(rebuild, all_docs):
    """4. Every doc REBUILD.md names exists; every DOC.md "Section" points to a heading."""
    for cells in table_rows(rebuild):
        for cell in cells:
            for doc in re.findall(r"\b([A-Z][A-Z_]+\.md)\b", cell):
                if doc not in all_docs:
                    gap(f"REBUILD.md: names {doc}, which does not exist in etc/mentor")
    heads = {name: [norm(h) for h in headings(text)] for name, text in all_docs.items()}
    ref = re.compile(r"\b([A-Z][A-Z_]+\.md)(?:'s)?,?\s+((?:\"[^\"\n]+\"(?:,\s*|\s+and\s+|\s+or\s+)?)+)")
    for name, text in all_docs.items():
        for doc, quoted in ref.findall(text):
            if doc not in all_docs:
                gap(f"{name}: refers to {doc}, which does not exist")
                continue
            for section in re.findall(r"\"([^\"\n]+)\"", quoted):
                want = norm(section)
                if not any(h == want or h.startswith(want + " ") for h in heads[doc]):
                    gap(f'{name}: refers to {doc} "{section}", but {doc} has no such heading')


def path_known(path, files, made):
    path = path.rstrip("/.:")
    if not path or path == "/":
        return True
    if any(path == r or path.startswith(r + "/") for r in RUNTIME):
        return True
    pattern = PLACEHOLDER.sub("*", path)
    if any(fnmatch.fnmatchcase(f, pattern) or f.startswith(pattern + "/") or fnmatch.fnmatchcase(f, pattern + "/*")
           for f in files):
        return True
    return path in made


def check_paths(all_docs):
    """5. Every Mentor path in backticks exists in rootfs, is made by the build, or is runtime."""
    files = shipped()
    made = set()
    for script in ("distro/customize.sh", "build/build.sh"):
        made |= set(re.findall(r"/(?:usr|etc|var)/[\w./@+-]+", read(os.path.join(SRC, script))))
    made = {m.rstrip("/.") for m in made}
    found = re.compile(r"(?<![\w.~/$-])/(?:usr|etc|var)/[^\s`'\"),;|<>]*")
    for name, text in all_docs.items():
        seen = set()
        for tok in ticks(text):
            for path in found.findall(tok):
                # Only Mentor's own: other packages' files are not in this tree to check against.
                if "mentor" not in path.lower() or path in seen:
                    continue
                seen.add(path)
                if not path_known(path, files, made):
                    gap(f"{name}: `{path}` is not in distro/rootfs, not made by the build, not a runtime path")


def main():
    all_docs = docs()
    rebuild = all_docs.get("REBUILD.md", "")
    check_rebuild_rows(rebuild)
    check_extension_parts(all_docs.get("DESKTOP.md", ""))
    check_commands_and_tools(rebuild, all_docs)
    check_references(rebuild, all_docs)
    check_paths(all_docs)
    if gaps:
        print(f"check-docs: {len(gaps)} gap(s) between Mentor's files and etc/mentor/*.md", file=sys.stderr)
        return 1
    print("check-docs: every file, part, command and tool is in the docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
