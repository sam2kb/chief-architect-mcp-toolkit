"""Optional adapter around the installed Chief MCP Python bridge.

Keeps the vendor's tools and response content, flags native tool failures as
MCP errors, and optionally records raw replies. Imports the vendor package only
when launched, so importing this module does not connect to or launch Chief.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time

from mcp.server import Server


def normalize_result(result):
    """Preserve the reply; correct only a missing top-level MCP error flag."""
    if result.is_error:
        return result
    payload = result.structured_content
    text = "\n".join(getattr(block, "text", "") for block in result.content).strip()
    if payload is None:
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
    failed = isinstance(payload, dict) and payload.get("success") is False
    if failed or text.lower().startswith("failed:"):
        return result.model_copy(update={"is_error": True})
    return result


def _trace(path, record):
    if path is None:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError) as exc:
        logging.getLogger(__name__).warning("Cannot write bridge trace: %s", exc)


def wrap_handler(handler, trace_path=None):
    """Wrap one upstream call, with no retries or changes to request arguments."""
    async def call_tool(ctx, params):
        started = time.monotonic()
        stamp = datetime.now(timezone.utc).isoformat()
        _trace(trace_path, {"event": "call", "time": stamp, "tool": params.name})
        try:
            raw = await handler(ctx, params)
            result = normalize_result(raw)
        except BaseException as exc:
            _trace(trace_path, {"event": "raise", "time": stamp, "tool": params.name,
                                "seconds": time.monotonic() - started,
                                "exception": type(exc).__name__})
            raise
        if trace_path is not None:
            _trace(trace_path, {"event": "reply", "time": stamp, "tool": params.name,
                                "seconds": time.monotonic() - started,
                                "upstream": raw.model_dump(mode="json", by_alias=True),
                                "returned_is_error": result.is_error})
        return result

    return call_tool


def install_adapter(upstream, trace_path=None):
    """Use the vendor registry and startup routine with our wrapped handler."""
    upstream.app = Server("ca-mcp-x18", on_list_tools=upstream.list_tools,
                          on_call_tool=wrap_handler(upstream.call_tool, trace_path))


def main():
    # PYTHONPATH is supplied by the existing launch configuration. Do not copy
    # or modify the installed proprietary source tree.
    from camcp.chief import server as upstream

    install_adapter(upstream, os.environ.get("CAMCP_BRIDGE_TRACE_FILE") or None)
    asyncio.run(upstream._main())


if __name__ == "__main__":
    main()
