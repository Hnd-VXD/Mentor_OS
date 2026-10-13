"""Files: "Ask Mentor" in the right-click menu of files, folders and the folder background."""
from gi.repository import Gio, GObject, Nautilus


class AskMentor(GObject.GObject, Nautilus.MenuProvider):
    def _item(self, name, paths):
        if not paths:
            return []
        item = Nautilus.MenuItem(name=name, label="Ask Mentor…")
        item.connect("activate", lambda *_: Gio.Subprocess.new(
            ["/usr/local/bin/mentor-chat", "--file", *paths], Gio.SubprocessFlags.NONE))
        return [item]

    # The two menus need items of different names: Files keeps one action per name, and
    # with a shared one a click on a selected folder asked about the folder it is in.
    def get_file_items(self, files):
        return self._item("Mentor::ask_selection",
                          [path for path in (f.get_location().get_path() for f in files) if path])

    def get_background_items(self, folder):
        path = folder.get_location().get_path()
        return self._item("Mentor::ask_folder", [path] if path else [])
