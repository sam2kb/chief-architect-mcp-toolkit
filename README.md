# chief-architect-mcp-toolkit

Helpers for working with **Chief Architect Premier X18**'s bundled `ca-mcp-x18`
MCP server from an AI coding agent.

The server ships with the application at `<install>/resources/camcp/` and speaks
MCP over stdio, relaying to the running Chief instance across a local named pipe.
It exposes ~30 tools for inspecting a drawing, driving the UI, and exporting
views. What it does *not* give you is ergonomic Python access — every discovery
tool writes its payload to a temp JSON report and returns only a filename.

This toolkit papers over that, and records what actually works.

## Use at your own risk

**This code drives a real CAD program and edits real drawings. It can destroy
work, and it has.** Read this before pointing it at anything you care about.

- **Back up, and work on a copy.** No undo is offered or guaranteed. Some
  operations refuse to be undone at all.
- **The MCP surface is undocumented and unversioned.** Anything here can break
  on a Chief Architect update, a build number, a preference change, or a UI
  setting, without warning and without a deprecation period.
- **It is incomplete and lightly tested.** Continuous testing is a handful of
  unit tests against pure functions — nothing exercises the app itself. The
  integration paths have been run on one machine, one build (`28.2.1.14`), with
  Project Management off. Several are known to be flaky.
- **The input layer is Win32 keystroke injection.** It sends real mouse and
  keyboard events. A mis-aimed click lands on whatever is under it, in whatever
  window has focus. Delete and other destructive hotkeys are refused by the
  server by design, and that refusal is only as strong as this code's restraint.
- **Identifiers, coordinates and viewport state go stale** the moment anyone
  touches the file. A stale object id or a stale point edits the wrong thing.
- **Not affiliated with, endorsed by, or supported by Chief Architect.** No
  warranty of any kind; see the licence. If it corrupts a plan, that is on you.

If that is not what you want, stop here.

## What is in here

| File | Purpose |
|---|---|
| `chief_mcp.py` | Async helpers + CLI over the MCP tools |
| `instruction-set.md` | Guardrails to paste into an agent's rules file |
| `selftest.py` | Read-only smoke test: connect, list views/rooms, pick a hit point |
| `NOTES.md` | Field notes: capability matrix, working recipes, pitfalls |

## Helpers

Reads: `objects`, `properties`, `rooms`, `selection`, `views`, `commands`,
`docs`, `status`.

Input: `select`, `click`, `dblclick`, `export_image`, `export_pdf`. Clicks go
through `gesture`, which does *not* front the window first: a click brings Chief
forward on its own, and forcing activation takes the keyboard from whatever the
user is typing into, which reads as the app hanging until they click back.
`ensure_active` is there for the times it is genuinely wanted — it taps ALT,
which is what Windows requires before it will grant the foreground — and
`python chief_mcp.py active` runs the same thing from a shell.

Dialogs (the reliable way to edit anything): `dialog_fields`, `find_node`,
`node_value`, `set_field`, `press`.

Geometry: `bbox`, `left`, `width`, `contains`, `free_point`, `fmt_inches`,
`parse_inches`.

Recipes, each of which opens a Specification dialog, writes the value, and
confirms it: `open_spec`, `move_object`, `rename_room`, `set_text_fill`.
These exist because the dialogs are the only edit path that reliably commits.
They go through `spec_dialog`, a context manager that cancels the dialog if the
body raises: a dialog left open holds the keyboard and refuses every later
gesture, with no timeout.

When one is already stuck, `recover()` cancels the tracked dialog, force-closes
anything left on top, and reports whether a dialog is still open. Nothing in this
module takes the foreground on its own: doing so steals the keyboard from
whatever you are typing into, and the ALT tap Windows requires can leave a menu
grabbed in the window that had focus. `recover(focus=True)` and
`python chief_mcp.py active` are the deliberate exceptions.
`recover(keyboard=True)` taps Escape, which clears an in-place text edit that has
no dialog to inspect.

A refused gesture retries once with Escape when no dialog is open, which covers
the state with no dialog to find: an in-place dimension edit. Escape can only
reach Chief while Chief has the foreground, so that retry fronts it for a moment
and restores the previous window. `python chief_mcp.py escape [--steal]` sends
the same keystroke by hand.

Set `CAMCP_TRACE=1` (and optionally `CAMCP_TRACE_FILE`) to append a line per MCP
call to `~/.chief_mcp/trace.jsonl`. A hang shows up as a `call` with no matching
`done`, which distinguishes "Chief is busy" from "the agent stopped talking".

