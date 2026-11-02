"""Tests for the read-only analysis helpers (no Chief connection needed)."""

import json
import os
import tempfile
import unittest

import chief_mcp


def make_object(name, x, y, width, depth, layer="Walls,  Normal", oid=None, locked=False):
    return {
        "name": name,
        "layer": layer,
        "layerLocked": locked,
        "objectId": oid or f"{name}-{x}-{y}",
        "location": {"x": x, "y": y, "z": 0.0},
        "size": {"width": width, "depth": depth, "height": 0.0},
    }


def make_room(name, with_bounds=True, oid="room-1"):
    room = {"roomName": name, "roomType": "Office", "objectId": oid}
    if with_bounds:
        room["boundingBox"] = {"minX": 0.0, "minY": 0.0, "maxX": 10.0, "maxY": 10.0}
    return room


class AuditTests(unittest.TestCase):
    def rules(self, objects, rooms):
        return {f["rule"] for f in chief_mcp.audit_findings(objects, rooms)}

    def test_clean_model_reports_nothing(self):
        found = chief_mcp.audit_findings([make_object("Wall", 0, 0, 10, 1)], [make_room("Office")])
        self.assertEqual(found, [])

    def test_unnamed_room(self):
        self.assertIn("unnamed-room", self.rules([], [make_room("")]))

    def test_room_without_bounds(self):
        self.assertIn("room-without-bounds", self.rules([], [make_room("Office", with_bounds=False)]))

    def test_zero_size_object(self):
        self.assertIn("zero-size-object", self.rules([make_object("Wall", 0, 0, 0, 10)], []))

    def test_text_on_foreign_layer(self):
        objs = [make_object("Text", 0, 0, 1, 1, layer="CAD,  Default")]
        self.assertIn("text-off-text-layer", self.rules(objs, []))

    def test_text_on_text_layer_is_clean(self):
        objs = [make_object("Text", 0, 0, 1, 1, layer="Text")]
        self.assertNotIn("text-off-text-layer", self.rules(objs, []))

    def test_locked_layer(self):
        objs = [make_object("Wall", 0, 0, 1, 1, locked=True)]
        self.assertIn("locked-layer-object", self.rules(objs, []))

    def test_exact_duplicate(self):
        objs = [make_object("Wall", 5, 5, 1, 1, oid="a"), make_object("Wall", 5, 5, 1, 1, oid="b")]
        self.assertIn("exact-duplicate", self.rules(objs, []))

    def test_near_duplicate_is_not_flagged(self):
        objs = [make_object("Wall", 5, 5, 1, 1, oid="a"),
                make_object("Wall", 5.001, 5, 1, 1, oid="b")]
        self.assertNotIn("exact-duplicate", self.rules(objs, []))

    def test_findings_are_plain_data(self):
        found = chief_mcp.audit_findings([], [make_room("")])
        self.assertEqual(set(found[0]), {"rule", "detail", "objects"})


class CandidatePointTests(unittest.TestCase):
    bounds = {"minX": 0.0, "minY": 0.0, "maxX": 100.0, "maxY": 40.0}

    def test_points_stay_inside(self):
        for x, y in chief_mcp._candidate_points(self.bounds, []):
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x, 100.0)
            self.assertGreaterEqual(y, 0.0)
            self.assertLessEqual(y, 40.0)

    def test_points_are_unique(self):
        points = chief_mcp._candidate_points(self.bounds, [])
        self.assertEqual(len(points), len(set(points)))

    def test_attempt_limit_is_honoured(self):
        self.assertEqual(len(chief_mcp._candidate_points(self.bounds, [], attempts=2)), 2)

    def test_first_point_avoids_a_covering_obstacle(self):
        blocker = make_object("Dimension Line", 50, 20, 60, 30, layer="CAD,  Default")
        x, y = chief_mcp._candidate_points(self.bounds, [blocker])[0]
        self.assertFalse(chief_mcp.contains(chief_mcp.bbox(blocker), x, y))


