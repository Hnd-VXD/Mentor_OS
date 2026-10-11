# Mentor OS

Agentic Linux: an Arch-based GNOME system that runs on Windows 11 in its own window (QEMU with the Windows Hypervisor Platform), with an assistant on the desktop that changes the system when you ask it to. Changes are tried in a sandbox first, and a start that fails is undone automatically.

## Install

Download **[MentorSetup.exe](../../releases/latest/download/MentorSetup.exe)** and run it. It

- installs QEMU (with winget) if it is not there,
- turns on the Windows Hypervisor Platform (Windows asks for permission, and has to be restarted once),
- downloads Mentor into the folder you choose (about 3 GB to download, 12 GB of disk space in use later),
- puts a shortcut on the desktop.

Windows may warn about an unsigned program the first time.

### What you need

- Windows 11, 64-bit, with virtualization enabled in the firmware
- 8 GB of memory or more

### By hand

From the [latest release](../../releases/latest) download `Mentor.exe` and the `mentor.qcow2.*` parts into one new folder, then in PowerShell, in that folder:

```powershell
winget install SoftwareFreedomConservancy.QEMU
Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform   # as administrator, then restart
mkdir out
cmd /c copy /b mentor.qcow2.001+mentor.qcow2.002 out\mentor.qcow2
```

and double-click `Mentor.exe`. The folder ends up as:

```
Mentor.exe
out\mentor.qcow2      the system, never written to
vm\                   your own disk, created on the first start
```

## First start

- The launcher window offers memory, processors, full screen, the graphics card (experimental) and sharp text.
- The assistant asks to be connected: with a free NVIDIA key from build.nvidia.com that you paste in, or with your own Claude or ChatGPT account (Claude Code or Codex is then downloaded for you). Nothing is preconfigured, and keys stay on your computer.
- The user is `admin` and its first password is `admin`. Change it: open Console and run `passwd`.
- Text, files and folders copy and paste between Windows and Mentor (up to 256 MB at a time).

## Going back

- `Mentor.exe --restore` returns to a restore point; the launcher window has the same choice.
- `Mentor.exe --reset` starts again from the clean system. Everything in `vm\` is lost.

## Notes

- The system is built from Arch Linux packages, each under its own licence; their sources are at archlinux.org.
- This is an early release. Expect rough edges, the graphics-card mode in particular.
