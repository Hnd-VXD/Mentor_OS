# Mentor OS

Agentic Linux: an Arch-based GNOME system that runs on Windows 11 in its own window, with an assistant on the desktop that changes the system when you ask it to. Changes are tried in a sandbox first, and a start that fails is undone automatically.

## Install

Download **[MentorSetup.exe](../../releases/latest/download/MentorSetup.exe)** and run it. It

- turns on the Windows Hypervisor Platform (Windows asks for permission, and has to be restarted once),
- downloads Mentor and the QEMU it runs on into the folder you choose (about 2.3 GB to download, 12 GB of disk space in use later),
- puts a shortcut on the desktop.

Nothing else has to be installed, and Mentor starts by itself when it is ready.

**Windows will probably warn you first.** The setup program is not signed yet, and Windows shows "Windows protected your PC" for a downloaded program it has not seen often. Click **More info**, then **Run anyway**. To check that the file is the one published here, compare its SHA-256 with the one in the [release notes](../../releases/latest):

```powershell
Get-FileHash MentorSetup.exe
```

### Without the warning

Open PowerShell (right-click the Start button, Terminal) and paste:

```powershell
irm https://raw.githubusercontent.com/Hnd-VXD/Mentor_OS/main/install.ps1 | iex
```

It downloads the same setup program and starts it. Windows does not warn this way, because the program was not downloaded by a browser. [`install.ps1`](install.ps1) is a dozen lines: read it first.

### What you need

- Windows 11, 64-bit, with virtualization enabled in the firmware
- 8 GB of memory or more

### By hand

