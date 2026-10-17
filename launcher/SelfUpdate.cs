// Mentor.exe updating itself, after Try Omarchy for Windows (github.com/omacom/try-omarchy-windows,
// MIT, app/update*.go): at start it looks for a newer launcher in a signed feed, downloads and checks
// it while Mentor runs, puts it in place at the next start, and goes back to the one before when the
// new one does not come up.
//
// The feed is the GitHub release "updates" of Hnd-VXD/Mentor_OS (the one that carries the image's
// updates), with three files that build/publish-launcher.ps1 puts there:
//     launcher.json      {"version": 202610180930, "file": "Mentor-202610180930.exe", "size": n,
//                         "sha256": "...", "summary": "...", "built": "..."}
//     launcher.json.sig  `ssh-keygen -Y sign -n mentor-launcher` of launcher.json, with Mentor's
//                        update key ($HOME\.mentor\update-signing-key on the maker's PC)
//     Mentor-VERSION.exe the program
// Only a launcher.json signed by the key built into this program (the public half that the images
// carry in etc/mentor/update-signers) and only a program with exactly its size and SHA-256 is used.
// The namespace "mentor-launcher" keeps a signature of an image update (namespace "mentor-update")
// from passing for one of these.
//
// The signature is checked here, in C#: the .NET Framework 4 that Windows ships has no Ed25519, and
// neither has Windows' own CNG. Ed25519 (RFC 8032) is written out below with System.Numerics'
// BigInteger: slow by the standards of cryptographic libraries (a few milliseconds a signature) and
// not constant-time, which does not matter for checking a public signature. Calling Windows'
// ssh-keygen instead would depend on the optional OpenSSH client being installed.
//
// What is where, beside Mentor.exe in launcher-update\:
//     Mentor-VERSION.exe, staged.json   a new launcher, downloaded and checked, for the next start
//     state.json                       a new launcher on trial: {"version", "previous", "tries"}
//     Mentor.previous.exe              the one before it: the way back
//     alive                            written by a new launcher as soon as it runs
//     failed                           versions that did not come up: not tried again
//     checked                          when the feed was last read (once in 12 hours)
//     log.txt                          what happened, for the diagnostics file
//
// A new launcher is on trial until its first start of the system works (the system reports its
// desktop, or ran for three minutes without trouble). It is put back when:
//  - it does not run at all: the old one starts it and waits up to a minute for "alive"; it then
//    goes on itself;
//  - the start under it failed (QEMU stopped with an error, the system never came up): the next start
//    of Mentor.exe, which is the new one, puts the old one back and starts it.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

static class SelfUpdate
{
    // MENTOR_LAUNCHER_UPDATES: another address for the feed (a test server), ending in "/".
    static readonly string Feed = Environment.GetEnvironmentVariable("MENTOR_LAUNCHER_UPDATES") ??
                                  "https://github.com/Hnd-VXD/Mentor_OS/releases/download/updates/";
    const string Namespace = "mentor-launcher";
    const long MaxProgram = 32L << 20;
    static readonly TimeSpan Every = TimeSpan.FromHours(12);
    static string dir, root;
    static bool trial;  // this launcher is the new one, on trial
    static DateTime runStarted;

    public static long Version { get { return LauncherBuild.Version; } }

    // One short line for the Mentor window (LauncherWindow shows it under the name): that this launcher
    // was just put in place, or that a newer one is downloaded for the next start. Null: nothing to say.
    // The user asked to be told both (2026-10-17); the update itself still needs no click.
    public static string Note;
    public static event Action NoteChanged;  // raised on the checking thread: the window Invokes
    const string UpdatedNote = "Updated to the newest version.";  // under Start: short
    const string ReadyNote = "A new version is ready for next time.";

    static void SetNote(string note)
    {
        Note = note;
        Action changed = NoteChanged;
        if (changed != null) changed();
    }

    static string PathOf(string name) { return Path.Combine(dir, name); }

    public static void Log(string text)
    {
        try
        {
            string log = PathOf("log.txt");
            if (File.Exists(log) && new FileInfo(log).Length > 256 * 1024) File.Delete(log);
            File.AppendAllText(log, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + Version + "  " + text + "\r\n");
        }
        catch (Exception) { }
    }

