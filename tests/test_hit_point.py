"""Tests for the bounding-box scan that finds a clickable point on a covered object."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


class ScanPointTests(unittest.TestCase):
    def setUp(self):
        self.bounds = {"minX": 0.0, "maxX": 10.0, "minY": 0.0, "maxY": 10.0}

    def test_starts_at_the_centre(self):
        points = chief_mcp.scan_points(self.bounds, steps=5, inset=0.0)
        self.assertAlmostEqual(points[0][0], 5.0)
        self.assertAlmostEqual(points[0][1], 5.0)

    def test_stays_inside_the_bounds(self):
        for inset in (0.0, 1.0):
            for x, y in chief_mcp.scan_points(self.bounds, steps=7, inset=inset):
                self.assertGreaterEqual(x, 0.0)
                self.assertLessEqual(x, 10.0)
                self.assertGreaterEqual(y, 0.0)
                self.assertLessEqual(y, 10.0)

    def test_returns_the_requested_number_of_points(self):
        self.assertEqual(len(chief_mcp.scan_points(self.bounds, steps=7)), 49)
        self.assertEqual(len(chief_mcp.scan_points(self.bounds, steps=3)), 9)

    def test_inset_smaller_than_the_box_shrinks_the_scan(self):
        points = chief_mcp.scan_points(self.bounds, steps=3, inset=1.0)
        self.assertEqual(min(x for x, _ in points), 1.0)
        self.assertEqual(max(x for x, _ in points), 9.0)

    def test_tiny_box_falls_back_to_its_edges(self):
        tiny = {"minX": 0.0, "maxX": 1.0, "minY": 0.0, "maxY": 1.0}
        points = chief_mcp.scan_points(tiny, steps=3, inset=1.0)
        self.assertEqual(len(points), 9)
        self.assertAlmostEqual(points[0][0], 0.5)
        self.assertAlmostEqual(points[0][1], 0.5)

    def test_ordering_is_centre_out(self):
        points = chief_mcp.scan_points(self.bounds, steps=5)
        distances = [((x - 5) ** 2 + (y - 5) ** 2) ** 0.5 for x, y in points]
        self.assertEqual(distances, sorted(distances))

    def test_a_single_step_still_returns_points(self):
        points = chief_mcp.scan_points(self.bounds, steps=1, inset=0.0)
        self.assertTrue(points)
        for x, y in points:
            self.assertTrue(chief_mcp.contains(self.bounds, x, y))


if __name__ == "__main__":
    unittest.main()
