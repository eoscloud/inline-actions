"""Integration tests for inline-actions.

Each test case is a subdirectory containing:
  - workflow-sources/   : input workflows
  - expected/workflows/ : expected inlined output
  - (optional) actions/ : local composite actions
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_inline_actions(test_case_dir: Path, tmp_path: Path) -> None:
    """Run inline-actions on a test case and compare output to expected."""
    source_dir = test_case_dir / "workflow-sources"
    expected_dir = test_case_dir / "expected" / "workflows"
    output_dir = tmp_path / "workflows"

    assert source_dir.is_dir(), f"Missing workflow-sources/ in {test_case_dir.name}"
    assert expected_dir.is_dir(), f"Missing expected/workflows/ in {test_case_dir.name}"

    # Run inline-actions from the test case directory so ./actions/ paths resolve
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inline_actions",
            "--source-dir",
            str(source_dir),
            "--output-dir",
            str(output_dir),
        ],
        cwd=str(test_case_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"inline-actions failed for {test_case_dir.name}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # Compare each expected output file
    expected_files = sorted(expected_dir.glob("*.yaml")) + sorted(
        expected_dir.glob("*.yml")
    )
    assert expected_files, f"No expected output files in {expected_dir}"

    for expected_file in expected_files:
        actual_file = output_dir / expected_file.name
        assert actual_file.exists(), (
            f"Expected output file {expected_file.name} was not generated"
        )

        expected_content = expected_file.read_text()
        actual_content = actual_file.read_text()
        assert actual_content == expected_content, (
            f"Output mismatch for {expected_file.name} in {test_case_dir.name}:\n"
            f"--- expected ---\n{expected_content}\n"
            f"--- actual ---\n{actual_content}"
        )
