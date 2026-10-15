// Mentor launcher: starts the VM in QEMU (WHPX when available) without a console
// window and shares the Windows clipboard with the guest.
//
//   Mentor.exe [--memory GB] [--cpus N] [--cpu MODEL] [--reset] [--iso FILE]
//               [--fullscreen | --windowed] [--no-accel] [--vm-dir DIR] [--image FILE]
//               [--restore] [--yes] [--boot-timeout SECONDS] [--gpu] [--vulkan] [--repair]
//               [-- extra qemu arguments]
//
// --repair (the "Repair" button) starts the system without its desktop, on a text screen
// where the user talks to the agent, for when the desktop no longer comes up: the kernel
// is given systemd.unit=mentor-repair.target (through SMBIOS, which systemd-boot reads),
// and the start is not watched for a desktop. A restart from there is an ordinary start.
//
// The QEMU it runs is Mentor's own when there is a qemu folder beside this program (the
// WINQ-EMU runtime: a QEMU and virglrenderer patched for Windows, with only an SDL
// window), otherwise the one QEMU's installer put on the computer.
//
// --gpu lets the host's graphics card draw the desktop (virgl, in an SDL window) instead
// of the VM's CPU; --vulkan adds Vulkan for the system inside (Venus), with Mentor's own
// QEMU only. The window's keyboard is taken with a click and given back with Ctrl+Alt+G.
// The installer's QEMU tends to freeze for good when the guest first uses the card while
// that window is on screen (half of the starts, measured), and never did when the window
// was created minimized. So there it is, and it comes up by itself once the system inside
// is running; a start that freezes anyway is stopped and made again. Mentor's own QEMU
// has no such trouble and shows its window from the start.
//
// It also keeps restore points: snapshots of the VM's whole disk, made when the
// system inside asks for one (before the assistant changes it) and once a day
// after a start that worked. The system reports how each start went; when it
// fails to come up twice in a row, the launcher offers to go back to one.
// --restore offers that at any time; --yes takes the newest without asking.
//
// The system is drawn at the screen's own resolution instead of having Windows stretch a
// smaller picture (the blur on a display scaled to 150% or 200%): QEMU is started so that
// it gets real pixels, and the system inside is told the screen's scale and scales its
// desktop to match.
//
// Started without options (a double click), it first shows a small window with the
// choices people actually use: graphics card, Vulkan, full screen, memory, restore points,
// starting over. They are remembered in Mentor.settings next to the program.
//
// Ctrl+Alt+F (QEMU's own shortcut) switches between full screen and a window; so
// does `mentor window toggle` (Super+F11) inside the VM. The last mode is remembered.
//
// Built with the C# compiler that ships with Windows, see build-launcher.ps1.
using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

static class Program
{
    const string Title = "Mentor";
    public static int Freezes;  // starts in a row that froze with the graphics card drawing
    public static bool SoundFailed;  // QEMU would not start with sound: the next start is without

    [DllImport("winmm.dll")] static extern uint waveOutGetNumDevs();
    [DllImport("winmm.dll")] static extern uint waveInGetNumDevs();

    // How the system's sound reaches Windows. DirectSound, the usual way, refuses to start at
    // all on a computer without a microphone ("Could not initialize DirectSoundCapture"), and
    // QEMU then stops: there SDL plays the sound, without a microphone. With nothing to play
    // on either, or after a start that failed over sound, the system gets a sound card that
    // goes nowhere.
    static string[] Sound()
    {
        uint speakers = 0, microphones = 0;
        try { speakers = waveOutGetNumDevs(); microphones = waveInGetNumDevs(); }
        catch (Exception) { }
        if (SoundFailed || speakers == 0)
            return new[] { "-audiodev", "none,id=snd", "-device", "ich9-intel-hda", "-device", "hda-output,audiodev=snd" };
        if (microphones == 0)
            return new[] { "-audiodev", "sdl,id=snd", "-device", "ich9-intel-hda", "-device", "hda-output,audiodev=snd" };
        return new[] { "-audiodev", "dsound,id=snd", "-device", "ich9-intel-hda", "-device", "hda-duplex,audiodev=snd" };
    }

