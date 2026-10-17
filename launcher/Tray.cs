// Mentor's icon in Windows' notification area while it runs, after Try Omarchy for Windows
// (github.com/omacom/try-omarchy-windows, MIT, docs/DESKTOP-CONTROLS.md, app/tray_windows.go):
//   Open Mentor                 brings Mentor's window to the front (also a double click on the icon)
//   Settings                    the launcher window, for the next start
//   Make a diagnostics file     the logs of the launcher and of the system inside, zipped to the Desktop
//   Shut down Mentor            properly, as from Mentor's own menu
using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

class Tray : IDisposable
{
    readonly NotifyIcon icon = new NotifyIcon();
    readonly ToolStripMenuItem diagnostics;
    HostBridge bridge;
    Form settingsOpen;

    public Tray()
    {
        try { icon.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
        catch (Exception) { icon.Icon = SystemIcons.Application; }
        icon.Text = "Mentor";
        var menu = new ContextMenuStrip();
        var open = new ToolStripMenuItem("Open Mentor", null, (s, e) => Open()) { Font = new Font(SystemFonts.MenuFont, FontStyle.Bold) };
        diagnostics = new ToolStripMenuItem("Make a diagnostics file", null, (s, e) => MakeDiagnostics());
        menu.Items.AddRange(new ToolStripItem[] {
            open,
            new ToolStripMenuItem("Settings…", null, (s, e) => OpenSettings()),
            diagnostics,
            new ToolStripSeparator(),
            new ToolStripMenuItem("Shut down Mentor", null, (s, e) => ShutDown()),
        });
        icon.ContextMenuStrip = menu;
        icon.DoubleClick += (s, e) => Open();
    }

    // While a system runs: the icon is there, and its commands go to that system.
    public void Attach(HostBridge running)
    {
        bridge = running;
        icon.Visible = true;
    }

    public void Detach()
    {
        bridge = null;
        if (settingsOpen != null) settingsOpen.Close();
    }

    public void Dispose()
    {
        icon.Visible = false;
        icon.Dispose();
    }

    public void Say(string title, string text)
    {
        icon.BalloonTipTitle = title;
        icon.BalloonTipText = text;
        icon.ShowBalloonTip(5000);
    }

    void Open()
    {
        if (bridge != null) bridge.ShowVm();
    }

    void OpenSettings()
    {
        if (settingsOpen != null) { settingsOpen.Activate(); return; }
        Settings settings = Settings.Load(Program.SettingsFile);
        using (var window = new LauncherWindow(settings, Program.Own, File.Exists(Path.Combine(Program.VmDir, "fullscreen")),
                                               Program.Points, Program.Watch, Program.VmDir, Program.Image, Program.Root,
                                               Program.QemuDir, true))
        {
            settingsOpen = window;
            window.TopMost = true;
            if (window.ShowDialog() == DialogResult.OK) settings.Save();
            settingsOpen = null;
        }
    }

    void MakeDiagnostics()
    {
        if (!diagnostics.Enabled) return;
        diagnostics.Enabled = false;
        diagnostics.Text = "Making the diagnostics file…";
        HostLink link = bridge != null ? bridge.Link : null;
        Diagnostics.MakeInBackground(link, path => {
            diagnostics.Enabled = true;
            diagnostics.Text = "Make a diagnostics file";
            if (path == null) Say("Mentor", "The diagnostics file could not be made.");
            else
            {
                Say("Mentor", "The diagnostics file is on your Desktop: " + Path.GetFileName(path));
                try { System.Diagnostics.Process.Start("explorer.exe", "/select,\"" + path + "\""); }
                catch (Exception) { }
            }
        });
    }

    void ShutDown()
    {
        if (bridge == null) return;
        if (MessageBox.Show("Shut down Mentor?\n\nThe apps inside it are closed: save your work in them first.", "Mentor",
                            MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
            return;
        if (bridge != null) bridge.ShutDown();
    }
}
