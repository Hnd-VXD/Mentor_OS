// The whole of Mentor in one file and back ("Back up…" and "Restore a backup…" under More options), and
// the installation moved to another drive ("Move Mentor…"). After Try Omarchy for Windows
// (github.com/omacom/try-omarchy-windows, MIT, docs/BACKUP.md, docs/MOVING.md). Only while Mentor is
// shut down: its disk must not change while it is copied. Restore points (RestorePoints in Mentor.cs)
// are inside the disk, so they go along.
//
// A backup is a ZIP:
//     mentor-backup.json      {"format": 1, "made", "launcher", "files": [{"name", "size", "sha256"}]}
//     vm/...                  the disk (everything done inside Mentor, with its restore points), the
//                             firmware's variables, the restore points' list
//     out/mentor.qcow2        the system image the disk is made on
// Restoring checks every file against mentor-backup.json before anything is replaced; then the Mentor
// that was there is replaced by the one in the file. The disk names its image by its full path, so it
// is pointed at the image where it is now (qemu-img rebase -u) after a restore and after a move.
//
// For the command line and tests, without any window:
//     Mentor.exe --backup FILE.zip | --restore-backup FILE.zip | --move FOLDER  [--vm-dir DIR] [--image FILE]
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// A long job with a line of words, a bar and Cancel; the job runs on its own thread.
class Working : Form
{
    readonly Label words = new Label();
    readonly ProgressBar bar = new ProgressBar { Minimum = 0, Maximum = 1000 };
    readonly PillButton cancel = new PillButton { Text = "Cancel" };
    readonly Func<Working, string> job;
    public volatile bool Cancelled;
    public string Error;
    bool finished;

    public Working(string first, Func<Working, string> job)
    {
        this.job = job;
        Text = "Mentor";
        AutoScaleMode = AutoScaleMode.None;
        ClientSize = new Size(440, 170);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = MinimizeBox = false;
        BackColor = Theme.Back;
        ForeColor = Theme.Text;
        Font = Theme.Font(9.5f, FontStyle.Regular);
        Theme.Dress(this);
        words.SetBounds(28, 24, 384, 44);
        words.ForeColor = Theme.Text;
        words.BackColor = Theme.Back;
        words.Text = first;
        bar.SetBounds(28, 76, 384, 14);
        cancel.SetBounds(276, 112, 136, 38);
        cancel.Click += (s, e) => { Cancelled = true; cancel.Enabled = false; words.Text = "Stopping…"; };
        FormClosing += (s, e) => { if (!finished) { Cancelled = true; e.Cancel = true; } };
        Controls.AddRange(new Control[] { words, bar, cancel });
        Theme.Fit(this);
        Shown += (s, e) => new Thread(() => {
            string error;
            try { error = job(this); }
            catch (OperationCanceledException) { error = "Stopped. Nothing was changed."; }
            catch (Exception ex) { error = "It did not work: " + ex.Message; }
            Error = error;
            try { BeginInvoke((Action)(() => { finished = true; Close(); })); } catch (InvalidOperationException) { }
        }) { IsBackground = true }.Start();
    }

    // From the job's thread. `done` of `total` moves the bar.
    public void Say(string text, long done, long total)
    {
        if (Cancelled) throw new OperationCanceledException();
        try
        {
            BeginInvoke((Action)(() => {
                if (!Cancelled) words.Text = text;
                bar.Value = total > 0 ? (int)Math.Min(1000, done * 1000 / total) : 0;
            }));
        }
        catch (InvalidOperationException) { }
    }

    // Runs it with the window (owner given) or, from the command line, without any. Null when it worked.
    public static string Run(IWin32Window owner, string first, Func<Working, string> job)
    {
        if (owner == null)
        {
            try { return job(null); }
            catch (Exception e) { return e.Message; }
        }
        using (var form = new Working(first, job))
        {
            form.ShowDialog(owner);
            return form.Error;
        }
    }
}

static class Backup
{
    const int Format = 1;
    // What of an installation is Mentor: in vm\, and the image. The rest (logs, QEMU, Mentor.exe) is not.
    static readonly string[] VmSkip = { "running", "launcher.log", "launcher.log.old", "qemu.log", "qemu-said.txt" };

    static string Gb(long bytes) { return (bytes / (double)(1L << 30)).ToString("0.0") + " GB"; }

    static void Step(Working work, string text, long done, long total)
    {
        if (work != null) work.Say(text, done, total);
    }

