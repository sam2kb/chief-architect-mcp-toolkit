"""Selection verification, dialog option discovery, and export shortcuts."""
import argparse
import contextlib
import io
from pathlib import Path
import unittest
from unittest import mock

import chief_mcp as ca


OBJECT = {"objectId": "one", "name": "CAD Block", "layer": "CAD", "floor": 1}


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_then_verifies_ids_instead_of_trusting_the_count(self):
        others = [OBJECT, {**OBJECT, "objectId": "two", "name": "Wall"}]
        with mock.patch.object(ca, "objects", mock.AsyncMock(return_value=others)), \
             mock.patch.object(ca, "select", mock.AsyncMock(return_value=999)) as select, \
             mock.patch.object(ca, "selection", mock.AsyncMock(return_value=[OBJECT])):
            result = await ca.select_matching(None, name="block", layer="CAD", floor=1)
        select.assert_awaited_once_with(None, ["one"])
        self.assertEqual(result["selected"], [OBJECT])

    async def test_no_matches_leaves_the_existing_selection_untouched(self):
        with mock.patch.object(ca, "objects", mock.AsyncMock(return_value=[OBJECT])), \
             mock.patch.object(ca, "select", mock.AsyncMock()) as select:
            result = await ca.select_matching(None, name="door")
        select.assert_not_awaited()
        self.assertTrue(result["unchanged"])

    async def test_wrong_selection_is_an_error_even_when_the_count_matches(self):
        with mock.patch.object(ca, "objects", mock.AsyncMock(return_value=[OBJECT])), \
             mock.patch.object(ca, "select", mock.AsyncMock(return_value=1)), \
             mock.patch.object(ca, "selection", mock.AsyncMock(return_value=[{"objectId": "other"}])):
            with self.assertRaisesRegex(RuntimeError, "1 missing, 1 unexpected"):
                await ca.select_matching(None, layer="CAD")

    async def test_a_refused_selection_is_reported_clearly(self):
        with mock.patch.object(ca, "call", mock.AsyncMock(return_value={"success": False, "message": "blocked"})):
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                await ca.select(None, ["one"])


class FieldTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dialog = {"questionId": "q1", "title": "CAD Block Specification", "panels": [
            {"name": "General", "active": True}, {"name": "Style", "active": False}]}
        self.inline = {"optionId": 0, "label": "Solid", "enabled": True}
        self.overflow = {"optionId": 11, "label": "Dashed", "enabled": False}
        self.general = {"panel": {"title": "General", "nodes": [
            {"kind": "field", "id": "height", "label": "Height", "value": '12"', "support": "writable"},
            {"kind": "field", "id": "style", "value": 0, "support": "writable",
             "currentSelectionLabel": "Solid", "constraints": {"options": [self.inline]}},
        ]}}
        self.style = {"panel": {"title": "Style", "nodes": [
            {"kind": "field", "id": "line", "label": "Line Style", "value": 11,
             "support": "writable", "constraints": {"optionCount": 12}},
        ]}, "overflow": {"line": {"options": [self.overflow]}}}

    async def inspect(self, replies, **kwargs):
        with mock.patch.object(ca, "selection", mock.AsyncMock(return_value=[OBJECT])), \
             mock.patch.object(ca, "objects", mock.AsyncMock(return_value=[OBJECT])), \
             mock.patch.object(ca, "open_spec_anywhere", mock.AsyncMock(return_value=self.dialog)), \
             mock.patch.object(ca, "dialog_fields", mock.AsyncMock(side_effect=replies)) as fields, \
             mock.patch.object(ca, "_cancel", mock.AsyncMock()) as cancel:
            try:
                return await ca.describe_fields(None, **kwargs)
            finally:
                self.field_calls = fields.await_args_list
                cancel.assert_awaited_once_with(None, "q1")

    async def test_selected_object_all_panels_keep_panel_context_and_full_options(self):
        result = await self.inspect([self.general, self.style], all_panels=True, include_options=True)
        self.assertEqual(self.field_calls, [mock.call(None, panel=None), mock.call(None, panel="Style")])
        self.assertEqual(result["fields"][1]["options"], [self.inline])
        self.assertEqual(result["fields"][2]["options"], [self.overflow])
        self.assertEqual(result["fields"][2]["panel"], "Style")
        self.assertEqual(result["fields"][2]["optionCount"], 12)
        self.assertEqual(result["fields"][1]["currentSelectionLabel"], "Solid")

    async def test_filter_matches_labels_ignoring_case(self):
        result = await self.inspect([self.general], object_id="one", contains="HEIGHT")
        self.assertEqual([f["id"] for f in result["fields"]], ["height"])

    async def test_cancel_runs_when_a_later_panel_fails(self):
        with self.assertRaisesRegex(RuntimeError, "panel failed"):
            await self.inspect([self.general, RuntimeError("panel failed")], all_panels=True)

    async def test_ambiguous_or_empty_selection_opens_no_dialog(self):
        for chosen in ([], [OBJECT, {**OBJECT, "objectId": "two"}]):
            with self.subTest(chosen=chosen), \
                 mock.patch.object(ca, "selection", mock.AsyncMock(return_value=chosen)), \
                 mock.patch.object(ca, "open_spec_anywhere", mock.AsyncMock()) as opened:
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    await ca.describe_fields(None)
                opened.assert_not_awaited()


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_supported_types_use_absolute_paths_and_export_deadline(self):
        for name, wire in (("image", "Image"), ("pdf", "PDF"), ("dwg2d", "DWG 2D")):
            with self.subTest(name=name), \
                 mock.patch.object(ca, "call", mock.AsyncMock(return_value={"success": True})) as called:
                await ca.export_view(None, "example.out", export_type=name)
                called.assert_awaited_once_with(None, "chief_export_data", exportType=wire,
                                               exportPath=str(Path("example.out").resolve()),
                                               timeout=ca.EXPORT_TIMEOUT)

    async def test_tool_failures_are_not_reported_as_successful_exports(self):
        for reply in ({"success": False, "message": "not writable"}, "failed: no view"):
            with self.subTest(reply=reply), \
                 mock.patch.object(ca, "call", mock.AsyncMock(return_value=reply)):
                with self.assertRaisesRegex(RuntimeError, "not writable|no view"):
                    await ca.export_view(None, "example.pdf", export_type="pdf")


class CliTests(unittest.TestCase):
    def test_invalid_field_and_selection_arguments_fail_before_connecting(self):
        for argv in (["fields"], ["fields", "one", "--selected"],
                     ["fields", "one", "--panel", "General", "--all-panels"],
                     ["select"], ["select", "--clear", "--name", "door"]):
            with self.subTest(argv=argv), mock.patch.object(ca, "client") as client, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    ca.main(argv)
                self.assertEqual(caught.exception.code, 2)
                client.assert_not_called()


class CliDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_fields_passes_the_requested_options(self):
        @contextlib.asynccontextmanager
        async def client():
            yield "session"

        args = argparse.Namespace(cmd="fields", object_id=None, panel=None, expect=None,
                                  all_panels=True, options=True, contains="line")
        result = {"title": "Specification", "panel": None, "panels": ["General"],
                  "fields": [{"id": "line", "label": "Line", "value": 0, "support": "writable",
                              "panel": "General", "options": [{"optionId": 0, "label": "Solid"}]}]}
        output = io.StringIO()
        with mock.patch.object(ca, "client", client), \
             mock.patch.object(ca, "describe_fields", mock.AsyncMock(return_value=result)) as fields, \
             contextlib.redirect_stdout(output):
            await ca._main(args)
        fields.assert_awaited_once_with("session", None, panel=None, expect=None,
                                       all_panels=True, include_options=True, contains="line")
        self.assertIn("[General]", output.getvalue())
        self.assertIn("0: Solid", output.getvalue())


if __name__ == "__main__":
    unittest.main()
