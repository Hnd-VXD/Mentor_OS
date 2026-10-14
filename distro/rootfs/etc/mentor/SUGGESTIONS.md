# What the system brings up by itself: updates, a full disk, failed services, and the news

This is for the agent, written so that a small model can follow it. Mentor looks the system over now and then and tells the user what is worth a word. No model is involved in the looking, so it costs no tokens; a model is only called when the user takes a suggestion up. This file says what the user is meant to have, what makes it, what of other people's services it leans on, how to tell that it works, and how to mend it.

## What the user has

- **A bell on the desktop** (top right of the assistant) with a count, only when there is something. It opens a list of cards. Each card has a title, a line or two under it, and three buttons: **Send to the chat** (the agent takes it up in a conversation of its own), **Not now** (not again for three days), **Don't suggest this again** (never again for that kind).
- **A card can be read in full**: a click on the words under the title opens the whole text (the list of updates, the whole news item), with links that open in the browser.
- **What there are cards for**:

| Kind | Card when | Says |
|---|---|---|
| `updates` | 25 or more updates wait, or a kernel is among them, or the last upgrade was 7 days ago or more | how many, the best-known among them, days since the last upgrade |
| `updates` (id `gnome-N`) | a new major GNOME is among the updates | whether Mentor is made for it (the extension's `shell-version` list) |
| `disk` | the system disk is 85% full or more | free space, the package cache, the logs |
| `failed` | a system service has failed in this session (at most three) | the last thing it logged |
| `news` | Arch Linux announced something in the last 21 days (at most three) | the announcement |
| `gnome` | "This Week in GNOME" published in the last 10 days (one) | the post |
| `apps` | applications were published on Flathub in the last 2 days (one card, at most 12 apps) | their names |
| `github` | projects for GNOME and GTK started in the last 45 days gathered 15 stars or more (one card, at most 8, each for 3 days) | their names and stars |

- **Settings for it** in the assistant: suggestions on or off altogether, and the kinds turned away, which can be brought back (tool suggestions_restore).
- **A card in the chat for what cannot wait**, yellow for a warning and red for a problem: a file of Mentor's own missing or changed (red), a part of Mentor's desktop not working (red), the disk at 90% (red), failed units (yellow). It has a button "Let Mentor look". When the assistant is covered a notification says so. The same finding is not raised again for three days.

## What makes it

**`/usr/local/lib/mentor/mentor-advisor`** (Python, standard library only), run as root by `mentor-advisor.service`, which `mentor-advisor.timer` starts four minutes after the system starts and every twelve hours. It writes

```
/var/lib/mentor/advice/suggestions.json
    [{"id", "kind", "title", "body", "prompt", "since", "details"?, "link"?}, ...]
```

- `id` names one suggestion (so that "not now" can be remembered); `kind` is one of the table above; `prompt` is what goes to the agent when the user presses "Send to the chat"; `details` is the whole text for reading; `link` its page.
- One function per look: `failed()`, `disk()`, `updates()`, and `news()`, which calls `arch_news()`, `gnome_news()`, `new_apps()`, `github_projects()`. `main()` runs them in that order; one that fails is reported on standard error and does not cost the others.
- `updates()` does not touch the system's package lists: it keeps its own copy in `/var/lib/mentor/advice/db` (`pacman -Sy --dbpath …`, then `pacman -Qu --dbpath …`).
- The news is read once a day (the file `/var/lib/mentor/advice/news-read` is the mark); in between, what was found last time stands.
- The figures at the top of the file are the thresholds: `MANY_UPDATES`, `OLD_UPDATES`, `DISK_FULL`, `NEWS_DAYS`, `GNOME_DAYS`, `APPS_DAYS`, `GITHUB_STARS`, and so on.
- By hand: `sudo /usr/local/lib/mentor/mentor-advisor --print` runs it now and prints what it found.

**What it reads from the network** (each one can change or go away without notice):

| What | Address | Shape |
|---|---|---|
| Arch news | `https://archlinux.org/feeds/news/` | RSS: `item` with `title`, `link`, `pubDate`, `description` (HTML) |
| GNOME news | `https://thisweek.gnome.org/index.xml` | RSS, the same |
| New applications | `https://flathub.org/api/v2/feed/new` | RSS, the same |
| New projects | `https://api.github.com/search/repositories?q=topic:TOPIC created:>DATE stars:>=15&sort=stars` for the topics `libadwaita`, `gtk4`, `gnome` | JSON: `items[]` with `full_name`, `name`, `description`, `stargazers_count`, `created_at`, `language`, `html_url`, `archived`, `fork` |

`read_feed(url)` reads any of the RSS ones. GitHub is asked without a key, which allows a few requests a minute; three are made, once a day.

**The assistant's half** is in `/usr/local/bin/mentor-chat` (class `DesktopWindow`): `suggestions()` reads the file and leaves out what the user turned away; `refresh_advice()` fills the bell; `show_advice_details()` shows one in full; `take_advice()` sends its `prompt` to a new conversation; `put_off()` remembers "not now" and "never"; `show_advice_settings()` is the settings. The file is watched, so a new run shows at once. What the user decided is kept in `~/.config/mentor/advice.json` (`off`, `never`, `until`). `ADVICE_KINDS` and `ADVICE_ICONS` near the top name the kinds and their icons: a new kind needs an entry in both.

**The cards for what cannot wait** come from `/usr/local/lib/mentor/mentor-watch`, run as the user by `mentor-watch.timer` (three minutes after login, then every six hours; enabled for every user with `systemctl --global enable mentor-watch.timer`). A part that `mentor doctor` finds broken is looked at again 30 seconds later (`DOCTOR_AGAIN`), and only what is still broken makes a card: a moment of change (the assistant restarted by an update, the shell busy just after login) gave a red card once for a desktop that was fine seconds later. A group of checks the user switched off in Mentor Settings (`watch_off` in `~/.config/mentor/settings.json`; SETTINGS.md) is not raised. Its checks, in `findings()`: the user's safety (`mentor_security.checks()`, SECURITY.md), `mentor verify` (lines `missing` or `changed`; `accepted` ones are fine), `mentor doctor` (lines `BROKEN`), the disk, `systemctl --failed` for the system and for the user. It keeps what it raised in `~/.local/state/mentor/watch.json` and speaks by leaving a notice (`mentor_tools.leave_notice`), which the assistant shows as a card: see "Notices" in ASSISTANT.md. Only when the assistant is not running does it send a plain notification (`notify-send`, package `libnotify`), which says to run `mentor repair` in a terminal.

## How to tell that it works

| Check | Good answer |
|---|---|
| `systemctl is-enabled mentor-advisor.timer` | `enabled` |
| `systemctl list-timers mentor-advisor.timer` | a time for the next run |
| `systemctl status mentor-advisor.service` | the last run ended with status 0 |
| `python3 -m json.tool /var/lib/mentor/advice/suggestions.json \| head -20` | a list, possibly empty (`[]`). The file is first written four minutes after the system's first start; before that it is not there, and that is not a fault |
| `journalctl -u mentor-advisor -n 20 -o cat` | no lines `mentor-advisor: NAME: …` (each is a look that failed, with why) |
| tool suggestions_status | what there is now, and what the user turned away |
| `systemctl --user is-enabled mentor-watch.timer` | `enabled` |
| the bell | shows when the list is not empty and suggestions are not switched off |

No bell is not a fault when nothing is waiting. To see a card on purpose, ask the user to run `sudo /usr/local/lib/mentor/mentor-advisor --print` on a day with Arch news, or look at the list in the file.

## When something here is broken

1. `mentor verify` (REBUILD.md). `mentor-advisor` and `mentor-watch` are in a folder you cannot write; the user puts them back with `sudo mentor restore PATH`. The units and the assistant you can.
2. **A news source has changed** (the log says `mentor-advisor: arch_news: …`, or a card is missing for days): fetch the address yourself and look at what comes back.

   ```
   curl -sL https://archlinux.org/feeds/news/ | head -40
   ```

   - It answers with something that is not RSS, or 404: the feed has moved. Find its new address on the site (`archlinux.org`, `thisweek.gnome.org`, `flathub.org`), check that it has `item` elements with `title`, `link`, `pubDate`, `description`.
   - It answers with a feed of another shape (Atom has `entry`, `updated`, `summary` or `content`, and `link` as an attribute `href`): `read_feed` has to read that shape too.
   - GitHub answers 403 with a message about a rate limit: nothing is broken, it will work at the next run. If it asks for a key from now on, say so to the user; do not put a key of theirs into a file readable by everyone.
3. **Make the change.** The source of the program is `/etc/mentor/source/rootfs/usr/local/lib/mentor/mentor-advisor`. Since you cannot write the installed one: copy it to the user's folder, change the address (a constant at the top) or `read_feed`, test it with

   ```
   python3 ~/mentor-advisor --print 2>&1 | head -60
   ```

   (it will complain that it cannot write `/var/lib/mentor/advice`, after printing what it found: that is enough to see that the look works), then give the user the line `sudo install -m 755 ~/mentor-advisor /usr/local/lib/mentor/mentor-advisor`, and write the change in `~/.local/share/mentor/notes.md`.
4. **The timer does not run**: `systemctl enable --now mentor-advisor.timer` (service_control). The unit files are in `/usr/local/lib/systemd/system/`; after putting one back, `systemctl daemon-reload`.
5. **The bell does not show though the file has entries**: read `~/.config/mentor/advice.json`. `"off": true` or the kind in `"never"` is the user's own choice (suggestions_restore brings it back, when they ask). Otherwise look for an error of the assistant's: `journalctl -b --user -o cat | grep -A12 Traceback`, and ASSISTANT.md.

## Adding a kind of suggestion

In `mentor-advisor`: a function that returns a list of dictionaries with the fields above, added to the tuple in `main()` (or to `news()` if it reads the network once a day). In `mentor-chat`: its name in `ADVICE_KINDS` and an icon in `ADVICE_ICONS`. Write the `prompt` so that it carries the figures and says what is wanted and that nothing is to be changed before the user agrees: that one text is all the agent gets.

## Making it again from nothing

```
src=/etc/mentor/source/rootfs
# for the user, as root (a folder the agent cannot write):
cp -a $src/usr/local/lib/mentor/mentor-advisor $src/usr/local/lib/mentor/mentor-watch /usr/local/lib/mentor/
# these the agent can do, in the sandbox:
cp -a $src/usr/local/lib/systemd/system/mentor-advisor.service $src/usr/local/lib/systemd/system/mentor-advisor.timer /usr/local/lib/systemd/system/
cp -a $src/etc/systemd/user/mentor-watch.service $src/etc/systemd/user/mentor-watch.timer /etc/systemd/user/
systemctl daemon-reload
systemctl enable --now mentor-advisor.timer
systemctl --global enable mentor-watch.timer
```

`/var/lib/mentor/advice/` is made by the program itself. Then the checks above.
