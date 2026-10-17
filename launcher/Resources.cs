// How much of the computer Mentor gets: "balanced" (the default), "maximum" (what Windows is not using
// right now) or "manual" (the sliders). After Try Omarchy for Windows (github.com/omacom/try-omarchy-windows,
// MIT, docs/USER-GUIDE.md "CPU and RAM profiles", app/resource_profile.go). Worked out at every start,
// as what Windows has free changes.
using System;
using System.Runtime.InteropServices;
using System.Threading;

static class Resources
{
    [StructLayout(LayoutKind.Sequential)]
    struct MemoryStatus
    {
        public uint length, load;
        public ulong totalPhysical, availablePhysical, totalPageFile, availablePageFile, totalVirtual, availableVirtual, extended;
    }
    [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
    [DllImport("kernel32.dll")] static extern bool GetSystemTimes(out long idle, out long kernel, out long user);

    public const string Balanced = "balanced", Maximum = "maximum", Manual = "manual";
    const int MostCpus = 64, MostGB = 64, LeastGB = 2;

    // The computer's memory in GB, and how much of it is free now (both 0 when Windows will not say).
    public static void Memory(out double totalGB, out double freeGB)
    {
        var status = new MemoryStatus { length = (uint)Marshal.SizeOf(typeof(MemoryStatus)) };
        if (GlobalMemoryStatusEx(ref status))
        {
            totalGB = status.totalPhysical / (double)(1L << 30);
            freeGB = status.availablePhysical / (double)(1L << 30);
        }
        else totalGB = freeGB = 0;
    }

    // How busy the processors are, from 0 to 1, over three quarters of a second; -1 when unknown.
    static double Busy()
    {
        long idle1, kernel1, user1, idle2, kernel2, user2;
        if (!GetSystemTimes(out idle1, out kernel1, out user1)) return -1;
        Thread.Sleep(750);
        if (!GetSystemTimes(out idle2, out kernel2, out user2)) return -1;
        long total = (kernel2 - kernel1) + (user2 - user1), idle = idle2 - idle1;  // kernel time includes idle
        if (total <= 0 || idle < 0 || idle > total) return -1;
        return (total - idle) / (double)total;
    }

    // Memory (GB) and processors for a start with this profile. `manualGB` and `manualCpus` are the
    // sliders' values, used by "manual".
    public static int[] Plan(string profile, int manualGB, int manualCpus)
    {
        int cores = Environment.ProcessorCount;
        if (profile == Manual) return new[] { manualGB, Math.Max(1, Math.Min(cores, manualCpus)) };
        double total, free;
        Memory(out total, out free);
        // Balanced: half the processors, 4 to 8 (the desktop is drawn by them when the graphics card
        // is not); a third of the memory, 4 to 8 GB, as long as Windows keeps 2 GB of what is free now.
        int cpus = Math.Min(cores, Math.Max(4, Math.Min(8, cores / 2)));
        int gb = total > 0 ? Math.Max(4, Math.Min(8, (int)(total / 3))) : 6;
        if (free > 0 && gb > free - 2) gb = Math.Max(LeastGB, (int)(free - 2));
        if (profile != Maximum) return new[] { gb, cpus };
        // Maximum: what Windows is not using now, less some room for it: two processors (an eighth of
        // them on larger computers) and 4 GB of memory (an eighth on larger ones).
        double busy = Busy();
        // Never less than Balanced gives.
        if (busy >= 0)
            cpus = Math.Max(cpus, Math.Min(Math.Min(cores, MostCpus), (int)Math.Floor(cores * (1 - busy)) - Math.Max(2, (cores + 7) / 8)));
        if (total > 0 && free > 0)
        {
            int most = (int)Math.Floor(Math.Min(total, free) - Math.Max(4, total / 8));
            if (most >= LeastGB) gb = Math.Min(MostGB, Math.Max(gb, most));
        }
        return new[] { gb, cpus };
    }
}
