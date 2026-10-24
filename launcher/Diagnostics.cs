// "Make a diagnostics file" (the tray icon): what the launcher and the system inside wrote down, in
// one zip on the Desktop, for when the user is asked for it, or wants to look themselves. After Try
// Omarchy for Windows (github.com/omacom/try-omarchy-windows, MIT, app/diagnostics*.go).
//
// From Windows: about.txt (versions, the computer, the settings), the launcher's logs (vm\launcher.log,
// vm\qemu.log, what QEMU said, the self-update's log), the restore points' list. From the system inside,
// asked over the root-only link (mentor-host-link, "diagnostics"): its journal since this start and the
// last one before, Mentor's own logs (/var/log/mentor), failed services, disk and memory. Nothing leaves
// the computer: the file is the user's to share or not.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Management;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class Diagnostics
{
    // Makes it on another thread; `done` gets its path (or null) on the thread that asked.
    public static void MakeInBackground(HostLink link, Action<string> done, string folder = null)
    {
        var context = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        new Thread(() => {
            string path = null;
            try { path = Make(link, folder); }
            catch (Exception e) { Program.Note("the diagnostics file could not be made: " + e.Message); }
            context.Post(_ => done(path), null);
        }) { IsBackground = true }.Start();
    }

    static string Make(HostLink link, string folder)
    {
        string desktop = folder ?? Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        string path = Path.Combine(desktop, "Mentor diagnostics " + DateTime.Now.ToString("yyyy-MM-dd HHmm") + ".zip");
        string guest = null, guestError = "Mentor was not running.";
        if (link != null)
        {
            link.DiagnosticsId = Guid.NewGuid().ToString("N").Substring(0, 12);
            link.DiagnosticsData = link.DiagnosticsError = null;
            link.DiagnosticsDone.Reset();
            if (!link.Send(new System.Collections.Generic.Dictionary<string, object> { { "diagnostics", link.DiagnosticsId } }))
                guestError = "The system inside could not be asked.";
            else if (!link.DiagnosticsDone.WaitOne(90000))
                guestError = "The system inside did not answer (an image from before 2026-10-18 cannot).";
            else
            {
                guest = link.DiagnosticsData;
                guestError = link.DiagnosticsError ?? (guest == null ? "The system inside sent nothing." : null);
            }
        }
        string partial = path + ".part";
        using (FileStream file = File.Create(partial))
        using (var zip = new ZipArchive(file, ZipArchiveMode.Create))
        {
            Text(zip, "about.txt", About());
            foreach (string name in new[] { "launcher.log.old", "launcher.log", "qemu.log", "qemu-said.txt", "boot-failures", @"restore\points.json",
                                            "start-trace.log", "start-trace.previous.log" })
                Copy(zip, Path.Combine(Program.VmDir, name), name.Replace('\\', '-'));
            // the starts that stood still or crashed (Program.KeepStall)
            string stalls = Path.Combine(Program.VmDir, "stalls");
            if (Directory.Exists(stalls))
                foreach (string stall in Directory.GetFiles(stalls, "start-*.log"))
                    Copy(zip, stall, "stalls-" + Path.GetFileName(stall));
            Copy(zip, Path.Combine(Program.Root, @"launcher-update\log.txt"), "launcher-update.log");
            Copy(zip, Program.SettingsFile, "Mentor.settings");
            if (guest != null)
            {
                byte[] data = Convert.FromBase64String(guest);
                ZipArchiveEntry entry = zip.CreateEntry("system-inside.tar.gz", CompressionLevel.NoCompression);
                using (Stream to = entry.Open()) to.Write(data, 0, data.Length);
            }
            else Text(zip, "system-inside-missing.txt", guestError + "\r\n");
        }
        if (File.Exists(path)) File.Delete(path);
        File.Move(partial, path);
        Program.Note("made " + path);
        return path;
    }

    static void Text(ZipArchive zip, string name, string text)
    {
        using (var writer = new StreamWriter(zip.CreateEntry(name).Open(), new UTF8Encoding(false))) writer.Write(text);
    }

    static void Copy(ZipArchive zip, string file, string name)
    {
        try
        {
            if (!File.Exists(file)) return;
            using (var from = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (Stream to = zip.CreateEntry(name).Open())
                from.CopyTo(to);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    static string Query(string wql, string property)
    {
        var found = new StringBuilder();
        try
        {
            using (var search = new ManagementObjectSearcher(wql))
                foreach (ManagementBaseObject item in search.Get())
                    found.Append(found.Length > 0 ? "; " : "").Append(Convert.ToString(item[property]));
        }
        catch (Exception) { }
        return found.ToString();
    }

    static string About()
    {
        var about = new StringBuilder();
        double total, free;
        Resources.Memory(out total, out free);
        about.AppendLine("Mentor diagnostics, " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss zzz"));
        about.AppendLine("Mentor.exe: " + LauncherBuild.Version + " (" + Application.ExecutablePath + ")");
        about.AppendLine("Windows: " + Query("SELECT Caption FROM Win32_OperatingSystem", "Caption") + " " +
                         Query("SELECT Version FROM Win32_OperatingSystem", "Version"));
        about.AppendLine("Processor: " + Query("SELECT Name FROM Win32_Processor", "Name").Trim() + ", " + Environment.ProcessorCount + " logical");
        about.AppendLine("Memory: " + total.ToString("0.0") + " GB, " + free.ToString("0.0") + " GB free now");
        about.AppendLine("Graphics: " + Query("SELECT Name FROM Win32_VideoController", "Name"));
        about.AppendLine("Time zone: " + TimeZoneInfo.Local.Id + " -> " + (WindowsZone.Iana() ?? "?"));
        about.AppendLine("QEMU: " + Program.QemuDir + (Program.Own ? " (Mentor's own)" : " (installed separately)"));
        try
        {
            string manifest = Path.Combine(Path.GetDirectoryName(Program.QemuDir), @"provenance\runtime-manifest.json");
            if (File.Exists(manifest))
            {
                string text = File.ReadAllText(manifest);
                int at = text.IndexOf("\"name\"");
                if (at >= 0) about.AppendLine("Runtime: " + text.Substring(at, Math.Min(80, text.Length - at)).Split('\n')[0].Trim());
            }
        }
        catch (Exception) { }
        try
        {
            var image = new FileInfo(Program.Image);
            about.AppendLine("Image: " + image.FullName + ", " + (image.Length >> 20) + " MB, " + image.LastWriteTime.ToString("yyyy-MM-dd HH:mm"));
            var disk = new FileInfo(Path.Combine(Program.VmDir, "disk.qcow2"));
            if (disk.Exists) about.AppendLine("Disk: " + (disk.Length >> 20) + " MB");
            var drive = new DriveInfo(Path.GetPathRoot(Program.VmDir));
            about.AppendLine("Free on " + drive.Name + ": " + (drive.AvailableFreeSpace >> 30) + " GB");
        }
        catch (Exception) { }
        return about.ToString();
    }
}
