"""Integration tests for remote action resolution.

These tests require network access to clone from GitHub.
They cover remote inlining, vendoring, metadata generation, and frozen mode.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


WORKFLOW_TEMPLATE = """\
name: test-tailscale
on: push
jobs:
  connect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: connect to tailscale
        uses: https://github.com/tailscale/github-action@{ref}
        with:
          oauth-client-id: fake-client-id
          oauth-secret: fake-secret
          tags: tag:ci
"""


def run_inline_actions(cwd: Path, *extra_args: str) -> subprocess.CompletedProcess:
    """Run inline-actions and return the completed process."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "inline_actions",
            "--source-dir",
            "workflow-sources",
            "--output-dir",
            "workflows",
            *extra_args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def setup_workspace(tmp_path: Path, ref: str) -> Path:
    """Create a workspace with a workflow source referencing tailscale/github-action."""
    source_dir = tmp_path / "workflow-sources"
    source_dir.mkdir()
    (source_dir / "test.yaml").write_text(WORKFLOW_TEMPLATE.format(ref=ref))
    return tmp_path


class TestRemoteInline:
    """Tests for remote action inlining (replaces CI test-inline job)."""

    def test_vendor(self, tmp_path: Path) -> None:
        """Remote action is inlined, metadata generated, sources vendored."""
        ws = setup_workspace(tmp_path, "v3")
        result = run_inline_actions(ws)
        assert result.returncode == 0, f"Failed:\n{result.stderr}"

        output = (ws / "workflows" / "test.yaml").read_text()

        # Composite action was inlined (no uses: reference remains)
        assert "tailscale/github-action" not in output

        # Metadata file was generated
        metadata = ws / "inline-actions" / "actions.yaml"
        assert metadata.exists(), "Metadata file not generated"
        metadata_content = metadata.read_text()
        assert "github.com/tailscale/github-action@v3" in metadata_content
        assert "revision:" in metadata_content

        # Vendored sources exist
        vendor_dir = (
            ws / "inline-actions" / "github.com" / "tailscale" / "github-action@v3"
        )
        assert vendor_dir.is_dir(), f"Vendored sources not found at {vendor_dir}"

        # action.yml present in vendored copy
        assert (vendor_dir / "action.yml").is_file() or (
            vendor_dir / "action.yaml"
        ).is_file(), "No action.yml in vendored sources"

        # .git directory excluded
        assert not (vendor_dir / ".git").exists(), ".git should not be vendored"

    def test_no_vendor(self, tmp_path: Path) -> None:
        """With --no-vendor, no vendored sources are created."""
        ws = setup_workspace(tmp_path, "v3")
        result = run_inline_actions(ws, "--no-vendor")
        assert result.returncode == 0, f"Failed:\n{result.stderr}"

        output = (ws / "workflows" / "test.yaml").read_text()

        # Composite action was inlined
        assert "tailscale/github-action" not in output

        # Metadata file was generated
        metadata = ws / "inline-actions" / "actions.yaml"
        assert metadata.exists(), "Metadata file not generated"

        # No vendored sources
        vendor_dir = (
            ws / "inline-actions" / "github.com" / "tailscale" / "github-action@v3"
        )
        assert not vendor_dir.exists(), (
            "Vendored sources should not exist with --no-vendor"
        )


class TestFrozen:
    """Tests for frozen mode with lock file pinning (replaces CI test-frozen job)."""

    def test_frozen_pins_revision(self, tmp_path: Path) -> None:
        """--frozen uses the lock file revision, not the current ref target."""
        ws = setup_workspace(tmp_path, "v2")

        # Phase 1: Inline v2 to capture its revision.
        # v2 is Linux-only; its output contains "Support Linux Only".
        result = run_inline_actions(ws)
        assert result.returncode == 0, f"v2 inline failed:\n{result.stderr}"

        v2_output = (ws / "workflows" / "test.yaml").read_text()
        assert "Support Linux Only" in v2_output, (
            "v2 output missing 'Support Linux Only'"
        )

        metadata_content = (ws / "inline-actions" / "actions.yaml").read_text()
        # Extract revision from lock file
        v2_revision = None
        for line in metadata_content.splitlines():
            if "revision:" in line:
                v2_revision = line.split("revision:")[-1].strip()
                break
        assert v2_revision, "Lock file has no revision for v2"

        # Phase 2: Forge lock file mapping v3 identity to v2's revision,
        # switch workflow to v3, run with --frozen.
        (ws / "workflow-sources" / "test.yaml").write_text(
            WORKFLOW_TEMPLATE.format(ref="v3")
        )
        lock_content = (
            f"github.com/tailscale/github-action@v3:\n"
            f"  url: https://github.com/tailscale/github-action\n"
            f"  ref: v3\n"
            f"  checkout_path: inline-actions/github.com/tailscale/github-action@v3\n"
            f"  revision: {v2_revision}\n"
        )
        (ws / "inline-actions" / "actions.yaml").write_text(lock_content)

        result = run_inline_actions(ws, "--frozen")
        assert result.returncode == 0, f"frozen inline failed:\n{result.stderr}"

        frozen_output = (ws / "workflows" / "test.yaml").read_text()
        # Should get v2 code despite v3 ref
        assert "Support Linux Only" in frozen_output, (
            "--frozen output missing v2 marker 'Support Linux Only'"
        )
        assert "Support Linux, Windows, and macOS Only" not in frozen_output, (
            "--frozen output contains v3 marker — revision was not pinned"
        )

        # Phase 3: Run without --frozen to verify v3 is resolved fresh.
        result = run_inline_actions(ws)
        assert result.returncode == 0, f"unfrozen inline failed:\n{result.stderr}"

        v3_output = (ws / "workflows" / "test.yaml").read_text()
        assert "Support Linux, Windows, and macOS Only" in v3_output, (
            "unfrozen output missing v3 marker"
        )
        assert "Support Linux Only" not in v3_output, (
            "unfrozen output still contains v2 marker"
        )

        # Lock file revision should have been updated
        updated_metadata = (ws / "inline-actions" / "actions.yaml").read_text()
        v3_revision = None
        for line in updated_metadata.splitlines():
            if "revision:" in line:
                v3_revision = line.split("revision:")[-1].strip()
                break
        assert v3_revision, "Updated lock file has no revision"
        assert v3_revision != v2_revision, (
            f"Revision was not updated (still {v2_revision})"
        )
