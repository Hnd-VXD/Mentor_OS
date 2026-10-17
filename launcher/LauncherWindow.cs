// The window a double click on Mentor.exe opens: start, with the few choices worth having at hand.
// The tray icon opens it too while Mentor runs ("Settings"), with Save in place of Start: what is
// chosen then is for the next start.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// What the launcher window remembers between starts (Mentor.settings beside the program).
class Settings
{
    public int memory, cpus;
    public bool gpu, vulkan;
    public string profile;  // Resources.Balanced, Maximum or Manual
    public string speaker, microphone;  // "" for Windows' own; the microphone can be "off" (Devices.cs)
    public string usb;  // a USB device for the next start, "" for none (Usb.cs)
    public bool hello;  // Windows Hello for passwords inside Mentor (Hello.cs)
    string path;

    public static Settings Load(string path)
    {
        Settings settings = null;
        try { settings = new JavaScriptSerializer().Deserialize<Settings>(File.ReadAllText(path)); }
        catch (IOException) { }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
        if (settings == null) settings = new Settings();
        // Settings from before the profiles have the sliders' sizes, which were chosen: they stay.
        if (settings.profile != Resources.Balanced && settings.profile != Resources.Maximum && settings.profile != Resources.Manual)
            settings.profile = settings.memory > 0 ? Resources.Manual : Resources.Balanced;
        settings.speaker = settings.speaker ?? "";
        settings.microphone = settings.microphone ?? "";
        settings.usb = settings.usb ?? "";
        settings.path = path;
        return settings;
    }

