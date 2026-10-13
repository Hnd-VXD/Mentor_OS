// MentorSetup.exe: the one file to download. It puts Mentor on a Windows computer:
//  - puts Mentor's own QEMU (the WINQ-EMU runtime) in the qemu folder beside the launcher;
//    from a release that has none, installs QEMU with winget when it is not there
//  - turns on the Windows Hypervisor Platform (asks for administrator rights; needs a restart)
//  - downloads Mentor.exe and the system image from the latest release into a folder
//    of the user's choosing, and puts a shortcut on the desktop
//  - starts Mentor when all of it is there; when Windows has to restart first (for the
//    hypervisor), offers to restart it and has Mentor start by itself afterwards
//
// It is the one thing a new user downloads and runs: the rest follows from it.
//
// What a release holds is read from its release.json:
//     {"launcher": "Mentor.exe",
//      "runtime": {"file": "winq-emu-alpha10-portable.zip", "size": bytes, "sha256": "hex"},
//      "image": {"parts": ["mentor.qcow2.001", ...], "size": bytes, "sha256": "hex"}}
// The image comes in parts because a release takes no file over 2 GB; they are joined
// as they arrive, into out\mentor.qcow2, where Mentor.exe looks for it.
//
// Without a window, for trying it out:
//     MentorSetup.exe --unattended --folder DIR [--source URL/] [--log FILE] [--no-shortcut]
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class SetupException : Exception
{
    public SetupException(string message) : base(message) { }
}

// The work, apart from the window that shows it.
class Installer
{
    public const string Release = "https://github.com/Hnd-VXD/Mentor_OS/releases/latest/download/";
    public static readonly string[] Steps = { "QEMU", "Windows Hypervisor Platform", "Mentor", "System image" };

    public string Folder, Source = Release;
    public bool Shortcut = true;
    public bool RestartNeeded;
    public Action<int, string> Step = delegate { };      // which step, and what became of it
    public Action<long, long> Progress = delegate { };   // bytes of the image so far, of how many
    public volatile bool Cancelled;

    public static string QemuFolder()
    {
        var dirs = new List<string>((Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'));
        dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "qemu"));
        foreach (string dir in dirs)
        {
            try { if (dir != "" && File.Exists(Path.Combine(dir, "qemu-system-x86_64w.exe"))) return dir; }
            catch (ArgumentException) { }
        }
        return null;
    }

    // The library programs reach the hypervisor through is only there with the feature on.
    public static bool HasHypervisor()
    {
        return File.Exists(Path.Combine(Environment.SystemDirectory, "WinHvPlatform.dll"));
    }

    public void Run()
    {
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;  // TLS 1.2
        Directory.CreateDirectory(Path.Combine(Folder, "out"));
        Dictionary<string, object> release = ReadRelease();
        var runtime = release.ContainsKey("runtime") ? release["runtime"] as Dictionary<string, object> : null;
        if (runtime != null) DownloadRuntime(runtime);
        else InstallQemu();
        EnableHypervisor();
        Step(2, "downloading");
        DownloadLauncher(release["launcher"] as string ?? "Mentor.exe");
        Step(2, "done");
        DownloadImage(release["image"] as Dictionary<string, object>);
        if (Shortcut) MakeShortcut();
    }

