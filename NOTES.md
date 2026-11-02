# Field notes

Measured against Chief Architect Premier X18, build 28.2.1.14, with
**Project Management disabled** and files kept outside Chief's managed store.

Chief staff have said the tool set is incomplete in the initial release and that
more tools are coming. Retest the refusals after each X18 update rather than
treating them as permanent.

## Wiring

| Piece | Value |
|---|---|
| Server source | `<install>/resources/camcp/src` (Python, src layout) |
| Launch | `python -m camcp.chief.server` with `PYTHONPATH` pointing at that `src` |
| Dependencies | `mcp[cli]` 2.x, `psutil` |
| Transport | stdio; relays to Chief over `\\.\pipe\chief-architect-mcp-28` |
| Tool cache | `%LOCALAPPDATA%` (Windows) under the server's own directory |

The core server is local-only: no HTTP client, no telemetry, no license call.
The one component that talks to the internet is the optional image-utilities
server, which needs a Google API key and is not registered by default.

## Capability matrix (Project Management off)

| Capability | Status |
|---|---|
| Discover objects / rooms / views / commands / selection | works |
| Read object properties (~17–25 fields each) | works |
| Select objects by id | works |
| Export view to PDF / image / DWG | works |
| Search bundled help docs | works |
| Pointer click, double-click, scroll | works |
| Drag to move an object | **no-op** |
| `invoke_command`, `input_hotkey`, `open_document`, project browser | refused: needs project management mode (this build) |
| Layout page navigation | unavailable (the relevant command is gated) |
| Read text object contents | impossible |

## Recipes that work

0. **Before anything else** — `recover()` the app, then `snapshot` the front view.
   Keep the snapshot file so a `diff` afterwards can prove what changed. A dialog
   left open refuses every later gesture, and the refusal looks exactly like a
   click that missed.
1. **Edit an object's numeric properties** — `doubleClick` a free point on the
   object, then in the Specification dialog write the field and press OK.
   Position fields live on the General panel (`boxID_XPos`, `boxID_YPos`).
2. **Rename rooms** — room labels are generated from `roomID_RoomName`, so
   renaming the room changes the label. `doubleClick` the interior first.
3. **Fill behind a text object** — Text Specification → panel `Fill Style` →
   press `attrID_PatternColor` → in *Select Color* write `ColorShower_Hex`
   (`#FFFF00`) → OK → OK.
4. **Verify geometry without screenshots** — re-read `discover_all_objects` or
   `discover_rooms` and compare numbers.
5. **Change a property across many objects** — `find` the set, `fields` to read a
   field id off one member, then `apply` with `--apply`. One dialog per object:
   the multi-object dialog edits only the object you double-clicked.
6. **Verify a dialog value without screenshots** — reopen the dialog, read the
   field, then Cancel.
7. **Read annotation text** — export the view to PDF and extract with `pypdf`.
   Complete but noisy: some styles come out letter-spaced, and dimensions
   interleave with notes.

## Pitfalls

- **A focused edit box holds Chief hostage, indefinitely.** Open a Specification
  dialog, leave the cursor in a field, and every gesture comes back
  `success: false` with "Chief is showing an agent-tracked modal dialog".
  Nothing times out; it waits for a decision that never comes. Reproduced on
  demand: open a dialog, gesture refused, `recover()`, gesture works again.
  `spec_dialog()` exists so the recipes cancel their own dialog when the body
  raises, and `recover()` is the manual fix -- including `--keyboard`, which taps
  Escape for an in-place text edit, the case with no dialog to inspect. Escape
  is the only key exposed: Delete and the other hotkeys are refused over MCP by
  design, and driving them through Win32 would be a way around that, not a fix.
- **Do not front the window before every gesture.** A click already activates
  Chief, so pre-activation adds nothing and steals the keyboard from whatever the
  user is typing into; it reads as the app hanging on input until they click back
  to their editor. Worse, the ALT tap Windows requires can leave a menu grabbed
  in the window that had focus, and then clicking that window is not enough.
  Nothing in the module touches the foreground unless asked: `recover(focus=True)`
  or `python chief_mcp.py active`.
- **Gestures are not blocked by a background window, but activation is blocked
  until ALT is tapped.** Measured here: the same double-click opened its dialog
  with Chief covered by another app, minimized, and in front; a 9-door
  click-and-read-selection hit test scored identically either way. What does
  fail is `SetForegroundWindow` from a background process, which returns true
  while the foreground stays put -- a plain click on the window works because
  the click itself activates it. `ensure_active()` reproduces that, and every
  gesture reply now carries an `activation` block saying what the foreground
  was, so "it stopped responding" can be answered from the log rather than by
  memory.
- **Delete is refused on purpose.** Rebinding it to a fresh hotkey does not help;
  the server recognises the action. Park objects at a fixed offset and record
  their original positions so they can be restored.
- **`invoke_command` cannot be undone.** Work on a copy of the plan before letting
  an agent edit anything.
- **Resetting a room label deletes the macro inside it.** Agents do this while
  tidying; the label has to be restored by name, not by undo alone.
- **Long option lists move into a report file.** Merge `reportFilename` into the
  payload instead of replacing it. Replacing it drops `panel`, and with it every
  dialog field, which looks exactly like a dialog that answered nothing.
- **Drags never commit.** A single `drag`, a long `drag`, and
  press → move → move → release all reported success while every position
  stayed identical. Clicks hit-test correctly, so it is drag-move specifically
  that fails.
- **A room's reported interior point can sit under a dimension line**, so a
  double-click aimed at it opens the dimension's dialog instead. Use
  `chief_mcp.free_point()`.
- **Room-layer bounding boxes overlap**, and the exterior room spans the whole
  building. Exclude layer `Rooms` when choosing a hit point or nothing looks
  free.
- **A multi-object Specification dialog edits only the double-clicked object.**
  Loop per object.
- **Position fields display rounded to 1/16" but store decimals.** Hitting an
  exact target may take two passes.
- **Text content is never exposed.** Properties are metadata only; asking for
  `text`/`contents`/`string`/`caption` returns nothing. The rich text editor
  control inside the dialog reports `support: unsupported` and
  `hasUnreadableContent: true`.
- **`discover_all_objects(entireDocument=True)` omits `layoutPage`.**
- **The mcp 2.x client** uses `init.server_info`, not `init.serverInfo`.
- **The front view can change underneath you** if the user switches tabs
  mid-task. Re-check `discover_open_views` before firing gestures at
  coordinates.

## Project Management

Preferences → Project Management → *Use Chief Architect Project Management*.
Every plan and layout must be closed to switch. It relocates files into a
hidden managed store with hashed names and warns against placing that store on
a synced or network location, so check how you store project files first.
Enabling it unlocks commands, hotkeys, document opening, and the project browser.

Whether the dependency is architectural is still open. The staff reply in the
forum thread addressed missing tools in the initial release rather than saying
Project Management is technically required.
