# chief-architect-mcp-toolkit

Helpers for working with **Chief Architect Premier X18**'s bundled `ca-mcp-x18`
MCP server from an AI coding agent.

The server ships with the application at `<install>/resources/camcp/` and speaks
MCP over stdio, relaying to the running Chief instance across a local named pipe.
It exposes ~30 tools for inspecting a drawing, driving the UI, and exporting
views. What it does *not* give you is ergonomic Python access — every discovery
tool writes its payload to a temp JSON report and returns only a filename.

This toolkit papers over that, and records what actually works.

## What is in here

| File | Purpose |
|---|---|
| `camcp.py` | Async helpers + CLI over the MCP tools |
| `selftest.py` | Read-only smoke test: connect, list views/rooms, pick a hit point |
| `NOTES.md` | Field notes: capability matrix, working recipes, pitfalls |
| `privacy_check.py` | Fails if personal or secret-looking data reaches tracked files |

## Helpers

Reads: `objects`, `properties`, `rooms`, `selection`, `views`, `commands`,
`docs`, `status`.

Input: `select`, `click`, `dblclick`, `export_image`, `export_pdf`.

Dialogs (the reliable way to edit anything): `dialog_fields`, `find_node`,
`node_value`, `set_field`, `press`.

Geometry: `bbox`, `left`, `width`, `contains`, `free_point`, `fmt_inches`.

`call()` follows `reportFilename` automatically, so
`await camcp.objects(s)` returns the list rather than a path.

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
python camcp.py rooms
python camcp.py objects --name Kitchen
python camcp.py objects --entire
python camcp.py views
python camcp.py docs "layer sets"
python camcp.py image out.png
```

```python
import camcp

async with camcp.client() as s:
    rooms = await camcp.rooms(s)
    office = next(r for r in rooms if r["roomType"] == "Office")
    x, y = camcp.free_point(office["boundingBox"], await camcp.objects(s))
    await camcp.select(s, [office["objectId"]])
```

## Before you trust it

Read `NOTES.md`. The short version:

- Reads and dialog field writes are dependable.
- Synthetic drags do not commit — positions never change.
- Text object contents are not exposed anywhere.
- With Project Management off, `invoke_command`, `input_hotkey`,
  `open_document` and the project browser are refused.

## License

MIT. Not affiliated with Chief Architect, Inc.
