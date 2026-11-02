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


if __name__ == "__main__":
    unittest.main()