    [STAThread]
    static int Main(string[] args)
    {
        Theme.SetProcessDPIAware();  // sharp on a high-resolution screen instead of stretched
        Application.EnableVisualStyles();
        try
        {
            return Run(args);
        }
        catch (LauncherException e)
        {
            MessageBox.Show(e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    static int Run(string[] args)
    {
        // The desktop is rendered on the CPU, so it gets half of the host's cores (4 to 8).
        int memoryGB = 6, cpus = Math.Max(4, Math.Min(8, Environment.ProcessorCount / 2));
        // 'max' passes the host's CPU features through. The bare qemu64 model has no
        // AVX/SSE4, which Claude Code's runtime needs (it hangs at startup without them).
        string cpu = "max", iso = null, vmDir = null, image = null;
        bool reset = false, accel = true, restore = false, yes = false, gpu = false, vulkan = false;
        // The window shows the screen's real pixels and the desktop inside is scaled to match,
        // always: it used to be a choice ("Sharp text", --sharp), and nobody wanted it off.
        bool sharp = true;
        int bootTimeout = 480;
        bool repair = false;
        bool? fullscreen = null;
        var extra = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--memory": memoryGB = int.Parse(Value(args, ref i)); break;
                case "--cpus": cpus = int.Parse(Value(args, ref i)); break;
                case "--cpu": cpu = Value(args, ref i); break;
                case "--iso": iso = Path.GetFullPath(Value(args, ref i)); break;
                case "--vm-dir": vmDir = Path.GetFullPath(Value(args, ref i)); break;
                case "--image": image = Path.GetFullPath(Value(args, ref i)); break;
                case "--reset": reset = true; break;
                case "--fullscreen": fullscreen = true; break;
                case "--windowed": fullscreen = false; break;
                case "--no-accel": accel = false; break;
                case "--restore": restore = true; break;
                case "--yes": yes = true; break;
                case "--gpu": gpu = true; break;
                case "--sharp": break;  // from when it was a choice
                case "--vulkan": vulkan = true; break;
                case "--boot-timeout": bootTimeout = int.Parse(Value(args, ref i)); break;
                case "--repair": repair = true; break;
                case "--":
                    for (i++; i < args.Length; i++) extra.Add(args[i]);
                    break;
                default: throw new LauncherException("Unknown option: " + args[i]);
            }
        }

        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        if (image == null) image = Path.Combine(root, @"out\mentor.qcow2");
        if (vmDir == null) vmDir = Path.Combine(root, "vm");
        string disk = Path.Combine(vmDir, "disk.qcow2");
        string vars = Path.Combine(vmDir, "efivars.fd");

        if (AlreadyRunning(vmDir, args.Length == 0)) return 0;
        string qemuDir = FindQemu(root);
        // Mentor's own QEMU (the WINQ-EMU runtime, in the qemu folder beside this program) differs
        // from the one QEMU's installer puts on a computer: it has a graphics path that works
        // from the first moment, gives memory back to Windows, and only an SDL window.
        bool own = File.Exists(Path.Combine(qemuDir, "libvirglrenderer-1.dll")) &&
                   !File.Exists(Path.Combine(qemuDir, "libgtk-3-0.dll"));
        string firmware = Path.Combine(qemuDir, @"share\edk2-x86_64-code.fd");
        string varsTemplate = Path.Combine(qemuDir, @"share\edk2-i386-vars.fd");
        if (!File.Exists(firmware) || !File.Exists(varsTemplate))
            throw new LauncherException("UEFI firmware not found in " + Path.Combine(qemuDir, "share"));
        if (!File.Exists(image))
            throw new LauncherException("No image at " + image + "\n\nBuild it first:\n    .\\build\\build.ps1");

        string modeFile = Path.Combine(vmDir, "fullscreen");  // exists = start in full screen
        var points = new RestorePoints(Path.Combine(qemuDir, "qemu-img.exe"), vmDir, disk, vars);
        var watch = new BootWatch(vmDir);
        if (args.Length == 0)
        {
            Settings settings = Settings.Load(Path.Combine(root, "Mentor.settings"));
            if (settings.memory > 0) memoryGB = settings.memory;
            if (settings.cpus > 0) cpus = settings.cpus;
            using (var window = new LauncherWindow(memoryGB, cpus, settings.gpu, settings.vulkan && own, own,
                                                   File.Exists(modeFile), points, watch, vmDir, image))
            {
                if (window.ShowDialog() != DialogResult.OK) return 0;
                settings.memory = memoryGB = window.Memory;
                settings.cpus = cpus = window.Cpus;
                settings.gpu = gpu = window.Gpu;
                if (own) settings.vulkan = vulkan = window.Vulkan;
                fullscreen = window.Fullscreen;
                repair = window.Repair;
            }
            settings.Save();
        }

        if (reset && Directory.Exists(vmDir)) Directory.Delete(vmDir, true);
        Directory.CreateDirectory(vmDir);
        if (!File.Exists(disk))
        {
            // The VM writes to an overlay, so the built image stays pristine and --reset is instant.
            string error;
            int code = RunHidden(Path.Combine(qemuDir, "qemu-img.exe"),
                "create -q -f qcow2 -F qcow2 -b " + Quote(image) + " " + Quote(disk), out error);
            if (code != 0) throw new LauncherException("Could not create the VM disk:\n" + error);
        }
        if (!File.Exists(vars)) File.Copy(varsTemplate, vars);

        // Resetting a running VM crashes QEMU under WHPX, so QEMU is told to exit
        // on a guest reboot instead (-no-reboot) and is started again here.
        if (fullscreen == true) File.WriteAllText(modeFile, "");
        else if (fullscreen == false) File.Delete(modeFile);

        if (restore)
        {
            List<RestorePoint> all = points.List();
            if (all.Count == 0)
                throw new LauncherException("There are no restore points yet.\n\nOne is made before every change " +
                    "the assistant applies to the system, and once a day after a start that worked.");
            RestorePoint chosen = yes ? all[all.Count - 1] : RestoreDialog.Ask(
                "Go back to a restore point. Mentor's whole disk becomes what it was at that moment: " +
                "everything changed inside Mentor since then is lost.", all, "Cancel");
            if (chosen == null) return 0;
            GoBack(points, watch, chosen);
        }
        bool again = true;
        while (again)
        {
            // A start is watched until the system inside says how it went. Not after the
            // user chose to go on with a system that does not come up: they are repairing it.
            int timeout = iso == null ? bootTimeout : 0;
            if (iso == null && watch.Enabled && watch.Failures >= 2)
            {
                watch.Failures = 0;
                List<RestorePoint> all = points.List();
                RestorePoint chosen = null;
                if (all.Count == 0)
                    MessageBox.Show("Mentor did not finish starting the last two times, and there is no restore " +
                        "point to go back to.\n\nIt will be started again. If it stays broken, Mentor.exe --reset " +
                        "starts over from the built image; everything inside Mentor is lost then.",
                        Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                else
                    chosen = yes ? all[all.Count - 1] : RestoreDialog.Ask(
                        "Mentor did not finish starting the last two times.\n\nYou can go back to a restore " +
                        "point: its whole disk becomes what it was at that moment, and everything changed " +
                        "inside Mentor since then is lost.", all, "Start again");
                if (chosen != null) GoBack(points, watch, chosen);
                else timeout = 0;
            }
            if (gpu && Freezes >= 2)
            {
                gpu = false;
                MessageBox.Show("Mentor froze twice while starting with the graphics card drawing.\n\n" +
                    "It is started without it this time.", Title, MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            points.Trim();
            var extraNow = new List<string>(extra);
            if (repair)
            {
                // No desktop is coming, so none is waited for, and nothing draws but the text screen.
                extraNow.Add("-smbios");
                extraNow.Add("type=11,value=io.systemd.boot.kernel-cmdline-extra=systemd.unit=mentor-repair.target mentor.repair=1");
                timeout = 0;
            }
            again = RunVm(qemuDir, firmware, vars, disk, iso, cpu, cpus, memoryGB, accel, extraNow, modeFile,
                          watch, points, timeout, gpu && !repair, sharp, own, vulkan && own && gpu && !repair);
            repair = false;  // a restart from the repair screen is an ordinary start
        }
        return 0;
    }

    // Mentor is running from this folder already: its window cannot be closed, so this is
    // where it is stopped from outside, for when it cannot be done from inside. True when it was running.
    static bool AlreadyRunning(string vmDir, bool ask)
    {
        string running = Path.Combine(vmDir, "running");
        int pid, port;
        try
        {
            string[] parts = File.ReadAllText(running).Split(' ');
            pid = int.Parse(parts[0]);
            port = int.Parse(parts[1]);
            if (!Process.GetProcessById(pid).ProcessName.StartsWith("qemu-system", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException();
        }
        catch (Exception)  // no such file, or what it names is gone: not running
        {
            try { File.Delete(running); }
            catch (IOException) { }
            return false;
        }
        if (!ask) throw new LauncherException("Mentor is already running from this folder.");
        DialogResult choice = MessageBox.Show(
            "Mentor is already running.\n\n" +
            "Yes: shut it down properly, as from its own menu. It takes a few seconds.\n" +
            "No: turn it off at once, as if the power were cut. Unsaved work inside is lost.\n" +
            "Cancel: leave it running.",
            Title, MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button3);
        if (choice == DialogResult.Yes) Tell(port, "system_powerdown");
        else if (choice == DialogResult.No) Tell(port, "quit");
        return true;
    }

    // One command to a running QEMU's monitor.
    static void Tell(int port, string command)
    {
        try
        {
            using (var client = new TcpClient("127.0.0.1", port))
            using (var reader = new StreamReader(client.GetStream()))
            {
                reader.ReadLine();  // greeting
                foreach (string execute in new[] { "qmp_capabilities", command })
                {
                    byte[] line = Encoding.ASCII.GetBytes("{\"execute\": \"" + execute + "\"}\n");
                    client.GetStream().Write(line, 0, line.Length);
                    reader.ReadLine();
                }
            }
        }
        catch (IOException) { }
        catch (SocketException) { }
    }

    static void GoBack(RestorePoints points, BootWatch watch, RestorePoint point)
    {
        string error = points.Restore(point);
        if (error != null)
            throw new LauncherException("Could not go back to the restore point of " + point.time + ":\n\n" + error +
                                        "\n\nIf Mentor is running, close it first.");
        watch.Failures = 0;
    }

    // Runs the VM until it stops. Returns true when the guest asked for a reboot.
    static bool RunVm(string qemuDir, string firmware, string vars, string disk, string iso,
                      string cpu, int cpus, int memoryGB, bool accel, List<string> extra, string modeFile,
                      BootWatch watch, RestorePoints points, int bootTimeout, bool gpu, bool sharp,
                      bool own, bool vulkan)
    {
        int clipboardPort = FreePort(), controlPort = FreePort(), qmpPort = FreePort(), stopPort = FreePort();
        string running = Path.Combine(Path.GetDirectoryName(modeFile), "running");
        // The resolution the system inside starts with: the one its window is going to have,
        // so that it does not change in front of the user once the desktop is up. In real
        // pixels when the window shows those (sharp), otherwise in the screen's scaled ones.
        // Only with the graphics card: without it the picture is drawn the slow way until the
        // system's own driver takes over, and at this size that made the start minutes long.
        // There the window is given its size when the system says it has started (OnBoot).
        // Mentor's own QEMU shows its window from the start, so there the window gets its size
        // when the system says it has started, as without the graphics card.
        string firstMode = "";
        if (gpu && !own)
        {
            float dpi;
            using (Graphics g = Graphics.FromHwnd(IntPtr.Zero)) dpi = g.DpiX / 96f;
            Size picture = File.Exists(modeFile) ? Screen.PrimaryScreen.Bounds.Size : VmWindow.Picture();
            if (!sharp) picture = new Size((int)(picture.Width / dpi) / 2 * 2, (int)(picture.Height / dpi) / 2 * 2);
            firstMode = ",xres=" + picture.Width + ",yres=" + picture.Height;
        }
        var q = new List<string> {
            "-name", Title,
            "-machine", "q35",
            "-cpu", cpu,
            "-smp", cpus.ToString(),
            "-m", memoryGB + "G",
            "-drive", "if=pflash,format=raw,readonly=on,file=" + firmware,
            "-drive", "if=pflash,format=raw,file=" + vars,
            // An explicit boot order: the firmware's remembered one breaks whenever
            // the set of devices changes, and it then falls back to network boot.
            "-drive", "if=none,id=disk,format=qcow2,file=" + disk,
            "-device", "virtio-blk-pci,drive=disk,bootindex=" + (iso == null ? 0 : 1),
            "-netdev", "user,id=net",
            "-device", "virtio-net-pci,netdev=net",
            "-device", (gpu ? "virtio-vga-gl" : "virtio-vga") + firstMode +
                       // Vulkan for the system inside (Venus), with memory of the host's for what it draws.
                       (vulkan ? ",venus=on,blob=on,hostmem=" + HostMemory(memoryGB) + "G" : ""),
            // The guest follows the size of the GTK window. While the pointer is over it the
            // keyboard belongs to the guest, including the Windows key (Super) and Alt+Tab.
            // QEMU's GTK window cannot show a GPU-drawn guest on Windows; its SDL one can.
            // The window's X does nothing: closing it would be pulling the plug on a running
            // system. It is shut down from inside, or by starting this program again (AlreadyRunning).
            "-display", (own ? (gpu ? "sdl,gl=on" : "sdl") : gpu ? "sdl,gl=on"
                            // With real pixels a window that fills the screen from the firmware on makes
                            // the start minutes long: there it goes full screen later (HostBridge.OnBoot).
                            : "gtk,show-menubar=off,grab-on-hover=on" + (File.Exists(modeFile) && !sharp ? ",full-screen=on" : ""))
                        + ",window-close=off",
            "-device", "qemu-xhci",
            "-device", "usb-tablet",
            "-device", "virtio-rng-pci",
            "-device", "virtio-serial-pci",
            "-chardev", "socket,id=clipboard,host=127.0.0.1,port=" + clipboardPort + ",server=on,wait=off",
            "-device", "virtserialport,chardev=clipboard,name=org.mentor.clipboard",
            "-chardev", "socket,id=control,host=127.0.0.1,port=" + controlPort + ",server=on,wait=off",
            "-device", "virtserialport,chardev=control,name=org.mentor.control",
            "-no-reboot",
            "-qmp", "tcp:127.0.0.1:" + qmpPort + ",server=on,wait=off",
            "-qmp", "tcp:127.0.0.1:" + stopPort + ",server=on,wait=off",
        };
        // QEMU tries the accelerators in order, so it still starts (slowly) without WHPX.
        // The installer's QEMU needs the interrupt controller kept out of the hypervisor; Mentor's
        // own does not start the system at all that way.
        if (accel) { q.Add("-accel"); q.Add(own ? "whpx" : "whpx,kernel-irqchip=off"); }
        // Memory the system inside has freed goes back to Windows (a 16 GB system at rest holds about 2).
        if (own) { q.Add("-device"); q.Add("virtio-balloon-pci,free-page-reporting=on"); }
        q.Add("-accel"); q.Add("tcg");
        if (iso != null)
        {
            q.Add("-drive"); q.Add("if=none,id=iso,media=cdrom,readonly=on,file=" + iso);
            q.Add("-device"); q.Add("ide-cd,drive=iso,bootindex=0");
        }
        // What the screen is scaled by, for the system inside to scale its desktop to (1: leave it).
        float hostScale = 1f;
        if (sharp)
            using (Graphics g = Graphics.FromHwnd(IntPtr.Zero)) hostScale = g.DpiX / 96f;
        q.Add("-fw_cfg");
        q.Add("name=opt/mentor/scale,string=" + hostScale.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture));
        q.AddRange(extra);
        // Real pixels for QEMU's window: its SDL window has to be declared aware of the scaling,
        // its GTK one is aware already and has to be told not to do the scaling itself.
        string sharpName = gpu || own ? "__COMPAT_LAYER" : "GDK_SCALE", sharpValue = gpu || own ? "HighDpiAware" : "1";

        // With the graphics card drawing, the window waits minimized (see HostBridge.Reveal).
        // Not for someone who chose the display themselves.
        // Nor with Mentor's own QEMU, whose window does not freeze when it is there from the start.
        bool waitMinimized = gpu && !own && !extra.Contains("-display");
        if (gpu && !own && !waitMinimized && File.Exists(modeFile)) q.Add("-full-screen");
        if (!extra.Contains("-audiodev")) q.AddRange(Sound());
        var stderr = new StringBuilder();
        string program = Path.Combine(qemuDir, "qemu-system-x86_64w.exe");
        string said = Path.Combine(Path.GetDirectoryName(modeFile), "qemu-said.txt");
        Process qemu;
        if (waitMinimized)
        {
            // Running from here on: Process.Start cannot ask for a minimized window.
            if (sharp) Environment.SetEnvironmentVariable(sharpName, sharpValue);
            qemu = MinimizedProcess.Start(program, Join(q), said);
            if (sharp) Environment.SetEnvironmentVariable(sharpName, null);
        }
        else
        {
            qemu = new Process();
            qemu.StartInfo = new ProcessStartInfo(program, Join(q)) {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
            };
            if (sharp) qemu.StartInfo.EnvironmentVariables[sharpName] = sharpValue;
            qemu.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (stderr) stderr.AppendLine(e.Data); };
        }
        var qmp = new Qmp(qmpPort);
        watch.Begin();
        var bridge = new HostBridge(clipboardPort, controlPort, qemu, modeFile, qmp, watch, points, bootTimeout,
                                    waitMinimized, File.Exists(modeFile), sharp, own);
        qemu.EnableRaisingEvents = true;
        // Closing the window ends Application.Run below. Not Application.Exit():
        // after it, a second Application.Run (guest reboot) returns immediately.
        qemu.Exited += (s, e) => {
            try { bridge.BeginInvoke((Action)bridge.Close); }
            catch (InvalidOperationException) { }
        };
        if (!waitMinimized)
        {
            qemu.Start();
            qemu.BeginErrorReadLine();
        }
        // For this program started again meanwhile: which QEMU it is and where to tell it to stop.
        try { File.WriteAllText(running, qemu.Id + " " + stopPort); }
        catch (IOException) { }

        Application.Run(bridge);

        qemu.WaitForExit();
        try { File.Delete(running); }
        catch (IOException) { }
        if (waitMinimized)
        {
            try { stderr.Append(File.ReadAllText(said)); }
            catch (IOException) { }
        }
        qmp.Reader.Join(2000);
        watch.End(qmp.StopReason, bridge.TimedOut);
        // What QEMU itself had to say, for when something goes wrong.
        try
        {
            File.AppendAllText(Path.Combine(Path.GetDirectoryName(modeFile), "qemu.log"),
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  exit " + qemu.ExitCode + ", " + (qmp.StopReason ?? "no reason given") +
                "\r\n" + Tail(stderr.ToString(), 4000) + "\r\n");
        }
        catch (IOException) { }
        if (bridge.Froze)
        {
            Freezes++;
            return true;  // start it again
        }
        if (bridge.Revealed) Freezes = 0;
        // Sound that Windows will not give (a device that went away, a driver that is broken)
        // must not keep the system from starting: once more, without.
        string complaint = stderr.ToString();
        if (qemu.ExitCode != 0 && !bridge.TimedOut && !bridge.Revealed && !SoundFailed &&
            (complaint.Contains("DirectSound") || complaint.Contains("audio driver") || complaint.Contains("audiodev")))
        {
            SoundFailed = true;
            return true;  // start it again
        }
        if (qemu.ExitCode != 0 && !bridge.TimedOut)
            throw new LauncherException("QEMU stopped with an error:\n\n" + Tail(stderr.ToString(), 1500));
        return qmp.StopReason == "guest-reset" || bridge.TimedOut;
    }

    // QEMU opens its sockets a moment after the process starts.
    public static TcpClient Connect(int port)
    {
        for (int attempt = 0; attempt < 100; attempt++)
        {
            try { return new TcpClient("127.0.0.1", port); }
            catch (SocketException) { Thread.Sleep(200); }
        }
        return null;
    }

    static string Value(string[] args, ref int i)
    {
        if (i + 1 >= args.Length) throw new LauncherException(args[i] + " needs a value");
        return args[++i];
    }

    // Memory of the host's for what Vulkan draws: half the system's, 8 GB at most, and a power
    // of two, which the device insists on.
    static int HostMemory(int memoryGB)
    {
        int size = 1;
        while (size * 2 <= Math.Min(8, memoryGB / 2)) size *= 2;
        return size;
    }

    // Mentor's own, beside this program, before one installed on the computer.
    static string FindQemu(string root)
    {
        const string exe = "qemu-system-x86_64w.exe";
        var dirs = new List<string> { Path.Combine(root, @"qemu\bin"), Path.Combine(root, "qemu") };
        dirs.AddRange((Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'));
        dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "qemu"));
        foreach (string dir in dirs)
        {
            try { if (dir != "" && File.Exists(Path.Combine(dir, exe))) return dir; }
            catch (ArgumentException) { }
        }
        throw new LauncherException("QEMU is not installed. Install it with:\n    winget install SoftwareFreedomConservancy.QEMU");
    }

    static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    public static int RunHidden(string file, string arguments, out string error)
    {
        var p = Process.Start(new ProcessStartInfo(file, arguments) {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true,
        });
        error = p.StandardError.ReadToEnd();
        p.WaitForExit();
        return p.ExitCode;
    }

    public static string Quote(string s) { return s.IndexOf(' ') >= 0 ? "\"" + s + "\"" : s; }

    static string Join(List<string> args)
    {
        var parts = new List<string>();
        foreach (string a in args) parts.Add(Quote(a));
        return string.Join(" ", parts);
    }

    static string Tail(string s, int max) { return s.Length <= max ? s : s.Substring(s.Length - max); }
}

// Starts a program with its first window minimized, which Process.Start cannot do for a program
// it starts directly, and with what it prints going to a file.
static class MinimizedProcess
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct StartupInfo
    {
        public int size;
        public string reserved, desktop, title;
        public int x, y, width, height, columns, rows, fill, flags;
        public short showWindow, reserved2;
        public IntPtr reserved3, input, output, error;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInformation { public IntPtr process, thread; public int processId, threadId; }

    [StructLayout(LayoutKind.Sequential)]
    struct SecurityAttributes { public int length; public IntPtr descriptor; public bool inherit; }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcess(string application, StringBuilder commandLine, IntPtr processAttributes,
        IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
        ref StartupInfo startup, out ProcessInformation information);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateFile(string name, uint access, uint share, ref SecurityAttributes security,
        uint disposition, uint flags, IntPtr template);

    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    const int UseShowWindow = 0x1, UseStdHandles = 0x100;
    const short ShowMinimizedNotActive = 7;
    const uint GenericWrite = 0x40000000, ShareReadWrite = 0x3, CreateAlways = 2;

    public static Process Start(string program, string arguments, string outputFile)
    {
        var inheritable = new SecurityAttributes { length = Marshal.SizeOf(typeof(SecurityAttributes)), inherit = true };
        IntPtr output = CreateFile(outputFile, GenericWrite, ShareReadWrite, ref inheritable, CreateAlways, 0, IntPtr.Zero);
        if (output == new IntPtr(-1)) throw new LauncherException("Could not write " + outputFile);
        var startup = new StartupInfo {
            size = Marshal.SizeOf(typeof(StartupInfo)), flags = UseShowWindow | UseStdHandles,
            showWindow = ShowMinimizedNotActive, output = output, error = output,
        };
        ProcessInformation information;
        var commandLine = new StringBuilder(Program.Quote(program) + " " + arguments);
        bool started = CreateProcess(null, commandLine, IntPtr.Zero, IntPtr.Zero, true, 0, IntPtr.Zero, null,
                                     ref startup, out information);
        int error = Marshal.GetLastWin32Error();
        CloseHandle(output);
        if (!started) throw new LauncherException("Could not start " + program + " (Windows error " + error + ").");
        Process process = Process.GetProcessById(information.processId);
        IntPtr keep = process.Handle;  // held from now on, so that its exit code can be read later
        CloseHandle(information.thread);
        CloseHandle(information.process);
        return process;
    }
}

class LauncherException : Exception
{
    public LauncherException(string message) : base(message) { }
}

// The launcher's invisible window: the host end of everything the guest and the
// user can ask of it while the VM runs.
//  - shared clipboard: {"text": "..."} lines over one QEMU TCP chardev, both ways,
//    and copied files as a stream of lines on the same; see ClipboardFiles; a picture
//    (Windows' Snipping Tool, PrtScr) as {"image": "<base64 PNG>"}, to the guest only
//  - window mode: {"fullscreen": true|false|"toggle"} lines from the guest over a
//    second chardev; see VmWindow
//  - how the start went: {"boot": "ok"|"trial"|"restoring"} on that chardev; see BootWatch
//  - {"restore-point": "why"} on it asks for a snapshot of the disk, and gets an answer
class HostBridge : Form
{
    const int WM_CLIPBOARDUPDATE = 0x031D;
    const int MaxBytes = 1 << 20;

    [DllImport("user32.dll")] static extern bool AddClipboardFormatListener(IntPtr hwnd);

    readonly Process qemu;
    readonly Qmp qmp;
    readonly BootWatch watch;
    readonly RestorePoints points;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly object sendLock = new object();
    NetworkStream clipboard, control;
    bool? toldFullscreen;  // what the guest was last told of the window: for its Full Screen switch
    readonly ClipboardFiles files;
    string synced;  // the text both sides already agree on
    string syncedImage;  // a fingerprint of the picture last sent, so that it is sent once
    const int MaxImageBytes = 32 << 20;  // a PNG larger than this stays on the host

    // True once a start that never reported back was stopped from here.
    public bool TimedOut { get; private set; }
    // True once a QEMU that stopped answering while starting was stopped from here.
    public bool Froze { get; private set; }
    // True once QEMU's window, if it waited minimized, was brought up.
    public bool Revealed { get; private set; }
    bool enteringFullscreen;  // a window that is to be full screen and has not been made so yet
    readonly bool waitMinimized, wantFullscreen;
    DateTime revealedAt;
    readonly bool sharp;
    readonly bool late;  // the window is made full screen when the system has started, not from the firmware on
    bool sized;  // a sharp window has been given its size
    StartSplash splash;
    int frozenFor;  // looks in a row at which QEMU's window did not answer
    const int RevealAnyway = 45;  // seconds, for a system that never reports its desktop

    public HostBridge(int clipboardPort, int controlPort, Process qemu, string modeFile,
                      Qmp qmp, BootWatch watch, RestorePoints points, int bootTimeout,
                      bool waitMinimized, bool wantFullscreen, bool sharp, bool late)
    {
        this.sharp = sharp;
        this.late = late;
        this.waitMinimized = waitMinimized;
        this.wantFullscreen = wantFullscreen;
        Revealed = !waitMinimized;
        enteringFullscreen = (sharp || late) && !waitMinimized && wantFullscreen;
        this.qemu = qemu;
        this.qmp = qmp;
        this.watch = watch;
        this.points = points;
        if (waitMinimized)
        {
            // Something to look at meanwhile: the system's own boot screen is in that window.
            splash = new StartSplash(wantFullscreen);
            splash.Show();
            FormClosed += (s, e) => splash.Close();
            // The window sometimes comes up by itself when the guest changes the picture's
            // size, which is exactly when it must not be on screen: back down it goes.
            var keepDown = new System.Windows.Forms.Timer { Interval = 150 };
            keepDown.Tick += (s, e) => {
                if (Revealed || qemu.HasExited) keepDown.Stop();
                else VmWindow.KeepMinimized(qemu);
            };
            keepDown.Start();
        }
        ShowInTaskbar = false;
        IntPtr unused = Handle;  // create the window before the threads post to it
        files = new ClipboardFiles(this, WriteClipboard);
        Listen(clipboardPort, stream => { clipboard = stream; toldFullscreen = null; }, message => {
            string text = message["text"] as string;
            if (!string.IsNullOrEmpty(text)) SetClipboard(text);
        }, files.Receive);
        Listen(controlPort, stream => control = stream, message => {
            object value;
            if (message.TryGetValue("fullscreen", out value))
                VmWindow.SetFullscreen(qemu, value is bool ? (bool)value : !VmWindow.IsFullscreen(qemu));
            if (message.TryGetValue("boot", out value)) OnBoot(value as string);
            if (message.TryGetValue("restore-point", out value)) OnRestorePoint(value as string);
        });
        DateTime started = DateTime.UtcNow;
        var timer = new System.Windows.Forms.Timer { Interval = 2000 };
        timer.Tick += (s, e) => {
            // A system that is known to report its starts and says nothing for this long is
            // stuck: stop it, so the next start can fall back or a restore point be offered.
            if (bootTimeout > 0 && !TimedOut && watch.Enabled && !watch.Explained &&
                (DateTime.UtcNow - started).TotalSeconds > bootTimeout)
            {
                TimedOut = true;
                if (qmp.Execute("quit", null, 5000) != null && !qemu.HasExited) qemu.Kill();
                return;
            }
            if (waitMinimized && !Froze && !qemu.HasExited &&
                (!Revealed || (DateTime.UtcNow - revealedAt).TotalSeconds < 10))
            {
                // A window that stops answering during the start does not come back.
                qemu.Refresh();
                frozenFor = qemu.MainWindowHandle != IntPtr.Zero && !qemu.Responding ? frozenFor + 1 : 0;
                if (frozenFor >= 4)  // eight seconds
                {
                    Froze = true;
                    try { qemu.Kill(); }
                    catch (InvalidOperationException) { }
                    return;
                }
                if (!Revealed && (DateTime.UtcNow - started).TotalSeconds > RevealAnyway) Reveal();
            }
            // Remember the mode for the next start, however it was changed.
            if (!Revealed) return;
            if (enteringFullscreen && (DateTime.UtcNow - started).TotalSeconds < 180) return;
            if (VmWindow.Find(qemu) == IntPtr.Zero) return;
            // The desktop inside can only be scaled by two when the picture's sides are even.
            if (sharp && sized && !VmWindow.IsFullscreen(qemu)) VmWindow.KeepEven(qemu);
            bool on = VmWindow.IsFullscreen(qemu);
            if (toldFullscreen != on &&
                WriteClipboard(Encoding.UTF8.GetBytes("{\"window-fullscreen\": " + (on ? "true" : "false") + "}\n")))
                toldFullscreen = on;
            if (on == File.Exists(modeFile)) return;
            if (on) File.WriteAllText(modeFile, "");
            else File.Delete(modeFile);
        };
        timer.Start();
    }

    protected override void SetVisibleCore(bool value) { base.SetVisibleCore(false); }

    // Brings QEMU's window up from the taskbar, where it waited for the guest to get past
    // its first uses of the graphics card. That is when the desktop is up: brought up
    // earlier, at the system's first sign of life, it still froze in 2 starts of 6.
    void Reveal()
    {
        if (Revealed) return;
        Revealed = true;
        revealedAt = DateTime.UtcNow;
        if (splash != null) splash.Close();
        VmWindow.Restore(qemu);
        if (wantFullscreen) EnterFullscreen();
    }

    void EnterFullscreen()
    {
        enteringFullscreen = false;
        // The key press that switches to full screen does not always land on a window that
        // has only just come up: look again a few times.
        int tries = 0;
        var again = new System.Windows.Forms.Timer { Interval = 1200 };
        again.Tick += (s, e) => {
            if (qemu.HasExited || VmWindow.IsFullscreen(qemu) || ++tries > 4) again.Stop();
            else VmWindow.SetFullscreen(qemu, true);
        };
        VmWindow.SetFullscreen(qemu, true);
        again.Start();
    }

    void OnBoot(string how)
    {
        if (how == "starting")
        {
            // With real pixels the window opens half as large as it used to. It gets a proper
            // size now, before the desktop inside starts, so that the desktop starts in that
            // size rather than changing to it. Not earlier: a large window makes the firmware
            // and the first seconds of the system, drawn the slow way, take a minute longer.
            if ((sharp || late) && !waitMinimized && !VmWindow.IsFullscreen(qemu))
            {
                if (wantFullscreen) EnterFullscreen();
                else if (sharp) sized = VmWindow.Resize(qemu);
            }
            return;
        }
        if (how == "ok") Reveal();
        if (how == "ok" && (sharp || late))
        {
            // Should the window not have got its size or its full screen at the start (a system
            // from before it said when it starts), or have lost it.
            sized = sharp;
            if (!waitMinimized && !VmWindow.IsFullscreen(qemu))
            {
                if (enteringFullscreen) EnterFullscreen();
                else if (sharp) VmWindow.Resize(qemu);
            }
        }
        watch.Signal(how);
        // A system that has just come up is worth keeping, if nothing recent is kept.
        if (how == "ok" && points.NewestIsOlderThan(TimeSpan.FromHours(24)))
            points.Create(qmp, "Automatic, after a start that worked");
    }

    void OnRestorePoint(string reason)
    {
        var answer = new Dictionary<string, object>();
        string error = points.Create(qmp, string.IsNullOrEmpty(reason) ? "Before a change" : reason);
        answer["ok"] = error == null;
        if (error == null) answer["name"] = points.Newest.name;
        else answer["error"] = error;
        byte[] line = Encoding.UTF8.GetBytes(json.Serialize(answer) + "\n");
        lock (sendLock)
        {
            if (control == null) return;
            try { control.Write(line, 0, line.Length); }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        AddClipboardFormatListener(Handle);
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_CLIPBOARDUPDATE) SendClipboard();
        base.WndProc(ref m);
    }

    // One line to the guest's clipboard channel. False when there is nobody to take it.
    bool WriteClipboard(byte[] line)
    {
        lock (sendLock)
        {
            if (clipboard == null) return false;
            try { clipboard.Write(line, 0, line.Length); return true; }
            catch (IOException) { return false; }
            catch (ObjectDisposedException) { return false; }
        }
    }

    void SendClipboard()
    {
        // Files copied in Explorer go over as files; a paste inside finds copies of them.
        StringCollection copied = null;
        try { if (Clipboard.ContainsFileDropList()) copied = Clipboard.GetFileDropList(); }
        catch (ExternalException) { return; }  // another program holds the clipboard open
        if (copied != null && copied.Count > 0)
        {
            var paths = new string[copied.Count];
            copied.CopyTo(paths, 0);
            files.Send(paths);
            return;
        }
        // A picture (Windows' own PrtScr / Snipping Tool, which Windows keeps even while Mentor is
        // full screen) goes over as a PNG: a paste inside Mentor finds it.
        Image picture = null;
        try { if (Clipboard.ContainsImage()) picture = Clipboard.GetImage(); }
        catch (ExternalException) { return; }
        if (picture != null)
        {
            using (picture) SendImage(picture);
            return;
        }
        string text;
        try { text = Clipboard.ContainsText() ? Clipboard.GetText() : null; }
        catch (ExternalException) { return; }  // another program holds the clipboard open
        if (string.IsNullOrEmpty(text) || text == synced) return;
        byte[] line = Encoding.UTF8.GetBytes(json.Serialize(new Dictionary<string, string> { { "text", text } }) + "\n");
        if (line.Length > MaxBytes) return;
        synced = text;
        lock (sendLock)
        {
            if (clipboard == null) return;
            try { clipboard.Write(line, 0, line.Length); }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }
    }

    void SendImage(Image picture)
    {
        byte[] png;
        using (var stream = new MemoryStream())
        {
            try { picture.Save(stream, ImageFormat.Png); }
            catch (ExternalException) { return; }
            png = stream.ToArray();
        }
        if (png.Length == 0 || png.Length > MaxImageBytes) return;
        string print;
        using (var sha = System.Security.Cryptography.SHA256.Create())
            print = Convert.ToBase64String(sha.ComputeHash(png));
        if (print == syncedImage) return;
        syncedImage = print;
        // Written by hand: base64 needs no escaping, and the serializer has a length limit.
        byte[] line = Encoding.ASCII.GetBytes("{\"image\": \"" + Convert.ToBase64String(png) + "\"}\n");
        lock (sendLock)
        {
            if (clipboard == null) return;
            try { clipboard.Write(line, 0, line.Length); }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }
    }

    void SetClipboard(string text)
    {
        if (text == synced) return;
        synced = text;
        try { Clipboard.SetText(text); }
        catch (ExternalException) { }
    }

    // Reads JSON lines from one of QEMU's chardev sockets on a background thread
    // and hands each object to `handle` on the window's thread.
    // `early`, when given, sees each object first, on the reading thread, and may keep it.
    void Listen(int port, Action<NetworkStream> connected, Action<Dictionary<string, object>> handle,
                Func<Dictionary<string, object>, bool> early = null)
    {
        var thread = new Thread(() => {
            TcpClient client = Program.Connect(port);
            if (client == null) return;
            NetworkStream stream = client.GetStream();
            lock (sendLock) connected(stream);
            try
            {
                var reader = new StreamReader(stream, new UTF8Encoding(false));
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    Dictionary<string, object> message;
                    try { message = json.Deserialize<Dictionary<string, object>>(line); }
                    catch (Exception) { continue; }  // not a message of ours
                    if (message != null && (early == null || !early(message))) BeginInvoke((Action)(() => {
                        try { handle(message); }
                        catch (KeyNotFoundException) { }
                    }));
                }
            }
            catch (IOException) { }
            catch (InvalidOperationException) { }  // window already closed
        }) { IsBackground = true };
        thread.Start();
    }
}

// Copied files and folders, both ways, over the clipboard channel. A copy is sent as a
// stream of JSON lines (the same in both directions):
//     {"files": id, "count": n, "bytes": total}
//     {"dir": id, "name": "relative/path"}             for each folder
//     {"file": id, "name": "relative/path", "size": n}
//     {"chunk": id, "data": "<base64>"}                as many as the file needs
//     {"files-end": id}                                or {"files-cancel": id}
// and the receiving side saves them and puts the copies on its own clipboard. Everything
// is sent when it is copied, so there is a limit to how much; {"files-refused": "why"}
// tells the other side that a copy was over it.
class ClipboardFiles
{
    const long MaxBytes = 256L << 20;
    const int MaxCount = 2000, Chunk = 48 * 1024;

    readonly Control window;
    readonly Func<byte[], bool> write;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly string staging = Path.Combine(Path.GetTempPath(), "Mentor", "clipboard");
    int sending;                 // counts copies; a newer one stops the transfer of an older
    string incoming, folder;     // a transfer from the guest under way, and where it is saved
    FileStream file;
    List<string> tops;           // what a paste should find: the first part of each name
    string[] ours = new string[0];  // what was last put on the Windows clipboard from here

    public ClipboardFiles(Control window, Func<byte[], bool> write)
    {
        this.window = window;
        this.write = write;
        try { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    bool Line(Dictionary<string, object> message)
    {
        return write(Encoding.UTF8.GetBytes(json.Serialize(message) + "\n"));
    }

    // Files were copied in Windows: send them, unless they are the ones that came from the guest.
    public void Send(string[] paths)
    {
        if (paths.Length == ours.Length && Array.TrueForAll(paths, path => Array.IndexOf(ours, path) >= 0)) return;
        int mine = Interlocked.Increment(ref sending);
        new Thread(() => {
            try { Transfer(paths, mine); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }) { IsBackground = true }.Start();
    }

    void Transfer(string[] paths, int mine)
    {
        var entries = new List<string[]>();  // path on disk, name for the other side, "d" for a folder
        long total = 0;
        foreach (string top in paths)
        {
            string parent = Path.GetDirectoryName(top.TrimEnd('\\')) ?? "";
            if (Directory.Exists(top))
            {
                entries.Add(new[] { top, Name(top, parent), "d" });
                foreach (string inside in Directory.GetFileSystemEntries(top, "*", SearchOption.AllDirectories))
                    entries.Add(new[] { inside, Name(inside, parent), Directory.Exists(inside) ? "d" : "" });
            }
            else if (File.Exists(top)) entries.Add(new[] { top, Path.GetFileName(top), "" });
        }
        foreach (string[] entry in entries) if (entry[2] == "") total += new FileInfo(entry[0]).Length;
        if (entries.Count == 0) return;
        if (total > MaxBytes || entries.Count > MaxCount)
        {
            Line(new Dictionary<string, object> { { "files-refused",
                "The clipboard carries up to " + (MaxBytes >> 20) + " MB and " + MaxCount + " files at a time." } });
            return;
        }
        string id = Guid.NewGuid().ToString("N").Substring(0, 12);
        if (!Line(new Dictionary<string, object> { { "files", id }, { "count", entries.Count }, { "bytes", total } })) return;
        var buffer = new byte[Chunk];
        foreach (string[] entry in entries)
        {
            bool ok;
            if (entry[2] == "d") ok = Line(new Dictionary<string, object> { { "dir", id }, { "name", entry[1] } });
            else
                using (FileStream source = File.OpenRead(entry[0]))
                {
                    ok = Line(new Dictionary<string, object> { { "file", id }, { "name", entry[1] }, { "size", source.Length } });
                    int read;
                    while (ok && (read = source.Read(buffer, 0, buffer.Length)) > 0)
                        ok = mine == sending && Line(new Dictionary<string, object> {
                            { "chunk", id }, { "data", Convert.ToBase64String(buffer, 0, read) } });
                }
            if (!ok || mine != sending)
            {
                Line(new Dictionary<string, object> { { "files-cancel", id } });
                return;
            }
        }
        Line(new Dictionary<string, object> { { "files-end", id } });
    }

    static string Name(string path, string parent)
    {
        return path.Substring(parent.Length).TrimStart('\\').Replace('\\', '/');
    }

    // A message from the guest, on the reading thread. True when it was about files.
    public bool Receive(Dictionary<string, object> message)
    {
        object value;
        try
        {
            if (message.TryGetValue("files", out value))
            {
                Drop();
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
                catch (IOException) { }
                incoming = value as string;
                folder = Path.Combine(staging, Clean(incoming ?? "x"));
                Directory.CreateDirectory(folder);
                tops = new List<string>();
            }
            else if (message.TryGetValue("files-refused", out value)) { }  // the guest says so itself
            else if (incoming == null) return message.ContainsKey("dir") || message.ContainsKey("file") ||
                message.ContainsKey("chunk") || message.ContainsKey("files-end") || message.ContainsKey("files-cancel");
            else if (message.TryGetValue("dir", out value) && value as string == incoming)
                Directory.CreateDirectory(Place(message["name"] as string));
            else if (message.TryGetValue("file", out value) && value as string == incoming)
            {
                if (file != null) file.Dispose();
                string path = Place(message["name"] as string);
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                file = File.Create(path);
            }
            else if (message.TryGetValue("chunk", out value) && value as string == incoming && file != null)
            {
                byte[] data = Convert.FromBase64String(message["data"] as string);
                file.Write(data, 0, data.Length);
            }
            else if (message.TryGetValue("files-cancel", out value) && value as string == incoming) Drop();
            else if (message.TryGetValue("files-end", out value) && value as string == incoming)
            {
                if (file != null) file.Dispose();
                file = null;
                incoming = null;
                string[] arrived = tops.ToArray();
                if (arrived.Length > 0) window.BeginInvoke((Action)(() => {
                    var list = new StringCollection();
                    list.AddRange(arrived);
                    ours = arrived;
                    try { Clipboard.SetFileDropList(list); }
                    catch (ExternalException) { }
                }));
            }
            else return false;
        }
        catch (IOException) { Drop(); }
        catch (UnauthorizedAccessException) { Drop(); }
        catch (ArgumentException) { Drop(); }
        catch (FormatException) { Drop(); }
        catch (KeyNotFoundException) { Drop(); }
        return true;
    }

    void Drop()
    {
        if (file != null) file.Dispose();
        file = null;
        incoming = null;
    }

    static string Clean(string part)
    {
        foreach (char c in Path.GetInvalidFileNameChars()) part = part.Replace(c, '_');
        return part;
    }

    // Where a file of that (relative) name goes. Never outside the folder of this transfer.
    string Place(string name)
    {
        var parts = new List<string>();
        foreach (string part in (name ?? "").Replace('\\', '/').Split('/'))
            if (part != "" && part != "." && part != "..") parts.Add(Clean(part));
        if (parts.Count == 0) throw new ArgumentException(name);
        string top = Path.Combine(folder, parts[0]);
        if (!tops.Contains(top)) tops.Add(top);
        return Path.Combine(folder, string.Join("\\", parts));
    }
}

// Shown while a graphics-card start waits with its window minimized: the emblem and a word,
// in a small window of its own, or on a black screen when the system will open in full screen.
class StartSplash : Form
{
    public StartSplash(bool fullscreen)
    {
        Text = "Mentor";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        ShowInTaskbar = false;
        BackColor = Color.Black;
        AutoScaleMode = AutoScaleMode.None;
        ClientSize = new Size(420, 420);
        var content = new Panel { Left = 0, Top = 0, Width = 420, Height = 420, BackColor = Color.Black };
        var emblem = new PictureBox { Left = 90, Top = 70, Width = 240, Height = 240, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.Black };
        try { emblem.Image = Image.FromStream(typeof(StartSplash).Assembly.GetManifestResourceStream("emblem.png")); }
        catch (Exception) { }
        var text = new Label { Text = "Starting\u2026", Left = 0, Top = 330, Width = 420, Height = 30, ForeColor = Theme.Dim,
                               BackColor = Color.Black, TextAlign = ContentAlignment.MiddleCenter, Font = Theme.Font(11f, FontStyle.Regular) };
        content.Controls.AddRange(new Control[] { emblem, text });
        Controls.Add(content);
        Theme.Fit(this);
        if (fullscreen)
        {
            Rectangle screen = Screen.PrimaryScreen.Bounds;
            StartPosition = FormStartPosition.Manual;
            Bounds = screen;
            content.Location = new Point((screen.Width - content.Width) / 2, (screen.Height - content.Height) / 2);
        }
    }

    // It is there to be seen, not to take the keyboard from whatever the user is doing.
    protected override bool ShowWithoutActivation { get { return true; } }
}

// QEMU's window. Full screen is QEMU's own (its Ctrl+Alt+F), so GTK lays the
// display out properly; the launcher only presses that key for it.
static class VmWindow
{
    const int GWL_STYLE = -16;
    const long WS_CAPTION = 0x00C00000;
    const byte VK_CONTROL = 0x11, VK_MENU = 0x12, VK_F = 0x46;
    const uint KEYEVENTF_KEYUP = 2;

    [DllImport("user32.dll")] static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint mapType);

    // With the key's scan code: QEMU's SDL window (--gpu) goes by that, not by the key's name.
    static void Key(byte key, bool down)
    {
        keybd_event(key, (byte)MapVirtualKey(key, 0), down ? 0 : KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int how);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);

    public static void KeepMinimized(Process qemu)
    {
        IntPtr hwnd = Find(qemu);
        if (hwnd != IntPtr.Zero && !IsIconic(hwnd)) ShowWindow(hwnd, 7);  // SW_SHOWMINNOACTIVE
    }

    [StructLayout(LayoutKind.Sequential)] struct Edges { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd, out Edges edges);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd, out Edges edges);

    // The size of the picture in a window of a proper size: four fifths of the screen, 16:10,
    // its sides multiples of four.
    public static Size Picture()
    {
        Rectangle area = Screen.PrimaryScreen.WorkingArea;
        int width = Math.Min(area.Width * 8 / 10, area.Height * 8 / 10 * 16 / 10) / 4 * 4;
        return new Size(width, width * 10 / 16 / 4 * 4);
    }

    // Gives the window that size, in the middle of the screen. The guest's resolution follows
    // the window. False when there is no window yet.
    public static bool Resize(Process qemu)
    {
        IntPtr hwnd = Find(qemu);
        Edges outer, inner;
        if (hwnd == IntPtr.Zero || !GetWindowRect(hwnd, out outer) || !GetClientRect(hwnd, out inner)) return false;
        int frameWidth = (outer.Right - outer.Left) - inner.Right, frameHeight = (outer.Bottom - outer.Top) - inner.Bottom;
        Rectangle area = Screen.PrimaryScreen.WorkingArea;
        int width = Picture().Width, height = Picture().Height;
        if (inner.Right == width && inner.Bottom == height) return true;  // it has it already
        SetWindowPos(hwnd, IntPtr.Zero, area.Left + (area.Width - width - frameWidth) / 2,
                     area.Top + (area.Height - height - frameHeight) / 2, width + frameWidth, height + frameHeight, 0x0004);
        return true;
    }

    // After the user has resized the window: its picture back to even sides, a pixel smaller at most.
    public static void KeepEven(Process qemu)
    {
        IntPtr hwnd = Find(qemu);
        Edges outer, inner;
        if (hwnd == IntPtr.Zero || IsIconic(hwnd) || !GetWindowRect(hwnd, out outer) || !GetClientRect(hwnd, out inner)) return;
        if (inner.Right % 2 == 0 && inner.Bottom % 2 == 0) return;
        SetWindowPos(hwnd, IntPtr.Zero, 0, 0, (outer.Right - outer.Left) - inner.Right % 2,
                     (outer.Bottom - outer.Top) - inner.Bottom % 2, 0x0006);  // SWP_NOMOVE | SWP_NOZORDER
    }

    public static void Restore(Process qemu)
    {
        IntPtr hwnd = Find(qemu);
        if (hwnd == IntPtr.Zero) return;
        if (IsIconic(hwnd)) ShowWindow(hwnd, 9);  // SW_RESTORE
        // A window that was born minimized comes up small.
        Resize(qemu);
        SetForegroundWindow(hwnd);
        Thread.Sleep(300);  // let it settle before any key is sent to it
    }

    public static IntPtr Find(Process qemu)
    {
        if (qemu.HasExited) return IntPtr.Zero;
        qemu.Refresh();
        return qemu.MainWindowHandle;
    }

    // A full-screen GTK window has no title bar.
    public static bool IsFullscreen(Process qemu)
    {
        IntPtr hwnd = Find(qemu);
        return hwnd != IntPtr.Zero && (GetWindowLongPtr(hwnd, GWL_STYLE).ToInt64() & WS_CAPTION) == 0;
    }

    public static void SetFullscreen(Process qemu, bool on)
    {
        IntPtr hwnd = Find(qemu);
        if (hwnd == IntPtr.Zero || on == IsFullscreen(qemu)) return;
        // Windows only lets a process that just produced input take the foreground,
        // so the modifiers go down first and F follows once QEMU has the focus.
        Key(VK_CONTROL, true);
        Key(VK_MENU, true);
        SetForegroundWindow(hwnd);
        Thread.Sleep(150);
        Key(VK_F, true);
        Thread.Sleep(30);
        foreach (byte key in new[] { VK_F, VK_MENU, VK_CONTROL }) Key(key, false);
    }
}

// QEMU's monitor (QMP): why the VM stopped, and commands to it.
class Qmp
{
    readonly int port;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly object sendLock = new object();
    readonly Queue<Dictionary<string, object>> answers = new Queue<Dictionary<string, object>>();
    NetworkStream stream;
    bool closed;

    // From {"event": "SHUTDOWN", "data": {"reason": ...}}: guest-reset, guest-shutdown, host-ui, ...
    public volatile string StopReason;
    public readonly Thread Reader;

    public Qmp(int port)
    {
        this.port = port;
        Reader = new Thread(Read) { IsBackground = true };
        Reader.Start();
    }

    void Read()
    {
        try
        {
            using (TcpClient client = Program.Connect(port))
            {
                if (client == null) return;
                var reader = new StreamReader(client.GetStream());
                reader.ReadLine();  // greeting
                byte[] hello = Encoding.ASCII.GetBytes("{\"execute\": \"qmp_capabilities\"}\n");
                lock (sendLock)
                {
                    client.GetStream().Write(hello, 0, hello.Length);
                    stream = client.GetStream();
                }
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    Dictionary<string, object> message;
                    try { message = json.Deserialize<Dictionary<string, object>>(line); }
                    catch (Exception) { continue; }
                    if (message == null) continue;
                    object name, data, reason;
                    if (message.TryGetValue("event", out name))
                    {
                        if (name as string == "SHUTDOWN" && message.TryGetValue("data", out data) &&
                            data is Dictionary<string, object> &&
                            ((Dictionary<string, object>)data).TryGetValue("reason", out reason))
                            StopReason = reason as string;
                    }
                    else lock (answers) { answers.Enqueue(message); Monitor.PulseAll(answers); }
                }
            }
        }
        catch (IOException) { }
        finally
        {
            lock (answers) { closed = true; Monitor.PulseAll(answers); }
        }
    }

    // Runs one command. Returns null when it worked, otherwise what went wrong.
    public string Execute(string command, Dictionary<string, object> arguments, int timeoutMs)
    {
        lock (sendLock)
        {
            if (stream == null) return "QEMU is not reachable";
            lock (answers) answers.Clear();
            var request = new Dictionary<string, object> { { "execute", command } };
            if (arguments != null) request["arguments"] = arguments;
            byte[] line = Encoding.UTF8.GetBytes(json.Serialize(request) + "\n");
            try { stream.Write(line, 0, line.Length); }
            catch (IOException e) { return e.Message; }
            catch (ObjectDisposedException) { return "QEMU is not reachable"; }  // it has just stopped
            lock (answers)
            {
                DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
                while (answers.Count == 0)
                {
                    int left = (int)(end - DateTime.UtcNow).TotalMilliseconds;
                    if (closed || left <= 0) return "QEMU did not answer";
                    Monitor.Wait(answers, left);
                }
                Dictionary<string, object> answer = answers.Dequeue();
                object error, description;
                if (!answer.TryGetValue("error", out error)) return null;
                var details = error as Dictionary<string, object>;
                return details != null && details.TryGetValue("desc", out description) ? description as string : "QEMU refused";
            }
        }
    }
}

// Whether the system inside finishes starting. It says so itself over the control
// channel: "ok" once the desktop is up, "trial" when the start tries a change (it
// then looks after itself), "restoring" when it is undoing one. A start that ends
// without a word counts as failed; two of those and a restore point is offered.
// Only for a system that has reported at least once: an older image never does.
class BootWatch
{
    readonly string enabledFile, failuresFile;

    public BootWatch(string vmDir)
    {
        enabledFile = Path.Combine(vmDir, "boot-reports");
        failuresFile = Path.Combine(vmDir, "boot-failures");
    }

    public bool Enabled { get { return File.Exists(enabledFile); } }
    public bool Explained { get; private set; }

    public int Failures
    {
        get
        {
            int count;
            try { return int.TryParse(File.ReadAllText(failuresFile), out count) ? count : 0; }
            catch (IOException) { return 0; }
        }
        set
        {
            if (value == 0) File.Delete(failuresFile);
            else File.WriteAllText(failuresFile, value.ToString());
        }
    }

    public void Begin() { Explained = false; }

    public void Signal(string how)
    {
        Explained = true;
        if (how != "ok") return;
        if (!Enabled) File.WriteAllText(enabledFile, "");
        Failures = 0;
    }

    // `reason` is why QEMU stopped. Closing the window (host-ui) is the user's doing.
    public void End(string reason, bool timedOut)
    {
        if (!Enabled || Explained) return;
        if (timedOut || reason == "guest-reset" || reason == "guest-panic" || reason == "guest-shutdown")
            Failures = Failures + 1;
    }
}

class RestorePoint
{
    public string name, time, reason;
}

// Snapshots of the VM's disk, kept inside the disk file itself (qcow2), with the
// firmware's variables next to it. Taken while the VM runs, restored while it is stopped.
class RestorePoints
{
    const int Keep = 3;
    readonly string qemuImg, disk, vars, dir, listFile;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();

    public RestorePoints(string qemuImg, string vmDir, string disk, string vars)
    {
        this.qemuImg = qemuImg;
        this.disk = disk;
        this.vars = vars;
        dir = Path.Combine(vmDir, "restore");
        listFile = Path.Combine(dir, "points.json");
    }

    // Oldest first.
    public List<RestorePoint> List()
    {
        try { return json.Deserialize<List<RestorePoint>>(File.ReadAllText(listFile)) ?? new List<RestorePoint>(); }
        catch (IOException) { return new List<RestorePoint>(); }
        catch (ArgumentException) { return new List<RestorePoint>(); }
        catch (InvalidOperationException) { return new List<RestorePoint>(); }
    }

    void Save(List<RestorePoint> all)
    {
        Directory.CreateDirectory(dir);
        File.WriteAllText(listFile, json.Serialize(all));
    }

    public RestorePoint Newest
    {
        get { List<RestorePoint> all = List(); return all.Count == 0 ? null : all[all.Count - 1]; }
    }

    public bool NewestIsOlderThan(TimeSpan age)
    {
        RestorePoint newest = Newest;
        DateTime taken;
        return newest == null || !DateTime.TryParse(newest.time, out taken) || DateTime.Now - taken > age;
    }

    string VarsOf(RestorePoint point) { return Path.Combine(dir, point.name + ".fd"); }

    // Of the running VM. Returns null when it worked, otherwise what went wrong.
    public string Create(Qmp qmp, string reason)
    {
        var point = new RestorePoint {
            name = "rp-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"),
            time = DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
            reason = reason,
        };
        string error = qmp.Execute("blockdev-snapshot-internal-sync",
            new Dictionary<string, object> { { "device", "disk" }, { "name", point.name } }, 120000);
        if (error != null) return error;
        Directory.CreateDirectory(dir);
        try { File.Copy(vars, VarsOf(point), true); }
        catch (IOException) { }  // the disk is what matters
        List<RestorePoint> all = List();
        all.Add(point);
        Save(all);
        return null;
    }

    // Only while the VM is stopped. Returns null when it worked, otherwise what went wrong.
    public string Restore(RestorePoint point)
    {
        string error;
        if (Program.RunHidden(qemuImg, "snapshot -a " + point.name + " " + Program.Quote(disk), out error) != 0)
            return error.Trim();
        try { if (File.Exists(VarsOf(point))) File.Copy(VarsOf(point), vars, true); }
        catch (IOException) { }
        return null;
    }

    // Drops all but the newest few. Only while the VM is stopped.
    public void Trim()
    {
        List<RestorePoint> all = List();
        if (all.Count <= Keep) return;
        while (all.Count > Keep)
        {
            string error;
            Program.RunHidden(qemuImg, "snapshot -d " + all[0].name + " " + Program.Quote(disk), out error);
            File.Delete(VarsOf(all[0]));
            all.RemoveAt(0);
        }
        Save(all);
    }
}

static class RestoreDialog
{
    // The restore point the user picked, or null when they chose `otherwise`.
    public static RestorePoint Ask(string message, List<RestorePoint> points, string otherwise)
    {
        var newestFirst = new List<RestorePoint>(points);
        newestFirst.Reverse();
        using (var form = new Form {
            Text = "Mentor", AutoScaleMode = AutoScaleMode.None,
            ClientSize = new Size(560, 330), FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterScreen, MinimizeBox = false, MaximizeBox = false, TopMost = true,
            BackColor = Theme.Back, ForeColor = Theme.Text, Font = Theme.Font(9.5f, FontStyle.Regular),
        })
        {
            Theme.Dress(form);
            var text = new Label { Text = message, Left = 22, Top = 18, Width = 516, Height = 84 };
            var list = new ListBox { Left = 22, Top = 106, Width = 516, Height = 150, IntegralHeight = false,
                                     BackColor = Theme.Card, ForeColor = Theme.Text, BorderStyle = BorderStyle.None,
                                     ItemHeight = 26, DrawMode = DrawMode.OwnerDrawFixed };
            list.DrawItem += (s, e) => {
                if (e.Index < 0) return;
                bool selected = (e.State & DrawItemState.Selected) != 0;
                using (var back = new SolidBrush(selected ? Theme.Accent : Theme.Card)) e.Graphics.FillRectangle(back, e.Bounds);
                TextRenderer.DrawText(e.Graphics, (string)list.Items[e.Index], list.Font, e.Bounds, Theme.Text,
                                      TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis);
            };
            foreach (RestorePoint point in newestFirst) list.Items.Add("  " + point.time + "      " + point.reason);
            list.SelectedIndex = 0;
            var restore = new PillButton { Text = "Go back to it", Primary = true, Result = DialogResult.OK,
                                           Left = 282, Top = 274, Width = 124, Height = 36 };
            var skip = new PillButton { Text = otherwise, Result = DialogResult.Cancel,
                                        Left = 414, Top = 274, Width = 124, Height = 36 };
            form.Controls.AddRange(new Control[] { text, list, restore, skip });
            list.ItemHeight = (int)(list.ItemHeight * Theme.Fit(form));
            return form.ShowDialog() == DialogResult.OK ? newestFirst[list.SelectedIndex] : null;
        }
    }
}

// What the launcher window remembers between starts.
class Settings
{
    public int memory, cpus;
    public bool gpu, vulkan;
    string path;

    public static Settings Load(string path)
    {
        Settings settings = null;
        try { settings = new JavaScriptSerializer().Deserialize<Settings>(File.ReadAllText(path)); }
        catch (IOException) { }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
        if (settings == null) settings = new Settings();
        settings.path = path;
        return settings;
    }

    public void Save()
    {
        var values = new Dictionary<string, object> { { "memory", memory }, { "cpus", cpus }, { "gpu", gpu }, { "vulkan", vulkan } };
        try { File.WriteAllText(path, new JavaScriptSerializer().Serialize(values)); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}

// An on/off switch.
class Toggle : Painted
{
    bool on;
    public event EventHandler CheckedChanged;
    public bool Checked
    {
        get { return on; }
        set
        {
            if (on == value) return;
            on = value;
            Invalidate();
            if (CheckedChanged != null) CheckedChanged(this, EventArgs.Empty);
        }
    }

    public Toggle() { Cursor = Cursors.Hand; }

    protected override void OnClick(EventArgs e) { Checked = !Checked; Focus(); base.OnClick(e); }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Space) Checked = !Checked;
        base.OnKeyDown(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = Begin(e);
        var area = new RectangleF(0.5f, 0.5f, Width - 1, Height - 1);
        using (GraphicsPath shape = Theme.Round(area, Height / 2f))
        using (var fill = new SolidBrush(on ? Theme.Accent : Theme.Track))
        {
            g.FillPath(fill, shape);
            if (Focused) using (var edge = new Pen(Theme.AccentHot)) g.DrawPath(edge, shape);
        }
        float knob = Height - 6f;
        g.FillEllipse(Brushes.White, on ? Width - knob - 3f : 3f, 3f, knob, knob);
    }
}

// A slider for a whole number: drag, click, or the arrow keys.
class Slider : Painted
{
    public int Minimum = 0, Maximum = 10;
    int current;
    public event EventHandler ValueChanged;

    public int Value
    {
        get { return current; }
        set
        {
            int clamped = Math.Max(Minimum, Math.Min(Maximum, value));
            if (clamped == current) return;
            current = clamped;
            Invalidate();
            if (ValueChanged != null) ValueChanged(this, EventArgs.Empty);
        }
    }

    public Slider() { Cursor = Cursors.Hand; }

    float Knob { get { return Height * 0.72f; } }

    void Follow(int x)
    {
        float span = Width - Knob;
        Value = Minimum + (int)Math.Round((x - Knob / 2f) / span * (Maximum - Minimum));
    }

    protected override void OnMouseDown(MouseEventArgs e) { Focus(); Capture = true; Follow(e.X); base.OnMouseDown(e); }
    protected override void OnMouseMove(MouseEventArgs e) { if (Capture && e.Button == MouseButtons.Left) Follow(e.X); base.OnMouseMove(e); }
    protected override void OnMouseUp(MouseEventArgs e) { Capture = false; base.OnMouseUp(e); }
    protected override bool IsInputKey(Keys key) { return key == Keys.Left || key == Keys.Right || base.IsInputKey(key); }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Left) Value = Value - 1;
        if (e.KeyCode == Keys.Right) Value = Value + 1;
        base.OnKeyDown(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = Begin(e);
        float knob = Knob, thick = Height * 0.22f, middle = Height / 2f;
        float at = Maximum == Minimum ? 0 : (float)(current - Minimum) / (Maximum - Minimum) * (Width - knob);
        using (GraphicsPath track = Theme.Round(new RectangleF(knob / 2f - thick / 2f, middle - thick / 2f, Width - knob + thick, thick), thick / 2f))
        using (var fill = new SolidBrush(Theme.Track)) g.FillPath(fill, track);
        using (GraphicsPath done = Theme.Round(new RectangleF(knob / 2f - thick / 2f, middle - thick / 2f, at + thick, thick), thick / 2f))
        using (var fill = new SolidBrush(Theme.Accent)) g.FillPath(fill, done);
        g.FillEllipse(Brushes.White, at, middle - knob / 2f, knob, knob);
        if (Focused) using (var ring = new Pen(Theme.AccentHot, 2f)) g.DrawEllipse(ring, at + 1f, middle - knob / 2f + 1f, knob - 2f, knob - 2f);
    }
}

// The window a double click on Mentor.exe opens: start, with the few choices worth having at hand.
class LauncherWindow : Form
{
    [StructLayout(LayoutKind.Sequential)]
    struct MemoryStatus
    {
        public uint length, load;
        public ulong totalPhysical, availablePhysical, totalPageFile, availablePageFile, totalVirtual, availableVirtual, extended;
    }
    [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);

    readonly Toggle gpu = new Toggle(), fullscreen = new Toggle(), vulkan = new Toggle();
    readonly Slider memory = new Slider(), cpus = new Slider();

    public bool Gpu { get { return gpu.Checked; } }
    public bool Vulkan { get { return vulkan.Checked && gpu.Checked; } }
    public bool Fullscreen { get { return fullscreen.Checked; } }
    public bool Repair { get; private set; }
    public int Memory { get { return memory.Value; } }
    public int Cpus { get { return cpus.Value; } }

    static Label Words(string text, int left, int top, int width, float size, Color colour, bool onCard)
    {
        return new Label { Text = text, Left = left, Top = top, Width = width, Height = (int)(size * 2.3f), ForeColor = colour,
                           BackColor = onCard ? Theme.Card : Theme.Back, Font = Theme.Font(size, FontStyle.Regular) };
    }

    public LauncherWindow(int memoryGB, int cpuCount, bool useGpu, bool useVulkan, bool own,
                          bool startFullscreen, RestorePoints points, BootWatch watch, string vmDir, string image)
    {
        Text = "Mentor";
        AutoScaleMode = AutoScaleMode.None;  // sized by Theme.Fit, below
        int more = own ? 62 : 0;  // the Vulkan row
        ClientSize = new Size(440, 668 + more);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        StartPosition = FormStartPosition.CenterScreen;
        MaximizeBox = false;
        BackColor = Theme.Back;
        ForeColor = Theme.Text;
        Font = Theme.Font(9.5f, FontStyle.Regular);
        KeyPreview = true;
        Theme.Dress(this);

        var emblem = new PictureBox { Left = 170, Top = 24, Width = 100, Height = 100, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Theme.Back };
        try { emblem.Image = Image.FromStream(typeof(LauncherWindow).Assembly.GetManifestResourceStream("emblem.png")); }
        catch (Exception) { }
        var title = new Label { Text = "Mentor", Left = 0, Top = 130, Width = 440, Height = 40, TextAlign = ContentAlignment.MiddleCenter,
                                Font = Theme.Font(20f, FontStyle.Bold), ForeColor = Theme.Text, BackColor = Theme.Back };
        var subtitle = new Label { Text = "Agentic Linux", Left = 0, Top = 170, Width = 440, Height = 22, TextAlign = ContentAlignment.MiddleCenter,
                                   ForeColor = Theme.Dim, BackColor = Theme.Back };
        var start = new PillButton { Text = "Start Mentor", Primary = true, Result = DialogResult.OK,
                                     Left = 28, Top = 210, Width = 384, Height = 52, Font = Theme.Font(12f, FontStyle.Bold) };

        var card = new Card { Left = 28, Top = 282, Width = 384, Height = 262 + more };
        gpu.Checked = useGpu;
        vulkan.Checked = useVulkan;
        fullscreen.Checked = startFullscreen;
        foreach (Painted control in new Painted[] { gpu, vulkan, fullscreen, memory, cpus }) control.BackColor = Theme.Card;
        gpu.SetBounds(322, 22, 44, 24);
        vulkan.SetBounds(322, 84, 44, 24);
        vulkan.Visible = own;
        vulkan.Enabled = gpu.Checked;  // it is drawn by the graphics card or not at all
        gpu.CheckedChanged += (s, e) => vulkan.Enabled = gpu.Checked;
        fullscreen.SetBounds(322, 84 + more, 44, 24);

        MemoryStatus status = new MemoryStatus { length = 64 };
        int hostGB = GlobalMemoryStatusEx(ref status) ? (int)(status.totalPhysical >> 30) + 1 : 16;
        memory.Minimum = 2;
        memory.Maximum = Math.Max(4, Math.Min(64, hostGB * 3 / 4));
        memory.Value = memoryGB;
        cpus.Minimum = 1;
        cpus.Maximum = Environment.ProcessorCount;
        cpus.Value = cpuCount;
        memory.SetBounds(16, 162 + more, 352, 26);
        cpus.SetBounds(16, 222 + more, 352, 26);
        Label memoryValue = Words("", 266, 138 + more, 100, 9.5f, Theme.Text, true);
        Label cpuValue = Words("", 266, 198 + more, 100, 9.5f, Theme.Text, true);
        memoryValue.TextAlign = cpuValue.TextAlign = ContentAlignment.TopRight;
        EventHandler show = (s, e) => {
            memoryValue.Text = memory.Value + " GB";
            cpuValue.Text = cpus.Value + " of " + Environment.ProcessorCount;
        };
        memory.ValueChanged += show;
        cpus.ValueChanged += show;
        show(null, EventArgs.Empty);

        card.Controls.AddRange(new Control[] {
            Words("Graphics card", 18, 14, 290, 10.5f, Theme.Text, true),
            Words(own ? "Smoother desktop, drawn by the graphics card." : "Smoother desktop. Experimental.",
                  18, 37, 300, 8.5f, Theme.Dim, true), gpu,
            new Label { Left = 18, Top = 68, Width = 348, Height = 1, BackColor = Theme.Line },
            Words("Full screen", 18, 76 + more, 290, 10.5f, Theme.Text, true),
            Words("Ctrl+Alt+F switches at any time.", 18, 99 + more, 290, 8.5f, Theme.Dim, true), fullscreen,
            new Label { Left = 18, Top = 130 + more, Width = 348, Height = 1, BackColor = Theme.Line },
            Words("Memory", 18, 138 + more, 200, 10.5f, Theme.Text, true), memoryValue, memory,
            Words("Processors", 18, 198 + more, 200, 10.5f, Theme.Text, true), cpuValue, cpus,
        });
        if (own)
            card.Controls.AddRange(new Control[] {
                Words("Vulkan", 18, 76, 290, 10.5f, Theme.Text, true),
                Words("For apps and games that draw with Vulkan. Experimental.", 18, 99, 300, 8.5f, Theme.Dim, true), vulkan,
                new Label { Left = 18, Top = 130, Width = 348, Height = 1, BackColor = Theme.Line },
            });

        var restore = new PillButton { Text = "Restore points", Left = 28, Top = 562 + more, Width = 186, Height = 38 };
        var fresh = new PillButton { Text = "Start over", Left = 226, Top = 562 + more, Width = 186, Height = 38 };
        var mend = new PillButton { Text = "Repair", Left = 28, Top = 608 + more, Width = 186, Height = 38 };
        var reinstall = new PillButton { Text = "Reinstall", Left = 226, Top = 608 + more, Width = 186, Height = 38 };

        reinstall.Click += (s, e) => {
            if (MessageBox.Show(this, "Reinstall Mentor from GitHub?\n\n" +
                    "The newest Mentor is downloaded (about 2.3 GB) and put in place of this one.\n\n" +
                    "Everything inside Mentor is deleted: your files in it, installed apps, settings, conversations, " +
                    "recipes, the sign-ins to Claude, ChatGPT and Gemini, the NVIDIA key, and all restore points. " +
                    "Copy anything you want to keep to Windows first.\n\n" +
                    "Your files on Windows are not touched. Nothing is deleted until the download has arrived whole: " +
                    "if it is stopped or fails, Mentor stays as it is.",
                    Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                return;
            if (Reinstall.Run(this, image, vmDir))
            {
                watch.Failures = 0;
                MessageBox.Show(this, "Done. Mentor is the newest one now, and starts fresh: press Start Mentor.", Text);
            }
        };

        mend.Click += (s, e) => {
            if (MessageBox.Show(this, "Start Mentor in repair mode?\n\nFor when the desktop no longer comes up, or something " +
                    "of Mentor's own is broken. The desktop is not started: you get a text screen where you talk to the " +
                    "assistant, and it works from its instructions to find what is broken and mend it. Nothing is changed " +
                    "without your say.\n\nType /restart there to start Mentor normally again.",
                    Text, MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK)
                return;
            Repair = true;
            DialogResult = DialogResult.OK;
        };

        restore.Click += (s, e) => {
            List<RestorePoint> all = points.List();
            if (all.Count == 0)
            {
                MessageBox.Show(this, "There are no restore points yet.\n\nOne is made before every change the " +
                    "assistant applies to the system, and once a day after a start that worked.", Text);
                return;
            }
            RestorePoint chosen = RestoreDialog.Ask(
                "Go back to a restore point. Mentor's whole disk becomes what it was at that moment: " +
                "everything changed inside Mentor since then is lost.", all, "Cancel");
            if (chosen == null) return;
            string error = points.Restore(chosen);
            if (error != null)
                MessageBox.Show(this, "Could not go back:\n\n" + error + "\n\nIf Mentor is running, close it first.",
                                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            else
            {
                watch.Failures = 0;
                MessageBox.Show(this, "Mentor is as it was on " + chosen.time + ".", Text);
            }
        };
        fresh.Click += (s, e) => {
            if (MessageBox.Show(this, "Start over from the system as it was built?\n\nEverything inside Mentor is " +
                    "deleted: installed apps, files, settings, the sign-in to Claude and all restore points.",
                    Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                return;
            try
            {
                if (Directory.Exists(vmDir)) Directory.Delete(vmDir, true);
                MessageBox.Show(this, "Done. The next start is a fresh system.", Text);
            }
            catch (IOException error)
            {
                MessageBox.Show(this, "Could not delete it:\n\n" + error.Message + "\n\nIf Mentor is running, close it first.",
                                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        };

        Controls.AddRange(new Control[] { emblem, title, subtitle, start, card, restore, fresh, mend, reinstall });
        Theme.Fit(this);
        ActiveControl = start;
        KeyDown += (s, e) => {
            if (e.KeyCode == Keys.Escape) Close();
            if (e.KeyCode == Keys.Enter && !(ActiveControl is PillButton)) DialogResult = DialogResult.OK;
        };
    }
}

// "Reinstall" in the launcher window: the newest Mentor from GitHub in place of the one here. The
// system image is downloaded beside the old one (resumed when the connection drops: GitHub ends
// long downloads now and then), checked against the size and SHA-256 that release.json gives,
// and only then is the old installation deleted (vm\: the disk with everything done inside
// Mentor, and the restore points) and the new image put in its place. Cancelled or failed, the
// old one is left exactly as it was.
class Reinstall : Form
{
    // MENTOR_RELEASE: another address to fetch the release from (a test server).
    static readonly string Release = Environment.GetEnvironmentVariable("MENTOR_RELEASE") ??
                                     "https://github.com/Hnd-VXD/Mentor_OS/releases/latest/download/";
    readonly string image, vmDir, partial;
    readonly Label words = new Label();
    readonly ProgressBar bar = new ProgressBar { Minimum = 0, Maximum = 1000 };
    readonly PillButton cancel = new PillButton { Text = "Cancel" };
    volatile bool cancelled;
    public string Error;

    Reinstall(string image, string vmDir)
    {
        this.image = image;
        this.vmDir = vmDir;
        partial = image + ".download";
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
        words.Text = "Asking GitHub for the newest Mentor…";
        bar.SetBounds(28, 76, 384, 14);
        cancel.SetBounds(276, 112, 136, 38);
        cancel.Click += (s, e) => { cancelled = true; cancel.Enabled = false; words.Text = "Stopping…"; };
        FormClosing += (s, e) => { if (e.CloseReason == CloseReason.UserClosing && cancel.Enabled) { cancelled = true; e.Cancel = true; } };
        Controls.AddRange(new Control[] { words, bar, cancel });
        Theme.Fit(this);
        Shown += (s, e) => new Thread(Work) { IsBackground = true }.Start();
    }

    // True when the new Mentor is in place.
    public static bool Run(IWin32Window owner, string image, string vmDir)
    {
        using (var form = new Reinstall(image, vmDir))
        {
            form.ShowDialog(owner);
            if (form.Error != null)
                MessageBox.Show(owner, form.Error, "Mentor", MessageBoxButtons.OK,
                                form.cancelled ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
            return form.Error == null;
        }
    }

    void Say(string text, long done, long size)
    {
        BeginInvoke((MethodInvoker)(() => {
            words.Text = text;
            bar.Value = size > 0 ? (int)Math.Min(1000, done * 1000 / size) : 0;
        }));
    }

    void Finish(string error)
    {
        Error = error;
        BeginInvoke((MethodInvoker)(() => { cancel.Enabled = false; Close(); }));
    }

    static HttpWebResponse Get(string name, long from)
    {
        var request = (HttpWebRequest)WebRequest.Create(Release + name);
        request.UserAgent = "Mentor";
        request.ReadWriteTimeout = 60000;
        request.Timeout = 60000;
        if (from > 0) request.AddRange(from);
        return (HttpWebResponse)request.GetResponse();
    }

    void Work()
    {
        try
        {
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;  // TLS 1.2
            Dictionary<string, object> release;
            using (HttpWebResponse response = Get("release.json", 0))
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                release = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
            var info = release != null && release.ContainsKey("image") ? release["image"] as Dictionary<string, object> : null;
            if (info == null) { Finish("The release on GitHub does not say what it holds. Nothing was changed."); return; }
            long size = Convert.ToInt64(info["size"]);
            string wanted = (info["sha256"] as string ?? "").ToLowerInvariant();
            var parts = new List<string>();
            foreach (object part in (System.Collections.IEnumerable)info["parts"]) parts.Add(Path.GetFileName(part as string));

            long free = new DriveInfo(Path.GetPathRoot(image)).AvailableFreeSpace;
            long have = File.Exists(partial) ? new FileInfo(partial).Length : 0;
            if (free + have < size + (512L << 20))
            {
                Finish("There is not enough free space on " + Path.GetPathRoot(image) + " for the download: it needs " +
                       (size >> 30) + "." + ((size >> 20) % 1024 * 10 / 1024) + " GB and a little more. Nothing was changed.");
                return;
            }

            // The parts one after the other into one file, each resumed where it stopped.
            if (File.Exists(partial)) File.Delete(partial);  // an earlier attempt may have been another release
            var buffer = new byte[1 << 20];
            using (var file = new FileStream(partial, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                foreach (string part in parts)
                {
                    long start = file.Length, length = -1;
                    for (int attempt = 1; ; attempt++)
                    {
                        if (cancelled) throw new OperationCanceledException();
                        long got = file.Length - start;
                        if (length >= 0 && got >= length) break;
                        try
                        {
                            using (HttpWebResponse response = Get(part, got))
                            using (Stream from = response.GetResponseStream())
                            {
                                if (got > 0 && response.StatusCode != HttpStatusCode.PartialContent)
                                {   // it sent the whole part again: start the part over
                                    file.SetLength(start);
                                    file.Position = start;
                                    got = 0;
                                }
                                if (length < 0) length = got + response.ContentLength;
                                int read;
                                while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
                                {
                                    if (cancelled) throw new OperationCanceledException();
                                    file.Write(buffer, 0, read);
                                    Say("Downloading the newest Mentor: " + (file.Length >> 20) + " of " + (size >> 20) + " MB",
                                        file.Length, size);
                                }
                            }
                        }
                        catch (Exception e)
                        {
                            if (!(e is IOException || e is WebException) || attempt >= 30) throw;
                            Say("The connection dropped; going on where it stopped…", file.Length, size);
                            Thread.Sleep(Math.Min(10, attempt) * 1000);
                        }
                    }
                }
            }

            Say("Checking that it arrived whole…", size, size);
            string got256;
            using (var sha = System.Security.Cryptography.SHA256.Create())
            using (var file = File.OpenRead(partial))
                got256 = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
            if (new FileInfo(partial).Length != size || (wanted != "" && got256 != wanted))
            {
                File.Delete(partial);
                Finish("The download did not arrive whole. Nothing was changed; try again.");
                return;
            }

            // Only now is the old installation taken away.
            Say("Putting the new Mentor in place…", size, size);
            if (Directory.Exists(vmDir)) Directory.Delete(vmDir, true);
            if (File.Exists(image)) File.Delete(image);
            File.Move(partial, image);
            Finish(null);
        }
        catch (OperationCanceledException)
        {
            try { if (File.Exists(partial)) File.Delete(partial); } catch (IOException) { }
            cancelled = true;
            Finish("Stopped. Nothing was changed: Mentor is as it was.");
        }
        catch (Exception e)
        {
            try { if (File.Exists(partial)) File.Delete(partial); } catch (IOException) { }
            Finish("It did not work: " + e.Message + "\n\nIf this happened while downloading, nothing was changed. " +
                   "If Mentor is running, close it first.");
        }
    }
}