    // Copies `from` to `to`, giving back the SHA-256 of what was read.
    static string CopyHashed(Stream from, Stream to, Working work, string what, ref long done, long total)
    {
        var buffer = new byte[1 << 20];
        using (var sha = SHA256.Create())
        {
            int read;
            DateTime said = DateTime.MinValue;
            while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
            {
                sha.TransformBlock(buffer, 0, read, null, 0);
                to.Write(buffer, 0, read);
                done += read;
                if ((DateTime.UtcNow - said).TotalMilliseconds > 200)
                {
                    Step(work, what + ": " + Gb(done) + " of " + Gb(total), done, total);
                    said = DateTime.UtcNow;
                }
            }
            sha.TransformFinalBlock(buffer, 0, 0);
            return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
        }
    }

    static string HashFile(string path, Working work, string what, ref long done, long total)
    {
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
            return CopyHashed(file, Stream.Null, work, what, ref done, total);
    }

    // The files of Mentor as (name in the backup, path on disk), or null with `why`.
    static List<string[]> Inventory(string vmDir, string image, out string why)
    {
        why = null;
        var files = new List<string[]>();
        if (!File.Exists(Path.Combine(vmDir, "disk.qcow2"))) { why = "There is no Mentor here to back up yet: it has not been started."; return null; }
        foreach (string path in Directory.GetFiles(vmDir, "*", SearchOption.AllDirectories))
        {
            string name = path.Substring(vmDir.Length).TrimStart('\\');
            if (Array.IndexOf(VmSkip, name) >= 0 || name.EndsWith(".download") || name.EndsWith(".part")) continue;
            files.Add(new[] { "vm/" + name.Replace('\\', '/'), path });
        }
        if (!File.Exists(image)) { why = "The system image is missing: " + image; return null; }
        files.Add(new[] { "out/mentor.qcow2", image });
        return files;
    }

    public static string NotWhileRunning(string vmDir)
    {
        return Program.Running(vmDir) != null ? "Mentor is running. Shut it down first (from its own menu, or the tray icon), then try again." : null;
    }

    // "Back up…": asks where, then makes it.
    public static void Make(IWin32Window owner, string root, string vmDir, string image)
    {
        string why = NotWhileRunning(vmDir);
        if (why != null) { MessageBox.Show(owner, why, "Mentor"); return; }
        string file;
        using (var dialog = new SaveFileDialog {
            Title = "Back up Mentor", Filter = "Mentor backup (*.zip)|*.zip", OverwritePrompt = true,
            FileName = "Mentor backup " + DateTime.Now.ToString("yyyy-MM-dd") + ".zip",
            InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments) })
        {
            if (dialog.ShowDialog(owner) != DialogResult.OK) return;
            file = dialog.FileName;
        }
        string error = Working.Run(owner, "Backing up Mentor…", work => MakeTo(work, file, root, vmDir, image));
        MessageBox.Show(owner, error ?? "Done. Everything of Mentor is in " + file + ".\n\nKeep it somewhere safe: " +
                        "it holds your files and sign-ins inside Mentor, and it is not locked with a password.", "Mentor",
                        MessageBoxButtons.OK, error == null ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
    }

