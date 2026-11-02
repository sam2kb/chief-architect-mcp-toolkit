"""Tests for the per-object retry in apply_property.

Most failures in a bulk write are a stale modal or a caret rather than the object
itself, and the watchdog has already cleared those by the time the failure is
reported. So one retry, after settling, is worth more than it costs -- but it must
not turn a real refusal into a silent success.
"""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402

TARGET = {"objectId": "abc12345", "name": "Room",
          "location": {"x": 0.0, "y": 0.0}, "size": {"width": 10.0, "depth": 10.0}}


def wire(open_behaviour, written=True):
    """Patch everything apply_property touches, and record the calls."""
    log = {"opens": 0, "settles": 0, "writes": 0}

    async def fake_open(_session, obj, _objs, expect=None):
        log["opens"] += 1
        return open_behaviour(log, obj)

    async def fake_fields(*_args, **_kwargs):
        return {"panel": {"nodes": [], "title": "Structure"}}

    async def fake_set(*_args, **_kwargs):
        log["writes"] += 1
        return {"written": written, "after": '144"', "refusal": "field is disabled"}

    async def fake_press(*_args, **_kwargs):
        return {"success": True}

    async def fake_settle(*_args, **_kwargs):
        log["settles"] += 1
        return {}

    async def fake_objects(*_args, **_kwargs):
        return [TARGET]

    patches = {
        "open_spec_anywhere": fake_open,
        "dialog_fields": fake_fields,
        "set_field": fake_set,
        "press": fake_press,
        "settle": fake_settle,
        "objects": fake_objects,
        "send_escape": lambda *a, **k: True,
    }
    return log, patches


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_apply(self, behaviour, **kwargs):
        log, patches = wire(behaviour, **kwargs)
        with mock.patch.multiple(chief_mcp, **patches):
            report = await chief_mcp.apply_property(
                None, [TARGET], "roomID_CeilingElevation", value='144"',
                panel="Structure", apply=True, on_error="continue")
        return log, report

    async def test_a_failed_object_is_retried_once(self):
        def behaviour(log, _obj):
            if log["opens"] == 1:
                raise RuntimeError("stale modal")
            return {"questionId": "q_1", "title": "Room Specification"}

        log, report = await self.run_apply(behaviour)
        result = report["results"][0]
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("retried"))
        self.assertEqual(result.get("after"), '144"')
        self.assertEqual(log["opens"], 2)

    async def test_a_second_failure_is_reported_not_hidden(self):
        def behaviour(_log, _obj):
            raise RuntimeError("no matching dialog opened inside those bounds")

        log, report = await self.run_apply(behaviour)
        result = report["results"][0]
        self.assertIn("no matching dialog", result["error"])
        self.assertEqual(log["opens"], 2, "one attempt plus one retry")

    async def test_a_refused_write_is_not_retried_into_success(self):
        def behaviour(_log, _obj):
            return {"questionId": "q_2", "title": "Room Specification"}

        log, report = await self.run_apply(behaviour, written=False)
        result = report["results"][0]
        self.assertIn("field is disabled", result["error"])
        self.assertNotIn("ok", result)

    async def test_planning_mode_touches_nothing(self):
        def behaviour(_log, _obj):
            return {"questionId": "q_3", "title": "Room Specification"}

        log, patches = wire(behaviour)
        with mock.patch.multiple(chief_mcp, **patches):
            report = await chief_mcp.apply_property(None, [TARGET], "someID", value="1")
        self.assertTrue(report["results"][0]["planned"])
        self.assertEqual(log["opens"], 0)
        self.assertEqual(log["writes"], 0)

    async def test_the_run_ends_with_a_settle(self):
        def behaviour(_log, _obj):
            return {"questionId": "q_4", "title": "Room Specification"}

        log, _report = await self.run_apply(behaviour)
        self.assertGreaterEqual(log["settles"], 1, "a run should not leave the app mid-dialog")


if __name__ == "__main__":
    unittest.main()
