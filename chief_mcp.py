"""chief_mcp.py -- helper layer over Chief Architect's bundled ``ca-mcp-x18`` MCP server.

Why this exists: every ``chief_discover_*`` MCP tool writes its payload to a
temp JSON report and returns only the filename. These helpers call the tool,
load that report, and hand back plain Python.

Requires a Python environment with the ``mcp`` package (the same one the MCP
server itself runs under).

CLI:
    python chief_mcp.py rooms
    python chief_mcp.py objects --name Kitchen
    python chief_mcp.py views

Library:
    import chief_mcp
    async with chief_mcp.client() as s:
        rooms = await chief_mcp.rooms(s)
        await chief_mcp.select(s, [r["objectId"] for r in rooms])
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent


def load_env(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, quotes optional.

    Never overrides variables that are already set, so shell/CI values win.
    No third-party dependency on purpose.
    """
    source = path or Path(os.environ.get("CAMCP_ENV_FILE", REPO_ROOT / ".env"))
    if not source.is_file():
        return
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def server_params() -> StdioServerParameters:
    """Launch params: explicit CAMCP_PYTHON/CAMCP_CHIEF_SRC from .env, else mcp.json."""
    python = os.environ.get("CAMCP_PYTHON")
    chief_src = os.environ.get("CAMCP_CHIEF_SRC")
    if python and chief_src:
        env = dict(os.environ)
        env["PYTHONPATH"] = chief_src
        return StdioServerParameters(
            command=python, args=["-m", "camcp.chief.server"], env=env
        )


load_env()

SERVER_NAME = os.environ.get("CAMCP_SERVER", "ca-mcp-x18")


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def mcp_config_path() -> Path:
    """Locate the VS Code user-level mcp.json without hard-coding a profile."""
    override = os.environ.get("CAMCP_MCP_JSON")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Code" / "User" / "mcp.json"
    return Path.home() / ".config" / "Code" / "User" / "mcp.json"


@asynccontextmanager
async def client():
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") for b in result.content).strip()


def _payload(result):
    """Parse a tool result, merging in any report file it refers to.

    Some tools answer with a short payload plus a ``reportFilename`` holding the
    bulky part (object lists, long option lists). The report is merged under the
    live payload rather than replacing it, so keys like ``panel`` survive.
    """
    text = _text(result)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(data, dict):
        return data

    report = data.get("reportFilename")
    if not report or not os.path.isfile(report):
        return data
    try:
        with open(report, encoding="utf-8") as fh:
            from_file = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return data
    if not isinstance(from_file, dict):
        return from_file

    merged = dict(from_file)
    merged.update(data)
    return merged


async def call(session: ClientSession, tool: str, **arguments):
    """Call a tool; report files are loaded for you."""
    args = {k: v for k, v in arguments.items() if v is not None}
    return _payload(await session.call_tool(tool, args))


async def raw(session: ClientSession, tool: str, **arguments):
    """Call a tool; return its raw text (no report following)."""
    args = {k: v for k, v in arguments.items() if v is not None}
    return _text(await session.call_tool(tool, args))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
async def objects(session, entire: bool = False):
    data = await call(session, "chief_discover_all_objects", entireDocument=entire or None)
    return data.get("objects", data) if isinstance(data, dict) else data


async def properties(session, object_ids, names=None):
    entries = [{"objectId": i} for i in object_ids]
    data = await call(
        session, "chief_discover_object_properties",
        objectIds=entries, propertyNames=names or None,
    )
    return data.get("objects", data)


async def rooms(session, floor=None):
    data = await call(session, "chief_discover_rooms", floor=floor)
    return data.get("rooms", data)


async def selection(session):
    data = await call(session, "chief_discover_selection")
    return data.get("selectedObjects", [])


async def views(session):
    data = await call(session, "chief_discover_open_views")
    return data.get("views", [])


async def commands(session):
    data = await call(session, "chief_discover_commands")
    return data.get("commands", data)


