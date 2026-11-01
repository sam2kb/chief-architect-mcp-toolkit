# Field notes

Measured against Chief Architect Premier X18, build 28.2.1.14, with
**Project Management disabled** and files kept outside Chief's managed store.

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
| `invoke_command`, `input_hotkey`, `open_document`, project browser | refused: needs project management mode |
| Layout page navigation | unavailable (the relevant command is gated) |
| Read text object contents | impossible |

## Recipes that work

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
5. **Verify a dialog value without screenshots** — reopen the dialog, read the
   field, then Cancel.
6. **Read annotation text** — export the view to PDF and extract with `pypdf`.
   Complete but noisy: some styles come out letter-spaced, and dimensions
   interleave with notes.

## Pitfalls

- **Drags never commit.** A single `drag`, a long `drag`, and
  press → move → move → release all reported success while every position
  stayed identical. Clicks hit-test correctly, so it is drag-move specifically
  that fails.
- **A room's reported interior point can sit under a dimension line**, so a
  double-click aimed at it opens the dimension's dialog instead. Use
  `camcp.free_point()`.
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
a synced or network location — worth checking against how you store project
files before flipping it. Enabling it unlocks commands, hotkeys, document
opening, and the project browser.
