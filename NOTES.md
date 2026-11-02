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
| Dependencies | `mcp[cli]` 2.x, `psutil` (the server imports `psutil`, so it must be in whichever interpreter launches it) |
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
| Tab, to cycle the selection through stacked objects | works, when sent as a real keystroke |
| Escape, to cancel an in-place edit | works as a real keystroke; not reachable over MCP |
| Drag to move an object | **no-op** |
| `invoke_command`, `input_hotkey`, `open_document`, project browser | refused: needs project management mode (this build) |
| Layout page navigation | unavailable (the relevant command is gated) |
| Read text object contents | impossible |

## Recipes that work

0. **Before anything else** — `recover()` the app, then `snapshot` the front view.
   Keep the snapshot file so a `diff` afterwards can prove what changed. A dialog
   left open refuses every later gesture, and the refusal looks exactly like a
   click that missed.
1. **Edit an object's numeric properties** — open its Specification with
   `open_spec_anywhere`, write the field, press OK. Position fields live on the
   General panel (`boxID_XPos`, `boxID_YPos`). Do not double-click a guessed
   point: if it lands on a dimension number, Chief starts an in-place edit and
   holds the keyboard until something cancels it.
2. **Rename rooms** — room labels are generated from `roomID_RoomName`, so
   renaming the room changes the label. Rooms have no object dict to hit-test,
   so they still go through `open_spec`, which guesses points inside the bounds.
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

## What was measured

Everything below was run against build `28.2.1.14` on 2026-11-01, Project
Management off, and is written down because most of it was not what we assumed.

| Question | Answer | How it was checked |
|---|---|---|
| Do gestures work while Chief is behind another window, or minimized? | Yes. Clicks and double-clicks land in all three states | the same double-click run covered, minimized and focused; a 9-door click-and-read hit test scored identically each way |
| Does Ctrl+click cycle through overlapping objects? | No. The selection stays on the topmost object | plain click, then three Ctrl+clicks, on every door a plain click missed |
| Does Tab cycle? | Yes, usually one press | click, then Tab, reading the selection after each press: `Marker` → `Hinged Door` |
| Can a covered object be reached at all? | Yes. 8 of 9 doors, usually within one click of centre | 7×7 grid of clicks across each door's bounds, reading the selection back |
| Is a *refused* gesture the only way the app gets stuck? | No, and this is the important one. It can hold a caret with no refused calls at all | a traced 26-gesture run: 0 failures, 0 exceptions, every call completed, and the dimension field was still open |
| What clears an in-place canvas edit? | Escape, delivered while Chief owns the foreground. Nothing else does | reproduced with a Specification dialog, which refuses gestures the same way |
| Does a dialog's focused edit box hold input? | Yes, indefinitely, with a message naming the dialog | open any Specification dialog, then send a gesture |
| Is the "hang" in this client? | No. Every MCP call completed in both a bad run and a good one | `CAMCP_TRACE=1`: 95–160 calls, each with a matching completion, none slower than 0.55 s |
| Does the front-most view matter? | Yes. Listings describe the front-most view, which may be a saved plan view rather than the floor plan | `views` reported `Mechanical Plan View` front-most; object counts drifted 76–79 between runs |
| Do drags commit? | No. Only dialog field writes do | single drag, long drag, and press/move/release all reported success with positions unchanged |

Three rules fell out of that:

1. **Clean up unconditionally, not on failure.** Escape sent in reaction to a
   refusal never fires, because the stuck state does not refuse anything. Cancel,
   Escape, and clear the selection after *every* object, in a `finally`.
2. **Double-click only a point that a single click proved**, by reading the
   selection back. A guessed double-click on a dimension number starts an
   in-place edit, and that is what strands the app.
3. **Never take the foreground implicitly.** It steals the keyboard from whoever
   is typing, and the ALT tap needed for it can leave a menu grabbed.

## Pitfalls

- **An in-place edit on the canvas holds the keyboard too, and hides better.**
  Select an object, click the dimension number, and Chief puts a caret on the
  canvas waiting for digits. There is no dialog: `discover_open_dialogs` reports
  nothing, so `clear_dialogs` has nothing to cancel, and every gesture is refused
  from then on. Escape is the only thing that clears it, and a key only reaches
  Chief while Chief has the foreground. `gesture()` now retries once with Escape
  when a gesture is refused and no dialog is open, briefly fronting Chief and
  putting the previous window back -- so the run unsticks instead of hanging, and
  the window being typed into keeps its focus. `python chief_mcp.py escape` does
  the same by hand.
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
