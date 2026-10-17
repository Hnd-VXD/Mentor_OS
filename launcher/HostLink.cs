// The launcher's end of the root-only link to the system inside (the virtio port org.mentor.host;
// distro/rootfs/usr/local/lib/mentor/mentor-host-link is the other end). One JSON object a line:
//   to the system:   {"timezone": "Europe/Athens"}    Windows' time zone (TimeZone.cs), when it changes
//                    {"hello-on": true|false}          whether Windows Hello is to be asked (Hello.cs)
//                    {"hello": ID, "ok": bool}         Windows Hello's answer
//                    {"notice": {...}}                 a card for the chat (a USB device that was not given)
//                    {"diagnostics": ID}               asks for the system's logs (Diagnostics.cs)
//   from it:         {"want": "timezone"}              it is listening: everything it should know is sent
//                    {"hello": ID, "why": "..."}       Windows Hello, please, for this
//                    {"diagnostics": ID, "data": "<base64 .tar.gz>"} or {"diagnostics": ID, "error": "..."}
// What is sent while nobody listens inside is lost (QEMU drops it), so what matters is sent again
// at each "want".
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class HostLink
{
    readonly Control window;
    readonly Process qemu;
    readonly Qmp qmp;
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 64 << 20 };
    readonly object sendLock = new object();
    readonly List<Dictionary<string, object>> notices = new List<Dictionary<string, object>>();
    NetworkStream stream;
    string sentZone;
    bool listening;  // the system inside has said it listens, since the link opened
    bool usbTried;
    IntPtr helloOperation = IntPtr.Zero;
    string helloId;
    DateTime helloAsked, helloQuietUntil;
    // The system's logs, when asked for: the id asked with, and what came back.
    public string DiagnosticsId, DiagnosticsData, DiagnosticsError;
    public readonly ManualResetEvent DiagnosticsDone = new ManualResetEvent(false);

    public HostLink(Control window, int port, Process qemu, Qmp qmp)
    {
        this.window = window;
        this.qemu = qemu;
        this.qmp = qmp;
        new Thread(() => Read(port)) { IsBackground = true }.Start();
    }

    void Read(int port)
    {
        TcpClient client = Program.Connect(port);
        if (client == null) return;
        lock (sendLock) stream = client.GetStream();
        try
        {
            var reader = new StreamReader(stream, new UTF8Encoding(false));
            string line;
            while ((line = reader.ReadLine()) != null)
            {
                Dictionary<string, object> message;
                try { message = json.Deserialize<Dictionary<string, object>>(line); }
                catch (Exception) { continue; }
                if (message == null) continue;
                object id;
                if (message.TryGetValue("diagnostics", out id) && id as string == DiagnosticsId)
                {
                    object data, error;
                    DiagnosticsData = message.TryGetValue("data", out data) ? data as string : null;
                    DiagnosticsError = message.TryGetValue("error", out error) ? error as string : null;
                    DiagnosticsDone.Set();
                    continue;
                }
                try { window.BeginInvoke((Action)(() => Handle(message))); }
                catch (InvalidOperationException) { return; }  // the window is gone
            }
        }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    public bool Send(Dictionary<string, object> message)
    {
        byte[] line = Encoding.UTF8.GetBytes(json.Serialize(message) + "\n");
        lock (sendLock)
        {
            if (stream == null) return false;
            try { stream.Write(line, 0, line.Length); return true; }
            catch (IOException) { return false; }
            catch (ObjectDisposedException) { return false; }
        }
    }

    void Handle(Dictionary<string, object> message)
    {
        object value;
        if (message.TryGetValue("want", out value))
        {
            listening = true;
            Again();
            lock (notices)
            {
                foreach (var notice in notices) Send(new Dictionary<string, object> { { "notice", notice } });
                notices.Clear();
            }
        }
        if (message.TryGetValue("hello", out value) && message.ContainsKey("why")) OnHello(value as string, message["why"] as string);
    }

    // Everything the system inside should know, again (it has just started listening, or Windows woke up).
    public void Again()
    {
        sentZone = null;
        SendZone();
        Send(new Dictionary<string, object> { { "hello-on", Program.HelloOn } });
    }

    // A card for the chat, now or as soon as the system inside listens.
    public void Notice(string level, string title, string text, string prompt)
    {
        var notice = new Dictionary<string, object> { { "level", level }, { "title", title }, { "text", text } };
        if (prompt != null) notice["prompt"] = prompt;
        if (listening && Send(new Dictionary<string, object> { { "notice", notice } })) return;
        lock (notices) notices.Add(notice);
    }

    void SendZone()
    {
        string zone = WindowsZone.Iana();
        if (zone == null || zone == sentZone) return;
        if (!Send(new Dictionary<string, object> { { "timezone", zone } })) return;
        if (sentZone != null) Program.Note("Windows' time zone is now " + zone);
        sentZone = zone;
    }

    int ticks;

    // Every two seconds, from the launcher's timer.
    public void Tick()
    {
        if (++ticks % 5 == 0) SendZone();  // Windows' time zone, when it has changed
        if (!usbTried && Program.Usb != "" && !qemu.HasExited) AttachUsb();
    }

    // The USB device chosen for this start, once QEMU answers. Once only: a device that would not go
    // is left to Windows, and the user is told in the chat.
    void AttachUsb()
    {
        object unused;
        if (qmp.Execute("query-status", null, 1000, out unused) != null) return;  // not yet
        usbTried = true;
        UsbDevice wanted = UsbDevice.Parse(Program.Usb);
        string name = wanted != null ? wanted.Name : "the USB device";
        string error = UsbDevices.Attach(qmp, Program.Usb);
        Program.Note(error == null ? "gave " + name + " to the system" : "could not give " + name + " to the system: " + error);
        if (error == null) return;
        Notice("warning", name + " could not be given to Mentor",
               error.Contains("not plugged in") ? "It was not plugged in where it was chosen; it stays with Windows."
                                                : "Windows keeps it with its own driver; it stays usable in Windows.",
               "Mentor.exe tried to give the USB device \"" + name + "\" (chosen in its Sound, USB and sign-in settings) to " +
               "this system at its start, and QEMU said: " + error + "\n\nExplain to me in two short sentences, in simple words, " +
               "what this means and what I can do. /etc/mentor/WINDOWS.md, \"USB devices\", says how it works.");
    }

    void OnHello(string id, string why)
    {
        Func<bool, bool> answer = ok => Send(new Dictionary<string, object> { { "hello", id }, { "ok", ok } });
        if (!Program.HelloOn || helloOperation != IntPtr.Zero || DateTime.UtcNow < helloQuietUntil || string.IsNullOrEmpty(id))
        {
            answer(false);  // the password, as always
            return;
        }
        string message = "Mentor wants to " + (string.IsNullOrEmpty(why) ? "make a change to the system" : why.TrimEnd('.'));
        if (Program.HelloTest != null)
        {
            Program.Note("Windows Hello (test, no prompt) for: " + message);
            answer(Program.HelloTest == "yes");
            return;
        }
        if (message.Length > 240) message = message.Substring(0, 240) + "…";
        // Over Mentor's window, so that the prompt is in front of it; over this program's own when that will not do.
        IntPtr operation = WindowsHello.Ask(VmWindow.Find(qemu), message);
        if (operation == IntPtr.Zero) operation = WindowsHello.Ask(window.Handle, message);
        if (operation == IntPtr.Zero)
        {
            Program.Note("Windows Hello could not be asked");
            answer(false);
            return;
        }
        helloOperation = operation;
        helloId = id;
        helloAsked = DateTime.UtcNow;
        var watch = new System.Windows.Forms.Timer { Interval = 250 };
        watch.Tick += (s, e) => { if (WatchHello()) { watch.Stop(); watch.Dispose(); } };
        watch.Start();
    }

    // True once the prompt has answered (or was given up on after 100 seconds).
    bool WatchHello()
    {
        bool? done = WindowsHello.Done(helloOperation);
        if (done == null && (DateTime.UtcNow - helloAsked).TotalSeconds < 100) return false;
        if (done == null) WindowsHello.Cancel(helloOperation);
        bool ok = done == true;
        Program.Note("Windows Hello: " + (ok ? "yes" : "no"));
        if (!ok) helloQuietUntil = DateTime.UtcNow.AddSeconds(3);  // not prompt after prompt
        Send(new Dictionary<string, object> { { "hello", helloId }, { "ok", ok } });
        helloOperation = IntPtr.Zero;
        helloId = null;
        return true;
    }
}
