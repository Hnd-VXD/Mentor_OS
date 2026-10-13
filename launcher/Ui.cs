// What Mentor's own windows on Windows share: their colours and the controls they draw
// themselves. Compiled into both Mentor.exe (Mentor.cs) and MentorSetup.exe (MentorSetup.cs).
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;
using System.Windows.Forms;

// How Mentor's own windows look: dark, like the system they start.
static class Theme
{
    public static readonly Color Back = Color.FromArgb(13, 17, 30);
    public static readonly Color Card = Color.FromArgb(23, 29, 47);
    public static readonly Color Line = Color.FromArgb(38, 46, 70);
    public static readonly Color Text = Color.FromArgb(238, 241, 248);
    public static readonly Color Dim = Color.FromArgb(138, 149, 176);
    public static readonly Color Accent = Color.FromArgb(53, 132, 228);
    public static readonly Color AccentHot = Color.FromArgb(84, 156, 242);
    public static readonly Color Track = Color.FromArgb(50, 59, 87);

    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    public static Font Font(float size, FontStyle style) { return new Font("Segoe UI", size, style); }

    // A dark title bar and the emblem as the window's icon.
    public static void Dress(Form form)
    {
        int on = 1;
        try { DwmSetWindowAttribute(form.Handle, 20, ref on, sizeof(int)); }
        catch (Exception) { }  // an older Windows: the title bar stays light
        try { form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
        catch (Exception) { }
    }

    // The windows are laid out for a plain screen; this sizes one for the screen it is on.
    // Returns the factor.
    public static float Fit(Form form)
    {
        float factor;
        using (Graphics g = form.CreateGraphics()) factor = g.DpiX / 96f;
        if (factor != 1f) form.Scale(new SizeF(factor, factor));
        return factor;
    }

    public static GraphicsPath Round(RectangleF r, float radius)
    {
        float d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
        var path = new GraphicsPath();
        path.AddArc(r.X, r.Y, d, d, 180, 90);
        path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }
}

// Base of the controls the launcher draws itself.
class Painted : Control
{
    protected Painted()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        BackColor = Theme.Back;
    }

    protected Graphics Begin(PaintEventArgs e)
    {
        e.Graphics.Clear(BackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        return e.Graphics;
    }

    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
}

// A rounded button. `Primary` is the one filled with the accent colour; `Result`
// closes the dialog it is in with that answer.
class PillButton : Painted
{
    public bool Primary;
    public DialogResult Result = DialogResult.None;
    bool hot, down;

    public PillButton() { Cursor = Cursors.Hand; }

    protected override void OnMouseEnter(EventArgs e) { hot = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hot = down = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs e) { down = true; Focus(); Invalidate(); base.OnMouseDown(e); }
    protected override void OnMouseUp(MouseEventArgs e) { down = false; Invalidate(); base.OnMouseUp(e); }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Space || e.KeyCode == Keys.Enter) OnClick(EventArgs.Empty);
        base.OnKeyDown(e);
    }

    protected override void OnClick(EventArgs e)
    {
        base.OnClick(e);
        Form form = FindForm();
        if (Result != DialogResult.None && form != null) form.DialogResult = Result;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = Begin(e);
        var area = new RectangleF(0.5f, 0.5f, Width - 1, Height - 1);
        using (GraphicsPath shape = Theme.Round(area, Height * (Primary ? 0.28f : 0.5f)))
        {
            if (Primary)
            {
                Color top = down ? Theme.Accent : hot ? Color.FromArgb(104, 172, 250) : Theme.AccentHot;
                Color bottom = down ? Color.FromArgb(40, 108, 196) : Theme.Accent;
                using (var fill = new LinearGradientBrush(area, top, bottom, 90f)) g.FillPath(fill, shape);
            }
            else
            {
                using (var fill = new SolidBrush(down ? Theme.Line : hot ? Color.FromArgb(32, 40, 62) : Theme.Card)) g.FillPath(fill, shape);
                using (var edge = new Pen(Focused ? Theme.Accent : Theme.Line)) g.DrawPath(edge, shape);
            }
        }
        TextRenderer.DrawText(g, Text, Font, ClientRectangle, Primary ? Color.White : Theme.Text,
                              TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
    }
}

// A rounded panel that groups the settings.
class Card : Panel
{
    public Card()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        BackColor = Theme.Back;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(Theme.Back);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using (GraphicsPath shape = Theme.Round(new RectangleF(0.5f, 0.5f, Width - 1, Height - 1), Width * 0.04f))
        {
            using (var fill = new SolidBrush(Theme.Card)) e.Graphics.FillPath(fill, shape);
            using (var edge = new Pen(Theme.Line)) e.Graphics.DrawPath(edge, shape);
        }
    }
}