    public static string MakeTo(Working work, string file, string root, string vmDir, string image)
    {
        string why = NotWhileRunning(vmDir);
        if (why != null) return why;
        List<string[]> files = Inventory(vmDir, image, out why);
        if (files == null) return why;
        string full = Path.GetFullPath(file);
        if (full.StartsWith(Path.GetFullPath(root).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) &&
            !full.StartsWith(Path.Combine(Path.GetFullPath(root), "out") + "\\", StringComparison.OrdinalIgnoreCase))
            return "Choose a place outside Mentor's own folder for the backup.";
        long total = 0;
        foreach (string[] f in files) total += new FileInfo(f[1]).Length;
        long free = new DriveInfo(Path.GetPathRoot(full)).AvailableFreeSpace;
        if (free < total + (256L << 20)) return "There is not enough room on " + Path.GetPathRoot(full) + ": the backup needs " + Gb(total) + ".";
        var listed = new List<Dictionary<string, object>>();
        string partial = full + ".part";
        long done = 0;
        try
        {
            using (var output = new FileStream(partial, FileMode.Create, FileAccess.ReadWrite, FileShare.None, 1 << 20))
            using (var zip = new ZipArchive(output, ZipArchiveMode.Create))
            {
                foreach (string[] f in files)
                {
                    // Disks and images gain little from packing and would take long: kept as they are.
                    bool big = new FileInfo(f[1]).Length > (64L << 20);
                    ZipArchiveEntry entry = zip.CreateEntry(f[0], big ? CompressionLevel.NoCompression : CompressionLevel.Optimal);
                    string sha;
                    using (var from = new FileStream(f[1], FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                    using (Stream to = entry.Open())
                        sha = CopyHashed(from, to, work, "Backing up Mentor", ref done, total);
                    listed.Add(new Dictionary<string, object> { { "name", f[0] }, { "size", new FileInfo(f[1]).Length }, { "sha256", sha } });
                }
                var manifest = new Dictionary<string, object> {
                    { "format", Format }, { "made", DateTime.Now.ToString("yyyy-MM-dd HH:mm") }, { "launcher", LauncherBuild.Version },
                    { "files", listed } };
                using (var writer = new StreamWriter(zip.CreateEntry("mentor-backup.json").Open()))
                    writer.Write(new JavaScriptSerializer().Serialize(manifest));
            }
            if (File.Exists(full)) File.Delete(full);
            File.Move(partial, full);
        }
        catch (Exception)
        {
            try { File.Delete(partial); } catch (Exception) { }
            throw;
        }
        Program.Note("backed up to " + full + " (" + Gb(total) + ")");
        return null;
    }

    // "Restore a backup…": asks which, warns, then puts it in place. True when it did.
    public static bool RestoreFrom(IWin32Window owner, string root, string vmDir, string image)
    {
        string why = NotWhileRunning(vmDir);
        if (why != null) { MessageBox.Show(owner, why, "Mentor"); return false; }
        string file;
        using (var dialog = new OpenFileDialog { Title = "Restore Mentor from a backup", Filter = "Mentor backup (*.zip)|*.zip",
                                                 InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments) })
        {
            if (dialog.ShowDialog(owner) != DialogResult.OK) return false;
            file = dialog.FileName;
        }
        if (MessageBox.Show(owner, "Put Mentor back as it is in this backup?\n\nEverything inside Mentor now is replaced by what " +
                "is in the backup. The backup is checked first: if it is damaged, nothing is changed.", "Mentor",
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
            return false;
        string error = Working.Run(owner, "Checking the backup…", work => RestoreFile(work, file, root, vmDir, image));
        MessageBox.Show(owner, error ?? "Done. Mentor is as it was in the backup: press Start Mentor.", "Mentor",
                        MessageBoxButtons.OK, error == null ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        return error == null;
    }

    public static string RestoreFile(Working work, string file, string root, string vmDir, string image)
    {
        string why = NotWhileRunning(vmDir);
        if (why != null) return why;
        string staging = Path.Combine(root, "restore-staging");
        if (Directory.Exists(staging)) Directory.Delete(staging, true);
        using (ZipArchive zip = ZipFile.OpenRead(file))
        {
            ZipArchiveEntry manifestEntry = zip.GetEntry("mentor-backup.json");
            if (manifestEntry == null) return "This is not a backup of Mentor.";
            Dictionary<string, object> manifest;
            using (var reader = new StreamReader(manifestEntry.Open()))
                manifest = new JavaScriptSerializer { MaxJsonLength = 1 << 24 }.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
            if (Convert.ToInt32(manifest["format"]) != Format) return "This backup was made by a newer Mentor.exe.";
            var files = new List<Dictionary<string, object>>();
            long total = 0;
            foreach (object item in (System.Collections.IEnumerable)manifest["files"])
            {
                var f = (Dictionary<string, object>)item;
                string name = (string)f["name"];
                // Only Mentor's own places, and nothing that climbs out of them.
                if (name.Contains("..") || name.Contains(":") || !(name.StartsWith("vm/") || name == "out/mentor.qcow2"))
                    return "This backup holds something it should not (" + name + "); nothing was changed.";
                files.Add(f);
                total += Convert.ToInt64(f["size"]);
            }
            if (!files.Exists(f => (string)f["name"] == "vm/disk.qcow2")) return "This backup has no disk in it; nothing was changed.";
            // The image is the same as the one here in most backups: then it is not unpacked again.
            Dictionary<string, object> imageInfo = files.Find(f => (string)f["name"] == "out/mentor.qcow2");
            bool sameImage = false;
            if (imageInfo != null && File.Exists(image) && new FileInfo(image).Length == Convert.ToInt64(imageInfo["size"]))
            {
                long seen = 0;
                sameImage = HashFile(image, work, "Comparing the system image", ref seen, new FileInfo(image).Length) == (string)imageInfo["sha256"];
            }
            long need = total - (sameImage ? Convert.ToInt64(imageInfo["size"]) : 0);
            long free = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(root))).AvailableFreeSpace;
            if (free < need + (512L << 20)) return "There is not enough room on " + Path.GetPathRoot(root) + ": the backup needs " + Gb(need) + ".";
            long done = 0;
            try
            {
                foreach (Dictionary<string, object> f in files)
                {
                    string name = (string)f["name"];
                    if (sameImage && name == "out/mentor.qcow2") continue;
                    ZipArchiveEntry entry = zip.GetEntry(name);
                    if (entry == null) return "The backup is not whole (" + name + " is missing); nothing was changed.";
                    string target = Path.Combine(staging, name.Replace('/', '\\'));
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    string sha;
                    using (Stream from = entry.Open())
                    using (var to = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
                        sha = CopyHashed(from, to, work, "Checking and unpacking the backup", ref done, need);
                    if (sha != (string)f["sha256"] || new FileInfo(target).Length != Convert.ToInt64(f["size"]))
                        throw new InvalidDataException("The backup is damaged (" + name + "); nothing was changed.");
                }
            }
            catch (InvalidDataException e)
            {
                Directory.Delete(staging, true);
                return e.Message;
            }
            catch (Exception)
            {
                try { Directory.Delete(staging, true); } catch (Exception) { }
                throw;
            }
            // Everything is here and checked: only now is the Mentor that was there replaced.
            Step(work, "Putting the backup in place…", need, need);
            string old = vmDir + ".before-restore";
            if (Directory.Exists(old)) Directory.Delete(old, true);
            if (Directory.Exists(vmDir)) Directory.Move(vmDir, old);
            Directory.Move(Path.Combine(staging, "vm"), vmDir);
            string stagedImage = Path.Combine(staging, @"out\mentor.qcow2");
            if (File.Exists(stagedImage))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(image));
                if (File.Exists(image)) File.Delete(image);
                File.Move(stagedImage, image);
            }
            Directory.Delete(staging, true);
            string error = PointDiskAt(Path.Combine(vmDir, "disk.qcow2"), image);
            if (error != null) return "The backup is in place, but its disk could not be joined to the system image: " + error;
            try { if (Directory.Exists(old)) Directory.Delete(old, true); }
            catch (Exception) { }  // only room, if it stays
            Program.Note("restored " + file);
            return null;
        }
    }

    // A disk made on an image names that image by its path: it is told the path where the image is now.
    public static string PointDiskAt(string disk, string image)
    {
        string qemuImg = Path.Combine(Program.QemuDir, "qemu-img.exe"), error;
        int code = Program.RunHidden(qemuImg, "rebase -u -f qcow2 -F qcow2 -b " + Program.Quote(image) + " " + Program.Quote(disk), out error);
        return code == 0 ? null : error.Trim();
    }
}

// "Move Mentor…": the installation copied to another folder (another drive), checked, and then used
// from there; the shortcuts follow, and the old copy is removed (only what was copied).
static class MoveMentor
{
    // What an installation is: the program, its settings, QEMU, the image, the disk.
    static readonly string[] Parts = { "Mentor.exe", "Mentor.settings", "qemu", @"out\mentor.qcow2", "vm", "launcher-update" };

