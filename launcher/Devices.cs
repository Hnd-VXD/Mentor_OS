// The sound devices Mentor uses on Windows, and the small window where they are chosen ("Devices…" in
// the launcher window). After Try Omarchy for Windows (github.com/omacom/try-omarchy-windows, MIT,
// docs/AUDIO-DEVICES.md): Mentor's own QEMU is Try Omarchy's WINQ-EMU runtime (qemu\README.txt), whose
// SDL sound opens the device named in OMARCHY_SDL_OUTPUT_DEVICE_NAME / OMARCHY_SDL_INPUT_DEVICE_NAME
// (its patch 0013) and falls back to Windows' default when that one is gone, and keeps the microphone
// working with no microphone plugged in (patch 0022). The names are SDL's own, so they are listed with
// the SDL2.dll that QEMU uses.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class AudioDevices
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr LoadLibrary(string path);
    [DllImport("SDL2.dll", CallingConvention = CallingConvention.Cdecl)] static extern int SDL_InitSubSystem(uint flags);
    [DllImport("SDL2.dll", CallingConvention = CallingConvention.Cdecl)] static extern void SDL_QuitSubSystem(uint flags);
    [DllImport("SDL2.dll", CallingConvention = CallingConvention.Cdecl)] static extern int SDL_GetNumAudioDevices(int capture);
    [DllImport("SDL2.dll", CallingConvention = CallingConvention.Cdecl)] static extern IntPtr SDL_GetAudioDeviceName(int index, int capture);
    const uint SDL_INIT_AUDIO = 0x10;

    // The speakers and the microphones Windows has now, by SDL's names; null when they cannot be listed.
    public static List<string>[] List(string qemuDir)
    {
        List<string>[] found = null;
        // On a thread of its own: SDL starts Windows' audio (COM) on the thread that asks.
        var thread = new Thread(() => {
            try
            {
                if (LoadLibrary(Path.Combine(qemuDir, "SDL2.dll")) == IntPtr.Zero) return;
                if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) return;
                try
                {
                    var both = new[] { new List<string>(), new List<string>() };
                    for (int capture = 0; capture < 2; capture++)
                    {
                        int count = SDL_GetNumAudioDevices(capture);
                        for (int i = 0; i < count; i++)
                        {
                            string name = Utf8(SDL_GetAudioDeviceName(i, capture));
                            if (!string.IsNullOrEmpty(name) && !both[capture].Contains(name)) both[capture].Add(name);
                        }
                    }
                    found = both;
                }
                finally { SDL_QuitSubSystem(SDL_INIT_AUDIO); }
            }
            catch (Exception) { }  // a QEMU without SDL2.dll (the installer's): no list
        }) { IsBackground = true };
        thread.SetApartmentState(ApartmentState.MTA);
        thread.Start();
        thread.Join(5000);
        return found;
    }

    static string Utf8(IntPtr text)
    {
        if (text == IntPtr.Zero) return null;
        int length = 0;
        while (Marshal.ReadByte(text, length) != 0) length++;
        var bytes = new byte[length];
        Marshal.Copy(text, bytes, 0, length);
        return Encoding.UTF8.GetString(bytes);
    }
}

