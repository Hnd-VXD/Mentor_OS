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

// The Mentor window is wide and low, the shape of the loading window that follows it (StartSplash), and in
// the same place: Start turns it over to that page, Back turns it back (the user's wish, 2026-10-22, after
// Try Omarchy's). The owl and the name at the top left of both; the settings in rows below, label on the
// left and what is chosen on the right; the rarer things (restore points, repair, backups, moving, starting
// over) on a second tab, "More"; Start the whole width at the bottom, where the loading page has Back.
class LauncherWindow : Form
{
    readonly Settings settings;
    readonly bool own, running;
    readonly Toggle gpu = new Toggle(), fullscreen = new Toggle(), vulkan = new Toggle();
    readonly Slider memory = new Slider(), cpus = new Slider();
    readonly Choice speed = new Choice { Items = new[] { "Balanced", "Maximum", "Manual" } };
    readonly Choice tabs = new Choice { Items = new[] { "Settings", "More" } };
    readonly Label speedWords, memoryValue, cpuValue, moreWords, gpuWord, vulkanWord, fullWord;
    readonly List<Control> settingsPage = new List<Control>(), morePage = new List<Control>();
    readonly string[] profiles = { Resources.Balanced, Resources.Maximum, Resources.Manual };
    readonly Control[] manualRow;
    readonly float factor;
    int[] maximum;  // what "Maximum" would give, measured in the background

    // The size both pages have, in the units of a screen that is not scaled (StartSplash takes it too).
    public const int PageWidth = 560, PageHeight = 352;
    // Where the button at the bottom is on both pages: Start here, Back on the loading page.
    public static readonly Rectangle BottomButton = new Rectangle(32, 296, 496, 40);

    public bool Fullscreen { get { return fullscreen.Checked; } }
    public bool Repair { get; private set; }

    static Label Words(string text, float size, Color colour)
    {
        return new Label { Text = text, ForeColor = colour, BackColor = Theme.Back,
                           Font = Theme.Font(size, FontStyle.Regular), AutoEllipsis = true };
    }

    // Where a control goes, in the units of a screen that is not scaled.
    void Place(Control control, int left, int top, int width, int height)
    {
        control.SetBounds((int)Math.Round(left * factor), (int)Math.Round(top * factor),
                          (int)Math.Round(width * factor), (int)Math.Round(height * factor));
    }