    // True when Mentor was moved, and the launcher window should close (the new Mentor.exe takes over).
    public static bool Run(IWin32Window owner, string root)
    {
        string why = Backup.NotWhileRunning(Program.VmDir);
        if (why != null) { MessageBox.Show(owner, why, "Mentor"); return false; }
        if (!string.Equals(Path.GetFullPath(Program.VmDir), Path.Combine(Path.GetFullPath(root), "vm"), StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(Path.GetFullPath(Program.Image), Path.Combine(Path.GetFullPath(root), @"out\mentor.qcow2"), StringComparison.OrdinalIgnoreCase))
        {
            MessageBox.Show(owner, "This Mentor keeps its files in other places (--vm-dir, --image), so it cannot be moved from here.", "Mentor");
            return false;
        }
        string parent;
        using (var dialog = new FolderBrowserDialog { Description = "Where should Mentor go? A folder called Mentor is made there.",
                                                      ShowNewFolderButton = true })
        {
            if (dialog.ShowDialog(owner) != DialogResult.OK) return false;
            parent = dialog.SelectedPath;
        }
        string target = Path.Combine(parent, "Mentor");
        string error = Working.Run(owner, "Moving Mentor…", work => Move(work, root, target));
        if (error != null)
        {
            MessageBox.Show(owner, error, "Mentor", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }
        MessageBox.Show(owner, "Done. Mentor is in " + target + " now, and its shortcuts lead there.", "Mentor");
        try { Process.Start(new ProcessStartInfo(Path.Combine(target, "Mentor.exe")) { WorkingDirectory = target }); }
        catch (Exception) { }
        return true;
    }

    static long Size(string path)
    {
        if (File.Exists(path)) return new FileInfo(path).Length;
        long total = 0;
        if (Directory.Exists(path)) foreach (string f in Directory.GetFiles(path, "*", SearchOption.AllDirectories)) total += new FileInfo(f).Length;
        return total;
    }

    static bool Linked(string path)
    {
        if (!File.Exists(path) && !Directory.Exists(path)) return false;
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) return true;
        if (Directory.Exists(path))
            foreach (string inside in Directory.GetFileSystemEntries(path, "*", SearchOption.AllDirectories))
                if ((File.GetAttributes(inside) & FileAttributes.ReparsePoint) != 0) return true;
        return false;
    }

    // Copies, checks, switches. Null when it worked.
    public static string Move(Working work, string root, string target)
    {
        root = Path.GetFullPath(root).TrimEnd('\\');
        target = Path.GetFullPath(target).TrimEnd('\\');
        string why = Backup.NotWhileRunning(Path.Combine(root, "vm"));
        if (why != null) return why;
        if (target.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase) || string.Equals(target, root, StringComparison.OrdinalIgnoreCase))
            return "Choose a place outside Mentor's own folder.";
        if (Directory.Exists(target) && Directory.GetFileSystemEntries(target).Length > 0)
            return target + " is there already and is not empty. Choose another place.";
        var parts = new List<string>();
        long total = 0;
        foreach (string part in Parts)
        {
            string path = Path.Combine(root, part);
            if (!File.Exists(path) && !Directory.Exists(path)) continue;
            if (Linked(path)) return part + " is a link to somewhere else, which Mentor cannot move. Nothing was changed.";
            parts.Add(part);
            total += Size(path);
        }
        if (!parts.Contains("Mentor.exe") || !parts.Contains(@"out\mentor.qcow2")) return "This folder does not hold a whole Mentor.";
        long free = new DriveInfo(Path.GetPathRoot(target)).AvailableFreeSpace;
        if (free < total + (512L << 20)) return "There is not enough room on " + Path.GetPathRoot(target) + ": Mentor needs " + (total >> 30) + " GB.";
        string staging = target + ".moving";
        if (Directory.Exists(staging)) Directory.Delete(staging, true);
        long done = 0;
        var copied = new List<string[]>();  // from, to, sha256
        try
        {
            foreach (string part in parts)
            {
                string from = Path.Combine(root, part);
                var files = File.Exists(from) ? new[] { from } : Directory.GetFiles(from, "*", SearchOption.AllDirectories);
                foreach (string file in files)
                {
                    if (Path.GetFileName(file) == "running") continue;
                    string to = Path.Combine(staging, file.Substring(root.Length + 1));
                    Directory.CreateDirectory(Path.GetDirectoryName(to));
                    string sha;
                    using (var input = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                    using (var output = new FileStream(to, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1 << 20))
                        sha = CopyHashedFor(input, output, work, "Copying Mentor", ref done, total * 2);
                    copied.Add(new[] { file, to, sha });
                }
            }
            // Read back from the new place: what is there is what was copied.
            foreach (string[] c in copied)
            {
                string sha;
                using (var input = new FileStream(c[1], FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                    sha = CopyHashedFor(input, Stream.Null, work, "Checking the copy", ref done, total * 2);
                if (sha != c[2]) throw new InvalidDataException("The copy of " + Path.GetFileName(c[0]) + " came out different. Nothing was changed.");
            }
        }
        catch (Exception e)
        {
            try { Directory.Delete(staging, true); } catch (Exception) { }
            if (e is InvalidDataException) return e.Message;
            throw;
        }
        // Too late to stop now: a Cancel here would leave the copy half in place.
        try { if (work != null) work.Say("Switching to the new place…", total * 2, total * 2); }
        catch (OperationCanceledException) { }
        if (Directory.Exists(target)) Directory.Delete(target);
        Directory.Move(staging, target);
        string error = Backup.PointDiskAt(Path.Combine(target, @"vm\disk.qcow2"), Path.Combine(target, @"out\mentor.qcow2"));
        if (error != null)
            return "Mentor was copied to " + target + ", but its disk could not be joined to the system image there: " + error +
                   "\n\nThe old one is still where it was, and works.";
        Shortcuts(Path.Combine(root, "Mentor.exe"), Path.Combine(target, "Mentor.exe"));
        Program.Note("moved to " + target);
        // The old copy goes: only the files that were copied, and the folders they leave empty.
        foreach (string[] c in copied)
            try { File.SetAttributes(c[0], FileAttributes.Normal); File.Delete(c[0]); }
            catch (Exception) { }  // the running Mentor.exe itself: it stays, and is harmless
        foreach (string part in parts)
        {
            string path = Path.Combine(root, part);
            if (!Directory.Exists(path)) continue;
            var dirs = new List<string>(Directory.GetDirectories(path, "*", SearchOption.AllDirectories));
            dirs.Sort((a, b) => b.Length.CompareTo(a.Length));
            dirs.Add(path);
            foreach (string dir in dirs)
                try { if (Directory.GetFileSystemEntries(dir).Length == 0) Directory.Delete(dir); } catch (Exception) { }
        }
        try { string outDir = Path.Combine(root, "out"); if (Directory.GetFileSystemEntries(outDir).Length == 0) Directory.Delete(outDir); }
        catch (Exception) { }
        LeaveNote(root, target);
        // This program, when it is the old Mentor.exe, cannot delete itself while it runs: a moment after it ends.
        string self = Path.GetFullPath(Application.ExecutablePath), old = Path.Combine(root, "Mentor.exe");
        if (string.Equals(self, old, StringComparison.OrdinalIgnoreCase) && File.Exists(old))
            try
            {
                Process.Start(new ProcessStartInfo("cmd.exe", "/c ping -n 4 127.0.0.1 > nul & del /f /q \"" + old + "\"") {
                    UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden });
            }
            catch (Exception) { }
        return null;
    }

    static string CopyHashedFor(Stream from, Stream to, Working work, string what, ref long done, long total)
    {
        var buffer = new byte[1 << 20];
        using (var sha = SHA256.Create())
        {
            int read;
            DateTime said = DateTime.MinValue;
            while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
            {
                sha.TransformBlock(buffer, 0, read, null, 0);
                to.Write(buffer, 0, read);
                done += read;
                if (work != null && (DateTime.UtcNow - said).TotalMilliseconds > 200)
                {
                    work.Say(what + "… " + (done * 100 / Math.Max(1, total)) + "%", done, total);
                    said = DateTime.UtcNow;
                }
            }
            sha.TransformFinalBlock(buffer, 0, 0);
            return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
        }
    }

    // The Desktop's and the Start menu's shortcuts to the old Mentor.exe lead to the new one.
    static void Shortcuts(string oldProgram, string newProgram)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType == null) return;
        object shell = Activator.CreateInstance(shellType);
        var places = new[] {
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory),
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
            Environment.GetFolderPath(Environment.SpecialFolder.Startup) };
        foreach (string place in places)
        {
            if (string.IsNullOrEmpty(place) || !Directory.Exists(place)) continue;
            string[] links;
            try { links = Directory.GetFiles(place, "*.lnk", SearchOption.AllDirectories); }
            catch (Exception) { continue; }
            foreach (string link in links)
            {
                try
                {
                    object shortcut = shellType.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, shell, new object[] { link });
                    Type t = shortcut.GetType();
                    string to = t.InvokeMember("TargetPath", System.Reflection.BindingFlags.GetProperty, null, shortcut, null) as string;
                    if (!string.Equals(to, oldProgram, StringComparison.OrdinalIgnoreCase)) continue;
                    t.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { newProgram });
                    t.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { Path.GetDirectoryName(newProgram) });
                    t.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, shortcut, null);
                }
                catch (Exception) { }
            }
        }
        // Mentor started with Windows (setup's choice) is found the same way.
        try
        {
            using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
                if (key != null && key.GetValue("Mentor") is string && ((string)key.GetValue("Mentor")).Trim('"') .Equals(oldProgram, StringComparison.OrdinalIgnoreCase))
                    key.SetValue("Mentor", "\"" + newProgram + "\"");
        }
        catch (Exception) { }
    }

    // In the old place, for anyone who looks: where Mentor went.
    static void LeaveNote(string root, string target)
    {
        try { File.WriteAllText(Path.Combine(root, "Mentor moved.txt"), "Mentor is in " + target + " now (moved " + DateTime.Now.ToString("yyyy-MM-dd HH:mm") + ").\r\n"); }
        catch (Exception) { }
    }
}
