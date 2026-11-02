"""Adapter tests against MCP result models, with no Chief connection."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mcp.types as types

import chief_bridge as bridge
import chief_mcp as ca


def reply(text, **kwargs):
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], **kwargs)


class ErrorFlagTests(unittest.TestCase):
    def test_native_failure_changes_only_the_error_flag(self):
        raw = reply('{"success":false,"message":"requires project management"}',
                    meta={"source": "chief"})
        result = bridge.normalize_result(raw)
        self.assertTrue(result.is_error)
        expected = raw.model_dump()
        expected["is_error"] = True
        self.assertEqual(result.model_dump(), expected)
        self.assertFalse(raw.is_error)

    def test_static_failure_is_marked_as_an_error(self):
        self.assertTrue(bridge.normalize_result(reply("failed: no help directory")).is_error)

    def test_structured_native_failure_is_also_recognized(self):
        raw = reply("Operation failed", structured_content={"success": False})
        self.assertTrue(bridge.normalize_result(raw).is_error)

    def test_existing_errors_and_successful_replies_are_untouched(self):
        for raw in (reply("connection failed", is_error=True), reply('[{"success":false}]'),
                    reply('{"success":true,"kind":"dialog"}'), reply("already_running"),
                    reply('{"success":true,"message":"failed: appears in a text field"}')):
            with self.subTest(raw=raw):
                self.assertIs(bridge.normalize_result(raw), raw)

    def test_unreadable_content_is_not_relabelled_as_a_tool_failure(self):
        raw = reply('{"success":true,"panel":{"hasUnreadableContent":true}}')
        self.assertIs(bridge.normalize_result(raw), raw)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_original_arguments_once_and_records_unmodified_reply(self):
        raw = reply('{"success":false,"message":"native refusal"}')
        upstream = mock.AsyncMock(return_value=raw)
        params = types.CallToolRequestParams(name="chief_test", arguments={"panel": "Text"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            result = await bridge.wrap_handler(upstream, path)("context", params)
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        upstream.assert_awaited_once_with("context", params)
        self.assertTrue(result.is_error)
        self.assertEqual(entries[1]["upstream"], raw.model_dump(mode="json", by_alias=True))
        self.assertFalse(entries[1]["upstream"]["isError"])
        self.assertTrue(entries[1]["returned_is_error"])

    async def test_protocol_exceptions_are_preserved_without_retry(self):
        error = ValueError("unknown tool")
        upstream = mock.AsyncMock(side_effect=error)
        params = types.CallToolRequestParams(name="missing")
        with self.assertRaises(ValueError) as caught:
            await bridge.wrap_handler(upstream)(None, params)
        self.assertIs(caught.exception, error)
        upstream.assert_awaited_once()

    async def test_trace_io_failure_does_not_change_the_tool_result(self):
        raw = reply('{"success":true}')
        upstream = mock.AsyncMock(return_value=raw)
        with mock.patch.object(Path, "open", side_effect=OSError("disk full")), \
             self.assertLogs("chief_bridge", level="WARNING"):
            result = await bridge.wrap_handler(upstream, "trace.jsonl")(
                None, types.CallToolRequestParams(name="chief_test"))
        self.assertIs(result, raw)


class LaunchTests(unittest.TestCase):
    def test_local_adapter_is_opt_in_and_preserves_vendor_source_environment(self):
        with mock.patch.dict(os.environ, {"CAMCP_PYTHON": "python", "CAMCP_CHIEF_SRC": "/chief/src",
                                          "CAMCP_BRIDGE": "1"}, clear=True):
            params = ca.server_params()
        self.assertEqual(params.args, [str(ca.REPO_ROOT / "chief_bridge.py")])
        self.assertEqual(params.env["PYTHONPATH"], "/chief/src")

    def test_adapter_refuses_to_silently_replace_a_custom_launcher(self):
        with mock.patch.dict(os.environ, {"CAMCP_BRIDGE": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "native"):
                ca._server_args(["custom-server.py"])

    def test_default_launcher_is_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ca._server_args(["-m", "camcp.chief.server"]), ["-m", "camcp.chief.server"])


if __name__ == "__main__":
    unittest.main()