async def docs(session, query: str, limit: int = 5):
    return await call(session, "chief_search_docs", query=query, maxResults=limit)


async def status(session):
    return await call(session, "chief_discover_application_status")


# --------------------------------------------------------------------------
# input (pointer only -- hotkeys and commands need Project Management)
# --------------------------------------------------------------------------
async def select(session, object_ids):
    data = await call(session, "chief_select_objects", objectIds=list(object_ids))
    return data.get("count", 0)


async def click(session, x, y):
    return await call(session, "chief_input_canvas_gesture",
                      gestures=[{"type": "click", "button": "left", "x": x, "y": y}])


async def dblclick(session, x, y):
    """Open a Specification dialog. Returns the dialog descriptor."""
    data = await call(session, "chief_input_canvas_gesture",
                      gestures=[{"type": "doubleClick", "button": "left", "x": x, "y": y}])
    return data


async def export_image(session, path):
    return await call(session, "chief_export_data", exportType="Image", exportPath=path)


async def export_pdf(session, path):
    return await call(session, "chief_export_data", exportType="PDF", exportPath=path)


# --------------------------------------------------------------------------
# dialogs (the reliable edit channel)
# --------------------------------------------------------------------------
async def dialog_fields(session, panel=None):
    return await call(session, "chief_discover_dialog_fields", panel=panel)


def find_node(fields, node_id):
    """Pull one node out of a dialog_fields payload."""
    panel = (fields or {}).get("panel") or {}
    for node in panel.get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


def node_value(fields, node_id):
    node = find_node(fields, node_id)
    return None if node is None else node.get("value")


async def set_field(session, field_id, value=None, option=None, label=None, question=None):
    return await call(
        session, "chief_set_dialog_field",
        fieldId=field_id, value=value, optionId=option, label=label, questionId=question,
    )


async def press(session, choice, label, question=None):
    return await call(
        session, "chief_click_dialog_button",
        choiceId=choice, label=label, questionId=question,
    )


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def bbox(obj):
    loc, size = obj["location"], obj["size"]
    return {
        "minX": loc["x"] - size["width"] / 2, "maxX": loc["x"] + size["width"] / 2,
        "minY": loc["y"] - size["depth"] / 2, "maxY": loc["y"] + size["depth"] / 2,
    }


def left(obj):
    return bbox(obj)["minX"]


def width(obj):
    return obj["size"]["width"]


def contains(b, x, y):
    return b["minX"] <= x <= b["maxX"] and b["minY"] <= y <= b["maxY"]


def free_point(bounds, objects, skip_ids=(), skip_names=("Room", "Exterior room"),
               skip_layers=("Rooms",), margin=6.0, steps=25):
    """Point inside ``bounds`` clear of every other object's bounding box.

    A room's reported interior point can sit under a dimension line, so a
    double-click aimed at it hits the dimension instead of the room. Candidates
    are tried from the centre outward.

    Room-layer objects are excluded by default: room bounding boxes overlap their
    neighbours, and the exterior room spans the whole building, so treating them
    as obstacles would reject every candidate.
    """
    skip = set(skip_ids)
    obstacles = [
        bbox(o) for o in objects
        if o.get("objectId") not in skip
        and o.get("name") not in skip_names
        and o.get("layer") not in skip_layers
    ]
    cx = (bounds["minX"] + bounds["maxX"]) / 2
    cy = (bounds["minY"] + bounds["maxY"]) / 2
    span_x = bounds["maxX"] - bounds["minX"] - 2 * margin
    span_y = bounds["maxY"] - bounds["minY"] - 2 * margin
    if span_x <= 0 or span_y <= 0:
        return cx, cy

    candidates = []
    for i in range(steps):
        x = bounds["minX"] + margin + span_x * i / (steps - 1)
        for j in range(steps):
            y = bounds["minY"] + margin + span_y * j / (steps - 1)
            candidates.append(((x - cx) ** 2 + (y - cy) ** 2, x, y))
    candidates.sort()

    for _, x, y in candidates:
        if not any(contains(b, x, y) for b in obstacles):
            return x, y
    return cx, cy


