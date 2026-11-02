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
import hashlib
import json
import math
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
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


async def clear_dialogs(session):
    """Cancel any agent-tracked dialog left open; returns its title or None.

    A stuck modal refuses every canvas gesture, and the refusal looks like a
    click that hit nothing. Call this before a run and after a crash.
    """
    info = await call(session, "chief_discover_open_dialogs")
    tracked = info.get("trackedQuestion") or {}
    if not tracked.get("active"):
        return None
    title = tracked.get("title")
    try:
        await press(session, "1", "Cancel", tracked.get("questionId"))
    except Exception:  # noqa: BLE001
        pass
    return title


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
# bulk selection and property application
# --------------------------------------------------------------------------
def match_objects(objects_list, name=None, layer=None, floor=None, exact=False):
    """Filter objects by name, layer, or floor.

    Matching is a case-insensitive substring unless ``exact`` is set, so
    ``name="wall"`` finds "Wall" while ``name="exterior"`` will not, because
    wall type lives in the specification rather than the object name.
    """

    def hit(value, needle):
        if needle is None:
            return True
        value = value or ""
        return value == needle if exact else needle.lower() in value.lower()

    return [
        o for o in objects_list
        if hit(o.get("name"), name)
        and hit(o.get("layer"), layer)
        and (floor is None or o.get("floor") == floor)
    ]


async def describe_fields(session, object_id, objects_list=None, panel=None):
    """Open one object's dialog, list its writable fields, then cancel."""
    objs = objects_list if objects_list is not None else await objects(session)
    target = next((o for o in objs if o["objectId"] == object_id), None)
    if target is None:
        raise ValueError("that object is not in the front view")

    dialog = await open_spec(session, bbox(target), objs, skip_ids=[object_id])
    question = dialog.get("questionId")
    try:
        found = await dialog_fields(session, panel=panel)
        panel_data = found.get("panel") or {}
        fields = [
            {
                "id": node.get("id"),
                "label": node.get("label"),
                "value": node.get("value"),
                "support": node.get("support"),
            }
            for node in (panel_data.get("nodes") or [])
            if node.get("kind") == "field"
        ]
        return {"title": dialog.get("title"), "panel": panel_data.get("title"), "fields": fields}
    finally:
        await _cancel(session, question)


async def apply_property(session, targets, field_id, value=None, option=None, panel=None,
                         apply=False, limit=None, on_error="stop", expect=None,
                         snapshot=None):
    """Write one dialog field on every target object.

    A multi-object dialog edits only the object you double-clicked, so the only
    way to change many objects is one dialog each. Returns a per-object report;
    nothing is written until ``apply`` is true.

    Pass ``expect`` with a word from the dialog title ("Door", "Room") so a
    click that lands on a neighbouring object is rejected instead of edited.
    Pass ``snapshot`` to abort the whole run when the document has moved on.
    """
    if snapshot is not None:
        check = await preflight(session, snapshot, [o["objectId"] for o in targets])
        if not check["ok"]:
            return {"applied": False, "aborted": True, "problems": check["problems"],
                    "count": len(targets), "results": []}

    objects_list = await objects(session)
    chosen = list(targets)
    if limit:
        chosen = chosen[:limit]

    results = []
    for obj in chosen:
        entry = {"objectId": obj["objectId"], "name": obj.get("name")}
        if not apply:
            results.append({**entry, "planned": True})
            continue

        try:
            dialog = await open_spec(session, bbox(obj), objects_list,
                                     skip_ids=[obj["objectId"]], expect=expect)
        except RuntimeError as exc:
            results.append({**entry, "error": str(exc)})
            if on_error == "stop":
                break
            continue

        question = dialog.get("questionId")
        try:
            if panel:
                await dialog_fields(session, panel=panel)
            written = await set_field(session, field_id, value=value,
                                      option=option, question=question)
            if not written.get("written"):
                raise RuntimeError(written.get("refusal") or "field was refused")
            await press(session, "0", "OK", question)
            results.append({**entry, "ok": True, "after": written.get("after")})
        except Exception as exc:  # noqa: BLE001
            await _cancel(session, question)
            results.append({**entry, "error": str(exc)})
            if on_error == "stop":
                break

    return {"applied": apply, "count": len(chosen), "results": results}


async def _cancel(session, question):
    """Cancel a dialog, tolerating one that already closed."""
    try:
        await press(session, "1", "Cancel", question)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# snapshots and preflight
# --------------------------------------------------------------------------
SNAPSHOT_DIR = Path(os.environ.get(
    "CAMCP_SNAPSHOT_DIR", str(Path.home() / ".chief_mcp")
))


