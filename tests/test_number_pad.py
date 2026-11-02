"""Tests for keeping candidate points away from editable numbers.

A double-click on a dimension's number opens an in-place editor, which then holds
the keyboard until something cancels it. The number sits outside the dimension
line's own bounding box, so avoiding the box is not enough.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


def obj(name, x, y, w=1.0, d=1.0, object_id="o", layer="Dimensions"):
    return {"objectId": object_id, "name": name, "layer": layer,
            "location": {"x": x, "y": y}, "size": {"width": w, "depth": d}}


def clearance(point, cx, cy):
    """Chebyshev distance from a point to a coordinate, in inches."""
    return max(abs(point[0] - cx), abs(point[1] - cy))


class CarriesNumberTests(unittest.TestCase):
    def test_dimension_and_text_carry_numbers(self):
        self.assertTrue(chief_mcp.carries_number(obj("Dimension Line", 0, 0)))
        self.assertTrue(chief_mcp.carries_number(obj("Text", 0, 0)))
        self.assertTrue(chief_mcp.carries_number(obj("Rich Text", 0, 0)))

    def test_other_objects_do_not(self):
        for name in ("Wall", "Hinged Door", "Room", "Marker", "CAD Line"):
            self.assertFalse(chief_mcp.carries_number(obj(name, 0, 0)), name)


class FreePointPaddingTests(unittest.TestCase):
    bounds = {"minX": 0.0, "maxX": 40.0, "minY": 0.0, "maxY": 40.0}

    def setUp(self):
        self.number = obj("Dimension Line", 20.5, 20.0, 1.0, 1.0, object_id="dim")

    def test_padding_moves_the_point_clear_of_the_number(self):
        plain = chief_mcp.free_point(self.bounds, [self.number], steps=21)
        padded = chief_mcp.free_point(self.bounds, [self.number], steps=21, number_pad=12.0)
        self.assertGreater(clearance(padded, 20.5, 20.0),
                           clearance(plain, 20.5, 20.0),
                           "the padded point should sit further from the number")

    def test_padding_leaves_other_objects_alone(self):
        wall = obj("Wall", 20.5, 20.0, 1.0, 1.0, object_id="w", layer="Walls")
        plain = chief_mcp.free_point(self.bounds, [wall], steps=11)
        padded = chief_mcp.free_point(self.bounds, [wall], steps=11, number_pad=12.0)
        self.assertEqual(plain, padded, "a wall's box should not be inflated")

    def test_padding_can_give_up_and_still_return_a_point(self):
        # a number covering the whole search area: better a usable point than none
        huge = obj("Dimension Line", 20.0, 20.0, 200.0, 200.0, object_id="dim")
        x, y = chief_mcp.free_point(self.bounds, [huge], steps=11, number_pad=12.0)
        self.assertTrue(self.bounds["minX"] <= x <= self.bounds["maxX"])
        self.assertTrue(self.bounds["minY"] <= y <= self.bounds["maxY"])


if __name__ == "__main__":
    unittest.main()
