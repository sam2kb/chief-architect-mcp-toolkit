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
- **Integration coverage is limited.** The integration paths have been run on
  one machine, one build (`28.2.1.14`), with Project Management off. Several are
  known to be flaky.
- **Leave the keyboard and mouse alone while the agent drives Chief.** During
  clicks, dialog inspection, edits, or recovery, do not type, click, switch
  windows, or change the active drawing or selection. Canvas gestures go through
  Chief's MCP server, but keyboard recovery sends real Windows keystrokes and
  can briefly bring Chief to the foreground. Your input can race those actions,
  dismiss a dialog, or send a key to the wrong window. Wait until the agent says
  it has finished before taking over. Pure data reads normally need no keyboard
  focus, but changing the drawing or view during a read can still change the
  result. Delete and other destructive hotkeys remain refused by design.
- **Identifiers, coordinates and viewport state go stale** the moment anyone
  touches the file. A stale object id or a stale point edits the wrong thing.
- **Not affiliated with, endorsed by, or supported by Chief Architect.** No
  warranty of any kind; see the licence. If it corrupts a plan, that is on you.

If that is not what you want, stop here.

## What is in here

| File | Purpose |
|---|---|
| `chief_mcp.py` | Async helpers + CLI over the MCP tools |
| `chief_bridge.py` | Optional adapter for native error flags and raw reply tracing |
| `instruction-set.md` | Guardrails to paste into an agent's rules file |
| `selftest.py` | Read-only smoke test: connect, list views/rooms, pick a hit point |
| `NOTES.md` | Field notes: capability matrix, working recipes, pitfalls |

## Helpers

Reads: `objects`, `properties`, `rooms`, `selection`, `views`, `commands`,
`docs`, `status`.

Input: `select`, `select_matching`, `click`, `dblclick`, `export_image`,
`export_pdf`, `export_view`. Clicks go
through `gesture`, which does *not* front the window first: a click brings Chief
forward on its own, and forcing activation takes the keyboard from whatever the
user is typing into, which reads as the app hanging until they click back.
`ensure_active` is there for the times it is genuinely wanted — it taps ALT,
which is what Windows requires before it will grant the foreground — and
`python chief_mcp.py active` runs the same thing from a shell.

Dialogs (the reliable way to edit anything): `dialog_fields`, `find_node`,
`node_value`, `set_field`, `press`, `clear_dialogs`.

Geometry: `bbox`, `left`, `width`, `contains`, `free_point`, `scan_points`,
`fmt_inches`, `parse_inches`.

Recipes, each of which opens a Specification dialog, writes the value, and
confirms it: `open_spec`, `open_spec_anywhere`, `move_object`, `rename_room`,
`set_text_fill`. These exist because the dialogs are the only edit path that
reliably commits. They go through `spec_dialog`, a context manager that cancels
the dialog if the body raises: a dialog left open holds the keyboard and refuses
every later gesture, with no timeout.

`open_spec` double-clicks candidate points blind, which is what starts an
in-place dimension edit when a guess lands on a dimension number. When you have
the object dict, use `open_spec_anywhere` instead: it clicks once, reads the
selection back to prove the point hits the object, and only then double-clicks.
`reachable_point` and `hit_point` are the pieces, the latter scanning the bounds
for a point that selects a covered object.

When one is already stuck, `recover()` cancels the tracked dialog, force-closes
anything left on top, and reports whether a dialog is still open. Normal gesture
calls skip forced activation, but keyboard cleanup, timeout recovery, and retries
can briefly bring Chief forward. The ALT tap used for activation can also leave
a menu grabbed in the window that had focus. `recover(focus=True)` and
`python chief_mcp.py active` explicitly request activation.
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

Calls run under a watchdog (`CAMCP_CALL_TIMEOUT`, default 2 seconds). Dialog
calls get 15 seconds; exports and help searches get 60. Help search needs time
to index the bundled documentation on its first run. An overrun raises
`CallTimeout`; calls that allow UI recovery also try to close the top-most modal
and tap Escape. Help search skips UI recovery. The CLI exits with status 2;
`python chief_mcp.py --timeout 5 <command>` overrides the default deadline, and
`--timeout 0` disables that default watchdog. The separate dialog, export, and
help-search deadlines still apply. After a UI call times out, `settle` or a
restart may be needed.

Keyboard helpers, for the states MCP cannot reach. `send_key` and `send_escape`
include Escape (cancel an in-place edit) and Tab (cycle the selection through
stacked objects). Keys are restricted to an allowlist; Delete remains refused.
Without `steal=True` they refuse unless Chief already
has the foreground; with it, Chief is fronted for the keystroke and the previous
window is put back. `settle` finishes a run cleanly: cancel the dialog, tap
Escape, clear the selection, report whether a dialog is still open.

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
`apply=True`, and printing the value each dialog reported afterwards. Each object
gets its own dialog, so count on about a second per object. A failed object is
retried once after settling, since most failures are a stale modal rather than
the object; `--on-error continue` keeps the rest of the batch going, and
`--selected` takes the targets from the current selection when an object cannot
be matched by name or reached by clicking.