def _canonical(obj):
    """The parts of an object that matter when comparing snapshots."""
    return {
        "id": obj.get("objectId"),
        "name": obj.get("name"),
        "layer": obj.get("layer"),
        "x": round(obj["location"]["x"], 3),
        "y": round(obj["location"]["y"], 3),
        "w": round(obj["size"]["width"], 3),
        "d": round(obj["size"]["depth"], 3),
    }


def fingerprint(objects_list) -> str:
    """Short hash of object positions and sizes, for spotting drift."""
    payload = json.dumps([_canonical(o) for o in objects_list], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


async def snapshot(session, entire=False, path=None):
    """Capture objects, rooms and the front view into a JSON file.

    ``scope`` records which listing produced it: the front view and the whole
    document return different objects, and the entire-document listing omits
    ``layoutPage``, so snapshots from the two modes are not interchangeable.
    """
    object_list = await objects(session, entire=entire)
    room_list = await rooms(session)
    front = next((v for v in await views(session) if v.get("front")), {})

    data = {
        "captured": datetime.now().isoformat(timespec="seconds"),
        "scope": "entire-document" if entire else "front-view",
        "front_view": front.get("viewTitle"),
        "fingerprint": fingerprint(object_list),
        "objects": object_list,
        "rooms": room_list,
    }

    target = Path(path) if path else SNAPSHOT_DIR / f"snap-{data['captured'].replace(':', '')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"path": str(target), "count": len(object_list),
            "scope": data["scope"], "fingerprint": data["fingerprint"]}


def diff_snapshots(before, after, tolerance=0.01):
    """Compare two snapshots. Returns added, removed, moved and resized."""
    old = {o["objectId"]: o for o in before.get("objects", [])}
    new = {o["objectId"]: o for o in after.get("objects", [])}

    moved, resized = [], []
    for oid in old.keys() & new.keys():
        was, now = _canonical(old[oid]), _canonical(new[oid])
        if abs(was["x"] - now["x"]) > tolerance or abs(was["y"] - now["y"]) > tolerance:
            moved.append({"objectId": oid, "name": now["name"],
                          "dx": round(now["x"] - was["x"], 3),
                          "dy": round(now["y"] - was["y"], 3)})
        if abs(was["w"] - now["w"]) > tolerance or abs(was["d"] - now["d"]) > tolerance:
            resized.append({"objectId": oid, "name": now["name"],
                            "dw": round(now["w"] - was["w"], 3),
                            "dd": round(now["d"] - was["d"], 3)})

    return {
        "added": [new[i] for i in new.keys() - old.keys()],
        "removed": [old[i] for i in old.keys() - new.keys()],
        "moved": moved,
        "resized": resized,
        "counts": {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
                   "moved": len(moved), "resized": len(resized)},
    }


