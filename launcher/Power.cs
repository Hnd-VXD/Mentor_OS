// Windows going to sleep, waking, and shutting down, while Mentor runs. After Try Omarchy for
// Windows (github.com/omacom/try-omarchy-windows, MIT, docs/WINDOWS-SLEEP.md):
//  - before Windows sleeps, the system inside is paused (QMP "stop"), and it goes on when Windows
//    wakes ("cont"), only if it was running and was paused from here. Without this, Windows froze
//    QEMU wherever it was, and the system inside took the gap for hangs (etc/mentor/BOOT.md, "When
//    Windows sleeps"). RegisterSuspendResumeNotification asks for the notice on computers with Modern
//    Standby as well, where Windows otherwise stops desktop programs without telling them;
//  - when Windows shuts down or signs out, the system inside is shut down properly (its power
//    button), with up to ten seconds for it, instead of losing its power with Windows.
// The guest's clock needs nothing: measured on WHPX (2026-10-17), it stays right through a pause.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Forms;

class PowerWatch
{
    const int WM_POWERBROADCAST = 0x0218, WM_QUERYENDSESSION = 0x0011, WM_ENDSESSION = 0x0016;
    const int PBT_APMSUSPEND = 0x4, PBT_APMRESUMESUSPEND = 0x7, PBT_APMRESUMEAUTOMATIC = 0x12;

    [DllImport("user32.dll")] static extern IntPtr RegisterSuspendResumeNotification(IntPtr recipient, int flags);
    [DllImport("user32.dll")] static extern bool UnregisterSuspendResumeNotification(IntPtr handle);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool ShutdownBlockReasonCreate(IntPtr hwnd, string reason);
    [DllImport("user32.dll")] static extern bool ShutdownBlockReasonDestroy(IntPtr hwnd);

    readonly Form window;
    readonly Qmp qmp;
    readonly Process qemu;
    IntPtr registration;
    bool pausedForSleep;  // paused from here when Windows went to sleep, and not yet continued

    // Something to tell the system inside when Windows has woken up (feature: it looks at the host again).
    public event Action Woke;

    public PowerWatch(Form window, Qmp qmp, Process qemu)
    {
        this.window = window;
        this.qmp = qmp;
        this.qemu = qemu;
        try { registration = RegisterSuspendResumeNotification(window.Handle, 0); }  // DEVICE_NOTIFY_WINDOW_HANDLE
        catch (EntryPointNotFoundException) { }  // before Windows 8: the ordinary broadcast only
        if (registration == IntPtr.Zero) Program.Note("no suspend notification registered; the broadcast only");
        window.FormClosed += (s, e) => {
            if (registration != IntPtr.Zero) UnregisterSuspendResumeNotification(registration);
            registration = IntPtr.Zero;
        };
    }

    // From the window's WndProc. True when the message was answered here.
    public bool Handle(ref Message m)
    {
        if (m.Msg == WM_POWERBROADCAST)
        {
            int what = m.WParam.ToInt32();
            if (what == PBT_APMSUSPEND) Sleeping();
            else if (what == PBT_APMRESUMESUSPEND || what == PBT_APMRESUMEAUTOMATIC) Waking();
            m.Result = (IntPtr)1;
            return true;
        }
        if (m.Msg == WM_QUERYENDSESSION)
        {
            // Yes at once; the work is done when Windows says it is really ending (WM_ENDSESSION).
            if (!qemu.HasExited) ShutdownBlockReasonCreate(window.Handle, "Mentor is shutting down");
            m.Result = (IntPtr)1;
            return true;
        }
        if (m.Msg == WM_ENDSESSION)
        {
            if (m.WParam != IntPtr.Zero) Ending();
            ShutdownBlockReasonDestroy(window.Handle);
            m.Result = IntPtr.Zero;
            return true;
        }
        return false;
    }

    string Status()
    {
        object result;
        if (qmp.Execute("query-status", null, 1500, out result) != null) return null;
        var status = result as Dictionary<string, object>;
        return status != null ? status["status"] as string : null;
    }

    void Sleeping()
    {
        if (qemu.HasExited || pausedForSleep) return;
        string status = Status();
        if (status != "running")
        {
            Program.Note("Windows is going to sleep; the system was " + (status ?? "not answering") + ", left as it is");
            return;
        }
        string error = qmp.Execute("stop", null, 1500);
        pausedForSleep = error == null;
        Program.Note("Windows is going to sleep: " + (error == null ? "paused the system" : "could not pause it: " + error));
    }

    void Waking()
    {
        // Windows sends one notice for the wake that it did by itself and another once the user is
        // back; the first one that arrives does it.
        if (!pausedForSleep || qemu.HasExited) { if (Woke != null) Woke(); return; }
        string status = Status();
        if (status == "paused")
        {
            string error = qmp.Execute("cont", null, 3000);
            Program.Note("Windows woke up: " + (error == null ? "the system goes on" : "could not continue it: " + error));
            if (error != null) return;  // tried again at the next notice
        }
        else Program.Note("Windows woke up; the system was " + (status ?? "not answering") + ", left as it is");
        pausedForSleep = false;
        if (Woke != null) Woke();
    }

    // Windows is shutting down or signing out: the system inside is shut down properly, as from its own
    // menu, within the ten seconds that are fair to ask of Windows.
    void Ending()
    {
        if (qemu.HasExited) return;
        Program.Note("Windows is shutting down: shutting the system down");
        if (pausedForSleep) qmp.Execute("cont", null, 1500);
        qmp.Execute("system_powerdown", null, 1500);
        bool gone = qemu.WaitForExit(9000);
        Program.Note(gone ? "the system shut down in time" : "the system did not shut down in time");
    }
}
