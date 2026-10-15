# Mentor update: <one line, what it is>

<!--
The maker's notes for the assistant on each Mentor (distro/rootfs/etc/mentor/UPDATES.md). They are signed
with the update and kept at /etc/mentor/update-notes/VERSION.md.

- "What is new" is explained to the user before and after installing ("What's new?" on the card).
- "Steps" is only for what the update's files cannot do by themselves: something that depends on the
  machine or on what the user chose. Leave the section out when there is nothing; the card then has no
  "Let Mentor finish". Never put Mentor's own files here: they come with the update, exactly.
- Write the steps for a small model: one action each, the exact tool or command, what to check after
  it, and what to do when the check does not come out as expected (usually: stop and tell the user).
-->

## What is new

<For the user, in plain words: what changed and why it matters to them. Two to five short sentences.>

## Why

<For the assistant: what was wrong or missing, which parts changed (files, services), what to look at if
the user says something does not work since the update.>

## Steps

1. **<What this step is for, in a few words.>**
   - Look first: <tool or command that shows the current state, e.g. settings_get org.gnome.… key>
   - If <the state that means the step is needed>: <the exact action, e.g. settings_set … to …>.
     If <the state that means the user chose otherwise>: leave it, and say so at the end.
   - Check: <what shows that it worked>. If it does not: stop, say what you saw.

2. **<…>**

## Check at the end

- <A command or tool and the answer it should give, e.g. `mentor verify` says every file is as built.>
- <What the user should see or be able to do now.>
