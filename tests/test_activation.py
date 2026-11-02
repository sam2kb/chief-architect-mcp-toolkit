"""Tests for bringing Chief to the front before sending input.

The Windows calls are faked, so these run anywhere and check the decisions --
which window is chosen, whether activation is attempted, what is reported.
"""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class FakeUser32:
    """Just enough of user32 for the activation helpers."""

    def __init__(self, windows, foreground=0, restore_moves_foreground=True):
        self.windows = dict(windows)
        self.current = foreground
        self.restore_moves_foreground = restore_moves_foreground
        self.calls = []

    def EnumWindows(self, callback, param):
        for hwnd in list(self.windows):
            if not callback(hwnd, param):
                break
        return True

    def IsWindowVisible(self, hwnd):
        return True

    def GetWindowTextW(self, hwnd, buf, size):
        buf.value = self.windows.get(hwnd, "")
        return len(buf.value)

    def GetForegroundWindow(self):
        return self.current

    def keybd_event(self, *args):
        self.calls.append(("keybd_event", args[0]))

    def ShowWindow(self, hwnd, how):
        self.calls.append(("ShowWindow", hwnd, how))

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        if self.restore_moves_foreground:
            self.current = hwnd


class WindowTitleTests(unittest.TestCase):
    def test_reads_title(self):
        lib = FakeUser32({7: "Chief Architect Premier X18"})
        self.assertEqual(chief_mcp.window_title(7, lib), "Chief Architect Premier X18")

    def test_missing_window_has_no_title(self):
        lib = FakeUser32({})
        self.assertEqual(chief_mcp.window_title(7, lib), "")
        self.assertEqual(chief_mcp.window_title(0, lib), "")


class FindWindowTests(unittest.TestCase):
    def test_picks_the_chief_window(self):
        lib = FakeUser32({1: "Visual Studio Code", 2: "Chief Architect Premier X18"})
        self.assertEqual(chief_mcp.find_window(lib=lib), 2)

    def test_returns_none_when_chief_is_not_open(self):
        lib = FakeUser32({1: "Visual Studio Code"})
        self.assertIsNone(chief_mcp.find_window(lib=lib))

    def test_without_a_windows_api_there_is_nothing_to_find(self):
        with mock.patch.object(chief_mcp, "_user32", return_value=None):
            self.assertIsNone(chief_mcp.find_window())
            self.assertEqual(chief_mcp.foreground_title(), "")


class SlowUser32(FakeUser32):
    """Switches the foreground only after a few reads, like a real window switch."""

    def __init__(self, windows, foreground=0, reads_before_switch=3):
        super().__init__(windows, foreground)
        self.reads_before_switch = reads_before_switch
        self.pending = None
        self.reads = 0

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        self.pending = hwnd

    def GetForegroundWindow(self):
        if self.pending is not None:
            self.reads += 1
            if self.reads >= self.reads_before_switch:
                self.current, self.pending = self.pending, None
        return self.current


class EnsureActiveTests(unittest.TestCase):
    def test_no_op_when_already_in_front(self):
        lib = FakeUser32({2: "Chief Architect Premier X18"}, foreground=2)
        state = chief_mcp.ensure_active(lib=lib)
        self.assertTrue(state["active"])
        self.assertFalse(state["changed"])
        self.assertEqual(lib.calls, [], "should not touch a window that already has focus")

    def test_waits_for_a_slow_window_switch(self):
        lib = SlowUser32({1: "Visual Studio Code", 2: "Chief Architect Premier X18"},
                         foreground=1, reads_before_switch=3)
        state = chief_mcp.ensure_active(lib=lib, delay=0)
        self.assertTrue(state["active"], "should retry until the switch lands")
        self.assertIn("Chief Architect", state["foreground"])

    def test_brings_chief_forward_from_another_app(self):
        lib = FakeUser32({1: "Visual Studio Code", 2: "Chief Architect Premier X18"}, foreground=1)
        state = chief_mcp.ensure_active(lib=lib)
        self.assertTrue(state["active"])
        self.assertTrue(state["changed"])
        self.assertIn("Chief Architect", state["foreground"])
        self.assertIn(("keybd_event", chief_mcp.VK_MENU), lib.calls,
                      "the ALT tap is what unlocks SetForegroundWindow")

    def test_reports_failure_when_windows_refuses(self):
        lib = FakeUser32({1: "Visual Studio Code", 2: "Chief Architect Premier X18"},
                         foreground=1, restore_moves_foreground=False)
        state = chief_mcp.ensure_active(lib=lib, attempts=1, delay=0)
        self.assertFalse(state["active"])
        self.assertTrue(state["changed"])
        self.assertEqual(state["foreground"], "Visual Studio Code")

    def test_reports_a_missing_window_instead_of_raising(self):
        lib = FakeUser32({1: "Visual Studio Code"}, foreground=1)
        state = chief_mcp.ensure_active(lib=lib)
        self.assertFalse(state["active"])
        self.assertFalse(state["changed"])
        self.assertEqual(state["reason"], "no Chief window found")


if __name__ == "__main__":
    unittest.main()
