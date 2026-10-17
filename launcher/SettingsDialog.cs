// "Sound, USB and sign-in" in the launcher window: where the sound goes, which microphone (or none),
// a USB device for the next start, and Windows Hello for passwords inside Mentor. Each has one plain
// sentence; what is chosen is used from the next start of Mentor.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

// One of a list, shown as a rounded box with a chevron; a click opens the list as a menu. Drawn here,
// as Windows' own drop-down list will not take the dark colours.
class Picker : Painted
{
    public readonly List<string> Items = new List<string>();
    int selected = -1;
    bool hot;

    public int SelectedIndex
    {
        get { return selected; }
        set { selected = value; Invalidate(); }
    }

    public string Selected { get { return selected >= 0 && selected < Items.Count ? Items[selected] : null; } }

    public Picker() { Cursor = Cursors.Hand; }

    protected override void OnMouseEnter(EventArgs e) { hot = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hot = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnClick(EventArgs e) { Focus(); Open(); base.OnClick(e); }
    protected override bool IsInputKey(Keys key) { return key == Keys.Up || key == Keys.Down || base.IsInputKey(key); }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Space || e.KeyCode == Keys.Enter) Open();
        if (e.KeyCode == Keys.Down && selected < Items.Count - 1) SelectedIndex = selected + 1;
        if (e.KeyCode == Keys.Up && selected > 0) SelectedIndex = selected - 1;
        base.OnKeyDown(e);
    }

    void Open()
    {
        var menu = new ContextMenuStrip { Renderer = new DarkMenu(), ShowImageMargin = false, ShowCheckMargin = true,
                                          Font = Font, BackColor = Theme.Card, ForeColor = Theme.Text };
        for (int i = 0; i < Items.Count; i++)
        {
            int index = i;
            var item = new ToolStripMenuItem(Items[i]) { Checked = i == selected, ForeColor = Theme.Text };
            item.Click += (s, e) => SelectedIndex = index;
            menu.Items.Add(item);
        }
        menu.MinimumSize = new Size(Width, 0);
        menu.Closed += (s, e) => BeginInvoke((Action)menu.Dispose);
        menu.Show(this, new Point(0, Height));
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = Begin(e);
        var area = new RectangleF(0.5f, 0.5f, Width - 1, Height - 1);
        using (GraphicsPath shape = Theme.Round(area, Height * 0.25f))
        {
            using (var fill = new SolidBrush(hot ? Color.FromArgb(32, 40, 62) : Theme.Card)) g.FillPath(fill, shape);
            using (var edge = new Pen(Focused ? Theme.Accent : Theme.Line)) g.DrawPath(edge, shape);
        }
        float side = Height * 0.14f, x = Width - Height * 0.5f, y = Height / 2f;
        TextRenderer.DrawText(g, Selected ?? "", Font, new Rectangle(10, 0, (int)(x - side - 16), Height), Theme.Text,
                              TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis);
        using (var pen = new Pen(Theme.Dim, Math.Max(1.5f, Height / 18f)))
        {
            pen.StartCap = pen.EndCap = LineCap.Round;
            g.DrawLines(pen, new[] { new PointF(x - side, y - side / 2), new PointF(x, y + side / 2), new PointF(x + side, y - side / 2) });
        }
    }

    // The menu in the launcher's colours.
    class DarkMenu : ToolStripProfessionalRenderer
    {
        public DarkMenu() : base(new Colours()) { RoundedEdges = false; }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            e.TextColor = Theme.Text;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
        {
            Rectangle box = e.ImageRectangle;
            using (var pen = new Pen(Theme.AccentHot, 2f))
            {
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                e.Graphics.DrawLines(pen, new[] { new Point(box.Left + 3, box.Top + box.Height / 2), new Point(box.Left + box.Width / 2 - 1, box.Bottom - 4),
                                                  new Point(box.Right - 3, box.Top + 4) });
            }
        }

        class Colours : ProfessionalColorTable
        {
            public override Color ToolStripDropDownBackground { get { return Theme.Card; } }
            public override Color ImageMarginGradientBegin { get { return Theme.Card; } }
            public override Color ImageMarginGradientMiddle { get { return Theme.Card; } }
            public override Color ImageMarginGradientEnd { get { return Theme.Card; } }
            public override Color MenuBorder { get { return Theme.Line; } }
            public override Color MenuItemBorder { get { return Theme.Accent; } }
            public override Color MenuItemSelected { get { return Theme.Accent; } }
            public override Color MenuItemSelectedGradientBegin { get { return Theme.Accent; } }
            public override Color MenuItemSelectedGradientEnd { get { return Theme.Accent; } }
            public override Color CheckBackground { get { return Theme.Card; } }
            public override Color CheckSelectedBackground { get { return Theme.Accent; } }
            public override Color CheckPressedBackground { get { return Theme.Accent; } }
        }
    }
}

