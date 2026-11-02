"""The recipes must never leave a dialog open after they fail.

A stranded dialog holds the keyboard and refuses every later gesture with no
timeout, so a crash in the middle of an edit costs the rest of a session.
"""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class SpecDialogSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pressed = []

        async def fake_open(*_args, **_kwargs):
            return {"questionId": "q_9", "title": "Exterior Door Specification"}

        async def fake_press(_session, choice, label, question=None):
            self.pressed.append((choice, label, question))

        self.patches = [
            mock.patch.object(chief_mcp, "open_spec", fake_open),
            mock.patch.object(chief_mcp, "press", fake_press),
        ]
        for patch in self.patches:
            patch.start()
        self.addAsyncCleanup(self._stop)

    async def _stop(self):
        for patch in reversed(self.patches):
            patch.stop()

    async def test_cancels_the_dialog_when_the_body_raises(self):
        with self.assertRaises(ValueError):
            async with chief_mcp.spec_dialog(None, {}, []) as dialog:
                self.assertEqual(dialog["questionId"], "q_9")
                raise ValueError("boom")
        self.assertEqual(self.pressed, [("1", "Cancel", "q_9")])

    async def test_leaves_the_dialog_alone_when_the_body_succeeds(self):
        async with chief_mcp.spec_dialog(None, {}, []):
            pass
        self.assertEqual(self.pressed, [], "a finished edit closes its own dialog")

    async def test_cancel_failures_do_not_mask_the_original_error(self):
        async def exploding_press(*_args, **_kwargs):
            raise RuntimeError("dialog already gone")

        with mock.patch.object(chief_mcp, "press", exploding_press):
            with self.assertRaises(ValueError):
                async with chief_mcp.spec_dialog(None, {}, []):
                    raise ValueError("the real problem")


class CancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_tolerates_a_closed_dialog(self):
        async def exploding_press(*_args, **_kwargs):
            raise RuntimeError("no such dialog")

        with mock.patch.object(chief_mcp, "press", exploding_press):
            await chief_mcp._cancel(None, "q_1")  # must not raise


class RoomMetricsTests(unittest.IsolatedAsyncioTestCase):
    """room_metrics opens one dialog per room and must always cancel it."""

    ROOM = {"objectId": "r1", "roomName": "Kitchen", "roomType": "Kitchen",
            "boundingBox": {"minX": 0, "maxX": 10, "minY": 0, "maxY": 10}}

    @staticmethod
    def wire(pressed):
        async def fake_open(*_args, **_kwargs):
            return {"questionId": "q_7", "title": "Room Specification"}

        async def ok_fields(*_args, **_kwargs):
            return {"panel": {"nodes": [{"id": "roomID_RoomName", "value": "Kitchen"}]}}

        async def broken_fields(*_args, **_kwargs):
            raise RuntimeError("dialog fields timed out")

        async def fake_press(_session, choice, label, question=None):
            pressed.append((choice, label, question))

        return fake_open, ok_fields, broken_fields, fake_press

    async def test_the_dialog_is_cancelled_even_on_success(self):
        pressed = []
        fake_open, ok_fields, _, fake_press = self.wire(pressed)
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=[])), \
             mock.patch.object(chief_mcp, "open_spec", fake_open), \
             mock.patch.object(chief_mcp, "dialog_fields", ok_fields), \
             mock.patch.object(chief_mcp, "press", fake_press):
            rows = await chief_mcp.room_metrics(None, rooms_list=[self.ROOM])
        self.assertEqual(rows[0]["name"], "Kitchen")
        self.assertEqual(pressed, [("1", "Cancel", "q_7")])

    async def test_a_failed_read_still_cancels_the_dialog(self):
        pressed = []
        fake_open, _, broken_fields, fake_press = self.wire(pressed)
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=[])), \
             mock.patch.object(chief_mcp, "open_spec", fake_open), \
             mock.patch.object(chief_mcp, "dialog_fields", broken_fields), \
             mock.patch.object(chief_mcp, "press", fake_press):
            with self.assertRaises(RuntimeError):
                await chief_mcp.room_metrics(None, rooms_list=[self.ROOM])
        self.assertEqual(pressed, [("1", "Cancel", "q_7")])

    async def test_a_discovered_room_uses_selection_checked_opening(self):
        pressed = []
        fake_open, ok_fields, _, fake_press = self.wire(pressed)
        obj = {"objectId": "r1", "name": "Room"}
        with mock.patch.object(chief_mcp, "objects", mock.AsyncMock(return_value=[obj])), \
             mock.patch.object(chief_mcp, "open_spec", mock.AsyncMock()) as blind, \
             mock.patch.object(chief_mcp, "open_spec_anywhere", mock.AsyncMock(side_effect=fake_open)) as targeted, \
             mock.patch.object(chief_mcp, "dialog_fields", ok_fields), \
             mock.patch.object(chief_mcp, "press", fake_press):
            await chief_mcp.room_metrics(None, rooms_list=[self.ROOM])
        blind.assert_not_awaited()
        targeted.assert_awaited_once_with(None, obj, [obj], expect="Room")
        self.assertEqual(pressed, [("1", "Cancel", "q_7")])


class OpenSpecTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_wrong_dialog_is_cancelled_and_the_search_continues(self):
        dialogs = [{"kind": "dialog", "questionId": "q_1",
                    "title": "Dimension Line Specification"},
                   {"kind": "dialog", "questionId": "q_2",
                    "title": "Room Specification"}]

        async def fake_dblclick(*_args, **_kwargs):
            return dialogs.pop(0)

        async def flaky_press(*_args, **_kwargs):
            raise RuntimeError("dialog already gone")

        with mock.patch.object(chief_mcp, "dblclick", fake_dblclick), \
             mock.patch.object(chief_mcp, "press", flaky_press), \
             mock.patch.object(chief_mcp, "_dismiss_trial", mock.AsyncMock()):
            dialog = await chief_mcp.open_spec(
                None, {"minX": 0, "maxX": 10, "minY": 0, "maxY": 10}, [],
                expect="Room")
        self.assertEqual(dialog["questionId"], "q_2")


class MoveObjectTests(unittest.IsolatedAsyncioTestCase):
    async def run_move(self, value=0, written=None, confirmed=None, target=None):
        fields = {"panel": {"nodes": [
            {"id": "boxID_XPos", "value": value},
            {"id": "boxID_YPos", "value": '5"'},
        ]}}
        setter = mock.AsyncMock(return_value=written if written is not None else {"written": True})
        button = mock.AsyncMock(return_value=confirmed if confirmed is not None else {"success": True})
        with mock.patch.object(chief_mcp, "open_spec", mock.AsyncMock(return_value={
                 "questionId": "q_5", "title": "CAD Block Specification"})), \
             mock.patch.object(chief_mcp, "open_spec_anywhere", mock.AsyncMock(return_value={
                 "questionId": "q_5", "title": "CAD Block Specification"})) as targeted, \
             mock.patch.object(chief_mcp, "dialog_fields", mock.AsyncMock(return_value=fields)), \
             mock.patch.object(chief_mcp, "set_field", setter), \
             mock.patch.object(chief_mcp, "press", button):
            try:
                await chief_mcp.move_object(None, {"minX": 0, "maxX": 10,
                                                   "minY": 0, "maxY": 10},
                                            [target] if target else [], dx=5.0,
                                            skip_ids=[target["objectId"]] if target else [])
            finally:
                self.setter, self.button, self.targeted = setter, button, targeted

    async def test_known_objects_move_from_precise_coordinates_and_are_hit_tested(self):
        target = {"objectId": "block1", "name": "block",
                  "location": {"x": 178.627292, "y": 173.184253}}
        await self.run_move(value='178 5/8"', target=target)
        self.setter.assert_awaited_once_with(
            None, "boxID_XPos", value='183.627292"', question="q_5")
        self.targeted.assert_awaited_once_with(None, target, [target], expect=["block"])

    async def test_numeric_zero_is_a_valid_position(self):
        await self.run_move(value=0)
        self.setter.assert_awaited_once_with(
            None, "boxID_XPos", value='5.0"', question="q_5")
        self.button.assert_awaited_once_with(None, "0", "OK", "q_5")

    async def test_a_refused_position_write_cancels_instead_of_confirming(self):
        with self.assertRaisesRegex(RuntimeError, "field is disabled"):
            await self.run_move(written={"written": False, "refusal": "field is disabled"})
        self.button.assert_awaited_once_with(None, "1", "Cancel", "q_5")

    async def test_a_failed_confirmation_is_not_reported_as_a_move(self):
        with self.assertRaisesRegex(RuntimeError, "cannot confirm"):
            await self.run_move(confirmed={"success": False, "message": "cannot confirm"})
        self.assertEqual(self.button.await_args_list[-1], mock.call(None, "1", "Cancel", "q_5"))

    async def test_a_position_field_with_no_value_says_so_and_cancels(self):
        pressed = []

        async def fake_open(*_args, **_kwargs):
            return {"questionId": "q_5", "title": "CAD Block Specification"}

        async def fake_fields(*_args, **_kwargs):
            return {"panel": {"nodes": [
                {"id": "boxID_XPos", "value": None},
                {"id": "boxID_YPos", "value": '5"'},
            ]}}

        async def fake_press(_session, choice, label, question=None):
            pressed.append((choice, label, question))

        with mock.patch.object(chief_mcp, "open_spec", fake_open), \
             mock.patch.object(chief_mcp, "dialog_fields", fake_fields), \
             mock.patch.object(chief_mcp, "press", fake_press):
            with self.assertRaises(RuntimeError) as caught:
                await chief_mcp.move_object(None, {"minX": 0, "maxX": 10,
                                                   "minY": 0, "maxY": 10}, [], dx=5.0)
        self.assertIn("no value", str(caught.exception))
        self.assertEqual(pressed, [("1", "Cancel", "q_5")],
                         "the dialog must still be cancelled")


if __name__ == "__main__":
    unittest.main()