    // Mentor's own QEMU: unpacked into the qemu folder, where the launcher looks first.
    void DownloadRuntime(Dictionary<string, object> runtime)
    {
        string target = Path.Combine(Folder, "qemu");
        if (File.Exists(Path.Combine(target, @"bin\qemu-system-x86_64w.exe"))) { Step(0, "already there"); return; }
        Step(0, "downloading");
        string archive = Path.Combine(Folder, "qemu.zip"), unpacked = target + ".new";
        string wanted = (runtime["sha256"] as string ?? "").ToLowerInvariant(), got;
        using (SHA256 sha = SHA256.Create())
        {
            using (HttpWebResponse response = Get(Path.GetFileName(runtime["file"] as string)))
            using (Stream from = response.GetResponseStream())
            using (FileStream to = File.Create(archive))
            {
                var buffer = new byte[1 << 20];
                int read;
                while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (Cancelled) throw new OperationCanceledException();
                    to.Write(buffer, 0, read);
                    sha.TransformBlock(buffer, 0, read, null, 0);
                }
            }
            sha.TransformFinalBlock(new byte[0], 0, 0);
            got = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
        }
        if (wanted == "" || got != wanted)
        {
            File.Delete(archive);
            throw new SetupException("Mentor's QEMU did not arrive whole. Run this setup again.");
        }
        Step(0, "unpacking");
        if (Directory.Exists(unpacked)) Directory.Delete(unpacked, true);
        ZipFile.ExtractToDirectory(archive, unpacked);
        if (!File.Exists(Path.Combine(unpacked, @"bin\qemu-system-x86_64w.exe")))
            throw new SetupException("What arrived as Mentor's QEMU is not it.");
        if (Directory.Exists(target)) Directory.Delete(target, true);
        Directory.Move(unpacked, target);
        File.Delete(archive);
        Step(0, "done");
    }

    void InstallQemu()
    {
        if (QemuFolder() != null) { Step(0, "already installed"); return; }
        Step(0, "installing (Windows will ask for permission)");
        int code;
        try
        {
            code = Wait(new ProcessStartInfo("winget.exe",
                "install --id SoftwareFreedomConservancy.QEMU -e --accept-source-agreements --accept-package-agreements") {
                UseShellExecute = false, CreateNoWindow = true });
        }
        catch (Win32Exception)
        {
            throw new SetupException("QEMU could not be installed, because winget is not on this computer.\n" +
                "Install QEMU from https://qemu.weilnetz.de/w64/ and run this setup again.");
        }
        if (QemuFolder() == null)
            throw new SetupException("QEMU was not installed (winget ended with " + code + ").\n" +
                "Install it from https://qemu.weilnetz.de/w64/ and run this setup again.");
        Step(0, "installed");
    }

    void EnableHypervisor()
    {
        if (HasHypervisor()) { Step(1, "already on"); return; }
        Step(1, "turning on (Windows will ask for permission)");
        int code;
        try
        {
            code = Wait(new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "dism.exe"),
                "/online /enable-feature /featurename:HypervisorPlatform /all /norestart") {
                UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden });
        }
        catch (Win32Exception)  // the permission was not given
        {
            Step(1, "not turned on: Mentor will be very slow without it");
            return;
        }
        if (code == 0 || code == 3010)
        {
            RestartNeeded = true;
            Step(1, "on after Windows restarts");
        }
        else Step(1, "could not be turned on (" + code + "): Mentor will be very slow without it");
    }

    int Wait(ProcessStartInfo info)
    {
        using (Process process = Process.Start(info))
        {
            while (!process.WaitForExit(500))
                if (Cancelled) { try { process.Kill(); } catch (InvalidOperationException) { } throw new OperationCanceledException(); }
            return process.ExitCode;
        }
    }

    HttpWebResponse Get(string name)
    {
        var request = (HttpWebRequest)WebRequest.Create(Source + name);
        request.UserAgent = "MentorSetup";
        request.ReadWriteTimeout = 60000;
        return (HttpWebResponse)request.GetResponse();
    }

    Dictionary<string, object> ReadRelease()
    {
        using (HttpWebResponse response = Get("release.json"))
        using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
        {
            var release = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
            if (release == null || !(release.ContainsKey("image") && release["image"] is Dictionary<string, object>))
                throw new SetupException("The release does not say what it holds.");
            if (!release.ContainsKey("launcher")) release["launcher"] = "Mentor.exe";
            return release;
        }
    }

    void DownloadLauncher(string name)
    {
        string target = Path.Combine(Folder, "Mentor.exe"), fresh = target + ".new";
        using (HttpWebResponse response = Get(Path.GetFileName(name)))
        using (Stream from = response.GetResponseStream())
        using (FileStream to = File.Create(fresh))
            from.CopyTo(to);
        try
        {
            if (File.Exists(target)) File.Delete(target);
            File.Move(fresh, target);
        }
        catch (IOException) { throw new SetupException("Mentor is running from this folder. Close it and run this setup again."); }
        catch (UnauthorizedAccessException) { throw new SetupException("Mentor is running from this folder. Close it and run this setup again."); }
    }

    void DownloadImage(Dictionary<string, object> image)
    {
        string target = Path.Combine(Folder, @"out\mentor.qcow2"), partial = target + ".part";
        // A system already there is the one the disk in vm\ was made from: replacing it
        // would leave that disk unusable.
        if (File.Exists(target)) { Step(3, "already there, kept"); return; }
        long size = Convert.ToInt64(image["size"]);
        string wanted = (image["sha256"] as string ?? "").ToLowerInvariant();
        var buffer = new byte[1 << 20];
        long done = 0;
        using (SHA256 sha = SHA256.Create())
        {
            using (FileStream to = File.Create(partial))
                foreach (object part in (IEnumerable)image["parts"])
                    using (HttpWebResponse response = Get(Path.GetFileName(part as string)))
                    using (Stream from = response.GetResponseStream())
                    {
                        int read;
                        while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
                        {
                            if (Cancelled) throw new OperationCanceledException();
                            to.Write(buffer, 0, read);
                            sha.TransformBlock(buffer, 0, read, null, 0);
                            done += read;
                            Progress(done, size);
                        }
                    }
            sha.TransformFinalBlock(buffer, 0, 0);
            string got = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            if (done != size || (wanted != "" && got != wanted))
            {
                File.Delete(partial);
                throw new SetupException("The system image did not arrive whole. Run this setup again.");
            }
        }
        File.Move(partial, target);
        Step(3, "done");
    }

    void MakeShortcut()
    {
        try
        {
            Type type = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(type);
            string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Mentor.lnk");
            object link = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            Type linkType = link.GetType();
            linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(Folder, "Mentor.exe") });
            linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { Folder });
            linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
        }
        catch (Exception) { }  // a missing shortcut is no reason to call the setup failed
    }
}

