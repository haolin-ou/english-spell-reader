"""Publication-wrapper regression test; original parser tests are unchanged."""

import json
import subprocess
import sys
from pathlib import Path


def test_documented_cli_returns_a_json_speech_plan():
    result = subprocess.run(
        [sys.executable, "-m", "app", "hello 123!"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["source_text"] == "hello 123!"
    assert any(
        unit["action"] == "read_number" and unit["speak_text"] == "一二三"
        for unit in plan["units"]
    )
    assert any(
        unit["action"] == "read_symbol" and unit["speak_text"] == "感叹号"
        for unit in plan["units"]
    )