class SettingsDialog : Form
{
    const string Same = "Same as Windows", Off = "Off", NoUsb = "None";
    readonly Picker speaker = new Picker(), microphone = new Picker(), usb = new Picker();
    readonly Toggle hello = new Toggle();
    readonly List<UsbDevice> usbFound;

    static Label Words(string text, int top, int height, float size, Color colour)
    {
        return new Label { Text = text, Left = 24, Top = top, Width = 392, Height = height, ForeColor = colour,
                           BackColor = Theme.Back, Font = Theme.Font(size, FontStyle.Regular) };
    }

    static void Fill(Picker box, List<string> names, string chosen, string first, string second)
    {
        box.Items.Add(first);
        if (second != null) box.Items.Add(second);
        if (names != null) foreach (string name in names) if (!box.Items.Contains(name)) box.Items.Add(name);
        // A device that is not there now stays chosen: Mentor falls back to Windows' own until it is back.
        if (!string.IsNullOrEmpty(chosen) && chosen != "off" && !box.Items.Contains(chosen)) box.Items.Add(chosen);
        box.SelectedIndex = box.Items.IndexOf(string.IsNullOrEmpty(chosen) ? first : chosen == "off" ? second : chosen);
    }

    public SettingsDialog(string qemuDir, Settings settings, bool running)
    {
        Text = "Mentor";
        AutoScaleMode = AutoScaleMode.None;
        ClientSize = new Size(440, 486);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = MinimizeBox = false;
        BackColor = Theme.Back;
        ForeColor = Theme.Text;
        Font = Theme.Font(9.5f, FontStyle.Regular);
        Theme.Dress(this);
        List<string>[] sound = AudioDevices.List(qemuDir);
        usbFound = UsbDevices.List(qemuDir);
        Fill(speaker, sound != null ? sound[0] : null, settings.speaker, Same, null);
        Fill(microphone, sound != null ? sound[1] : null, settings.microphone, Same, Off);
        var usbNames = new List<string>();
        if (usbFound != null) foreach (UsbDevice device in usbFound) usbNames.Add(device.Label);
        string usbNow = null;
        if (settings.usb != "")
        {
            UsbDevice saved = UsbDevice.Parse(settings.usb);
            usbNow = saved == null ? null : saved.Label;
        }
        Fill(usb, usbNames, usbNow, NoUsb, null);
        bool helloThere = WindowsHello.Available();
        hello.Checked = settings.hello && helloThere;
        hello.Enabled = helloThere;
        speaker.SetBounds(24, 64, 392, 32);
        microphone.SetBounds(24, 156, 392, 32);
        usb.SetBounds(24, 266, 392, 32);
        hello.SetBounds(372, 322, 44, 24);
        var save = new PillButton { Text = "Save", Primary = true, Result = DialogResult.OK, Left = 160, Top = 426, Width = 124, Height = 38 };
        var cancel = new PillButton { Text = "Cancel", Result = DialogResult.Cancel, Left = 292, Top = 426, Width = 124, Height = 38 };
        Controls.AddRange(new Control[] {
            Words("Sound", 16, 24, 10.5f, Theme.Text),
            Words("Where Mentor's sound plays.", 38, 20, 8.5f, Theme.Dim), speaker,
            Words("Microphone", 108, 24, 10.5f, Theme.Text),
            Words("What Mentor hears. Off: no app inside Mentor can listen.", 130, 20, 8.5f, Theme.Dim), microphone,
            Words("USB device", 200, 24, 10.5f, Theme.Text),
            Words("Mentor gets it when it starts, and Windows cannot use it meanwhile. Experimental.", 222, 40, 8.5f, Theme.Dim), usb,
            new Label { Text = "Windows Hello", Left = 24, Top = 314, Width = 320, Height = 24, ForeColor = Theme.Text,
                        BackColor = Theme.Back, Font = Theme.Font(10.5f, FontStyle.Regular) },
            new Label { Text = helloThere ? "Your face, finger or PIN instead of the password inside Mentor. The password still works."
                                          : "Not set up on this Windows (Settings, Accounts, Sign-in options).",
                        Left = 24, Top = 338, Width = 330, Height = 40, ForeColor = Theme.Dim, BackColor = Theme.Back,
                        Font = Theme.Font(8.5f, FontStyle.Regular) }, hello,
            Words(running ? "Used from the next start of Mentor." : "", 392, 20, 8.5f, Theme.Dim),
            save, cancel,
        });
        Theme.Fit(this);
        FormClosing += (s, e) => {
            if (DialogResult != DialogResult.OK) return;
            settings.speaker = speaker.Selected == Same ? "" : speaker.Selected;
            settings.microphone = microphone.Selected == Same ? "" : microphone.Selected == Off ? "off" : microphone.Selected;
            int chosen = usb.SelectedIndex - 1;  // after "None"
            if (usb.SelectedIndex <= 0) settings.usb = "";
            else if (usbFound != null && chosen < usbFound.Count) settings.usb = usbFound[chosen].ToString();
            // else: the saved one, not plugged in now, stays
            settings.hello = hello.Checked;
        };
    }
}