class SetupWindow : Form
{
    static readonly Color Back = Color.FromArgb(22, 23, 27), Field = Color.FromArgb(34, 36, 42),
        Text1 = Color.FromArgb(240, 240, 244), Text2 = Color.FromArgb(160, 164, 174), Accent = Color.FromArgb(23, 147, 209);

    readonly TextBox folder = new TextBox();
    readonly Button browse = new Button(), go = new Button();
    readonly Label[] states = new Label[Installer.Steps.Length];
    readonly ProgressBar bar = new ProgressBar();
    readonly Label note = new Label();
    Installer installer;
    bool finished;

    public SetupWindow()
    {
        Text = "Mentor setup";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(520, 420);
        BackColor = Back;
        ForeColor = Text1;
        Font = new Font("Segoe UI", 10f);

        Stream emblem = Assembly.GetExecutingAssembly().GetManifestResourceStream("emblem.png");
        if (emblem != null)
            Controls.Add(new PictureBox { Image = Image.FromStream(emblem), SizeMode = PictureBoxSizeMode.Zoom,
                                          Bounds = new Rectangle(24, 20, 64, 64) });
        Controls.Add(new Label { Text = "Mentor", Font = new Font("Segoe UI Semibold", 20f), AutoSize = true, Location = new Point(100, 20) });
        Controls.Add(new Label { Text = "Agentic Linux, in a window on Windows", ForeColor = Text2, AutoSize = true, Location = new Point(103, 58) });

        Controls.Add(new Label { Text = "Folder (needs about 12 GB)", ForeColor = Text2, AutoSize = true, Location = new Point(24, 104) });
        folder.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Mentor");
        folder.Bounds = new Rectangle(24, 128, 372, 27);
        folder.BackColor = Field;
        folder.ForeColor = Text1;
        folder.BorderStyle = BorderStyle.FixedSingle;
        Style(browse, "Browse…", Field);
        browse.Bounds = new Rectangle(404, 127, 92, 29);
        browse.Click += delegate {
            using (var dialog = new FolderBrowserDialog { Description = "Where Mentor goes", SelectedPath = folder.Text })
                if (dialog.ShowDialog(this) == DialogResult.OK)
                    folder.Text = Path.GetFileName(dialog.SelectedPath).Equals("Mentor", StringComparison.OrdinalIgnoreCase)
                        ? dialog.SelectedPath : Path.Combine(dialog.SelectedPath, "Mentor");
        };
        Controls.Add(folder);
        Controls.Add(browse);

        for (int i = 0; i < states.Length; i++)
        {
            Controls.Add(new Label { Text = Installer.Steps[i], AutoSize = true, Location = new Point(24, 178 + i * 30) });
            states[i] = new Label { ForeColor = Text2, AutoSize = false, TextAlign = ContentAlignment.TopRight,
                                    Bounds = new Rectangle(220, 178 + i * 30, 276, 24) };
            Controls.Add(states[i]);
        }
        states[0].Text = "Mentor's own, about 80 MB";
        states[1].Text = Installer.HasHypervisor() ? "already on" : "will be turned on";

        bar.Bounds = new Rectangle(24, 306, 472, 8);
        bar.Maximum = 1000;
        bar.Visible = false;
        Controls.Add(bar);
        note.Bounds = new Rectangle(24, 322, 472, 40);
        note.ForeColor = Text2;
        Controls.Add(note);

        Style(go, "Install", Accent);
        go.Bounds = new Rectangle(356, 368, 140, 36);
        go.Click += delegate { OnGo(); };
        Controls.Add(go);
        AcceptButton = go;
    }

    static void Style(Button button, string text, Color color)
    {
        button.Text = text;
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 0;
        button.BackColor = color;
        button.ForeColor = Color.White;
    }