def fmt_inches(value: float, denom: int = 16) -> str:
    """81.375 -> 6'-9 3/8\". Fractions are reduced."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    feet = int(v // 12)
    frac = round((v - feet * 12) * denom) / denom
    if frac >= 12:
        feet += 1
        frac -= 12
    whole = int(frac)
    num = round((frac - whole) * denom)
    text = f"{sign}{feet}'-{whole}"
    if num:
        divisor = math.gcd(num, denom)
        text += f" {num // divisor}/{denom // divisor}"
    return text + '"'


def parse_inches(text: str) -> float:
    """`7 1/2"` -> 7.5, `-1 5/8"` -> -1.625, `2'-6"` -> 30.0, `120` -> 120.0."""
    raw = str(text).strip().replace('"', "").replace("\u201d", "")
    if not raw:
        raise ValueError("empty length")
    sign = -1.0 if raw.lstrip().startswith("-") else 1.0
    raw = raw.lstrip("+-").strip()

    feet = 0.0
    if "'" in raw:
        head, _, raw = raw.partition("'")
        feet = float(head.strip() or 0)
        raw = raw.strip().lstrip("-").strip()

    inches = 0.0
    for part in raw.split():
        if "/" in part:
            num, _, den = part.partition("/")
            inches += float(num) / float(den)
        elif part:
            inches += float(part)
    return sign * (feet * 12 + inches)


# --------------------------------------------------------------------------
# recipes -- the edit paths that actually commit
# --------------------------------------------------------------------------
def _candidate_points(bounds, objects, skip_ids=(), attempts=4):
    """Ordered double-click targets: the free point first, then fallbacks."""
    points = [free_point(bounds, objects, skip_ids=skip_ids)]
    points.append(((bounds["minX"] + bounds["maxX"]) / 2,
                   (bounds["minY"] + bounds["maxY"]) / 2))
    for fx, fy in ((0.25, 0.25), (0.75, 0.75), (0.25, 0.75), (0.75, 0.25)):
        points.append((
            bounds["minX"] + (bounds["maxX"] - bounds["minX"]) * fx,
            bounds["minY"] + (bounds["maxY"] - bounds["minY"]) * fy,
        ))
    seen = set()
    ordered = []
    for x, y in points:
        key = (round(x, 3), round(y, 3))
        if key in seen:
            continue
        seen.add(key)
        ordered.append((x, y))
    return ordered[:attempts]


async def open_spec(session, bounds, objects, skip_ids=(), expect=None, attempts=4):
    """Double-click until a dialog opens, and return its payload.

    The first click can land on a dimension line running across the object, so
    later attempts try other points inside the bounds. When ``expect`` is given,
    a dialog whose title does not contain it is cancelled and the next point is
    tried.
    """
    wrong = None
    for x, y in _candidate_points(bounds, objects, skip_ids, attempts):
        dialog = await dblclick(session, x, y)
        if not (isinstance(dialog, dict) and dialog.get("kind") == "dialog"):
            continue
        title = dialog.get("title") or ""
        if expect and expect.lower() not in title.lower():
            await press(session, "1", "Cancel", dialog.get("questionId"))
            wrong = title
            continue
        return dialog
    suffix = f" (last dialog opened was {wrong!r})" if wrong else ""
    raise RuntimeError(f"no matching dialog opened inside those bounds{suffix}")


async def move_object(session, bounds, objects, dx=0.0, dy=0.0, skip_ids=()):
    """Shift an object by (dx, dy) inches through its position fields.

    Works on objects whose Specification dialog exposes ``boxID_XPos`` /
    ``boxID_YPos`` on the General panel (CAD blocks, text, and similar).
    """
    dialog = await open_spec(session, bounds, objects, skip_ids=skip_ids)
    question = dialog.get("questionId")
    fields = await dialog_fields(session, panel="General")
    x_node = find_node(fields, "boxID_XPos")
    y_node = find_node(fields, "boxID_YPos")
    if x_node is None or y_node is None:
        await press(session, "1", "Cancel", question)
        raise RuntimeError("that dialog has no X/Y position fields")

    if dx:
        await set_field(session, "boxID_XPos",
                        value=f'{parse_inches(x_node["value"]) + dx}"', question=question)
    if dy:
        await set_field(session, "boxID_YPos",
                        value=f'{parse_inches(y_node["value"]) + dy}"', question=question)
    await press(session, "0", "OK", question)


async def rename_room(session, bounds, objects, name, skip_ids=()):
    """Set a room's name, which is what its plan label displays."""
    dialog = await open_spec(session, bounds, objects, skip_ids=skip_ids)
    question = dialog.get("questionId")
    fields = await dialog_fields(session, panel="General")
    if find_node(fields, "roomID_RoomName") is None:
        await press(session, "1", "Cancel", question)
        raise RuntimeError("that dialog has no room name field")
    await set_field(session, "roomID_RoomName", value=name, question=question)
    await press(session, "0", "OK", question)