    class State { public long version, previous; public int tries; }

    static State ReadState()
    {
        try { return new JavaScriptSerializer().Deserialize<State>(File.ReadAllText(PathOf("state.json"))); }
        catch (Exception) { return null; }
    }

    static void WriteState(State state)
    {
        File.WriteAllText(PathOf("state.json"), new JavaScriptSerializer().Serialize(state));
    }

    static bool Failed(long version)
    {
        try { return Array.IndexOf(File.ReadAllLines(PathOf("failed")), version.ToString()) >= 0; }
        catch (Exception) { return false; }
    }

    static string Installed { get { return Path.Combine(root, "Mentor.exe"); } }

    // At every start, before anything else. True when this process is to end: another Mentor.exe
    // took over (the new one, or the old one again). `busy`: a system is running from here already,
    // and the program is not swapped under it.
    public static bool AtStart(string rootDir, string[] args, bool busy)
    {
        root = rootDir;
        dir = Path.Combine(root, "launcher-update");
        try { Directory.CreateDirectory(dir); }
        catch (Exception) { return false; }  // a folder we may not write: no updates
        // Only the program called Mentor.exe updates itself; a copy under another name (a test one,
        // Mentor-previous.exe kept by hand) leaves the installation alone.
        string self = System.Reflection.Assembly.GetExecutingAssembly().Location;
        if (!string.Equals(Path.GetFullPath(self), Path.GetFullPath(Installed), StringComparison.OrdinalIgnoreCase))
            return false;
        State state = ReadState();
        if (state != null && state.version == Version)
        {
            trial = true;
            try { File.WriteAllText(PathOf("alive"), Version.ToString()); }
            catch (Exception) { }
            if (state.tries == 0)
            {
                SetNote(UpdatedNote);  // the first start under it: until the system has come up
                return false;
            }
            // The last start under this launcher did not work out: back to the one before.
            Log("the start under this launcher did not work: going back to " + state.previous);
            return GoBack(state, args, true);
        }
        if (state != null)
        {
            // Not ours (setup put another Mentor.exe here, or this is the old one after a way back).
            try { File.Delete(PathOf("state.json")); }
            catch (Exception) { }
        }
        if (busy)
        {
            if (StagedNewer()) SetNote(ReadyNote);  // not swapped under a running system
            return false;
        }
        return TakeStaged(args);
    }

    // Puts the launcher before back as Mentor.exe. With `restart`, starts it and says so (true).
    static bool GoBack(State state, string[] args, bool restart)
    {
        string previous = PathOf("Mentor.previous.exe");
        if (!File.Exists(previous))
        {
            Log("no previous launcher to go back to; keeping this one");
            try { File.Delete(PathOf("state.json")); } catch (Exception) { }
            return false;
        }
        try
        {
            string failedCopy = PathOf("Mentor-" + state.version + ".failed.exe");
            if (File.Exists(failedCopy)) File.Delete(failedCopy);
            File.Move(Installed, failedCopy);  // allowed while it runs: a rename
            File.Move(previous, Installed);
            File.AppendAllText(PathOf("failed"), state.version + "\r\n");
            File.Delete(PathOf("state.json"));
            File.Delete(PathOf("alive"));
        }
        catch (Exception e)
        {
            Log("going back failed: " + e.Message);
            if (!File.Exists(Installed))
                try { File.Move(PathOf("Mentor-" + state.version + ".failed.exe"), Installed); } catch (Exception) { }
            return false;
        }
        Log("back to " + state.previous);
        if (!restart) return false;
        try
        {
            Process.Start(new ProcessStartInfo(Installed, Arguments(args)) { UseShellExecute = false, WorkingDirectory = root });
            return true;
        }
        catch (Exception e)
        {
            Log("could not start the previous launcher: " + e.Message);
            return false;
        }
    }

