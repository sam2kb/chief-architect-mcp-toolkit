"""Reading a tool reply that is not a list.

A failed tool answers with its error text. Returning that as if it were a list of
objects only blows up further down, and the message then blames a string for not
having `.get` rather than saying the app is not running.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class ExpectListTests(unittest.TestCase):
    def test_takes_the_list_out_of_a_good_reply(self):
        reply = {"success": True, "objects": [{"objectId": "a"}]}
        self.assertEqual(chief_mcp._expect_list(reply, "objects", "tool"), [{"objectId": "a"}])

    def test_a_bare_list_is_accepted(self):
        self.assertEqual(chief_mcp._expect_list([1, 2], "objects", "tool"), [1, 2])

    def test_a_failed_reply_raises_with_its_message(self):
        reply = {"success": False, "message": "no such pipe"}
        with self.assertRaises(RuntimeError) as caught:
            chief_mcp._expect_list(reply, "objects", "chief_discover_all_objects")
        self.assertIn("chief_discover_all_objects", str(caught.exception))
        self.assertIn("no such pipe", str(caught.exception))

    def test_error_text_is_not_passed_off_as_data(self):
        # this is what the app being closed actually looks like
        text = "chief_discover_all_objects failed: [Errno 2] No such file or directory"
        with self.assertRaises(RuntimeError) as caught:
            chief_mcp._expect_list(text, "objects", "chief_discover_all_objects")
        self.assertIn("No such file or directory", str(caught.exception))
        self.assertNotIn("unexpected", str(caught.exception))

    def test_a_reply_missing_the_key_is_still_an_error(self):
        with self.assertRaises(RuntimeError):
            chief_mcp._expect_list({"success": True}, "objects", "tool")


if __name__ == "__main__":
    unittest.main()