async def set_text_fill(session, bounds, objects, hex_color, skip_ids=()):
    """Set the fill/background of a text object, e.g. '#FFFF00' for yellow."""
    dialog = await open_spec(session, bounds, objects, skip_ids=skip_ids)
    question = dialog.get("questionId")
    await dialog_fields(session, panel="Fill Style")

    await set_field(session, "attrID_PatternColor", value=True, question=question)
    colour = await dialog_fields(session)
    colour_question = colour.get("questionId")
    await set_field(session, "ColorShower_Hex", value=hex_color, question=colour_question)
    await press(session, "0", "OK", colour_question)
    await press(session, "0", "OK", question)


# --------------------------------------------------------------------------
# read-only analysis
# --------------------------------------------------------------------------
ROOM_FIELDS = {
    "roomID_RoomName": "name",
    "roomID_Dimensions": "dimensions",
    "roomID_Perimeter": "perimeter",
    "roomID_StandardArea": "standard_area",
    "roomID_InteriorArea": "interior_area",
    "roomID_Volume": "volume",
}


async def room_metrics(session, rooms_list=None, limit=None):
    """Read each room's areas and perimeter from its dialog, then cancel.

    Chief reports these on the General panel, so they are the app's own
    figures rather than a bounding-box estimate. The dialog is only read: every
    room is cancelled, never confirmed.
    """
    objs = await objects(session)
    targets = rooms_list if rooms_list is not None else await rooms(session)
    if limit:
        targets = targets[:limit]

    rows = []
    for room in targets:
        bounds = room.get("boundingBox")
        if not bounds:
            continue
        try:
            dialog = await open_spec(session, bounds, objs,
                                     skip_ids=[room.get("objectId")], expect="Room")
        except RuntimeError as exc:
            rows.append({"name": room.get("roomName"), "error": str(exc)})
            continue

        question = dialog.get("questionId")
        fields = await dialog_fields(session, panel="General")
        row = {"name": room.get("roomName"), "type": room.get("roomType")}
        for node_id, key in ROOM_FIELDS.items():
            row[key] = node_value(fields, node_id)
        await press(session, "1", "Cancel", question)
        rows.append(row)
    return rows


