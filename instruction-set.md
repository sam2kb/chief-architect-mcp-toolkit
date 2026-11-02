# Instruction set for an agent driving Chief Architect

Paste this into your agent's project instructions or rules file. Nothing here depends on a
particular template or office standard, so it should survive being shared between users.

## Before the first edit

Work on a copy of the plan. Changes made with `chief_invoke_command` cannot be undone, and an
agent that edits a live drawing has no rollback. Save the file before you start, and check
whether Project Management is on, because that decides which tools answer at all.

This toolkit drives a real CAD program with real mouse and keyboard events, and it can damage a
drawing. It is incomplete, lightly tested, and built against an undocumented API on one build.
Nothing here is a substitute for a backup.

## Do not

Do not rename, reformat, or reset room labels. A label can carry a macro, and setting it back
to default deletes the macro along with the text. If labels need to change, ask first.

Do not change defaults, layer sets, or text styles to solve a local problem. They affect the
whole plan.

Do not try to delete. The server refuses delete keystrokes even when you bind them to a new
hotkey. Move unwanted objects to a parking offset instead, and record where they came from so
they can be restored.

## Editing

Open the object's Specification dialog, write the field, and press OK. That path commits and
can be verified afterwards. Treat commands as a last resort.

Check every edit by reading the coordinates or properties back. A dialog that looked right on
screen can still have written something else.

## Placing things precisely

Seed construction lines at the major walls before asking for geometry, then describe each edit
relative to a named line. Coordinates quoted in a prompt drift once walls move; lines stay put
and give both of you the same reference.

## When something goes wrong

If a double-click opens the wrong dialog, try another point inside the object's bounds. Some
rooms have dimension lines running across their interior, and the click lands on the dimension.
Better still, click once and read the selection back before double-clicking: a double-click on a
dimension number starts an in-place edit, and Chief will not give the keyboard back until it is
cancelled.

If the app stops responding to clicks, treat it as an in-place edit holding the keyboard, not as
a tool that needs retrying. Escape cancels it, and Escape only reaches Chief while Chief owns the
foreground. Clean up after every object -- cancel the dialog, tap Escape, clear the selection --
without waiting for something to fail first, because this state refuses nothing on its own.

Do not bring the Chief window to the front to "fix" a run. It takes the keyboard away from
whoever is typing, and on Windows an ALT tap can leave a menu grabbed so that clicking back no
longer recovers.

If a tool answers "requires project management mode", report it and stop. Do not look for
another route that edits the file anyway.

## Cost

These sessions consume plan credits quickly. Put the rules and the known facts about the plan
up front instead of rediscovering them in each new conversation.
