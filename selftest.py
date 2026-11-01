"""Smoke test for the chief_mcp helpers: connect, read, and pick a hit point.

Run it after touching chief_mcp.py:

    python selftest.py

It only reads -- no dialog is opened and nothing in the drawing is modified.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chief_mcp  # noqa: E402


async def main() -> int:
    async with chief_mcp.client() as s:
        found = await chief_mcp.views(s)
        print(f"views      : {len(found)}")
        for v in found:
            mark = "front" if v.get("front") else "     "
            print(f"  {mark}  {v.get('viewTitle')}")

        objs = await chief_mcp.objects(s)
        print(f"objects    : {len(objs)} in the front view")

        rs = await chief_mcp.rooms(s)
        print(f"rooms      : {len(rs)}")
        for r in rs[:5]:
            b = r.get("boundingBox") or {}
            if not b:
                continue
            name = r.get("roomName") or "(unnamed)"
            w = chief_mcp.fmt_inches(b["maxX"] - b["minX"])
            d = chief_mcp.fmt_inches(b["maxY"] - b["minY"])
            print(f"  {name:<22} {w} x {d}")

        print(f"selection  : {len(await chief_mcp.selection(s))} object(s)")

        target = next((r for r in rs if r.get("boundingBox")), None)
        if target:
            x, y = chief_mcp.free_point(
                target["boundingBox"], objs, skip_ids=[target.get("objectId")]
            )
            print(f"free_point : ({x:.2f}, {y:.2f})  (no dialog opened)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