    // A checked new launcher is waiting: put it in place and hand over to it.
    static bool TakeStaged(string[] args)
    {
        Dictionary<string, object> staged;
        try { staged = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(PathOf("staged.json"))); }
        catch (Exception) { return false; }
        long version;
        string file, sha;
        try
        {
            version = Convert.ToInt64(staged["version"]);
            file = PathOf(Path.GetFileName((string)staged["file"]));
            sha = (string)staged["sha256"];
        }
        catch (Exception) { return false; }
        if (version <= Version || Failed(version) || !File.Exists(file)) return false;
        if (Sha256(file) != sha)
        {
            Log("the staged launcher " + version + " has changed on disk; dropped");
            try { File.Delete(file); File.Delete(PathOf("staged.json")); } catch (Exception) { }
            return false;
        }
        var state = new State { version = version, previous = Version, tries = 0 };
        string previous = PathOf("Mentor.previous.exe");
        try
        {
            File.Delete(PathOf("alive"));
            foreach (string old in Directory.GetFiles(dir, "*.failed.exe")) File.Delete(old);  // kept for one look only
            WriteState(state);
            if (File.Exists(previous)) File.Delete(previous);
            File.Move(Installed, previous);
            try { File.Move(file, Installed); }
            catch (Exception)
            {
                File.Move(previous, Installed);
                throw;
            }
            File.Delete(PathOf("staged.json"));
        }
        catch (Exception e)
        {
            Log("could not put " + version + " in place: " + e.Message);
            try { File.Delete(PathOf("state.json")); } catch (Exception) { }
            return false;
        }
        Log("put " + version + " in place; starting it");
        Process started = null;
        try { started = Process.Start(new ProcessStartInfo(Installed, Arguments(args)) { UseShellExecute = false, WorkingDirectory = root }); }
        catch (Exception e) { Log("it would not start: " + e.Message); }
        // It says it runs by writing "alive", within moments. A program that ends without having
        // written it, or does not start at all, is put back, and this one goes on.
        DateTime until = DateTime.UtcNow.AddSeconds(60);
        while (started != null && DateTime.UtcNow < until)
        {
            if (File.Exists(PathOf("alive"))) return true;
            if (started.WaitForExit(250) && !File.Exists(PathOf("alive"))) break;
        }
        if (started != null && File.Exists(PathOf("alive"))) return true;
        if (started != null && !started.HasExited)
            try { started.Kill(); started.WaitForExit(5000); } catch (Exception) { }
        Log("the new launcher " + version + " did not come up");
        // This process runs from Mentor.previous.exe now: going back renames it home.
        try
        {
            string failedCopy = PathOf("Mentor-" + version + ".failed.exe");
            if (File.Exists(failedCopy)) File.Delete(failedCopy);
            File.Move(Installed, failedCopy);
            File.Move(previous, Installed);
            File.AppendAllText(PathOf("failed"), version + "\r\n");
            File.Delete(PathOf("state.json"));
            Log("back to " + Version);
        }
        catch (Exception e) { Log("going back failed: " + e.Message); }
        return false;
    }

    // A start of the system is beginning under this launcher.
    public static void RunStarting()
    {
        runStarted = DateTime.UtcNow;
        if (!trial) return;
        State state = ReadState();
        if (state == null || state.version != Version) return;
        state.tries++;
        try { WriteState(state); } catch (Exception) { }
    }

    // That start ended without an error. Three minutes of running count as working, for a system that
    // does not report its desktop.
    public static void RunEnded()
    {
        if (trial && (DateTime.UtcNow - runStarted).TotalMinutes >= 3) Commit();
    }

    // The system came up under this launcher: it is kept.
    public static void Commit()
    {
        if (!trial) return;
        trial = false;
        try
        {
            File.Delete(PathOf("state.json"));
            File.Delete(PathOf("alive"));
        }
        catch (Exception) { }
        Log("kept: the system came up under it");
    }

    // Looks for a newer launcher, in the background, at most once in 12 hours. What it finds is
    // downloaded and checked here, and put in place at the next start.
    public static void CheckInBackground()
    {
        if (dir == null || trial) return;
        new Thread(() => {
            try { Check(); }
            catch (Exception e) { Log("check failed: " + e.Message); }
        }) { IsBackground = true, Priority = ThreadPriority.BelowNormal }.Start();
    }

    static void Check()
    {
        DateTime last;
        try
        {
            if (DateTime.TryParse(File.ReadAllText(PathOf("checked")), null,
                    System.Globalization.DateTimeStyles.RoundtripKind, out last) && DateTime.UtcNow - last < Every)
                return;
        }
        catch (IOException) { }
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;  // TLS 1.2
        byte[] manifest = Fetch(Feed + "launcher.json", 64 * 1024);
        byte[] signature = Fetch(Feed + "launcher.json.sig", 8 * 1024);
        string why = SshSignature.Check(manifest, signature, Namespace, LauncherBuild.Signer);
        if (why != null) { Log("launcher.json refused: " + why); return; }
        Dictionary<string, object> info = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(manifest));
        long version = Convert.ToInt64(info["version"]);
        string file = info["file"] as string ?? "", sha = (info["sha256"] as string ?? "").ToLowerInvariant();
        long size = Convert.ToInt64(info["size"]);
        if (!Regex.IsMatch(file, @"^Mentor-\d{12}\.exe$") || !Regex.IsMatch(sha, "^[0-9a-f]{64}$") || size <= 0 || size > MaxProgram)
        {
            Log("launcher.json is signed but not as expected; ignored");
            return;
        }
        if (version > Version && !Failed(version) && !IsStaged(version, sha))
        {
            Log("found " + version + "; downloading");
            string part = PathOf(file + ".part");
            byte[] program = Fetch(Feed + file, MaxProgram);
            if (program.Length != size || Sha256(program) != sha)
            {
                Log(file + " did not match launcher.json; dropped");
                return;
            }
            File.WriteAllBytes(part, program);
            foreach (string old in Directory.GetFiles(dir, "Mentor-*.exe"))
                if (!old.EndsWith(".failed.exe", StringComparison.OrdinalIgnoreCase))
                    try { File.Delete(old); } catch (Exception) { }
            File.Move(part, PathOf(file));
            File.WriteAllText(PathOf("staged.json"), new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
                { "version", version }, { "file", file }, { "sha256", sha }, { "summary", info.ContainsKey("summary") ? info["summary"] : "" } }));
            Log("staged " + version + " for the next start");
            SetNote(ReadyNote);
        }
        File.WriteAllText(PathOf("checked"), DateTime.UtcNow.ToString("o"));
    }

    static bool StagedNewer()
    {
        try
        {
            var staged = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(PathOf("staged.json")));
            long version = Convert.ToInt64(staged["version"]);
            return version > Version && !Failed(version) && File.Exists(PathOf(Path.GetFileName((string)staged["file"])));
        }
        catch (Exception) { return false; }
    }

    static bool IsStaged(long version, string sha)
    {
        try
        {
            var staged = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(PathOf("staged.json")));
            return Convert.ToInt64(staged["version"]) == version && (string)staged["sha256"] == sha &&
                   File.Exists(PathOf((string)staged["file"]));
        }
        catch (Exception) { return false; }
    }

    static byte[] Fetch(string url, long most)
    {
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.UserAgent = "Mentor";
        request.Timeout = 30000;
        request.ReadWriteTimeout = 60000;
        using (var response = (HttpWebResponse)request.GetResponse())
        using (Stream from = response.GetResponseStream())
        using (var to = new MemoryStream())
        {
            var buffer = new byte[64 * 1024];
            int read;
            while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
            {
                to.Write(buffer, 0, read);
                if (to.Length > most) throw new IOException(url + " is larger than expected");
            }
            return to.ToArray();
        }
    }

    public static string Sha256(string file)
    {
        using (var sha = SHA256.Create())
        using (FileStream stream = File.OpenRead(file))
            return Hex(sha.ComputeHash(stream));
    }

    static string Sha256(byte[] data)
    {
        using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(data));
    }

    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }

    // The arguments again as one command line, quoted the way Windows programs split it.
    public static string Arguments(string[] args)
    {
        var line = new StringBuilder();
        foreach (string a in args)
        {
            if (line.Length > 0) line.Append(' ');
            if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) { line.Append(a); continue; }
            line.Append('"');
            int backslashes = 0;
            foreach (char c in a)
            {
                if (c == '\\') { backslashes++; continue; }
                line.Append('\\', c == '"' ? backslashes * 2 + 1 : backslashes);
                line.Append(c);
                backslashes = 0;
            }
            line.Append('\\', backslashes * 2).Append('"');
        }
        return line.ToString();
    }
}

