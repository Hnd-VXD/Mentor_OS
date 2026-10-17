// One volume for Windows and Mentor (distro/rootfs/etc/mentor/WINDOWS.md, "One volume"): Windows' master
// volume and mute, read five times a second and sent to the system inside when they change (HostLink), and
// set when the user changes Mentor's own volume. Inside, mentor-volume makes Mentor's volume show Windows'
// without lowering the sound a second time. Before this, 22% on Windows and 70% in Mentor sounded like 15%.
//
// Windows' Core Audio (IMMDeviceEnumerator, IAudioEndpointVolume) through COM, on a thread of its own: the
// default output can change (headphones), so it is looked up again every few seconds.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

class WindowsVolume
{
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class MMDeviceEnumerator { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
        [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
    }

    [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioEndpointVolume
    {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int GetChannelCount(out uint count);
        [PreserveSig] int SetMasterVolumeLevel(float levelDB, ref Guid context);
        [PreserveSig] int SetMasterVolumeLevelScalar(float level, ref Guid context);
        [PreserveSig] int GetMasterVolumeLevel(out float levelDB);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
        [PreserveSig] int SetChannelVolumeLevel(uint channel, float levelDB, ref Guid context);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
        [PreserveSig] int GetChannelVolumeLevel(uint channel, out float levelDB);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint channel, out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }

    const int eRender = 0, eMultimedia = 1, CLSCTX_ALL = 23;
    static Guid ourContext = new Guid("6d3b8a7e-4f1c-4c2e-9a3b-6e7d2c1f0a58");  // marks the changes made here

    readonly Func<Dictionary<string, object>, bool> send;
    readonly object wantedLock = new object();
    float[] wanted;            // {volume, mute 0/1} the system inside asked for, not yet set
    bool sendAgain;            // send the current one even when unchanged (the system inside asks, "want")
    float lastVolume = -1;     // what was last sent or set
    bool lastMute;
    volatile bool stopped;     // this run of the system has ended (each run has its own link)

    public void Stop() { stopped = true; }

    public WindowsVolume(Func<Dictionary<string, object>, bool> send)
    {
        this.send = send;
        var thread = new Thread(Run) { IsBackground = true, Name = "Windows volume" };
        thread.SetApartmentState(ApartmentState.MTA);
        thread.Start();
    }

    // From the system inside: the user changed Mentor's volume.
    public void Set(double volume, bool mute)
    {
        lock (wantedLock) wanted = new[] { (float)Math.Max(0, Math.Min(1, volume)), mute ? 1f : 0f };
    }

    // The system inside has just started listening: tell it Windows' volume even if unchanged.
    public void Again()
    {
        lock (wantedLock) sendAgain = true;
    }

    void Run()
    {
        IAudioEndpointVolume endpoint = null;
        DateTime lookedUp = DateTime.MinValue;
        while (!stopped)
        {
            Thread.Sleep(200);
            try
            {
                if (endpoint == null || DateTime.UtcNow - lookedUp > TimeSpan.FromSeconds(3))
                {
                    if (endpoint != null) Marshal.ReleaseComObject(endpoint);
                    endpoint = Endpoint();
                    lookedUp = DateTime.UtcNow;
                }
                if (endpoint == null) continue;  // no sound output on Windows now
                float[] asked;
                bool again;
                lock (wantedLock)
                {
                    asked = wanted;
                    wanted = null;
                    again = sendAgain;
                    sendAgain = false;
                }
                if (asked != null)
                {
                    endpoint.SetMasterVolumeLevelScalar(asked[0], ref ourContext);
                    endpoint.SetMute(asked[1] > 0, ref ourContext);
                    lastVolume = asked[0];
                    lastMute = asked[1] > 0;
                    continue;  // its own change is not sent back
                }
                float volume;
                bool mute;
                if (endpoint.GetMasterVolumeLevelScalar(out volume) != 0 || endpoint.GetMute(out mute) != 0) continue;
                if (!again && Math.Abs(volume - lastVolume) < 0.005 && mute == lastMute) continue;
                if (send(new Dictionary<string, object> { { "volume", Math.Round(volume, 3) }, { "mute", mute } }))
                {
                    lastVolume = volume;
                    lastMute = mute;
                }
                else if (again) lock (wantedLock) sendAgain = true;  // the link is not there yet: again
            }
            catch (Exception)
            {
                endpoint = null;  // the device went away: looked up again
            }
        }
    }

    static IAudioEndpointVolume Endpoint()
    {
        var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        try
        {
            IMMDevice device;
            if (enumerator.GetDefaultAudioEndpoint(eRender, eMultimedia, out device) != 0 || device == null) return null;
            try
            {
                Guid iid = typeof(IAudioEndpointVolume).GUID;
                object found;
                if (device.Activate(ref iid, CLSCTX_ALL, IntPtr.Zero, out found) != 0) return null;
                return (IAudioEndpointVolume)found;
            }
            finally { Marshal.ReleaseComObject(device); }
        }
        finally { Marshal.ReleaseComObject(enumerator); }
    }

    // `Mentor.exe --volume`: what it reads now, for a check (changes nothing).
    public static string Describe()
    {
        IAudioEndpointVolume endpoint = Endpoint();
        if (endpoint == null) return "no sound output on Windows";
        float volume;
        bool mute;
        endpoint.GetMasterVolumeLevelScalar(out volume);
        endpoint.GetMute(out mute);
        Marshal.ReleaseComObject(endpoint);
        return "Windows' volume " + Math.Round(volume * 100) + "%" + (mute ? ", muted" : "");
    }
}
