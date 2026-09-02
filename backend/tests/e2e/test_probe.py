"""The synthetic game, played against the real server the E2E suite starts.

This is the probe an operator's cron will run, unchanged, so a step it
cannot get through here is a step it will page on in production.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from app.probe import STEPS, run_probe

BASE_URL = "http://localhost:8000"

pytestmark = pytest.mark.asyncio


async def test_a_stranger_can_open_a_room_be_joined_and_draw(tmp_path):
    state = tmp_path / "sessions.json"
    result = await run_probe(BASE_URL, name_prefix="e2e", state_path=state)
    assert result.ok, (result.failed_step, result.error)
    assert list(result.steps) == list(STEPS)
    assert all(seconds >= 0 for seconds in result.steps.values())
    assert result.duration_seconds < 20
    assert result.provisioned is True

    # The run a minute later reuses both sessions rather than minting two
    # more, which is what keeps a one-minute cadence under the provisioning
    # allowance.
    saved = state.read_text(encoding="utf-8")
    again = await run_probe(BASE_URL, name_prefix="e2e", state_path=state)
    assert again.ok, (again.failed_step, again.error)
    assert again.provisioned is False
    assert state.read_text(encoding="utf-8") == saved


def test_the_command_line_reports_json_and_exits_zero(tmp_path):
    textfile = tmp_path / "sketchy.prom"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.probe",
            "--base-url",
            BASE_URL,
            "--json",
            "--textfile",
            str(textfile),
            "--state",
            str(tmp_path / "cli-sessions.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert set(payload["steps"]) == set(STEPS)
    text = textfile.read_text(encoding="utf-8")
    assert "sketchy_probe_success 1\n" in text
    assert 'sketchy_probe_step_seconds{step="draw"}' in text
