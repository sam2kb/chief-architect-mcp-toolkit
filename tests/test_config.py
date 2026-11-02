"""Tests for launch configuration.

`server_params` had a docstring and a README both promising that a blank `.env`
falls back to VS Code's `mcp.json`, while the code returned `None` -- so the
documented setup path crashed. These pin the behaviour down.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import chief_mcp  # noqa: E402


def write_config(directory, servers):
    path = pathlib.Path(directory) / "mcp.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return path


class ServerParamsTests(unittest.TestCase):
    def test_explicit_environment_wins(self):
        env = {"CAMCP_PYTHON": "/venv/bin/python", "CAMCP_CHIEF_SRC": "/chief/src"}
        with mock.patch.dict(os.environ, env, clear=True):
            params = chief_mcp.server_params()
        self.assertEqual(params.command, "/venv/bin/python")
        self.assertEqual(params.env["PYTHONPATH"], "/chief/src")

    def test_falls_back_to_the_mcp_json_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(tmp, {
                chief_mcp.SERVER_NAME: {
                    "command": "/usr/bin/python3",
                    "args": ["-m", "camcp.chief.server"],
                    "env": {"PYTHONPATH": "/chief/src"},
                }
            })
            with mock.patch.dict(os.environ, {"CAMCP_MCP_JSON": str(path)}, clear=True):
                params = chief_mcp.server_params()
        self.assertEqual(params.command, "/usr/bin/python3")
        self.assertEqual(params.args, ["-m", "camcp.chief.server"])
        self.assertEqual(params.env["PYTHONPATH"], "/chief/src")

    def test_missing_configuration_says_what_to_set(self):
        with mock.patch.dict(os.environ, {"CAMCP_MCP_JSON": "/nope/mcp.json"}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                chief_mcp.server_params()
        self.assertIn("CAMCP_PYTHON", str(caught.exception))

    def test_entry_without_a_command_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(tmp, {chief_mcp.SERVER_NAME: {"args": ["-m"]}})
            with mock.patch.dict(os.environ, {"CAMCP_MCP_JSON": str(path)}, clear=True):
                with self.assertRaises(RuntimeError) as caught:
                    chief_mcp.server_params()
        self.assertIn("with a command", str(caught.exception))

    def test_unknown_server_name_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(tmp, {"some-other-server": {"command": "py"}})
            with mock.patch.dict(os.environ, {"CAMCP_MCP_JSON": str(path)}, clear=True):
                with self.assertRaises(RuntimeError) as caught:
                    chief_mcp.server_params()
        self.assertIn(chief_mcp.SERVER_NAME, str(caught.exception))


class ConfigPathTests(unittest.TestCase):
    def test_override_is_honoured(self):
        with mock.patch.dict(os.environ, {"CAMCP_MCP_JSON": "/tmp/x/mcp.json"}, clear=True):
            self.assertEqual(str(chief_mcp.mcp_config_path()).replace("\\", "/"), "/tmp/x/mcp.json")

    def test_default_follows_appdata(self):
        with mock.patch.dict(os.environ, {"APPDATA": "/tmp/appdata"}, clear=True):
            path = str(chief_mcp.mcp_config_path()).replace("\\", "/")
        self.assertEqual(path, "/tmp/appdata/Code/User/mcp.json")


if __name__ == "__main__":
    unittest.main()