// An OpenSSH signature (`ssh-keygen -Y sign`, the format in OpenSSH's PROTOCOL.sshsig) of a file, by
// an Ed25519 key.
static class SshSignature
{
    // Null when `armored` is a good signature of `data` in `space` by the key `signer` (the base64
    // public key blob, as in an authorized_keys line); otherwise what is wrong with it.
    public static string Check(byte[] data, byte[] armored, string space, string signer)
    {
        byte[] blob;
        try
        {
            string text = Encoding.ASCII.GetString(armored);
            int begin = text.IndexOf("-----BEGIN SSH SIGNATURE-----"), end = text.IndexOf("-----END SSH SIGNATURE-----");
            if (begin < 0 || end < begin) return "not an SSH signature";
            begin += "-----BEGIN SSH SIGNATURE-----".Length;
            blob = Convert.FromBase64String(Regex.Replace(text.Substring(begin, end - begin), @"\s", ""));
        }
        catch (FormatException) { return "not an SSH signature"; }
        try
        {
            int at = 0;
            if (Encoding.ASCII.GetString(blob, 0, 6) != "SSHSIG") return "not an SSH signature";
            at = 6;
            if (UInt32(blob, ref at) != 1) return "an unknown version of SSH signature";
            byte[] key = Field(blob, ref at), nameSpace = Field(blob, ref at), reserved = Field(blob, ref at),
                   hashName = Field(blob, ref at), signature = Field(blob, ref at);
            if (at != blob.Length) return "an SSH signature with more in it than expected";
            if (Convert.ToBase64String(key) != signer) return "signed by another key";
            if (Encoding.ASCII.GetString(nameSpace) != space) return "signed for something else (" + Encoding.ASCII.GetString(nameSpace) + ")";
            string hash = Encoding.ASCII.GetString(hashName);
            byte[] digest;
            if (hash == "sha512") using (var h = SHA512.Create()) digest = h.ComputeHash(data);
            else if (hash == "sha256") using (var h = SHA256.Create()) digest = h.ComputeHash(data);
            else return "an unknown hash (" + hash + ")";
            int k = 0;
            if (Encoding.ASCII.GetString(Field(key, ref k)) != "ssh-ed25519") return "not an Ed25519 key";
            byte[] publicKey = Field(key, ref k);
            int s = 0;
            if (Encoding.ASCII.GetString(Field(signature, ref s)) != "ssh-ed25519") return "not an Ed25519 signature";
            byte[] raw = Field(signature, ref s);
            // What was signed: the magic, the namespace, the reserved field, the hash's name and the hash.
            var signed = new MemoryStream();
            signed.Write(Encoding.ASCII.GetBytes("SSHSIG"), 0, 6);
            foreach (byte[] field in new[] { nameSpace, reserved, hashName, digest }) Put(signed, field);
            return Ed25519.Verify(publicKey, signed.ToArray(), raw) ? null : "the signature does not match";
        }
        catch (ArgumentException) { return "a damaged SSH signature"; }
        catch (IndexOutOfRangeException) { return "a damaged SSH signature"; }
    }

