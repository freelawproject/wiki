"""Tests for safe JSON serialization into <script> blocks."""

import json

from wiki.lib.safe_json import dump_json_for_script


class TestDumpJsonForScript:
    def test_escapes_script_breakout(self):
        payload = "</script><script>alert(1)</script>"
        out = dump_json_for_script({"x": payload})
        assert "</script>" not in out
        assert "<" not in out and ">" not in out

    def test_escapes_ampersand(self):
        out = dump_json_for_script({"x": "a & b"})
        assert "&" not in out

    def test_round_trips_to_original(self):
        payload = "</script>&<b>"
        out = dump_json_for_script({"x": payload})
        assert json.loads(out)["x"] == payload

    def test_plain_values_unchanged(self):
        out = dump_json_for_script([{"path": "a/b", "title": "Engineering"}])
        assert json.loads(out) == [{"path": "a/b", "title": "Engineering"}]
