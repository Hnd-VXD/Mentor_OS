// Windows' time zone, by the name Linux knows it by, for the system inside to follow. After Try Omarchy
// for Windows (github.com/omacom/try-omarchy-windows, MIT, docs/HOST-TIMEZONE.md), which sends it over
// a port of its own and lets a zone chosen inside win; the guest's side here is
// distro/rootfs/usr/local/lib/mentor/mentor-host-link.
//
// Windows calls its zones "GTB Standard Time"; Linux "Europe/Athens". The table between the two is
// Unicode's (CLDR windowsZones), which Windows carries in its own ICU (icu.dll, Windows 10 1903 and
// later). The country of Windows' region settings picks among the cities of one zone.
using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

static class WindowsZone
{
    [DllImport("icu.dll", CharSet = CharSet.Unicode, CallingConvention = CallingConvention.Cdecl)]
    static extern int ucal_getTimeZoneIDForWindowsID(string windowsId, int length,
        [MarshalAs(UnmanagedType.LPStr)] string region, StringBuilder id, int capacity, ref int status);

    // The IANA name of Windows' zone now, or null when it cannot be told.
    public static string Iana()
    {
        string windows;
        try
        {
            TimeZoneInfo.ClearCachedData();  // the user may have changed it since
            windows = TimeZoneInfo.Local.Id;
        }
        catch (Exception) { return null; }
        string region = null;
        try { region = RegionInfo.CurrentRegion.TwoLetterISORegionName; }
        catch (Exception) { }
        foreach (string where in new[] { region, null })
        {
            try
            {
                var id = new StringBuilder(128);
                int status = 0;
                int length = ucal_getTimeZoneIDForWindowsID(windows, windows.Length, where, id, id.Capacity, ref status);
                if (status <= 0 && length > 0) return id.ToString(0, length);
            }
            catch (DllNotFoundException) { return null; }
            catch (EntryPointNotFoundException) { return null; }
        }
        return null;
    }
}