class MatchObjectsTests(unittest.TestCase):
    objects = [
        make_object("Wall", 0, 0, 10, 1, layer="Walls,  Normal", oid="w1"),
        make_object("Hinged Door", 1, 1, 3, 1, layer="Doors", oid="d1"),
        make_object("Text", 2, 2, 1, 1, layer="Text", oid="t1"),
    ]

    def ids(self, **kwargs):
        return [o["objectId"] for o in chief_mcp.match_objects(self.objects, **kwargs)]

    def test_name_substring_ignores_case(self):
        self.assertEqual(self.ids(name="door"), ["d1"])

    def test_layer_substring(self):
        self.assertEqual(self.ids(layer="walls"), ["w1"])

    def test_exact_requires_whole_string(self):
        self.assertEqual(self.ids(name="wal", exact=True), [])
        self.assertEqual(self.ids(name="Wall", exact=True), ["w1"])

    def test_no_filter_returns_everything(self):
        self.assertEqual(len(self.ids()), 3)

    def test_filters_combine(self):
        self.assertEqual(self.ids(name="Wall", layer="doors"), [])

    def test_floor_filter_excludes_unset(self):
        upper = make_object("Light", 0, 0, 1, 1, oid="l2")
        upper["floor"] = 2
        pool = self.objects + [upper]
        self.assertEqual([o["objectId"] for o in chief_mcp.match_objects(pool, name="light", floor=2)], ["l2"])


class SnapshotTests(unittest.TestCase):
    @staticmethod
    def snap(objects):
        return {"scope": "front-view", "front_view": "Plan", "objects": objects}

    def test_fingerprint_ignores_dict_order(self):
        a = make_object("Wall", 1, 2, 3, 4, oid="w1")
        b = dict(reversed(list(make_object("Wall", 1, 2, 3, 4, oid="w1").items())))
        self.assertEqual(chief_mcp.fingerprint([a]), chief_mcp.fingerprint([b]))

    def test_fingerprint_changes_when_an_object_moves(self):
        before = [make_object("Wall", 1, 2, 3, 4, oid="w1")]
        after = [make_object("Wall", 1, 2.5, 3, 4, oid="w1")]
        self.assertNotEqual(chief_mcp.fingerprint(before), chief_mcp.fingerprint(after))

    def test_diff_detects_move(self):
        before = self.snap([make_object("Door", 10, 10, 3, 7, oid="d1")])
        after = self.snap([make_object("Door", 10.5, 10, 3, 7, oid="d1")])
        result = chief_mcp.diff_snapshots(before, after)
        self.assertEqual(result["counts"]["moved"], 1)
        self.assertAlmostEqual(result["moved"][0]["dx"], 0.5)

    def test_diff_detects_resize(self):
        before = self.snap([make_object("Door", 10, 10, 3, 7, oid="d1")])
        after = self.snap([make_object("Door", 10, 10, 3, 6.5, oid="d1")])
        result = chief_mcp.diff_snapshots(before, after)
        self.assertEqual(result["counts"]["resized"], 1)
        self.assertAlmostEqual(result["resized"][0]["dd"], -0.5)

    def test_diff_detects_add_and_remove(self):
        before = self.snap([make_object("Door", 0, 0, 3, 7, oid="d1")])
        after = self.snap([make_object("Window", 0, 0, 3, 4, oid="w9")])
        result = chief_mcp.diff_snapshots(before, after)
        self.assertEqual(result["counts"]["added"], 1)
        self.assertEqual(result["counts"]["removed"], 1)

    def test_diff_ignores_sub_tolerance_noise(self):
        before = self.snap([make_object("Door", 10, 10, 3, 7, oid="d1")])
        after = self.snap([make_object("Door", 10.001, 10, 3, 7, oid="d1")])
        self.assertEqual(chief_mcp.diff_snapshots(before, after)["counts"]["moved"], 0)


class PayloadMergeTests(unittest.TestCase):
    def test_report_is_merged_into_the_live_payload(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump({"overflow": {"widget": [1, 2]}}, fh)
            path = fh.name
        live = {"panel": {"nodes": [{"id": "roomID_RoomName", "value": "Office"}]},
                "reportFilename": path}

        class Block:
            text = json.dumps(live)

        class Result:
            content = [Block()]

        try:
            merged = chief_mcp._payload(Result())
            self.assertEqual(merged["panel"]["nodes"][0]["id"], "roomID_RoomName")
            self.assertEqual(merged["overflow"], {"widget": [1, 2]})
        finally:
            os.unlink(path)

    def test_missing_report_leaves_payload_alone(self):
        live = {"count": 1, "reportFilename": "no-such-file.json"}

        class Block:
            text = json.dumps(live)

        class Result:
            content = [Block()]

        self.assertEqual(chief_mcp._payload(Result()), live)


if __name__ == "__main__":
    unittest.main()