    // The owl, the name and the line under it, as on the loading page (StartSplash uses this too).
    public static Label Header(Form form, Action<Control, int, int, int, int> place, string line)
    {
        var emblem = new PictureBox { SizeMode = PictureBoxSizeMode.Zoom, BackColor = Theme.Back };
        try { emblem.Image = Image.FromStream(typeof(LauncherWindow).Assembly.GetManifestResourceStream("emblem.png")); }
        catch (Exception) { }
        var name = Words("Mentor", 16f, Theme.Text);
        name.Font = Theme.Font(16f, FontStyle.Bold);
        var subtitle = Words(line, 9f, Theme.Dim);
        var rule = new Label { BackColor = Theme.Line };
        // Name and line end before the tabs (from 360): a label's solid background covered them.
        place(emblem, 30, 18, 56, 56);
        place(name, 96, 20, 250, 32);
        place(subtitle, 98, 51, 250, 20);
        place(rule, 32, 88, 496, 1);
        form.Controls.AddRange(new Control[] { emblem, name, subtitle, rule });
        return subtitle;
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
        // Back from the loading window: where it was, as it is the same window turning back a page.
        if (!running && !Program.WindowPlace.IsEmpty)
        {
            StartPosition = FormStartPosition.Manual;
            Location = Program.WindowPlace.Location;
        }
        MaximizeBox = false;
        BackColor = Theme.Back;
        ForeColor = Theme.Text;
        Font = Theme.Font(9.5f, FontStyle.Regular);
        KeyPreview = true;
        Theme.Dress(this);
        using (Graphics g = CreateGraphics()) factor = g.DpiX / 96f;
        ClientSize = new Size((int)Math.Round(PageWidth * factor), (int)Math.Round(PageHeight * factor));

        Label subtitle = Header(this, Place, running ? "Settings for the next start" : "Agentic Linux");
        // News of the launcher's own update, in the subtitle's place (SelfUpdate.Note): at once when it
        // is known, or when the check in the background finds one while the window is open.
        Action showNote = () => {
            if (SelfUpdate.Note == null || running) return;
            subtitle.Text = SelfUpdate.Note;
            subtitle.ForeColor = Theme.AccentHot;
        };
        showNote();
        Action noteChanged = () => {
            try { if (IsHandleCreated && !IsDisposed) BeginInvoke(showNote); }
            catch (Exception) { }
        };
        SelfUpdate.NoteChanged += noteChanged;
        Shown += (s, e) => showNote();
        FormClosed += (s, e) => SelfUpdate.NoteChanged -= noteChanged;
        var start = new PillButton { Text = running ? "Save" : "Start Mentor", Primary = true, Result = DialogResult.OK,
                                     Font = Theme.Font(11f, FontStyle.Bold) };
        Place(start, BottomButton.X, BottomButton.Y, BottomButton.Width, BottomButton.Height);
        // The two tabs, in the header's right half; while Mentor runs there is only the one page.
        Place(tabs, 360, 32, 168, 26);
        tabs.Font = speed.Font = Theme.Font(9f, FontStyle.Regular);
        tabs.Visible = !running;
        tabs.Changed += (s, e) => Arrange();

        gpu.Checked = settings.gpu;
        vulkan.Checked = settings.vulkan && own;
        fullscreen.Checked = startFullscreen;
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
        memoryValue = Words("", 8.5f, Theme.Text);
        cpuValue = Words("", 8.5f, Theme.Text);
        memoryValue.TextAlign = cpuValue.TextAlign = ContentAlignment.TopRight;
        speedWords = Words("", 8.5f, Theme.Dim);
        moreWords = Words("", 8.5f, Theme.Dim);
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

        var change = new PillButton { Text = "Change…", Font = Theme.Font(9f, FontStyle.Regular) };
        change.Click += (s, e) => {
            using (var dialog = new SettingsDialog(qemuDir, settings, running))
                if (dialog.ShowDialog(this) == DialogResult.OK) ShowMore();
        };
        // Graphics card, Vulkan and Full screen side by side, each a switch with its name beside it; what
        // each does is in its tooltip.
        var tips = new ToolTip();
        Func<Toggle, string, string, Label> named = (toggle, name, tip) => {
            Label word = Words(name, 9f, Theme.Text);
            word.TextAlign = ContentAlignment.MiddleLeft;
            word.Cursor = Cursors.Hand;
            word.Click += (s, e) => { if (toggle.Enabled) toggle.Checked = !toggle.Checked; };
            tips.SetToolTip(word, tip);
            tips.SetToolTip(toggle, tip);
            return word;
        };
        gpuWord = named(gpu, "Graphics card", own ? "Smoother desktop, drawn by the graphics card." : "Smoother desktop. Experimental.");
        vulkanWord = named(vulkan, "Vulkan", "For apps and games that use Vulkan. Experimental. Needs the graphics card.");
        fullWord = named(fullscreen, "Full screen", "Mentor fills the whole screen. Ctrl+Alt+F switches at any time.");
        vulkanWord.Visible = own;
        vulkanWord.ForeColor = gpu.Checked ? Theme.Text : Theme.Dim;
        gpu.CheckedChanged += (s, e) => vulkanWord.ForeColor = gpu.Checked ? Theme.Text : Theme.Dim;

        var lines = new Label[2];
        for (int i = 0; i < lines.Length; i++) lines[i] = new Label { BackColor = Theme.Line };
        Label screenName = Words("Screen", 9.5f, Theme.Text), speedName = Words("Speed", 9.5f, Theme.Text),
              moreName = Words("Sound, USB and sign-in", 9.5f, Theme.Text);
        manualRow = new Control[] { Words("Memory", 8.5f, Theme.Text), memoryValue, memory,
                                    Words("Processors", 8.5f, Theme.Text), cpuValue, cpus };
        // The rows, top to bottom, label on the left, at 32; what is chosen from 150.
        Place(screenName, 32, 101, 110, 22);
        int x = 150;
        foreach (Control[] pair in new[] { new Control[] { gpu, gpuWord }, own ? new Control[] { vulkan, vulkanWord } : null,
                                            new Control[] { fullscreen, fullWord } })
        {
            if (pair == null) continue;
            int words = pair[1] == gpuWord ? 84 : pair[1] == vulkanWord ? 52 : 68;
            Place(pair[0], x, 103, 32, 18);
            Place(pair[1], x + 36, 100, words, 24);
            x += 36 + words + (own ? 16 : 60);
        }
        Place(lines[0], 32, 134, 496, 1);
        Place(speedName, 32, 147, 110, 22);
        Place(speed, 150, 144, 378, 26);
        Place(speedWords, 150, 178, 378, 18);
        Place(manualRow[0], 150, 176, 90, 18);
        Place(manualRow[1], 240, 176, 86, 18);
        Place(manualRow[2], 148, 194, 180, 22);
        Place(manualRow[3], 350, 176, 90, 18);
        Place(manualRow[4], 442, 176, 86, 18);
        Place(manualRow[5], 348, 194, 182, 22);
        Place(lines[1], 32, 226, 496, 1);
        Place(moreName, 32, 238, 300, 22);
        Place(moreWords, 32, 260, 380, 18);
        Place(change, 428, 240, 100, 32);
        settingsPage.AddRange(new Control[] { screenName, gpu, gpuWord, vulkan, vulkanWord, fullscreen, fullWord, lines[0],
                                              speedName, speed, speedWords, lines[1], moreName, moreWords, change });
        settingsPage.AddRange(manualRow);

        // "More": the rarer choices, which all want Mentor stopped (so not while it runs).
        var restore = new PillButton { Text = "Restore points" };  // the six in 9 point, as Change…
        var mend = new PillButton { Text = "Repair" };
        var backUp = new PillButton { Text = "Back up…" };
        var fromBackup = new PillButton { Text = "Restore a backup…" };
        var move = new PillButton { Text = "Move Mentor…" };
        // One button for starting from nothing; whether the newest Mentor is downloaded too is a choice
        // inside it (StartOverDialog). It was two, Reinstall and Start over, which the user found the same.
        var fresh = new PillButton { Text = "Start over…" };
        Control[] buttons = { restore, mend, backUp, fromBackup, move, fresh };
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].Font = Theme.Font(9f, FontStyle.Regular);
            Place(buttons[i], i % 2 == 0 ? 32 : 284, 102 + i / 2 * 42, 244, 34);
        }
        var moreNote = Words("For when something went wrong, or something is to be kept or moved.", 8.5f, Theme.Dim);
        Place(moreNote, 32, 236, 496, 20);
        morePage.AddRange(buttons);
        morePage.Add(moreNote);

        Controls.Add(tabs);
        Controls.Add(start);
        Controls.AddRange(settingsPage.ToArray());
        Controls.AddRange(morePage.ToArray());
        Arrange();

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
            string why = Backup.NotWhileRunning(vmDir);
            if (why != null) { MessageBox.Show(this, why, Text); return; }
            switch (StartOverDialog.Ask(this))
            {
                case StartOverChoice.BackUpFirst:
                    Backup.Make(this, root, vmDir, image);  // then Start over… again, when they want
                    return;
                case StartOverChoice.Download:
                    // The old one is deleted only once the new image has arrived whole and checked.
                    if (global::Reinstall.Run(this, image, vmDir))
                    {
                        watch.Failures = 0;
                        MessageBox.Show(this, "Done. Mentor is the newest one now, and starts fresh: press Start Mentor.", Text);
                    }
                    return;
                case StartOverChoice.Here:
                    try
                    {
                        if (Directory.Exists(vmDir)) Directory.Delete(vmDir, true);
                        watch.Failures = 0;
                        MessageBox.Show(this, "Done. The next start is a fresh Mentor: press Start Mentor.", Text);
                    }
                    catch (IOException error)
                    {
                        MessageBox.Show(this, "Could not delete it:\n\n" + error.Message + "\n\nIf Mentor is running, close it first.",
                                        Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    }
                    return;
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
            if (!running) Program.WindowPlace = Bounds;  // for StartSplash, which takes this place
            settings.gpu = gpu.Checked;
            if (own) settings.vulkan = vulkan.Checked && gpu.Checked;
            settings.profile = profiles[speed.Selected];
            settings.memory = memory.Value;  // kept for Manual whatever is chosen now
            settings.cpus = cpus.Value;
        };
    }

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

    // Shows the page of the tab chosen, and on Settings Manual's sliders in place of Speed's line.
    void Arrange()
    {
        bool more = tabs.Selected == 1 && !running;
        foreach (Control control in settingsPage) control.Visible = !more;
        foreach (Control control in morePage) control.Visible = more;
        if (more) return;
        bool manual = profiles[speed.Selected] == Resources.Manual;
        foreach (Control control in manualRow) control.Visible = manual;
        speedWords.Visible = !manual;
        vulkan.Visible = vulkanWord.Visible = own;
    }
}