    static uint UInt32(byte[] b, ref int at)
    {
        if (at + 4 > b.Length) throw new ArgumentException();
        uint v = (uint)(b[at] << 24 | b[at + 1] << 16 | b[at + 2] << 8 | b[at + 3]);
        at += 4;
        return v;
    }

    static byte[] Field(byte[] b, ref int at)
    {
        uint length = UInt32(b, ref at);
        if (length > b.Length - at) throw new ArgumentException();
        var field = new byte[length];
        Array.Copy(b, at, field, 0, length);
        at += (int)length;
        return field;
    }

    static void Put(Stream to, byte[] field)
    {
        to.WriteByte((byte)(field.Length >> 24)); to.WriteByte((byte)(field.Length >> 16));
        to.WriteByte((byte)(field.Length >> 8)); to.WriteByte((byte)field.Length);
        to.Write(field, 0, field.Length);
    }
}

// Checking an Ed25519 signature (RFC 8032, section 5.1.7), after the reference code in its section 6.
// Points are kept in extended coordinates (X, Y, Z, T).
static class Ed25519
{
    static readonly BigInteger P = BigInteger.Pow(2, 255) - 19;
    static readonly BigInteger L = BigInteger.Pow(2, 252) + BigInteger.Parse("27742317777372353535851937790883648493");
    static readonly BigInteger D = Mod(-121665 * Inverse(121666));
    static readonly BigInteger SqrtMinusOne = BigInteger.ModPow(2, (P - 1) / 4, P);
    static readonly BigInteger[] Base;