def audit_findings(objects_list, rooms_list):
    """Checks that only read the model. Returns [{rule, detail, objects}]."""
    findings = []

    unnamed = [r for r in rooms_list if not (r.get("roomName") or "").strip()]
    if unnamed:
        findings.append({
            "rule": "unnamed-room",
            "detail": f"{len(unnamed)} room(s) have no name",
            "objects": [r.get("objectId") for r in unnamed],
        })

    unbounded = [r for r in rooms_list if not r.get("boundingBox")]
    if unbounded:
        findings.append({
            "rule": "room-without-bounds",
            "detail": f"{len(unbounded)} room(s) report no bounding box",
            "objects": [r.get("objectId") for r in unbounded],
        })

    degenerate = [o for o in objects_list
                  if o["size"]["width"] <= 0 or o["size"]["depth"] <= 0]
    if degenerate:
        findings.append({
            "rule": "zero-size-object",
            "detail": f"{len(degenerate)} object(s) have zero width or depth",
            "objects": [o["objectId"] for o in degenerate],
        })

    misfiled = [o for o in objects_list
                if o["name"] in ("Text", "Rich Text") and "text" not in o["layer"].lower()]
    if misfiled:
        findings.append({
            "rule": "text-off-text-layer",
            "detail": f"{len(misfiled)} text object(s) sit on a layer without 'text' in its name",
            "objects": [o["objectId"] for o in misfiled],
        })

    locked = [o for o in objects_list if o.get("layerLocked")]
    if locked:
        findings.append({
            "rule": "locked-layer-object",
            "detail": f"{len(locked)} object(s) are on locked layers",
            "objects": [o["objectId"] for o in locked],
        })

    buckets = {}
    for o in objects_list:
        key = (o["name"],
               round(o["location"]["x"], 3), round(o["location"]["y"], 3),
               round(o["size"]["width"], 3), round(o["size"]["depth"], 3))
        buckets.setdefault(key, []).append(o["objectId"])
    duplicates = {k: v for k, v in buckets.items() if len(v) > 1}
    if duplicates:
        findings.append({
            "rule": "exact-duplicate",
            "detail": f"{len(duplicates)} position(s) hold objects that match exactly",
            "objects": [oid for ids in duplicates.values() for oid in ids],
        })

    return findings


async def audit(session):
    """Run the read-only checks against the front view."""
    return audit_findings(await objects(session), await rooms(session))


# --------------------------------------------------------------------------
# parking -- the documented workaround for delete being refused
# --------------------------------------------------------------------------
PARK_OFFSET = (0.0, 5000.0)
PARK_MANIFEST = Path(os.environ.get(
    "CAMCP_PARK_MANIFEST", str(Path.home() / ".chief_mcp_parked.json")
))