`select` filters by name, layer, or floor and reads the selection back to verify
the object IDs. It requires at least one filter. If nothing matches, it leaves
the current selection alone; `select --clear` clears it explicitly. `--exact`
uses case-sensitive whole-string matching; ordinary name and layer filters
ignore case. Selection does not pan the view or navigate to another layout page.

`fields --selected` inspects exactly one selected object. An empty or multiple
selection is rejected before a dialog opens. The object must be reachable on
the current view or layout page. `--all-panels` reads every listed
panel during one opening, then cancels the dialog. `--contains` filters field
IDs and labels without regard to case. `--options` shows dropdown and other
option choices as IDs and labels, including disabled choices and long lists
loaded from the tool's report file. Use the panel, field ID, and option ID with
`apply --panel ... --field ... --option ...`; inspect again before writing if
the dialog state has changed, since option IDs can shift.

`export --type image|pdf|dwg2d <path>` exports the front view. The type is
required; use a matching `.png`, `.pdf`, or `.dwg` filename. `image <path>`
continues to work as the PNG shortcut.

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
- Python 3.10+ with the `mcp` package installed. `psutil` is in
  `requirements.txt` because the bundled server imports it — it has to be
  installed in whichever interpreter launches the server, which is usually this
  same one.
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
| `CAMCP_BRIDGE` | Set to `1` to launch the local bridge adapter |
| `CAMCP_BRIDGE_TRACE_FILE` | Optional private JSONL log of original bridge replies; requires the adapter |

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

To experiment with the bridge, set `CAMCP_BRIDGE=1` in `.env`. The helpers then
launch `chief_bridge.py`, which imports the installed vendor package and uses
its tool registry. Native replies containing `success: false`, and static
`failed:` replies, are marked as MCP errors. Their content is preserved.
The installed Chief files remain unchanged. This option requires the native
`-m camcp.chief.server` launch configuration shown above, or the explicit
`CAMCP_PYTHON` and `CAMCP_CHIEF_SRC` settings.

Set `CAMCP_BRIDGE_TRACE_FILE` to a private path to capture original replies and
the resulting error flags. These logs can contain drawing text and properties;
keep them out of source control. Chief continues to enforce its native
capabilities, including Project Management requirements and which dialog
controls can be read. Set `CAMCP_BRIDGE=0` to return to the original bridge.

## Usage

```bash
python chief_mcp.py rooms
python chief_mcp.py objects --name Kitchen
python chief_mcp.py objects --entire
python chief_mcp.py audit
python chief_mcp.py metrics
python chief_mcp.py find --name "hinged door"
python chief_mcp.py select --name "hinged door" --layer Doors --floor 1
python chief_mcp.py select --clear
python chief_mcp.py fields <object-id>
# With exactly one object selected in Chief:
python chief_mcp.py fields --selected --all-panels --contains height
python chief_mcp.py fields --selected --all-panels --options
python chief_mcp.py apply --name "hinged door" --field doorID_Height --value 80" --expect Door
python chief_mcp.py apply --name "hinged door" --field doorID_Height --value 84" --expect Door --apply
python chief_mcp.py apply --selected --field roomID_CeilingElevation --value '120"' --panel Structure --expect Room --apply
python chief_mcp.py snapshot
python chief_mcp.py diff ~/.chief_mcp/snap-2026-11-01T190949.json
python chief_mcp.py clear          # cancel a stranded dialog
python chief_mcp.py settle         # cancel, Escape, clear the selection: ready for a person
python chief_mcp.py recover        # cancel dialogs, report what is left
python chief_mcp.py escape --steal # cancel an in-place edit holding the keyboard
python chief_mcp.py active         # front Chief, deliberately, and say where focus went
python chief_mcp.py views
python chief_mcp.py docs "layer sets"
python chief_mcp.py image out.png
python chief_mcp.py export --type image out.png
python chief_mcp.py export --type pdf out.pdf
python chief_mcp.py export --type dwg2d out.dwg
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
| Gestures while Chief is behind another window, or minimized | work; the window does not need the foreground |
| Picking an object with something on top of it | works: Tab cycles the stack under the cursor; Ctrl+click does not |
| An in-place edit (click a dimension number) | holds the keyboard indefinitely; only Escape clears it |
| Ctrl+E on a selection | opens the specification, but untracked: it can only be closed |
| Bringing Chief to the front | takes the keyboard; recovery and cleanup may do this briefly |
| Synthetic drags | do not commit; positions never change |
| Text object contents | absent from object properties; Rich Text editor is unreadable through MCP; PDF text extraction is a workaround |
| `invoke_command`, `input_hotkey`, `open_document`, project browser | refused |
| Delete, by any route | refused by design |

## Tests

```bash
python -m unittest discover -s tests -t .
```

The unit tests are offline: inch formatting and parsing, bounding boxes,
hit-point selection against overlapping obstacles, launch configuration,
key handling against a fake `user32`, and dialog cleanup. Run `selftest.py` for
the live check -- it only reads, opening no dialogs.

## License

MIT. Not affiliated with Chief Architect, Inc.
