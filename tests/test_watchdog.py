"""Tests for the per-call watchdog.

The failure this guards against is not a wrong answer but no answer: a dialog tool
with no tracked dialog, or an app wedged on an in-place edit, waits forever. The
watchdog turns that into an exception, after one attempt at recovery.
"""
import asyncio
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class SlowSession:
    """Stands in for an MCP session that never answers."""

    def __init__(self, delay=5.0, reply=None):
        self.delay = delay
        self.reply = reply
        self.calls = 0

    async def call_tool(self, tool, arguments):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.reply


class FastSession(SlowSession):
    def __init__(self, payload_text='{"success": true, "objects": []}'):
        super().__init__(delay=0)

        class Content:
            text = payload_text

        class Result:
            content = [Content()]

        self.reply = Result()


class WatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_call_that_overruns_is_aborted(self):
        session = SlowSession()
        with mock.patch.object(chief_mcp, "recover_after_timeout",
                               mock.AsyncMock(return_value=[])) as recovered:
            with self.assertRaises(chief_mcp.CallTimeout):
                await chief_mcp.call(session, "chief_discover_selection", timeout=0.05)
        recovered.assert_awaited_once()

    async def test_the_error_names_the_tool_and_the_deadline(self):
        with mock.patch.object(chief_mcp, "recover_after_timeout", mock.AsyncMock()):
            with self.assertRaises(chief_mcp.CallTimeout) as caught:
                await chief_mcp.call(SlowSession(), "chief_discover_rooms", timeout=0.05)
        self.assertEqual(caught.exception.tool, "chief_discover_rooms")
        self.assertIn("0.05", str(caught.exception))

    async def test_recovery_itself_failing_does_not_hide_the_timeout(self):
        with mock.patch.object(chief_mcp, "recover_after_timeout", mock.AsyncMock()):
            with self.assertRaises(chief_mcp.CallTimeout):
                await chief_mcp.call(SlowSession(), "chief_discover_views", timeout=0.05)

    async def test_a_recovery_call_cannot_trigger_recovery_again(self):
        session = SlowSession()
        with mock.patch.object(chief_mcp, "recover_after_timeout",
                               mock.AsyncMock()) as recovered:
            with self.assertRaises(chief_mcp.CallTimeout):
                await chief_mcp.call(session, "chief_force_close_dialog",
                                     timeout=0.05, recover=False)
        recovered.assert_not_awaited()

    async def test_a_zero_timeout_disables_the_watchdog(self):
        session = FastSession()
        payload = await chief_mcp.call(session, "chief_discover_all_objects", timeout=0)
        self.assertIsInstance(payload, dict)

    async def test_the_default_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"CAMCP_CALL_TIMEOUT": "0.05"}, clear=False):
            self.assertAlmostEqual(chief_mcp.call_timeout(), 0.05)
            with mock.patch.object(chief_mcp, "recover_after_timeout", mock.AsyncMock()):
                with self.assertRaises(chief_mcp.CallTimeout):
                    await chief_mcp.call(SlowSession(), "chief_discover_rooms")

    async def test_an_unparsable_setting_falls_back_to_the_default(self):
        with mock.patch.dict(os.environ, {"CAMCP_CALL_TIMEOUT": "soon"}, clear=False):
            self.assertEqual(chief_mcp.call_timeout(), chief_mcp.CALL_TIMEOUT)

    async def test_a_normal_call_still_returns(self):
        payload = await chief_mcp.call(FastSession(), "chief_discover_selection", timeout=1.0)
        self.assertEqual(payload["success"], True)


class FindTimeoutTests(unittest.TestCase):
    class Group(Exception):
        def __init__(self, exceptions):
            super().__init__("group")
            self.exceptions = exceptions

    def test_unwraps_a_nested_timeout(self):
        inner = self.Group([ValueError("x"), chief_mcp.CallTimeout("chief_discover_rooms", 2)])
        outer = self.Group([inner])
        found = chief_mcp.find_timeout(outer)
        self.assertIsInstance(found, chief_mcp.CallTimeout)
        self.assertEqual(found.tool, "chief_discover_rooms")

    def test_returns_none_for_other_errors(self):
        self.assertIsNone(chief_mcp.find_timeout(self.Group([ValueError("x")])))
        self.assertIsNone(chief_mcp.find_timeout(ValueError("x")))

    def test_finds_a_bare_timeout(self):
        timeout = chief_mcp.CallTimeout("chief_discover_views", 1)
        self.assertIs(chief_mcp.find_timeout(timeout), timeout)


class RecoveryStepsTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_survives_every_step_failing(self):
        class BrokenSession:
            async def call_tool(self, tool, arguments):
                raise RuntimeError("session is gone")

        with mock.patch.object(chief_mcp, "send_escape", return_value=False):
            steps = await chief_mcp.recover_after_timeout(BrokenSession(), budget=0.05)
        self.assertEqual(steps, [])

    async def test_recovery_reports_what_it_managed(self):
        class OkSession:
            async def call_tool(self, tool, arguments):
                class Content:
                    text = '{"success": true}'

                class Result:
                    content = [Content()]

                return Result()

        with mock.patch.object(chief_mcp, "send_escape", return_value=True):
            steps = await chief_mcp.recover_after_timeout(OkSession(), budget=1.0)
        self.assertEqual(steps, ["force_close", "escape"])


if __name__ == "__main__":
    unittest.main()