async def preflight(session, snap, object_ids=None, tolerance=0.01):
    """Refuse to continue if the application no longer matches a snapshot.

    Checks that no modal is open, that the front view is the one captured, and
    that each named object still exists on the same layer in the same place.
    """
    problems = []

    info = await call(session, "chief_discover_open_dialogs")
    tracked = info.get("trackedQuestion") or {}
    if tracked.get("active"):
        problems.append(f"modal dialog is open: {tracked.get('title')!r}")

    front = next((v for v in await views(session) if v.get("front")), {})
    expected = snap.get("front_view")
    if expected and front.get("viewTitle") != expected:
        problems.append(
            f"front view changed: snapshot has {expected!r}, now {front.get('viewTitle')!r}"
        )

    if object_ids:
        captured = {o["objectId"]: o for o in snap.get("objects", [])}
        live = {o["objectId"]: o for o in await objects(session)}
        for oid in object_ids:
            was, now = captured.get(oid), live.get(oid)
            if was is None:
                problems.append(f"{oid}: not in the snapshot")
            elif now is None:
                problems.append(f"{oid}: no longer in the front view")
            else:
                a, b = _canonical(was), _canonical(now)
                if a["layer"] != b["layer"]:
                    problems.append(f"{oid}: layer changed since the snapshot")
                elif abs(a["x"] - b["x"]) > tolerance or abs(a["y"] - b["y"]) > tolerance:
                    problems.append(f"{oid}: moved since the snapshot")

    return {"ok": not problems, "problems": problems}


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
        elif args.cmd == "find":
            hits = match_objects(await objects(s), name=args.name, layer=args.layer,
                                 floor=args.floor, exact=args.exact)
            for obj in hits:
                print(f"{obj['objectId']}  {obj['name']:<20} layer={obj['layer']}")
            print(f"-- {len(hits)} match(es)")
        elif args.cmd == "fields":
            info = await describe_fields(s, args.object_id, panel=args.panel)
            print(f"{info['title']} / {info['panel']}")
            for field in info["fields"]:
                print(f"  {str(field['id']):<34} {str(field['value'])[:38]:<40} {field['support']}")
        elif args.cmd == "apply":
            targets = match_objects(await objects(s), name=args.name, layer=args.layer,
                                    floor=args.floor, exact=args.exact)
            if not targets:
                print("nothing matched")
                return
            report = await apply_property(s, targets, args.field, value=args.value,
                                          option=args.option, panel=args.panel,
                                          apply=args.apply, limit=args.limit,
                                          expect=args.expect, snapshot=args.snapshot_data)
            done = sum(1 for r in report["results"] if r.get("ok") or r.get("planned"))
            state = "applied" if report["applied"] else "planned"
            print(f"{state}: {done}/{report['count']}")
            for result in report["results"]:
                if result.get("error"):
                    print(f"  ERROR {result.get('name')}: {result['error']}")
        elif args.cmd == "clear":
            title = await clear_dialogs(s)
            print(f"cancelled {title!r}" if title else "no dialog open")
        elif args.cmd == "snapshot":
            info = await snapshot(s, entire=args.entire, path=args.out)
            print(f"saved {info['count']} object(s) from the {info['scope']} "
                  f"to {info['path']}")
            print(f"fingerprint {info['fingerprint']}")
        elif args.cmd == "diff":
            before = json.loads(Path(args.before).read_text(encoding="utf-8"))
            after = await snapshot(s, entire=(before.get("scope") == "entire-document"),
                                   path=args.out)
            after_data = json.loads(Path(after["path"]).read_text(encoding="utf-8"))
            result = diff_snapshots(before, after_data)
            print(json.dumps(result["counts"]))
            for item in result["moved"]:
                print(f"  moved   {str(item['name']):<18} {item['objectId'][:8]}  "
                      f"dx={item['dx']} dy={item['dy']}")
            for item in result["resized"]:
                print(f"  resized {str(item['name']):<18} {item['objectId'][:8]}  "
                      f"dw={item['dw']} dd={item['dd']}")
            for item in result["removed"]:
                print(f"  removed {str(item['name']):<18} {str(item.get('objectId'))[:8]}")
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
    find = sub.add_parser("find", help="list objects matching name, layer, or floor")
    find.add_argument("--name")
    find.add_argument("--layer")
    find.add_argument("--floor", type=int)
    find.add_argument("--exact", action="store_true", help="whole-string match")
    inspect = sub.add_parser("fields", help="list an object's dialog fields, read-only")
    inspect.add_argument("object_id")
    inspect.add_argument("--panel")
    bulk = sub.add_parser("apply", help="write one dialog field on many matching objects")
    bulk.add_argument("--name")
    bulk.add_argument("--layer")
    bulk.add_argument("--floor", type=int)
    bulk.add_argument("--exact", action="store_true")
    bulk.add_argument("--field", required=True, help="field id, as shown by `fields`")
    bulk.add_argument("--value")
    bulk.add_argument("--option", type=int, help="option id for a combo field")
    bulk.add_argument("--panel")
    bulk.add_argument("--limit", type=int)
    bulk.add_argument("--expect", help="require this word in the dialog title, e.g. Door")
    bulk.add_argument("--snapshot", help="abort unless the document still matches this snapshot")
    sub.add_parser("clear", help="cancel a stuck dialog")
    snap = sub.add_parser("snapshot", help="save objects, rooms and front view to JSON")
    snap.add_argument("--entire", action="store_true", help="whole document, not just the front view")
    snap.add_argument("--out")
    difference = sub.add_parser("diff", help="compare a saved snapshot with the current state")
    difference.add_argument("before")
    difference.add_argument("--out")
    bulk.add_argument("--apply", action="store_true", help="write for real; default is a plan only")
    sub.add_parser("views", help="open views")
    doc = sub.add_parser("docs", help="search Chief's help")
    doc.add_argument("query")
    sub.add_parser("tools", help="list MCP tools")
    img = sub.add_parser("image", help="export front view to PNG")
    img.add_argument("path")
    args = parser.parse_args(argv)
    snapshot_file = getattr(args, "snapshot", None)
    args.snapshot_data = (
        json.loads(Path(snapshot_file).read_text(encoding="utf-8"))
        if snapshot_file else None
    )
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
