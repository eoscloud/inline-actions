"""Integration test runner for inline-actions.

Discovers test cases as subdirectories of integration-tests/.
Each test case directory must contain:
  - workflow-sources/   : input workflow files
  - expected/workflows/ : expected output after inlining
  - (optional) actions/ : local composite actions used by the workflows
"""

from __future__ import annotations

from pathlib import Path


INTEGRATION_TESTS_DIR = Path(__file__).parent


def discover_test_cases() -> list[Path]:
    """Find all test case directories (those with a workflow-sources/ subdir)."""
    cases = []
    for child in sorted(INTEGRATION_TESTS_DIR.iterdir()):
        if child.is_dir() and (child / "workflow-sources").is_dir():
            cases.append(child)
    return cases


def pytest_collect_file(parent, file_path):
    """Let pytest know about our integration test cases."""
    # Only trigger for this conftest's directory
    if file_path == Path(__file__):
        return None
    return None


def pytest_generate_tests(metafunc):
    """Parametrize test functions that request a 'test_case_dir' fixture."""
    if "test_case_dir" in metafunc.fixturenames:
        cases = discover_test_cases()
        metafunc.parametrize(
            "test_case_dir",
            cases,
            ids=[c.name for c in cases],
        )
