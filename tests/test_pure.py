"""Offline tests for the pure helpers. No Chief connection required."""

import os
import tempfile
import unittest

import chief_mcp


class FormatInchesTests(unittest.TestCase):
    def test_whole_feet(self):
        self.assertEqual(chief_mcp.fmt_inches(120), "10'-0\"")
        self.assertEqual(chief_mcp.fmt_inches(12), "1'-0\"")

    def test_reduces_fractions(self):
        self.assertEqual(chief_mcp.fmt_inches(81.375), "6'-9 3/8\"")
        self.assertEqual(chief_mcp.fmt_inches(0.5), "0'-0 1/2\"")

    def test_negative(self):
        self.assertEqual(chief_mcp.fmt_inches(-1.625), "-0'-1 5/8\"")

    def test_rounds_up_into_next_foot(self):
        self.assertEqual(chief_mcp.fmt_inches(11.99), "1'-0\"")


class ParseInchesTests(unittest.TestCase):
    def test_mixed_fraction(self):
        self.assertAlmostEqual(chief_mcp.parse_inches('7 1/2"'), 7.5)

    def test_negative_fraction(self):
        self.assertAlmostEqual(chief_mcp.parse_inches('-1 5/8"'), -1.625)

    def test_feet_and_inches(self):
        self.assertAlmostEqual(chief_mcp.parse_inches("2'-6\""), 30.0)

    def test_plain_number(self):
        self.assertAlmostEqual(chief_mcp.parse_inches("120"), 120.0)

    def test_bare_fraction(self):
        self.assertAlmostEqual(chief_mcp.parse_inches('3/8"'), 0.375)

    def test_round_trip_with_fmt(self):
        for value in (0.375, 7.5, 81.375, 120.0, -1.625):
            self.assertAlmostEqual(chief_mcp.parse_inches(chief_mcp.fmt_inches(value)), value)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            chief_mcp.parse_inches("  ")


class BboxTests(unittest.TestCase):
    obj = {
        "location": {"x": 10.0, "y": 20.0, "z": 0.0},
        "size": {"width": 4.0, "depth": 6.0, "height": 0.0},
    }

    def test_bounds_from_centre(self):
        self.assertEqual(
            chief_mcp.bbox(self.obj),
            {"minX": 8.0, "maxX": 12.0, "minY": 17.0, "maxY": 23.0},
        )

    def test_left_edge(self):
        self.assertEqual(chief_mcp.left(self.obj), 8.0)

    def test_contains(self):
        b = chief_mcp.bbox(self.obj)
        self.assertTrue(chief_mcp.contains(b, 10.0, 20.0))
        self.assertFalse(chief_mcp.contains(b, 0.0, 0.0))


class FreePointTests(unittest.TestCase):
    bounds = {"minX": 0.0, "minY": 0.0, "maxX": 100.0, "maxY": 100.0}

    @staticmethod
    def _box(name, minx, miny, maxx, maxy, layer="Walls,  Normal"):
        return {
            "name": name,
            "layer": layer,
            "location": {"x": (minx + maxx) / 2, "y": (miny + maxy) / 2, "z": 0.0},
            "size": {"width": maxx - minx, "depth": maxy - miny, "height": 0.0},
        }

    def test_avoids_obstacle_covering_the_centre(self):
        blocker = self._box("Dimension Line", 20, 20, 80, 80)
        x, y = chief_mcp.free_point(self.bounds, [blocker])
        self.assertFalse(chief_mcp.contains(chief_mcp.bbox(blocker), x, y))

    def test_room_layer_is_not_an_obstacle(self):
        room = self._box("Exterior room", 0, 0, 100, 100, layer="Rooms")
        x, y = chief_mcp.free_point(self.bounds, [room])
        self.assertEqual((round(x, 3), round(y, 3)), (50.0, 50.0))

    def test_named_room_is_not_an_obstacle(self):
        room = self._box("Room", 0, 0, 100, 100, layer="Something")
        x, y = chief_mcp.free_point(self.bounds, [room])
        self.assertEqual((round(x, 3), round(y, 3)), (50.0, 50.0))

    def test_falls_back_to_centre_when_nothing_is_clear(self):
        blocker = self._box("Wall", -10, -10, 110, 110)
        x, y = chief_mcp.free_point(self.bounds, [blocker])
        self.assertEqual((round(x, 1), round(y, 1)), (50.0, 50.0))

    def test_skips_given_object_id(self):
        blocker = self._box("Text", 0, 0, 100, 100)
        blocker["objectId"] = "abc"
        x, y = chief_mcp.free_point(self.bounds, [blocker], skip_ids=["abc"])
        self.assertEqual((round(x, 3), round(y, 3)), (50.0, 50.0))


class LoadEnvTests(unittest.TestCase):
    def test_never_overrides_existing_values(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("# comment line\n")
            fh.write("CAMCP_TEST_VALUE=from-file\n")
            fh.write('CAMCP_TEST_QUOTED="quoted value"\n')
            path = fh.name
        os.environ["CAMCP_TEST_VALUE"] = "from-shell"
        try:
            chief_mcp.load_env(chief_mcp.Path(path))
            self.assertEqual(os.environ["CAMCP_TEST_VALUE"], "from-shell")
            self.assertEqual(os.environ["CAMCP_TEST_QUOTED"], "quoted value")
        finally:
            os.environ.pop("CAMCP_TEST_VALUE", None)
            os.environ.pop("CAMCP_TEST_QUOTED", None)
            os.unlink(path)

    def test_missing_file_is_ignored(self):
        chief_mcp.load_env(chief_mcp.Path("does-not-exist.env"))


if __name__ == "__main__":
    unittest.main()