    static Ed25519()
    {
        BigInteger y = Mod(4 * Inverse(5));
        BigInteger x = RecoverX(y, 0).Value;
        Base = new[] { x, y, BigInteger.One, Mod(x * y) };
    }

    static BigInteger Mod(BigInteger a)
    {
        BigInteger r = a % P;
        return r.Sign < 0 ? r + P : r;
    }

    static BigInteger Inverse(BigInteger a) { return BigInteger.ModPow(Mod(a), P - 2, P); }

    static BigInteger? RecoverX(BigInteger y, int sign)
    {
        if (y >= P) return null;
        BigInteger x2 = Mod((y * y - 1) * Inverse(D * y * y + 1));
        if (x2.IsZero) return sign == 0 ? (BigInteger?)BigInteger.Zero : null;
        BigInteger x = BigInteger.ModPow(x2, (P + 3) / 8, P);
        if (!Mod(x * x - x2).IsZero) x = Mod(x * SqrtMinusOne);
        if (!Mod(x * x - x2).IsZero) return null;
        if ((int)(x & 1) != sign) x = P - x;
        return x;
    }

    static BigInteger[] Add(BigInteger[] p, BigInteger[] q)
    {
        BigInteger a = Mod((p[1] - p[0]) * (q[1] - q[0])), b = Mod((p[1] + p[0]) * (q[1] + q[0]));
        BigInteger c = Mod(2 * p[3] * q[3] * D), d = Mod(2 * p[2] * q[2]);
        BigInteger e = b - a, f = d - c, g = d + c, h = b + a;
        return new[] { Mod(e * f), Mod(g * h), Mod(f * g), Mod(e * h) };
    }

    static BigInteger[] Multiply(BigInteger s, BigInteger[] p)
    {
        var q = new[] { BigInteger.Zero, BigInteger.One, BigInteger.One, BigInteger.Zero };
        while (s.Sign > 0)
        {
            if (!s.IsEven) q = Add(q, p);
            p = Add(p, p);
            s >>= 1;
        }
        return q;
    }

    static bool Same(BigInteger[] p, BigInteger[] q)
    {
        return Mod(p[0] * q[2] - q[0] * p[2]).IsZero && Mod(p[1] * q[2] - q[1] * p[2]).IsZero;
    }

    static BigInteger Number(byte[] littleEndian, int offset, int count)
    {
        var bytes = new byte[count + 1];  // the extra zero keeps it positive
        Array.Copy(littleEndian, offset, bytes, 0, count);
        return new BigInteger(bytes);
    }

    static BigInteger[] Decompress(byte[] b, int offset)
    {
        var copy = new byte[32];
        Array.Copy(b, offset, copy, 0, 32);
        int sign = copy[31] >> 7;
        copy[31] &= 0x7f;
        BigInteger y = Number(copy, 0, 32);
        BigInteger? x = RecoverX(y, sign);
        if (x == null) return null;
        return new[] { x.Value, y, BigInteger.One, Mod(x.Value * y) };
    }

    public static bool Verify(byte[] publicKey, byte[] message, byte[] signature)
    {
        if (publicKey == null || publicKey.Length != 32 || signature == null || signature.Length != 64) return false;
        BigInteger[] a = Decompress(publicKey, 0), r = Decompress(signature, 0);
        if (a == null || r == null) return false;
        BigInteger s = Number(signature, 32, 32);
        if (s >= L) return false;
        byte[] hash;
        using (var sha = SHA512.Create())
        {
            var all = new byte[32 + 32 + message.Length];
            Array.Copy(signature, 0, all, 0, 32);
            Array.Copy(publicKey, 0, all, 32, 32);
            Array.Copy(message, 0, all, 64, message.Length);
            hash = sha.ComputeHash(all);
        }
        BigInteger h = Number(hash, 0, 64) % L;
        return Same(Multiply(s, Base), Add(r, Multiply(h, a)));
    }
}