def _read_manifest() -> dict:
    if not PARK_MANIFEST.is_file():
        return {}
    try:
        return json.loads(PARK_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(data: dict) -> None:
    PARK_MANIFEST.write_text(json.dumps(data, indent=1), encoding="utf-8")


async def park_objects(session, object_ids, apply=False, offset=PARK_OFFSET):
    """Move objects out of the way, since delete is refused over MCP.

    Returns the plan and moves nothing unless ``apply`` is true. Each parked id
    is written to a manifest with its original position, so ``unpark_objects``
    can put it back.
    """
    objs = await objects(session)
    index = {o["objectId"]: o for o in objs}
    dx, dy = offset

    plan = []
    for oid in object_ids:
        obj = index.get(oid)
        if obj is None:
            plan.append({"objectId": oid, "error": "not in the front view"})
            continue
        plan.append({
            "objectId": oid,
            "name": obj["name"],
            "from": {"x": obj["location"]["x"], "y": obj["location"]["y"]},
            "to": {"x": obj["location"]["x"] + dx, "y": obj["location"]["y"] + dy},
        })

    if not apply:
        return {"applied": False, "plan": plan}

    manifest = _read_manifest()
    done = []
    for entry in plan:
        if "error" in entry:
            continue
        obj = index[entry["objectId"]]
        await move_object(session, bbox(obj), objs, dx=dx, dy=dy,
                          skip_ids=[entry["objectId"]])
        manifest[entry["objectId"]] = entry["from"]
        done.append(entry["objectId"])
    _write_manifest(manifest)
    return {"applied": True, "moved": done, "manifest": str(PARK_MANIFEST)}


async def unpark_objects(session, object_ids=None):
    """Move parked objects back to where the manifest says they came from."""
    manifest = _read_manifest()
    targets = list(manifest) if object_ids is None else list(object_ids)
    objs = await objects(session)
    index = {o["objectId"]: o for o in objs}

    restored = []
    for oid in targets:
        home = manifest.get(oid)
        obj = index.get(oid)
        if not home or obj is None:
            continue
        await move_object(session, bbox(obj), objs,
                          dx=home["x"] - obj["location"]["x"],
                          dy=home["y"] - obj["location"]["y"],
                          skip_ids=[oid])
        manifest.pop(oid, None)
        restored.append(oid)
    _write_manifest(manifest)
    return restored


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_rooms(rs):
    for r in rs:
        b = r.get("boundingBox") or {}
        w = b.get("maxX", 0) - b.get("minX", 0)
        d = b.get("maxY", 0) - b.get("minY", 0)
        print(f"{r.get('roomName') or '(unnamed)':<24} type={r.get('roomType'):<12} "
              f"{fmt_inches(w)} x {fmt_inches(d)}   at ({r.get('x')}, {r.get('y')})")


def _print_objects(objs, name=None):
    needle = (name or "").lower()
    for o in objs:
        if needle and needle not in o["name"].lower() and needle not in o["layer"].lower():
            continue
        b = bbox(o)
        print(f"{o['name']:<20} layer={o['layer']:<22} "
              f"x={b['minX']:>9.2f}..{b['maxX']:<9.2f} y={b['minY']:>9.2f}..{b['maxY']:<9.2f}")


async def _main(args):
    async with client() as s:
        if args.cmd == "rooms":
            _print_rooms(await rooms(s))
        elif args.cmd == "objects":
            _print_objects(await objects(s, entire=args.entire), args.name)
        elif args.cmd == "selection":
            _print_objects(await selection(s))
        elif args.cmd == "audit":
            findings = await audit(s)
            if not findings:
                print("clean: no findings")
            for finding in findings:
                print(f"{finding['rule']:<22} {finding['detail']}")
        elif args.cmd == "metrics":
            for row in await room_metrics(s):
                label = row.get("name") or "(unnamed)"
                if "error" in row:
                    print(f"{label:<24} ERROR {row['error']}")
                    continue
                print(f"{label:<24} {row.get('dimensions')}  "
                      f"area={row.get('standard_area')}  "
                      f"interior={row.get('interior_area')}  "
                      f"perimeter={row.get('perimeter')}")
        elif args.cmd == "views":
            for v in await views(s):
                front = "*" if v.get("front") else " "
                print(f"{front} {v.get('viewTitle')}  "
                      f"({v.get('dimension')}, editable={v.get('editable')})")
        elif args.cmd == "docs":
            for hit in await docs(s, args.query):
                print(f"{hit['score']:>7.2f}  {hit['title']}  [{hit['topicPath']}]")
        elif args.cmd == "tools":
            data = await call(s, "chief_discover_tools")
            names = [t["name"] for t in (data.get("tools") or [])] if isinstance(data, dict) else []
            print("\n".join(names) or data)
        elif args.cmd == "image":
            print((await export_image(s, args.path)).get("message"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chief Architect MCP helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rooms", help="room list with clear dimensions")
    objs = sub.add_parser("objects", help="objects in the front view")
    objs.add_argument("--entire", action="store_true", help="whole document")
    objs.add_argument("--name", help="filter by object name or layer substring")
    sub.add_parser("selection", help="current selection")
    sub.add_parser("audit", help="read-only checks on the front view")
    sub.add_parser("metrics", help="room areas and perimeters, read from each dialog")
    sub.add_parser("views", help="open views")
    doc = sub.add_parser("docs", help="search Chief's help")
    doc.add_argument("query")
    sub.add_parser("tools", help="list MCP tools")
    img = sub.add_parser("image", help="export front view to PNG")
    img.add_argument("path")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
