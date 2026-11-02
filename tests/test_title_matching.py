"""Tests for matching a dialog title against an object name.

A room that cannot be reached used to report whatever sat under the click, so a
Dimension Line Specification could be read as if it were the room. These pin the
check that stops that.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class TitleMatchesTests(unittest.TestCase):
    def test_a_word_matches_its_title(self):
        self.assertTrue(chief_mcp.title_matches("Room", "Room Specification"))
        self.assertTrue(chief_mcp.title_matches("door", "Exterior Door Specification"))

    def test_a_word_elsewhere_in_the_title_does_not_count(self):
        self.assertFalse(chief_mcp.title_matches("Room", "Dimension Line Specification"))

    def test_no_expectation_accepts_anything(self):
        for expect in (None, "", []):
            self.assertTrue(chief_mcp.title_matches(expect, "Anything At All"))

    def test_several_words_match_any_of_them(self):
        self.assertTrue(chief_mcp.title_matches(["hinged", "door"], "Interior Door Specification"))
        self.assertFalse(chief_mcp.title_matches(["hinged", "door"], "Room Specification"))


class TitleTokensTests(unittest.TestCase):
    def test_keeps_the_distinctive_word(self):
        self.assertEqual(chief_mcp.title_tokens("Hinged Door"), ["hinged", "door"])
        self.assertEqual(chief_mcp.title_tokens("Room"), ["room"])

    def test_drops_a_numeric_suffix(self):
        self.assertEqual(chief_mcp.title_tokens("block_4"), ["block"])

    def test_drops_short_words(self):
        self.assertEqual(chief_mcp.title_tokens("CAD Line"), ["line"])
        self.assertIsNone(chief_mcp.title_tokens("A B C"))

    def test_an_empty_name_has_no_tokens(self):
        self.assertIsNone(chief_mcp.title_tokens(""))
        self.assertIsNone(chief_mcp.title_tokens("   "))


if __name__ == "__main__":
    unittest.main()