    void OnGo()
    {
        if (finished)
        {
            // Only reached when Windows has to restart ("Restart now"); otherwise Mentor was started already.
            if (installer.RestartNeeded)
            {
                try
                {
                    Process.Start(new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "shutdown.exe"), "/r /t 5 /c \"Restarting to finish setting up Mentor.\"") {
                        UseShellExecute = false, CreateNoWindow = true });
                }
                catch (Win32Exception) { note.Text = "Windows could not be restarted from here. Restart it from the Start menu."; return; }
            }
            Close();
            return;
        }
        try { installer = new Installer { Folder = Path.GetFullPath(folder.Text.Trim()) }; }
        catch (Exception) { note.Text = "That is not a folder name."; return; }
        folder.Enabled = browse.Enabled = go.Enabled = false;
        bar.Visible = true;
        note.ForeColor = Text2;
        note.Text = "";
        installer.Step = (index, state) => BeginInvoke((Action)(() => states[index].Text = state));
        long shown = -1;
        installer.Progress = (done, total) => {
            long tenth = done * 1000 / Math.Max(total, 1);
            if (tenth == shown) return;
            shown = tenth;
            BeginInvoke((Action)(() => {
                bar.Value = (int)Math.Min(tenth, 1000);
                states[3].Text = (done >> 20) + " of " + (total >> 20) + " MB";
            }));
        };
        new Thread(() => {
            string problem = null;
            try { installer.Run(); }
            catch (OperationCanceledException) { return; }
            catch (SetupException e) { problem = e.Message; }
            catch (WebException e) { problem = "The download failed: " + e.Message; }
            catch (IOException e) { problem = e.Message; }
            catch (UnauthorizedAccessException e) { problem = e.Message; }
            try { BeginInvoke((Action)(() => Done(problem))); }
            catch (InvalidOperationException) { }  // the window was closed meanwhile
        }) { IsBackground = true }.Start();
    }

    void Done(string problem)
    {
        go.Enabled = true;
        bar.Visible = false;
        if (problem != null)
        {
            note.ForeColor = Color.FromArgb(255, 138, 117);
            note.Text = problem;
            go.Text = "Try again";
            folder.Enabled = browse.Enabled = true;
            return;
        }
        finished = true;
        note.ForeColor = Text1;
        if (!installer.RestartNeeded)
        {
            // Everything is there: Mentor's own window takes over from here.
            StartMentor();
            Close();
            return;
        }
        // The hypervisor is only there after a restart of Windows. Mentor starts by itself
        // once the user is back, so that the setup is still the one thing they had to run.
        bool after = StartAfterRestart();
        note.Text = "Installed. Windows has to restart once" +
            (after ? "; Mentor starts by itself after that." : ". Then start Mentor from the shortcut on the desktop.");
        go.Text = "Restart now";
    }

    void StartMentor()
    {
        try
        {
            Process.Start(new ProcessStartInfo(Path.Combine(installer.Folder, "Mentor.exe")) { WorkingDirectory = installer.Folder });
        }
        catch (Win32Exception) { }  // the shortcut on the desktop is still there
    }

    // Once, at the next sign-in to Windows (the RunOnce key of this user).
    bool StartAfterRestart()
    {
        try
        {
            using (var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\RunOnce"))
                key.SetValue("Mentor", "\"" + Path.Combine(installer.Folder, "Mentor.exe") + "\"");
            return true;
        }
        catch (Exception) { return false; }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (installer != null) installer.Cancelled = true;
        base.OnFormClosing(e);
    }
}

static class SetupProgram
{
    [STAThread]
    static int Main(string[] args)
    {
        var installer = new Installer();
        bool unattended = false;
        string log = null;
        for (int i = 0; i < args.Length; i++)
            switch (args[i])
            {
                case "--unattended": unattended = true; break;
                case "--no-shortcut": installer.Shortcut = false; break;
                case "--folder": installer.Folder = Path.GetFullPath(args[++i]); break;
                case "--source": installer.Source = args[++i]; break;
                case "--log": log = args[++i]; break;
            }
        if (!unattended)
        {
            Application.EnableVisualStyles();
            Application.Run(new SetupWindow());
            return 0;
        }
        if (installer.Folder == null) return 2;
        var lines = new List<string>();
        installer.Step = (index, state) => { lock (lines) lines.Add(Installer.Steps[index] + ": " + state); };
        int result = 0;
        try { installer.Run(); }
        catch (Exception e) { lines.Add("failed: " + e.Message); result = 1; }
        if (installer.RestartNeeded) lines.Add("restart needed");
        if (log != null) File.WriteAllLines(log, lines);
        return result;
    }
}
