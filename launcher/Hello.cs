// Windows Hello for the passwords inside Mentor (opt-in, in "Sound, USB and sign-in"). After Try Omarchy
// for Windows (github.com/omacom/try-omarchy-windows, MIT, docs/WINDOWS-HELLO.md), which answers the
// guest's sudo with Windows Hello over a root-only port. Mentor asks Windows' own consent prompt
// (UserConsentVerifier), which can say what the permission is for, instead of a WebAuthn passkey.
//
// The system inside asks over the root-only link (org.mentor.host, mentor-host-link there), for its
// PAM (/usr/local/lib/mentor/mentor-hello, before the password in polkit-1 and sudo):
//     {"hello": ID, "why": "what it is for"}   ->   {"hello": ID, "ok": true|false}
// Anything but a yes (no, cancelled, Hello not set up, switched off here, a second request while
// one is open) is a no, and the system asks for the password as before.
//
// UserConsentVerifier is a WinRT class; the .NET Framework that Windows ships cannot call WinRT
// directly, so it is called through its COM interfaces: IUserConsentVerifierInterop (the desktop
// version, which needs a window) and the IAsyncOperation it returns, read with IAsyncInfo.
using System;
using System.Runtime.InteropServices;

static class WindowsHello
{
    [DllImport("combase.dll")] static extern int WindowsCreateString([MarshalAs(UnmanagedType.LPWStr)] string text, int length, out IntPtr hstring);
    [DllImport("combase.dll")] static extern int WindowsDeleteString(IntPtr hstring);
    [DllImport("combase.dll")] static extern int RoGetActivationFactory(IntPtr classId, ref Guid iid, out IntPtr factory);

    const string Class = "Windows.Security.Credentials.UI.UserConsentVerifier";
    static Guid Statics = new Guid("AF4F3F91-564C-4DDC-B8B5-973447627C65");       // IUserConsentVerifierStatics
    static Guid Interop = new Guid("39E050C3-4E74-441A-8DC0-B81104DF949C");       // IUserConsentVerifierInterop
    static Guid AsyncInfo = new Guid("00000036-0000-0000-C000-000000000046");     // IAsyncInfo
    // IAsyncOperation<UserConsentVerificationResult>, the parameterized interface's ID as WinRT works it out.
    static Guid VerificationOperation = new Guid("FD596FFD-2318-558F-9DBE-D21DF43764A5");

    delegate int CheckAvailability(IntPtr self, out IntPtr operation);
    delegate int RequestForWindow(IntPtr self, IntPtr window, IntPtr message, ref Guid iid, out IntPtr operation);
    delegate int GetStatus(IntPtr self, out int status);
    delegate int GetResults(IntPtr self, out int result);
    delegate int QueryInterface(IntPtr self, ref Guid iid, out IntPtr found);

    static T Method<T>(IntPtr item, int slot) where T : class
    {
        IntPtr table = Marshal.ReadIntPtr(item);
        return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(table, slot * IntPtr.Size), typeof(T)) as T;
    }

    static IntPtr Factory(Guid iid)
    {
        IntPtr name, factory;
        if (WindowsCreateString(Class, Class.Length, out name) != 0) return IntPtr.Zero;
        try { return RoGetActivationFactory(name, ref iid, out factory) == 0 ? factory : IntPtr.Zero; }
        finally { WindowsDeleteString(name); }
    }

    // 0 running, 1 done, 2 cancelled, 3 failed; -1 when it cannot be read.
    static int Status(IntPtr operation)
    {
        IntPtr info;
        if (Method<QueryInterface>(operation, 0)(operation, ref AsyncInfo, out info) != 0) return -1;
        try
        {
            int status;
            return Method<GetStatus>(info, 7)(info, out status) == 0 ? status : -1;
        }
        finally { Marshal.Release(info); }
    }

    // Whether Windows Hello is set up for this user on this computer (no prompt is shown).
    public static bool Available()
    {
        try
        {
            IntPtr statics = Factory(Statics);
            if (statics == IntPtr.Zero) return false;
            try
            {
                IntPtr operation;
                if (Method<CheckAvailability>(statics, 6)(statics, out operation) != 0) return false;
                try
                {
                    for (int i = 0; i < 100 && Status(operation) == 0; i++) System.Threading.Thread.Sleep(30);
                    int availability;
                    return Status(operation) == 1 && Method<GetResults>(operation, 8)(operation, out availability) == 0 && availability == 0;
                }
                finally { Marshal.Release(operation); }
            }
            finally { Marshal.Release(statics); }
        }
        catch (Exception) { return false; }  // an older Windows, or no WinRT
    }

    // Shows Windows Hello's prompt with `message`, over `window`. The operation to watch with Done(),
    // or IntPtr.Zero when it could not be shown.
    public static IntPtr Ask(IntPtr window, string message)
    {
        try
        {
            IntPtr interop = Factory(Interop);
            if (interop == IntPtr.Zero) return IntPtr.Zero;
            IntPtr text;
            WindowsCreateString(message, message.Length, out text);
            try
            {
                IntPtr operation;
                return Method<RequestForWindow>(interop, 6)(interop, window, text, ref VerificationOperation, out operation) == 0
                    ? operation : IntPtr.Zero;
            }
            finally
            {
                WindowsDeleteString(text);
                Marshal.Release(interop);
            }
        }
        catch (Exception) { return IntPtr.Zero; }
    }

    delegate int Plain(IntPtr self);

    // Takes the prompt away and lets go of the operation.
    public static void Cancel(IntPtr operation)
    {
        IntPtr info;
        if (Method<QueryInterface>(operation, 0)(operation, ref AsyncInfo, out info) == 0)
        {
            Method<Plain>(info, 9)(info);  // IAsyncInfo.Cancel
            Marshal.Release(info);
        }
        Marshal.Release(operation);
    }

    // Null while the prompt is open; then true for "verified", false for anything else. The operation
    // is let go of once it has answered.
    public static bool? Done(IntPtr operation)
    {
        int status = Status(operation);
        if (status == 0) return null;
        int result = -1;
        if (status == 1) Method<GetResults>(operation, 8)(operation, out result);
        Marshal.Release(operation);
        return status == 1 && result == 0;  // UserConsentVerificationResult.Verified
    }
}