From the [latest release](../../releases/latest) download `Mentor.exe`, `winq-emu-alpha10-portable.zip` and the `mentor.qcow2.*` parts into one new folder, then in PowerShell, in that folder:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform   # as administrator, then restart
Expand-Archive winq-emu-alpha10-portable.zip qemu
mkdir out
cmd /c copy /b mentor.qcow2.001+mentor.qcow2.002 out\mentor.qcow2
```

and double-click `Mentor.exe`. The folder ends up as:

```
Mentor.exe
qemu\                 the QEMU Mentor runs on
out\mentor.qcow2      the system, never written to
vm\                   your own disk, created on the first start
```

## First start

- The launcher window offers memory, processors, full screen, the graphics card and Vulkan.
- The assistant asks which engine to use, and nothing is picked for you: free models hosted by NVIDIA, with a key from build.nvidia.com that you paste in, or your own Claude, ChatGPT or Google account (Claude Code, Codex or Google's Antigravity CLI is then downloaded for you). Nothing is preconfigured, and keys and sign-ins stay on your computer.
- The user is `admin` and its first password is `admin`. Change it: open Console and run `passwd`. Mentor reminds you with a card in the chat until you do.

## What is in it

- **The assistant is the desktop.** Click it or press Super+A and type what you want. It has tools for packages, settings, services, files (search and read), logs, sound, the network, open windows, the desktop itself and the web (search and read a page), and asks before it changes the system. An app it opens is confirmed by name from the shell, not guessed from a screenshot.
- **Safe changes.** System changes are made in a sandbox and applied when they work. A start after a change that does not reach the desktop is undone by itself. Restore points of the whole disk are kept on Windows.
- **When the desktop freezes.** The desktop gets more of the processor than apps. A watch outside the desktop notices when it stops answering, writes down what was behind it, and tells you in one sentence afterwards; when a freeze goes on, it gives the busy app less of the processor, and when memory has run out it closes the largest app. **Ctrl+Alt+Backspace** opens the assistant on a text screen even while the desktop is frozen, at the size of Mentor's window: it looks at what is going on, says what would help, and can write, build and apply a fix through the sandbox with your password. `/desktop` goes back; Ctrl+V pastes what you copied. The boot screen reminds you of the key.
- **Ask without leaving what you are doing.** Alt+Space (or Super+Z) lifts the assistant's text box over the program you are in. The assistant gets your words with a picture of your screen and answers in a small bubble above the box. A click anywhere else puts the box back on the desktop.
- **Conversations.** Tabs, one conversation for each workspace, a timeline down the side, quoting an answer, files attached by dropping or pasting. A click on an attached picture shows it at once over the chat; a right click offers Open with…. Clear chat is in the right-click menu of the desktop. Type three letters of an installed app and it is offered with its icon: Tab puts it in your message, and the assistant knows exactly which app you mean.
- **The model's menu** shows the limits of your Claude, ChatGPT or Gemini plan where the account tells them, and the effort setting.
- **Suggestions.** A bell on the desktop holds what the system noticed by itself: waiting updates, a filling disk, failed services, news from Arch and GNOME, new applications and projects. No model is used until you send one to the chat.
- **Warnings in the chat.** What cannot wait shows in the chat as a card: yellow for a warning, red for a problem, with a button that hands it to the assistant. Mentor checks itself this way too, after every login.
- **Made for people who do not know computers.** When your password is asked, the box says in one short sentence, written by the assistant in your language, what is about to happen and why. Mentor Settings is one short page of plain switches with an "Ask Mentor" button for everything else.
- **Looking after your safety.** A firewall that refuses connections from other computers is on from the first start. When other computers keep trying to get in, the assistant looks by itself and tells you in a few words what it was: one message, however many attempts. When it has just read a web page or a downloaded file and then wants to do something as root, a yellow window says so first. The system also checks for the first password, remote login and root without a password, and tells you in the chat.
- **Recipes.** When something you asked for finally works, a green card offers to write it down (or ask for it yourself): the assistant writes it down as a detailed Markdown file in Documents/Mentor recipes, from what it did, so that another Mentor user's assistant can build the same thing. Secrets and your name are kept out. The recipes are collected at https://mentor-recipes.netlify.app: the assistant can look there, download one, and post yours after showing you exactly what it would post and getting your yes. A post is signed by a key made on your computer (it names no one), checked by fixed rules and published by itself, and Mentors tell the site when a recipe from it looks harmful. A recipe from someone else is treated as untrusted: it is first inspected by rules (every command, file, download and anything that looks like harm), you get a short report in plain words (only what matters, and every problem), and nothing is changed until you have answered; then it is built in the sandbox. Pressing Download on the site is enough: Mentor notices the file and starts looking at it. After a recipe was used, a card asks whether it worked; the thumbs are counted on the site, and well-rated recipes come first and show up in the bell. Before building something, the assistant looks whether a recipe for it already exists. The Recipes app lists what you used (with a way to take each away), what you wrote, what waits in Downloads, and what you posted: only you can update or remove those. Update hands the published text to the assistant, which asks what to improve and sends the new version after your yes; the site checks it like a new recipe. A recipe you downloaded can be improved too: Improve makes your own version of it, which says what it was made from and is shown on the site as a version of the original. Every recipe says which model wrote it. `mentor recipes FILE` shows the report without running anything.
- **A journal of every change.** What the assistant changes is written down by itself, under the request it was for: packages, settings (with the value before), services, files, commands run as root, and the way back where there is one. `mentor journal` shows it; the assistant reads it when you ask what was changed, or when something stops working.
- **It can be rebuilt.** Every file Mentor adds to the system is kept as it was built, with step-by-step instructions for the assistant in `/etc/mentor/`. `mentor verify` says what is missing or changed; `sudo mentor restore` puts it back. A watch on memory, processor and network can be set up on request from the same place.
- **With Windows.** Text, files and folders copy and paste both ways (up to 256 MB at a time). A picture you take with Windows' own PrtScr (Snipping Tool) pastes into Mentor, into the chat too. Memory the system no longer needs goes back to Windows. Closing Mentor from the launcher shuts the system down properly, and Mentor keeps working after Windows has been asleep.
- **Screenshots and files.** Shift+Super+S: drag out an area of the screen (Alt+Print: the window in front); it opens in Gradia to draw on, copy or save. In Files, select a file and press Space to preview it, as on a Mac.
- **Graphics.** The desktop can be drawn by the computer's graphics card, with Vulkan for the applications that want it.

## Going back

- **Repair** in the launcher window (`Mentor.exe --repair`) is for when the desktop no longer comes up: Mentor starts without it, on a text screen where you talk to the assistant, and it works from its instructions to mend what is broken. `/restart` there starts Mentor normally.
- `Mentor.exe --restore` returns to a restore point; the launcher window has the same choice.
- `Mentor.exe --reset` starts again from the clean system. Everything in `vm\` is lost.

## Source

Everything Mentor is made of is in this repository.

| Folder | What it holds |
|---|---|
| `distro/` | the system: the package list, `customize.sh` (what is set up when the image is built), and `rootfs/`, every file Mentor adds to Arch Linux |
| `distro/rootfs/usr/local/bin/mentor-chat` | the assistant on the desktop |
| `distro/rootfs/usr/local/lib/mentor/` | the agent's tools, the journal of changes, the sandbox, safe start-up, repair mode, suggestions |
| `distro/rootfs/etc/mentor/` | what the agent is told, and the instructions it rebuilds Mentor from (`REBUILD.md` is the place to start) |
| `launcher/` | `Mentor.exe` and `MentorSetup.exe` (C#, compiled with the compiler that ships with Windows) |
| `build/` | builds the image inside an Arch Linux WSL2 distro |

To build it yourself, on Windows with `wsl --install archlinux` done once:

```powershell
.\build\build.ps1               # -> out\mentor.qcow2
.\launcher\build-launcher.ps1   # -> Mentor.exe
```

Mentor's own QEMU goes into a `qemu` folder beside `Mentor.exe` (unpack `winq-emu-alpha10-portable.zip` from a release there). `README.el.md` describes the inside of it in more detail, in Greek.

## Licences

- Mentor's own code and files (everything in this repository) are under the [MIT licence](LICENSE).
- The system is built from Arch Linux packages, each under its own licence; their sources are at archlinux.org.
- The QEMU in `qemu\` is the WINQ-EMU runtime as built by [Try Omarchy for Windows](https://github.com/omacom/try-omarchy-windows): QEMU (GPL-2.0) and virglrenderer (MIT) from the forks by cmspam, with the libraries they link. Its licences and the record of what it was built from are inside the archive, and the corresponding source is published with every release here as `winq-emu-alpha10-source.zip`.

This is an early release. Expect rough edges.
