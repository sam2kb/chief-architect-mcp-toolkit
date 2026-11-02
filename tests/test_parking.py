"""Parking is the delete workaround, so the manifest cannot lose its records.

Delete is refused over MCP; parking moves objects aside and the manifest is the
only record of where they came from. Save it before attempting each move, since
the app may commit a change before a call times out. One bad object must not
abandon the rest of the batch.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


def make_object(oid, x, y):
    return {"objectId": oid, "name": "CAD Block",
            "location": {"x": x, "y": y}, "size": {"width": 2.0, "depth": 2.0}}


class ManifestTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manifest_path = pathlib.Path(directory.name) / "parked.json"
        patch = mock.patch.object(chief_mcp, "PARK_MANIFEST", self.manifest_path)
        patch.start()
        self.addCleanup(patch.stop)

    def manifest(self):
        if not self.manifest_path.is_file():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))


class ParkingTests(ManifestTestCase):
    async def park(self, move):
        objs = [make_object("a", 0, 0), make_object("b", 10, 0)]
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=objs)), \
             mock.patch.object(chief_mcp, "move_object", move):
            return await chief_mcp.park_objects(None, ["a", "b"], apply=True)

    async def test_the_manifest_is_written_before_each_move_even_if_it_fails(self):
        async def move(_s, _b, _o, dx=0.0, dy=0.0, skip_ids=()):
            self.assertIn(list(skip_ids)[0], self.manifest())
            if list(skip_ids) == ["b"]:
                raise RuntimeError("that dialog has no X/Y position fields")

        report = await self.park(move)
        self.assertEqual(report["moved"], ["a"])
        self.assertEqual([f["objectId"] for f in report["failed"]], ["b"])
        self.assertEqual(self.manifest(), {"a": {"x": 0, "y": 0}, "b": {"x": 10, "y": 0}})

    async def test_a_crash_mid_batch_keeps_the_homes_of_moved_objects(self):
        async def move(_s, _b, _o, dx=0.0, dy=0.0, skip_ids=()):
            if list(skip_ids) == ["b"]:
                raise KeyboardInterrupt  # not an Exception: a hard abort

        with self.assertRaises(KeyboardInterrupt):
            await self.park(move)
        self.assertEqual(self.manifest(), {"a": {"x": 0, "y": 0}, "b": {"x": 10, "y": 0}})

    async def test_an_already_parked_object_keeps_its_home_and_is_not_moved_again(self):
        chief_mcp._write_manifest({"a": {"x": 20, "y": 30}})
        move = mock.AsyncMock()
        report = await self.park(move)
        self.assertEqual(report["moved"], ["b"])
        self.assertEqual(report["failed"][0]["objectId"], "a")
        self.assertEqual(self.manifest()["a"], {"x": 20, "y": 30})
        self.assertEqual(move.await_count, 1)

    async def test_duplicate_ids_are_moved_only_once(self):
        objs = [make_object("a", 0, 0)]
        move = mock.AsyncMock()
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=objs)), \
             mock.patch.object(chief_mcp, "move_object", move):
            report = await chief_mcp.park_objects(None, ["a", "a"], apply=True)
        self.assertEqual(report["moved"], ["a"])
        move.assert_awaited_once()

    async def test_an_unwritable_manifest_prevents_movement(self):
        move = mock.AsyncMock()
        with mock.patch.object(chief_mcp, "_write_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.park(move)
        move.assert_not_awaited()

    async def test_a_bad_manifest_is_preserved_and_prevents_movement(self):
        move = mock.AsyncMock()
        for text in ('{"a":', '[]', '{"a": {"x": 1}}',
                     '{"a": {"x": 1, "y": NaN}}'):
            with self.subTest(text=text):
                self.manifest_path.write_text(text, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    await self.park(move)
                self.assertEqual(self.manifest_path.read_text(encoding="utf-8"), text)
        move.assert_not_awaited()

    def test_a_failed_atomic_replace_preserves_the_previous_manifest(self):
        chief_mcp._write_manifest({"a": {"x": 1, "y": 2}})
        with mock.patch.object(chief_mcp.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                chief_mcp._write_manifest({"b": {"x": 3, "y": 4}})
        self.assertEqual(self.manifest(), {"a": {"x": 1, "y": 2}})
        self.assertEqual(list(self.manifest_path.parent.iterdir()), [self.manifest_path])

    async def test_planning_moves_nothing_and_writes_nothing(self):
        objs = [make_object("a", 0, 0)]
        touched = mock.AsyncMock(side_effect=AssertionError("touched"))
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=objs)), \
             mock.patch.object(chief_mcp, "move_object", touched):
            report = await chief_mcp.park_objects(None, ["a"], apply=False)
        self.assertFalse(report["applied"])
        self.assertEqual(self.manifest(), {})


class UnparkTests(ManifestTestCase):
    async def test_an_object_already_home_is_cleared_without_opening_a_dialog(self):
        self.manifest_path.write_text(
            json.dumps({"a": {"x": 0, "y": 0}}), encoding="utf-8")
        objs = [make_object("a", 0, 0)]
        move = mock.AsyncMock()
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=objs)), \
             mock.patch.object(chief_mcp, "move_object", move):
            report = await chief_mcp.unpark_objects(None)
        move.assert_not_awaited()
        self.assertEqual(report, {"restored": ["a"], "failed": []})
        self.assertEqual(self.manifest(), {})

    async def test_a_restore_failure_keeps_that_entry_for_the_next_run(self):
        self.manifest_path.write_text(
            json.dumps({"a": {"x": 0, "y": 0}, "b": {"x": 5000, "y": 5000}}),
            encoding="utf-8")
        objs = [make_object("a", 0, 40), make_object("b", 5010, 5040)]

        async def move(_s, _b, _o, dx=0.0, dy=0.0, skip_ids=()):
            if list(skip_ids) == ["b"]:
                raise RuntimeError("dialog refused")

        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=objs)), \
             mock.patch.object(chief_mcp, "move_object", move):
            report = await chief_mcp.unpark_objects(None)
        self.assertEqual(report["restored"], ["a"])
        self.assertEqual([f["objectId"] for f in report["failed"]], ["b"])
        self.assertEqual(self.manifest(), {"b": {"x": 5000, "y": 5000}})


if __name__ == "__main__":
    unittest.main()