    public void Save()
    {
        var values = new Dictionary<string, object> {
            { "memory", memory }, { "cpus", cpus }, { "gpu", gpu }, { "vulkan", vulkan }, { "profile", profile },
            { "speaker", speaker }, { "microphone", microphone }, { "usb", usb }, { "hello", hello } };
        try { File.WriteAllText(path, new JavaScriptSerializer().Serialize(values)); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}

// A row of choices, one of them on (Balanced / Maximum / Manual).
class Choice : Painted
{
    public string[] Items = new string[0];
    int current;
    public event EventHandler Changed;

    public int Selected
    {
        get { return current; }
        set
        {
            if (value < 0 || value >= Items.Length || value == current) return;
            current = value;
            Invalidate();
            if (Changed != null) Changed(this, EventArgs.Empty);
        }
    }

    public Choice() { Cursor = Cursors.Hand; }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        Focus();
        if (Items.Length > 0) Selected = Math.Min(Items.Length - 1, e.X * Items.Length / Math.Max(1, Width));
        base.OnMouseDown(e);
    }

    protected override bool IsInputKey(Keys key) { return key == Keys.Left || key == Keys.Right || base.IsInputKey(key); }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Left) Selected = current - 1;
        if (e.KeyCode == Keys.Right) Selected = current + 1;
        base.OnKeyDown(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = Begin(e);
        var area = new RectangleF(0.5f, 0.5f, Width - 1, Height - 1);
        using (GraphicsPath shape = Theme.Round(area, Height / 2f))
        {
            using (var fill = new SolidBrush(Theme.Track)) g.FillPath(fill, shape);
            if (Focused) using (var edge = new Pen(Theme.AccentHot)) g.DrawPath(edge, shape);
        }
        float part = (Width - 4f) / Math.Max(1, Items.Length);
        for (int i = 0; i < Items.Length; i++)
        {
            var cell = new RectangleF(2f + i * part, 2f, part, Height - 4f);
            if (i == current)
                using (GraphicsPath pill = Theme.Round(cell, cell.Height / 2f))
                using (var fill = new SolidBrush(Theme.Accent)) g.FillPath(fill, pill);
            TextRenderer.DrawText(g, Items[i], Font, Rectangle.Round(cell), i == current ? Color.White : Theme.Text,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
    }
}

class LauncherWindow : Form
{
    readonly Settings settings;
    readonly bool own, running;
    readonly Toggle gpu = new Toggle(), fullscreen = new Toggle(), vulkan = new Toggle();
    readonly Slider memory = new Slider(), cpus = new Slider();
    readonly Choice speed = new Choice { Items = new[] { "Balanced", "Maximum", "Manual" } };
    readonly Label speedWords, memoryValue, cpuValue, moreWords;
    readonly Card card = new Card();
    readonly Unfold unfold = new Unfold { Text = "More options" };
    readonly List<Control> folded = new List<Control>();
    readonly Dictionary<Control, Rectangle> places = new Dictionary<Control, Rectangle>();
    readonly string[] profiles = { Resources.Balanced, Resources.Maximum, Resources.Manual };
    readonly Control[] manualRow;
    readonly float factor;
    int[] maximum;  // what "Maximum" would give, measured in the background

    public bool Fullscreen { get { return fullscreen.Checked; } }
    public bool Repair { get; private set; }

    static Label Words(string text, float size, Color colour, bool onCard)
    {
        return new Label { Text = text, ForeColor = colour, BackColor = onCard ? Theme.Card : Theme.Back,
                           Font = Theme.Font(size, FontStyle.Regular), AutoEllipsis = true };
    }

    // Where a control goes, in the units of a screen that is not scaled.
    void Place(Control control, int left, int top, int width, int height)
    {
        places[control] = new Rectangle(left, top, width, height);
        control.SetBounds((int)Math.Round(left * factor), (int)Math.Round(top * factor),
                          (int)Math.Round(width * factor), (int)Math.Round(height * factor));
    }

    public LauncherWindow(Settings settings, bool own, bool startFullscreen, RestorePoints points, BootWatch watch,
                          string vmDir, string image, string root, string qemuDir, bool running)
    {
        this.settings = settings;
        this.own = own;
        this.running = running;
        Text = "Mentor";
        AutoScaleMode = AutoScaleMode.None;  // laid out by Place, below
        FormBorderStyle = FormBorderStyle.FixedSingle;
        StartPosition = FormStartPosition.CenterScreen;
        MaximizeBox = false;
        BackColor = Theme.Back;
        ForeColor = Theme.Text;
        Font = Theme.Font(9.5f, FontStyle.Regular);
        KeyPreview = true;
        Theme.Dress(this);
        using (Graphics g = CreateGraphics()) factor = g.DpiX / 96f;

        var emblem = new PictureBox { SizeMode = PictureBoxSizeMode.Zoom, BackColor = Theme.Back };
        try { emblem.Image = Image.FromStream(typeof(LauncherWindow).Assembly.GetManifestResourceStream("emblem.png")); }
        catch (Exception) { }
        var title = new Label { Text = "Mentor", TextAlign = ContentAlignment.MiddleCenter,
                                Font = Theme.Font(20f, FontStyle.Bold), ForeColor = Theme.Text, BackColor = Theme.Back };
        var subtitle = new Label { Text = running ? "Settings for the next start" : "Agentic Linux", TextAlign = ContentAlignment.MiddleCenter,
                                   ForeColor = Theme.Dim, BackColor = Theme.Back };
        var start = new PillButton { Text = running ? "Save" : "Start Mentor", Primary = true, Result = DialogResult.OK,
                                     Font = Theme.Font(12f, FontStyle.Bold) };
        Place(emblem, 170, 24, 100, 100);
        Place(title, 0, 130, 440, 40);
        Place(subtitle, 0, 170, 440, 22);
        Place(start, 28, 210, 384, 52);

        gpu.Checked = settings.gpu;
        vulkan.Checked = settings.vulkan && own;
        fullscreen.Checked = startFullscreen;
        foreach (Painted control in new Painted[] { gpu, vulkan, fullscreen, memory, cpus, speed }) control.BackColor = Theme.Card;
        vulkan.Visible = own;
        vulkan.Enabled = gpu.Checked;  // it is drawn by the graphics card or not at all
        gpu.CheckedChanged += (s, e) => vulkan.Enabled = gpu.Checked;

        double totalGB, freeGB;
        Resources.Memory(out totalGB, out freeGB);
        int hostGB = totalGB > 0 ? (int)totalGB + 1 : 16;
        memory.Minimum = 2;
        memory.Maximum = Math.Max(4, Math.Min(64, hostGB * 3 / 4));
        cpus.Minimum = 1;
        cpus.Maximum = Environment.ProcessorCount;
        int[] balanced = Resources.Plan(Resources.Balanced, 0, 0);
        memory.Value = settings.memory > 0 ? settings.memory : balanced[0];
        cpus.Value = settings.cpus > 0 ? settings.cpus : balanced[1];
        memoryValue = Words("", 9.5f, Theme.Text, true);
        cpuValue = Words("", 9.5f, Theme.Text, true);
        memoryValue.TextAlign = cpuValue.TextAlign = ContentAlignment.TopRight;
        speedWords = Words("", 8.5f, Theme.Dim, true);
        moreWords = Words("", 8.5f, Theme.Dim, true);
        speed.Selected = Math.Max(0, Array.IndexOf(profiles, settings.profile));
        EventHandler show = (s, e) => {
            memoryValue.Text = memory.Value + " GB";
            cpuValue.Text = cpus.Value + " of " + Environment.ProcessorCount;
            string profile = profiles[speed.Selected];
            if (profile == Resources.Balanced)
                speedWords.Text = Sizes(balanced) + ", with plenty left for Windows.";
            else if (profile == Resources.Maximum)
                speedWords.Text = maximum == null ? "Looking at what Windows is not using…"
                                                  : Sizes(maximum) + ": what Windows is not using now.";
            else speedWords.Text = "As you set it below.";
        };
        memory.ValueChanged += show;
        cpus.ValueChanged += show;
        speed.Changed += (s, e) => { show(s, e); Arrange(); };
        // "Maximum" looks at how busy Windows is for a moment: not in the way of the window.
        new Thread(() => {
            int[] found = Resources.Plan(Resources.Maximum, 0, 0);
            try { BeginInvoke((Action)(() => { maximum = found; show(null, EventArgs.Empty); })); }
            catch (InvalidOperationException) { }  // closed meanwhile
        }) { IsBackground = true }.Start();
        show(null, EventArgs.Empty);
        ShowMore();

        var change = new PillButton { Text = "Change…", BackColor = Theme.Card };
        change.Click += (s, e) => {
            using (var dialog = new SettingsDialog(qemuDir, settings, running))
                if (dialog.ShowDialog(this) == DialogResult.OK) ShowMore();
        };
        manualRow = new Control[] { Words("Memory", 10.5f, Theme.Text, true), memoryValue, memory,
                                    Words("Processors", 10.5f, Theme.Text, true), cpuValue, cpus };
        var lines = new Label[4];
        for (int i = 0; i < lines.Length; i++) lines[i] = new Label { BackColor = Theme.Line };
        // The card's rows, top to bottom; each Place()d by Arrange().
        rows = new List<Control[]> {
            new Control[] { Words("Graphics card", 10.5f, Theme.Text, true),
                            Words(own ? "Smoother desktop, drawn by the graphics card." : "Smoother desktop. Experimental.", 8.5f, Theme.Dim, true),
                            gpu, lines[0] },
            own ? new Control[] { Words("Vulkan", 10.5f, Theme.Text, true),
                                  Words("For apps and games that use Vulkan. Experimental.", 8.5f, Theme.Dim, true),
                                  vulkan, lines[1] } : null,
            new Control[] { Words("Full screen", 10.5f, Theme.Text, true),
                            Words("Ctrl+Alt+F switches at any time.", 8.5f, Theme.Dim, true), fullscreen, lines[2] },
            new Control[] { Words("Speed", 10.5f, Theme.Text, true), speedWords, speed, lines[3] },
            new Control[] { Words("Sound, USB and sign-in", 10.5f, Theme.Text, true), moreWords, change },
        };
        foreach (Control[] row in rows) if (row != null) card.Controls.AddRange(row);
        card.Controls.AddRange(manualRow);

        // The rarer choices start folded away under one quiet line (2026-10-15): the window is about
        // starting Mentor, and these are for when something went wrong or something is to be kept.
        var restore = new PillButton { Text = "Restore points" };
        var mend = new PillButton { Text = "Repair" };
        var backUp = new PillButton { Text = "Back up…" };
        var fromBackup = new PillButton { Text = "Restore a backup…" };
        var move = new PillButton { Text = "Move Mentor…" };
        var reinstall = new PillButton { Text = "Reinstall" };
        var fresh = new PillButton { Text = "Start over" };
        folded.AddRange(new Control[] { restore, mend, backUp, fromBackup, move, reinstall, fresh });
        foreach (Control button in folded) button.Visible = false;
        Controls.AddRange(new Control[] { emblem, title, subtitle, start, card, unfold });
        Controls.AddRange(folded.ToArray());
        unfold.Visible = !running;  // all of these want Mentor stopped
        unfold.Click += (s, e) => {
            unfold.Open = !unfold.Open;
            foreach (Control button in folded) button.Visible = unfold.Open;
            Arrange();
            unfold.Invalidate();
        };
        Arrange();

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
            if (global::Reinstall.Run(this, image, vmDir))
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
        backUp.Click += (s, e) => Backup.Make(this, root, vmDir, image);
        fromBackup.Click += (s, e) => { if (Backup.RestoreFrom(this, root, vmDir, image)) watch.Failures = 0; };
        move.Click += (s, e) => { if (MoveMentor.Run(this, root)) { DialogResult = DialogResult.Cancel; } };

        ActiveControl = start;
        KeyDown += (s, e) => {
            if (e.KeyCode == Keys.Escape) Close();
            if (e.KeyCode == Keys.Enter && !(ActiveControl is PillButton)) DialogResult = DialogResult.OK;
        };
        FormClosing += (s, e) => {
            if (DialogResult != DialogResult.OK) return;
            settings.gpu = gpu.Checked;
            if (own) settings.vulkan = vulkan.Checked && gpu.Checked;
            settings.profile = profiles[speed.Selected];
            settings.memory = memory.Value;  // kept for Manual whatever is chosen now
            settings.cpus = cpus.Value;
        };
    }

    readonly List<Control[]> rows;

    static string Sizes(int[] plan) { return plan[0] + " GB and " + plan[1] + (plan[1] == 1 ? " processor" : " processors"); }

    // The line under "Sound, USB and sign-in": what is chosen there, in a few words.
    void ShowMore()
    {
        var parts = new List<string>();
        parts.Add(settings.speaker == "" && settings.microphone == "" ? "Sound as on Windows" : "Sound chosen");
        if (settings.microphone == "off") parts.Add("no microphone");
        if (settings.usb != "") parts.Add("a USB device");
        if (settings.hello) parts.Add("Windows Hello");
        moreWords.Text = string.Join(", ", parts) + ".";
    }

    // Puts everything where it goes for what is shown now (Manual's sliders, the folded buttons).
    void Arrange()
    {
        int y = 0;
        foreach (Control[] row in rows)
        {
            if (row == null) continue;
            bool isSpeed = Array.IndexOf(row, speed) >= 0;
            // Labels have a solid background and lie above what is placed after them: kept clear of the
            // Speed choice (from 120) and of a button (from 262), which they covered.
            Place(row[0], 18, y + 14, isSpeed ? 96 : 200, 24);
            // Speed's line goes lower: its choice reaches further down than a switch (the user found it too close).
            Place(row[1], 18, isSpeed ? y + 45 : y + 37, isSpeed ? 348 : row[2] is Toggle ? 296 : 236, 20);
            if (row[2] is Toggle) Place(row[2], 322, y + 22, 44, 24);
            else if (isSpeed) Place(row[2], 120, y + 10, 246, 28);
            else Place(row[2], 262, y + 16, 104, 32);
            y += isSpeed ? 70 : 62;
            if (isSpeed)
            {
                bool manual = profiles[speed.Selected] == Resources.Manual;
                foreach (Control control in manualRow) control.Visible = manual;
                if (manual)
                {
                    Place(manualRow[0], 18, y + 6, 200, 24);
                    Place(manualRow[1], 266, y + 6, 100, 24);
                    Place(manualRow[2], 16, y + 30, 352, 26);
                    Place(manualRow[3], 18, y + 66, 200, 24);
                    Place(manualRow[4], 266, y + 66, 100, 24);
                    Place(manualRow[5], 16, y + 90, 352, 26);
                    y += 124;
                }
            }
            if (row.Length > 3) Place(row[3], 18, y + 6, 348, 1);
            y += row.Length > 3 ? 8 : 4;
        }
        Place(card, 28, 282, 384, y);
        int bottom = 282 + y + 16;
        Place(unfold, 28, bottom, 384, 28);
        bottom += running ? 0 : 40;
        if (unfold.Open && !running)
        {
            for (int i = 0; i < folded.Count; i++)
                Place(folded[i], i % 2 == 0 ? 28 : 226, bottom + i / 2 * 46, 186, 38);
            bottom += (folded.Count + 1) / 2 * 46;
        }
        ClientSize = new Size((int)Math.Round(440 * factor), (int)Math.Round((bottom + 8) * factor));
        card.Invalidate();
    }
}