Reading the model: `audit` checks the front view for unnamed rooms, zero-size
objects, text on the wrong layer, locked layers, and exact duplicates.
`room_metrics` opens each room, reads the areas and perimeter Chief computes,
and cancels the dialog without changing anything.

Deleting is refused over MCP. `park_objects` moves objects by a fixed offset and
records their original position in a manifest; `unpark_objects` puts them back.
It only moves things when you pass `apply=True`.

Bulk edits come in three steps. `match_objects` filters the front view by name,
layer or floor. `describe_fields` lists one object's dialog fields without
changing them, which is where you find a field id. `apply_property` writes one
field across every match, planning first and writing only when you pass
`apply=True`. Each object gets its own dialog, so count on about a second per
object.

Before a long run, `snapshot` writes the objects, rooms and front view to JSON.
`diff` compares a saved snapshot against the current state and reports what
moved, resized, appeared or vanished. `preflight` checks for an open modal, a
changed front view, and objects that have shifted since capture;
`apply_property` takes a snapshot and aborts rather than writing into a document
that moved on. `clear_dialogs` cancels a stranded modal, which otherwise makes
every gesture fail in a way that looks like a missed click.

`call()` follows `reportFilename` automatically, so
`await chief_mcp.objects(s)` returns the list rather than a path.

Note the module is `chief_mcp`, not `camcp`: naming it `camcp` would shadow the
`camcp` package that Chief's own server imports.

## Requirements

- Chief Architect Premier X18 with **Enable Chief MCP Server** on
  (Preferences → General → Agentic AI), and the application running.
- Python 3.10+ with the `mcp` package installed.
- Python 3.12 if you use the type syntax as written.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env
```

`.env` holds machine-specific settings and is git-ignored:

| Variable | Meaning |
|---|---|
| `CAMCP_PYTHON` | Interpreter that has `mcp` installed |
| `CAMCP_CHIEF_SRC` | `<Chief install>/resources/camcp/src` |
| `CAMCP_SERVER` | Server key in `mcp.json` (default `ca-mcp-x18`) |
| `CAMCP_MCP_JSON` | Optional explicit path to VS Code's `mcp.json` |

If `CAMCP_PYTHON` and `CAMCP_CHIEF_SRC` are both set, the helpers launch the
server directly. Otherwise they read the matching entry out of your VS Code
`mcp.json`, which is how the agent normally starts it:

```jsonc
{
  "servers": {
    "ca-mcp-x18": {
      "type": "stdio",
      "command": "<python with mcp installed>",
      "args": ["-m", "camcp.chief.server"],
      "env": { "PYTHONPATH": "<Chief install>/resources/camcp/src" }
    }
  }
}
```

## Usage

```bash
python chief_mcp.py rooms
python chief_mcp.py objects --name Kitchen
python chief_mcp.py objects --entire
python chief_mcp.py audit
python chief_mcp.py metrics
python chief_mcp.py find --name "hinged door"
python chief_mcp.py fields <object-id>
python chief_mcp.py apply --name "hinged door" --field doorID_Height --value 80" --apply
python chief_mcp.py snapshot
python chief_mcp.py diff ~/.chief_mcp/snap-2026-11-01T190949.json
python chief_mcp.py clear
python chief_mcp.py views
python chief_mcp.py docs "layer sets"
python chief_mcp.py image out.png
```

```python
import chief_mcp

async with chief_mcp.client() as s:
    rooms = await chief_mcp.rooms(s)
    office = next(r for r in rooms if r["roomType"] == "Office")
    x, y = chief_mcp.free_point(office["boundingBox"], await chief_mcp.objects(s))
    await chief_mcp.select(s, [office["objectId"]])
```

## Before you trust it

Read `NOTES.md` for the detail. What works and what does not:

| Without Project Management | Result |
|---|---|
| Reading objects, rooms, properties, selection, views | works |
| Reading values out of a Specification dialog | works, if you cancel afterwards |
| Writing a field and pressing OK | works |
| Selecting objects by id | works |
| Exporting PDF, image, DWG | works |
| Synthetic drags | do not commit; positions never change |
| Text object contents | not exposed anywhere |
| `invoke_command`, `input_hotkey`, `open_document`, project browser | refused |
| Delete, by any route | refused by design |

## Tests

```bash
python -m unittest discover -s tests -t .
```

The unit tests are offline: inch formatting and parsing, bounding boxes,
hit-point selection against overlapping obstacles, and `.env` loading. Run
`selftest.py` for the live check -- it only reads, opening no dialogs.

## License

MIT. Not affiliated with Chief Architect, Inc.
