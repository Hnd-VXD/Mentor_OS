// A USB device of Windows' given to Mentor, chosen before the start (experimental). After Try Omarchy
// for Windows (github.com/omacom/try-omarchy-windows, MIT, docs/USB-DEVICES.md, app/usb_*.go), whose
// runtime is Mentor's own QEMU: its patches 0003 and 0006 let a device be attached exactly at the USB
// port where it was chosen, and refuse when another one is there now.
//
// Devices are listed by a QEMU that runs no system (-machine none), through its libusb, which takes
// nothing away from Windows. The chosen one is attached once Mentor has started (QMP device_add), so a
// device that is missing, busy, or kept by its Windows driver never stops a start: it is only written
// to launcher.log, and the system inside is told (a card in the chat, mentor-host-link).
//
// What works depends on the device's Windows driver: libusb can only take a device whose driver is
// WinUSB (or libusbK), and most devices have their own. Mentor installs no driver.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Management;
using System.Text.RegularExpressions;
using System.Threading;

class UsbDevice
{
    public int Bus, Address, Vendor, Product;
    public string Port = "", Name = "";

    // As kept in Mentor.settings: bus, port, vendor, product and the name, for showing it while it is unplugged.
    public override string ToString()
    {
        return Bus + "|" + Port + "|" + Vendor.ToString("x4") + "|" + Product.ToString("x4") + "|" + Name.Replace("|", "/");
    }

    public static UsbDevice Parse(string saved)
    {
        string[] parts = (saved ?? "").Split('|');
        if (parts.Length < 5) return null;
        try
        {
            return new UsbDevice { Bus = int.Parse(parts[0]), Port = parts[1], Vendor = int.Parse(parts[2], NumberStyles.HexNumber),
                                   Product = int.Parse(parts[3], NumberStyles.HexNumber), Name = parts[4] };
        }
        catch (FormatException) { return null; }
        catch (OverflowException) { return null; }
    }

    public bool Same(UsbDevice other)
    {
        return other != null && Bus == other.Bus && Port == other.Port && Vendor == other.Vendor && Product == other.Product;
    }

    public string Label { get { return Name + "  (port " + Bus + "-" + Port + ")"; } }
}

static class UsbDevices
{
    static readonly Regex Row = new Regex(@"^\s*Bus (\d+), Addr (\d+), Port ([0-9.]+), Speed [^\r\n]+\r?\n\s*Class ([0-9a-fA-F]{2}): USB device ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})(?:, ([^\r\n]*))?",
                                          RegexOptions.Multiline);

    // What is plugged in now, or null when it cannot be listed (the installer's QEMU, which has no libusb).
    public static List<UsbDevice> List(string qemuDir)
    {
        string qemu = System.IO.Path.Combine(qemuDir, "qemu-system-x86_64.exe");
        if (!System.IO.File.Exists(System.IO.Path.Combine(qemuDir, "libusb-1.0.dll")) || !System.IO.File.Exists(qemu)) return null;
        int port;
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        Process process;
        try
        {
            process = Process.Start(new ProcessStartInfo(qemu, "-machine none -nodefaults -display none -S -qmp tcp:127.0.0.1:" + port + ",server=on,wait=off") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true });
        }
        catch (Exception) { return null; }
        try
        {
            var qmp = new Qmp(port);
            object result = null;
            string error = "QEMU is not reachable";
            for (int i = 0; i < 50 && error == "QEMU is not reachable"; i++)
            {
                error = qmp.Execute("human-monitor-command", new Dictionary<string, object> { { "command-line", "info usbhost" } }, 5000, out result);
                if (error == "QEMU is not reachable") Thread.Sleep(100);
            }
            if (error != null) return null;
            qmp.Execute("quit", null, 2000);
            return Parse(result as string ?? "");
        }
        finally
        {
            try { if (!process.WaitForExit(3000)) process.Kill(); } catch (Exception) { }
        }
    }

    static List<UsbDevice> Parse(string text)
    {
        var found = new List<UsbDevice>();
        Dictionary<string, string> windowsNames = null;
        foreach (Match row in Row.Matches(text))
        {
            var device = new UsbDevice {
                Bus = int.Parse(row.Groups[1].Value), Address = int.Parse(row.Groups[2].Value), Port = row.Groups[3].Value,
                Vendor = int.Parse(row.Groups[5].Value, NumberStyles.HexNumber), Product = int.Parse(row.Groups[6].Value, NumberStyles.HexNumber),
                Name = row.Groups[7].Value.Trim() };
            if (device.Address < 1 || device.Address > 127 || device.Port.Length > 27) continue;
            int hubClass = int.Parse(row.Groups[4].Value, NumberStyles.HexNumber);
            if (hubClass == 9) continue;  // a hub: nothing to give
            if (device.Name == "")
            {
                // The device does not say its name to libusb: Windows' name for it, if it has one.
                if (windowsNames == null) windowsNames = WindowsNames();
                string name;
                device.Name = windowsNames.TryGetValue(device.Vendor.ToString("X4") + ":" + device.Product.ToString("X4"), out name)
                    ? name : "USB device " + device.Vendor.ToString("x4") + ":" + device.Product.ToString("x4");
            }
            found.Add(device);
        }
        return found;
    }

    // Windows' names of the USB devices it has, by vendor and product, skipping the generic ones.
    static Dictionary<string, string> WindowsNames()
    {
        var names = new Dictionary<string, string>();
        try
        {
            using (var search = new ManagementObjectSearcher("SELECT Name, DeviceID FROM Win32_PnPEntity WHERE DeviceID LIKE 'USB%'"))
                foreach (ManagementBaseObject entity in search.Get())
                {
                    string id = (entity["DeviceID"] as string ?? "").ToUpperInvariant(), name = entity["Name"] as string ?? "";
                    Match m = Regex.Match(id, @"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})");
                    if (!m.Success || name == "" || name.StartsWith("USB Composite", StringComparison.OrdinalIgnoreCase) ||
                        name.StartsWith("USB Input Device", StringComparison.OrdinalIgnoreCase)) continue;
                    string key = m.Groups[1].Value + ":" + m.Groups[2].Value;
                    if (!names.ContainsKey(key)) names[key] = name;
                }
        }
        catch (Exception) { }
        return names;
    }

    // Gives the device saved in the settings to the running system. Null when it worked, otherwise why not.
    public static string Attach(Qmp qmp, string saved)
    {
        UsbDevice wanted = UsbDevice.Parse(saved);
        if (wanted == null) return "the saved USB device is not readable";
        object result;
        string error = qmp.Execute("human-monitor-command", new Dictionary<string, object> { { "command-line", "info usbhost" } }, 5000, out result);
        if (error != null) return error;
        UsbDevice now = null;
        foreach (UsbDevice device in Parse(result as string ?? "")) if (device.Same(wanted)) now = device;
        if (now == null) return "it is not plugged in at the same USB port";
        return qmp.Execute("device_add", new Dictionary<string, object> {
            { "driver", "usb-host" }, { "id", "mentor-usb" }, { "bus", "xhci.0" }, { "hostbus", now.Bus }, { "hostaddr", now.Address },
            { "hostport", now.Port }, { "vendorid", now.Vendor }, { "productid", now.Product }, { "auto-reconnect", false } }, 10000);
    }
}
