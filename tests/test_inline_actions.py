"""Unit tests for inline_actions."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import (
    FoldedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

import inline_actions as mod


# ---------------------------------------------------------------------------
# _strip_trailing_whitespace
# ---------------------------------------------------------------------------


class TestStripTrailingWhitespace:
    def test_removes_trailing_spaces(self):
        assert mod._strip_trailing_whitespace("foo  \nbar \n") == "foo\nbar\n"

    def test_preserves_leading_spaces(self):
        assert mod._strip_trailing_whitespace("  foo\n  bar\n") == "  foo\n  bar\n"

    def test_empty_string(self):
        assert mod._strip_trailing_whitespace("") == ""

    def test_removes_trailing_tabs(self):
        assert mod._strip_trailing_whitespace("a\t\nb\t\n") == "a\nb\n"

    def test_blank_lines_become_empty(self):
        assert mod._strip_trailing_whitespace("a\n   \nb\n") == "a\n\nb\n"


# ---------------------------------------------------------------------------
# parse_remote_uses
# ---------------------------------------------------------------------------


class TestParseRemoteUses:
    def test_basic_https(self):
        result = mod.parse_remote_uses("https://github.com/owner/repo@v1")
        assert result == ("https://github.com/owner/repo", "", "v1")

    def test_with_subpath(self):
        result = mod.parse_remote_uses("https://github.com/owner/repo/sub/path@main")
        assert result == ("https://github.com/owner/repo", "sub/path", "main")

    def test_non_https_returns_none(self):
        assert mod.parse_remote_uses("./local/action") is None
        assert mod.parse_remote_uses("actions/checkout@v4") is None

    def test_no_at_returns_none(self):
        assert mod.parse_remote_uses("https://github.com/owner/repo") is None

    def test_short_path_returns_none(self):
        assert mod.parse_remote_uses("https://github.com/owner@v1") is None

    def test_custom_host(self):
        result = mod.parse_remote_uses("https://git.example.com/org/repo@abc123")
        assert result == ("https://git.example.com/org/repo", "", "abc123")


# ---------------------------------------------------------------------------
# repo_url_to_identifier
# ---------------------------------------------------------------------------


class TestRepoUrlToIdentifier:
    def test_basic(self):
        assert (
            mod.repo_url_to_identifier("https://github.com/owner/repo", "v1")
            == "github.com/owner/repo@v1"
        )

    def test_trailing_slash_stripped(self):
        assert (
            mod.repo_url_to_identifier("https://github.com/owner/repo/", "main")
            == "github.com/owner/repo@main"
        )

    def test_custom_host(self):
        assert (
            mod.repo_url_to_identifier("https://git.example.com/org/ci", "abc")
            == "git.example.com/org/ci@abc"
        )


# ---------------------------------------------------------------------------
# https_to_ssh
# ---------------------------------------------------------------------------


class TestHttpsToSsh:
    def test_basic(self):
        assert (
            mod.https_to_ssh("https://github.com/owner/repo")
            == "git@github.com:owner/repo.git"
        )

    def test_already_has_git_suffix(self):
        assert (
            mod.https_to_ssh("https://github.com/owner/repo.git")
            == "git@github.com:owner/repo.git"
        )

    def test_custom_host(self):
        assert (
            mod.https_to_ssh("https://git.example.com/org/ci")
            == "git@git.example.com:org/ci.git"
        )


# ---------------------------------------------------------------------------
# RemoteActionTracker
# ---------------------------------------------------------------------------


class TestRemoteActionTracker:
    def test_empty(self):
        tracker = mod.RemoteActionTracker()
        assert tracker.entries == {}

    def test_record_and_entries(self):
        tracker = mod.RemoteActionTracker()
        tracker.record(
            "https://github.com/owner/repo",
            "v1",
            ".github/inline-actions/github.com/owner/repo@v1",
        )
        entries = tracker.entries
        assert "github.com/owner/repo@v1" in entries
        entry = entries["github.com/owner/repo@v1"]
        assert entry["url"] == "https://github.com/owner/repo"
        assert entry["ref"] == "v1"
        assert (
            entry["checkout_path"] == ".github/inline-actions/github.com/owner/repo@v1"
        )

    def test_entries_returns_copy(self):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/owner/repo", "v1", "path")
        entries1 = tracker.entries
        entries1["extra"] = {}
        assert "extra" not in tracker.entries

    def test_multiple_records(self):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "p1")
        tracker.record("https://github.com/c/d", "v2", "p2")
        assert len(tracker.entries) == 2

    def test_overwrite_same_identifier(self):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "old")
        tracker.record("https://github.com/a/b", "v1", "new")
        assert tracker.entries["github.com/a/b@v1"]["checkout_path"] == "new"


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self):
        args = mod.parse_args([])
        assert args.source_dir == Path(".github/workflow-sources")
        assert args.output_dir == Path(".github/workflows")
        assert args.git_ssh == []
        assert args.git_cache_dir is None
        assert args.no_vendor is False

    def test_custom_dirs(self):
        args = mod.parse_args(["--source-dir", "/src", "--output-dir", "/out"])
        assert args.source_dir == Path("/src")
        assert args.output_dir == Path("/out")

    def test_git_ssh_repeatable(self):
        args = mod.parse_args(["--git-ssh", "a.com", "--git-ssh", "b.com"])
        assert args.git_ssh == ["a.com", "b.com"]

    def test_no_vendor_flag(self):
        args = mod.parse_args(["--no-vendor"])
        assert args.no_vendor is True

    def test_git_cache_dir(self):
        args = mod.parse_args(["--git-cache-dir", "/cache"])
        assert args.git_cache_dir == Path("/cache")


# ---------------------------------------------------------------------------
# resolve_inputs
# ---------------------------------------------------------------------------


class TestResolveInputs:
    def test_with_values_override_defaults(self):
        action = {"inputs": {"name": {"default": "world"}}}
        result = mod.resolve_inputs(action, {"name": "alice"})
        assert result == {"name": "alice"}

    def test_defaults_used_when_no_with(self):
        action = {"inputs": {"name": {"default": "world"}}}
        result = mod.resolve_inputs(action, {})
        assert result == {"name": "world"}

    def test_none_with(self):
        action = {"inputs": {"x": {"default": "1"}}}
        result = mod.resolve_inputs(action, None)
        assert result == {"x": "1"}

    def test_no_inputs(self):
        assert mod.resolve_inputs({}, {"x": "1"}) == {}
        assert mod.resolve_inputs({"inputs": None}, None) == {}

    def test_required_input_without_default_omitted(self):
        action = {"inputs": {"x": {"required": True}}}
        result = mod.resolve_inputs(action, {})
        assert result == {}

    def test_values_converted_to_string(self):
        action = {"inputs": {"port": {"default": 8080}}}
        result = mod.resolve_inputs(action, {"port": 3000})
        assert result == {"port": "3000"}


# ---------------------------------------------------------------------------
# replace_expressions
# ---------------------------------------------------------------------------


class TestReplaceExpressions:
    def test_input_replacement(self):
        result = mod.replace_expressions(
            "Hello ${{ inputs.name }}", {"name": "world"}, "/action"
        )
        assert result == "Hello world"

    def test_action_path_replacement(self):
        result = mod.replace_expressions(
            "${{ env.GITHUB_ACTION_PATH }}/script.sh", {}, "/my/action"
        )
        assert result == "/my/action/script.sh"

    def test_unknown_input_preserved(self):
        result = mod.replace_expressions("${{ inputs.unknown }}", {}, "/action")
        assert result == "${{ inputs.unknown }}"

    def test_other_expressions_preserved(self):
        result = mod.replace_expressions(
            "${{ github.sha }} ${{ secrets.TOKEN }}", {}, "/action"
        )
        assert "${{ github.sha }}" in result
        assert "${{ secrets.TOKEN }}" in result

    def test_multiple_inputs(self):
        result = mod.replace_expressions(
            "${{ inputs.a }} and ${{ inputs.b }}", {"a": "X", "b": "Y"}, "/p"
        )
        assert result == "X and Y"

    def test_preserves_folded_scalar(self):
        val = FoldedScalarString("${{ inputs.x }}")
        result = mod.replace_expressions(val, {"x": "hi"}, "/p")
        assert isinstance(result, FoldedScalarString)
        assert str(result) == "hi"

    def test_preserves_literal_scalar(self):
        val = LiteralScalarString("${{ inputs.x }}")
        result = mod.replace_expressions(val, {"x": "hi"}, "/p")
        assert isinstance(result, LiteralScalarString)
        assert str(result) == "hi"

    def test_preserves_single_quoted_scalar(self):
        val = SingleQuotedScalarString("${{ inputs.x }}")
        result = mod.replace_expressions(val, {"x": "hi"}, "/p")
        assert isinstance(result, SingleQuotedScalarString)

    def test_whitespace_in_expression(self):
        result = mod.replace_expressions("${{  inputs.x  }}", {"x": "v"}, "/p")
        assert result == "v"


# ---------------------------------------------------------------------------
# replace_expressions_in_value
# ---------------------------------------------------------------------------


class TestReplaceExpressionsInValue:
    def test_string(self):
        result = mod.replace_expressions_in_value("${{ inputs.x }}", {"x": "v"}, "/p")
        assert result == "v"

    def test_dict(self):
        result = mod.replace_expressions_in_value(
            {"key": "${{ inputs.x }}"}, {"x": "v"}, "/p"
        )
        assert result == {"key": "v"}

    def test_list(self):
        result = mod.replace_expressions_in_value(
            ["${{ inputs.x }}", "static"], {"x": "v"}, "/p"
        )
        assert result == ["v", "static"]

    def test_nested(self):
        result = mod.replace_expressions_in_value(
            {"a": [{"b": "${{ inputs.x }}"}]}, {"x": "v"}, "/p"
        )
        assert result == {"a": [{"b": "v"}]}

    def test_non_string_passthrough(self):
        assert mod.replace_expressions_in_value(42, {}, "/p") == 42
        assert mod.replace_expressions_in_value(True, {}, "/p") is True
        assert mod.replace_expressions_in_value(None, {}, "/p") is None


# ---------------------------------------------------------------------------
# generate_header
# ---------------------------------------------------------------------------


class TestGenerateHeader:
    def test_format(self):
        header = mod.generate_header("workflow-sources/ci.yaml")
        assert "auto-generated by inline-actions" in header
        assert "Do not edit manually" in header
        assert "# Source: workflow-sources/ci.yaml\n" in header

    def test_ends_with_newline(self):
        header = mod.generate_header("test")
        assert header.endswith("\n")


# ---------------------------------------------------------------------------
# load_action
# ---------------------------------------------------------------------------


class TestLoadAction:
    def test_loads_action_yml(self, tmp_path):
        (tmp_path / "action.yml").write_text(
            "name: test\nruns:\n  using: composite\n  steps: []\n"
        )
        action = mod.load_action(tmp_path)
        assert action["name"] == "test"
        assert action["runs"]["using"] == "composite"

    def test_loads_action_yaml(self, tmp_path):
        (tmp_path / "action.yaml").write_text(
            "name: alt\nruns:\n  using: composite\n  steps: []\n"
        )
        action = mod.load_action(tmp_path)
        assert action["name"] == "alt"

    def test_prefers_yml_over_yaml(self, tmp_path):
        (tmp_path / "action.yml").write_text("name: yml-version\n")
        (tmp_path / "action.yaml").write_text("name: yaml-version\n")
        action = mod.load_action(tmp_path)
        assert action["name"] == "yml-version"

    def test_raises_on_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No action.yml found"):
            mod.load_action(tmp_path)


# ---------------------------------------------------------------------------
# inline_composite_steps
# ---------------------------------------------------------------------------


class TestInlineCompositeSteps:
    def _make_action(self, steps, inputs=None):
        action = {"runs": {"using": "composite", "steps": steps}}
        if inputs:
            action["inputs"] = inputs
        return action

    def test_basic_inlining(self):
        action = self._make_action([{"name": "step1", "run": "echo hello"}])
        step = {"uses": "./action", "with": {}}
        result = mod.inline_composite_steps(action, step, "/ws/path")
        assert len(result) == 1
        assert result[0]["run"] == "echo hello"

    def test_input_replacement(self):
        action = self._make_action(
            [{"run": "echo ${{ inputs.msg }}"}],
            inputs={"msg": {"default": "default_msg"}},
        )
        step = {"uses": "./action", "with": {"msg": "custom"}}
        result = mod.inline_composite_steps(action, step, "/ws")
        assert result[0]["run"] == "echo custom"

    def test_action_path_replacement(self):
        action = self._make_action([{"run": "${{ env.GITHUB_ACTION_PATH }}/run.sh"}])
        step = {"uses": "./action"}
        result = mod.inline_composite_steps(action, step, "my/action")
        assert result[0]["run"] == "my/action/run.sh"

    def test_deep_copy(self):
        """Ensure original action dict is not modified."""
        action = self._make_action(
            [{"name": "s1", "run": "${{ inputs.x }}"}],
            inputs={"x": {"default": "orig"}},
        )
        step = {"uses": "./a", "with": {"x": "replaced"}}
        mod.inline_composite_steps(action, step, "/p")
        assert action["runs"]["steps"][0]["run"] == "${{ inputs.x }}"

    def test_multiple_steps(self):
        action = self._make_action(
            [
                {"name": "s1", "run": "echo 1"},
                {"name": "s2", "run": "echo 2"},
                {"name": "s3", "run": "echo 3"},
            ]
        )
        result = mod.inline_composite_steps(action, {"uses": "./a"}, "/p")
        assert len(result) == 3

    def test_default_inputs_used(self):
        action = self._make_action(
            [{"run": "echo ${{ inputs.x }}"}],
            inputs={"x": {"default": "fallback"}},
        )
        step = {"uses": "./a"}
        result = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["run"] == "echo fallback"


# ---------------------------------------------------------------------------
# process_workflow
# ---------------------------------------------------------------------------


class TestProcessWorkflow:
    def test_passthrough_non_composite(self):
        """Steps without uses: are returned as-is."""
        workflow = {
            "jobs": {
                "build": {
                    "steps": [
                        {"name": "Run tests", "run": "pytest"},
                    ]
                }
            }
        }
        tracker = mod.RemoteActionTracker()
        result = mod.process_workflow(workflow, None, tracker)
        assert result["jobs"]["build"]["steps"][0]["run"] == "pytest"

    def test_does_not_modify_original(self):
        workflow = {"jobs": {"build": {"steps": [{"run": "echo hi"}]}}}
        tracker = mod.RemoteActionTracker()
        mod.process_workflow(workflow, None, tracker)
        assert workflow["jobs"]["build"]["steps"] == [{"run": "echo hi"}]

    def test_inline_local_action(self, tmp_path):
        """Integration-like: inline a local composite action."""
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: my-action
            inputs:
              greeting:
                default: hello
            runs:
              using: composite
              steps:
                - name: greet
                  run: echo ${{ inputs.greeting }}
        """)
        )
        workflow = {
            "jobs": {
                "build": {
                    "steps": [
                        {
                            "name": "use action",
                            "uses": f"./{action_dir.relative_to(tmp_path)}",
                            "with": {"greeting": "hi"},
                        }
                    ]
                }
            }
        }
        tracker = mod.RemoteActionTracker()
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.process_workflow(workflow, None, tracker)
        steps = result["jobs"]["build"]["steps"]
        assert len(steps) == 1
        assert steps[0]["run"] == "echo hi"

    def test_non_composite_action_kept(self, tmp_path):
        """Actions with using != composite are not inlined."""
        action_dir = tmp_path / "js-action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: js-action
            runs:
              using: node20
              main: index.js
        """)
        )
        workflow = {
            "jobs": {
                "build": {"steps": [{"uses": f"./{action_dir.relative_to(tmp_path)}"}]}
            }
        }
        tracker = mod.RemoteActionTracker()
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.process_workflow(workflow, None, tracker)
        steps = result["jobs"]["build"]["steps"]
        assert len(steps) == 1
        assert "uses" in steps[0]

    def test_empty_jobs(self):
        workflow = {"jobs": {}}
        tracker = mod.RemoteActionTracker()
        result = mod.process_workflow(workflow, None, tracker)
        assert result["jobs"] == {}


# ---------------------------------------------------------------------------
# resolve_action_dir
# ---------------------------------------------------------------------------


class TestResolveActionDir:
    def test_local_action_yml(self, tmp_path):
        action_dir = tmp_path / "my-action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text("name: test\n")
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.resolve_action_dir("./my-action")
        assert result is not None
        assert result[0] == action_dir
        assert result[1] == "my-action"

    def test_local_action_yaml(self, tmp_path):
        action_dir = tmp_path / "my-action"
        action_dir.mkdir()
        (action_dir / "action.yaml").write_text("name: test\n")
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.resolve_action_dir("./my-action")
        assert result is not None

    def test_non_local_returns_none(self):
        assert mod.resolve_action_dir("actions/checkout@v4") is None

    def test_missing_action_returns_none(self, tmp_path):
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            assert mod.resolve_action_dir("./nonexistent") is None


# ---------------------------------------------------------------------------
# resolve_remote_action
# ---------------------------------------------------------------------------


class TestResolveRemoteAction:
    def test_resolves_remote(self, tmp_path):
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = action_dir
        tracker = mod.RemoteActionTracker()

        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1", resolver, tracker
        )
        assert result is not None
        assert result[0] == action_dir
        assert "github.com/owner/repo@v1" in result[1]
        assert len(tracker.entries) == 1

    def test_non_url_returns_none(self):
        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()
        assert mod.resolve_remote_action("./local", resolver, tracker) is None

    def test_unresolvable_returns_none(self):
        resolver = MagicMock()
        resolver.resolve.return_value = None
        tracker = mod.RemoteActionTracker()
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1", resolver, tracker
        )
        assert result is None


# ---------------------------------------------------------------------------
# write_metadata
# ---------------------------------------------------------------------------


class TestWriteMetadata:
    def test_writes_file(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/owner/repo", "v1", "path/to/action")

        mod.write_metadata(output_dir, tracker)

        metadata_file = tmp_path / ".github" / "inline-actions" / "actions.yaml"
        assert metadata_file.exists()
        content = metadata_file.read_text()
        assert "Auto-generated" in content
        assert "owner/repo" in content

    def test_no_trailing_whitespace(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/owner/repo", "v1", "path/to/action")

        mod.write_metadata(output_dir, tracker)

        metadata_file = tmp_path / ".github" / "inline-actions" / "actions.yaml"
        content = metadata_file.read_text()
        for i, line in enumerate(content.split("\n"), 1):
            assert line == line.rstrip(), f"Line {i} has trailing whitespace: {line!r}"

    def test_empty_tracker_skips(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        tracker = mod.RemoteActionTracker()

        mod.write_metadata(output_dir, tracker)

        inline_dir = tmp_path / ".github" / "inline-actions"
        assert not inline_dir.exists()

    def test_valid_yaml(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "p1")
        tracker.record("https://github.com/c/d", "v2", "p2")

        mod.write_metadata(output_dir, tracker)

        metadata_file = tmp_path / ".github" / "inline-actions" / "actions.yaml"
        y = YAML()
        data = y.load(metadata_file)
        assert "github.com/a/b@v1" in data
        assert "github.com/c/d@v2" in data


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------


class TestProcessFile:
    def _make_source(self, source_dir, name="ci.yaml", content=None):
        if content is None:
            content = textwrap.dedent("""\
                name: CI
                on:
                  push:
                    branches: [main]
                jobs:
                  build:
                    runs-on: ubuntu-latest
                    steps:
                      - name: checkout
                        uses: actions/checkout@v4
                      - name: test
                        run: echo hello
            """)
        source_file = source_dir / name
        source_file.write_text(content)
        return source_file

    def test_generates_output(self, tmp_path):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        source_file = self._make_source(source_dir)
        tracker = mod.RemoteActionTracker()

        mod.process_file(source_file, source_dir, "sources", output_dir, None, tracker)

        output_file = output_dir / "ci.yaml"
        assert output_file.exists()
        content = output_file.read_text()
        assert "auto-generated" in content
        assert "# Source: sources/ci.yaml" in content

    def test_no_trailing_whitespace_in_output(self, tmp_path):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        source_file = self._make_source(source_dir)
        tracker = mod.RemoteActionTracker()

        mod.process_file(source_file, source_dir, "sources", output_dir, None, tracker)

        output_file = output_dir / "ci.yaml"
        content = output_file.read_text()
        for i, line in enumerate(content.split("\n"), 1):
            assert line == line.rstrip(), f"Line {i} has trailing whitespace: {line!r}"

    def test_skips_non_dict_workflow(self, tmp_path, capsys):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        source_file = self._make_source(source_dir, content="- not a workflow\n")
        tracker = mod.RemoteActionTracker()

        mod.process_file(source_file, source_dir, "sources", output_dir, None, tracker)

        assert not (output_dir / "ci.yaml").exists()
        assert "skipping" in capsys.readouterr().err

    def test_creates_subdirectories(self, tmp_path):
        source_dir = tmp_path / "sources"
        sub = source_dir / "sub"
        sub.mkdir(parents=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        self._make_source(sub, "deep.yaml")
        tracker = mod.RemoteActionTracker()

        mod.process_file(
            sub / "deep.yaml", source_dir, "sources", output_dir, None, tracker
        )

        assert (output_dir / "sub" / "deep.yaml").exists()

    def test_output_is_valid_yaml(self, tmp_path):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        source_file = self._make_source(source_dir)
        tracker = mod.RemoteActionTracker()

        mod.process_file(source_file, source_dir, "sources", output_dir, None, tracker)

        y = YAML()
        data = y.load(output_dir / "ci.yaml")
        assert data["name"] == "CI"
        assert "build" in data["jobs"]

    def test_preserves_list_indentation(self, tmp_path):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        source_file = self._make_source(source_dir)
        tracker = mod.RemoteActionTracker()

        mod.process_file(source_file, source_dir, "sources", output_dir, None, tracker)

        content = (output_dir / "ci.yaml").read_text()
        # Lists must be indented under their parent key, not at the same level
        assert "    steps:\n      - name:" in content
        assert "    branches: [main]" in content


# ---------------------------------------------------------------------------
# GitActionResolver
# ---------------------------------------------------------------------------


class TestGitActionResolver:
    def test_resolve_cached(self, tmp_path):
        """When the repo is already cloned, resolve returns from cache."""
        clone_dir = tmp_path / "clone"
        clone_dir.mkdir()
        (clone_dir / "action.yml").write_text("name: test\n")

        resolver = mod.GitActionResolver(tmp_path)
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        result = resolver.resolve("https://github.com/a/b", "", "v1")
        assert result == clone_dir

    def test_resolve_with_subpath(self, tmp_path):
        clone_dir = tmp_path / "clone"
        sub = clone_dir / "sub" / "path"
        sub.mkdir(parents=True)
        (sub / "action.yml").write_text("name: test\n")

        resolver = mod.GitActionResolver(tmp_path)
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        result = resolver.resolve("https://github.com/a/b", "sub/path", "v1")
        assert result == sub

    def test_resolve_no_action_file(self, tmp_path, capsys):
        clone_dir = tmp_path / "clone"
        clone_dir.mkdir()

        resolver = mod.GitActionResolver(tmp_path)
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        result = resolver.resolve("https://github.com/a/b", "", "v1")
        assert result is None
        assert "warning" in capsys.readouterr().err

    def test_ssh_domain(self):
        resolver = mod.GitActionResolver(
            Path("/tmp"), git_ssh_domains={"git.example.com"}
        )
        assert "git.example.com" in resolver._git_ssh_domains


# ---------------------------------------------------------------------------
# vendor_actions
# ---------------------------------------------------------------------------


class TestVendorActions:
    def test_vendors_action(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clone_dir = tmp_path / "cache" / "clone"
        clone_dir.mkdir(parents=True)
        (clone_dir / "action.yml").write_text("name: test\n")
        (clone_dir / ".git").mkdir()
        (clone_dir / ".git" / "config").write_text("gitconfig\n")

        resolver = mod.GitActionResolver(tmp_path / "cache")
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", str(tmp_path / "vendor" / "a"))

        mod.vendor_actions(resolver, tracker)

        vendored = tmp_path / "vendor" / "a"
        assert vendored.exists()
        assert (vendored / "action.yml").exists()
        assert not (vendored / ".git").exists()

    def test_empty_tracker_noop(self):
        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()
        mod.vendor_actions(resolver, tracker)

    def test_missing_clone_warns(self, capsys):
        resolver = mod.GitActionResolver(Path("/tmp"))
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "/some/path")
        mod.vendor_actions(resolver, tracker)
        assert "warning" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# print_no_vendor_notice
# ---------------------------------------------------------------------------


class TestPrintNoVendorNotice:
    def test_prints_notice(self, capsys):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "path/a")
        mod.print_no_vendor_notice(tracker)
        output = capsys.readouterr().out
        assert "WARNING" in output
        assert "github.com/a/b" in output

    def test_empty_tracker_no_output(self, capsys):
        tracker = mod.RemoteActionTracker()
        mod.print_no_vendor_notice(tracker)
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _make_yaml
# ---------------------------------------------------------------------------


class TestMakeYaml:
    def test_returns_yaml_instance(self):
        y = mod._make_yaml()
        assert isinstance(y, YAML)

    def test_preserve_quotes(self):
        y = mod._make_yaml()
        assert y.preserve_quotes is True

    def test_width(self):
        y = mod._make_yaml()
        assert y.width == 120

    def test_sequence_indent(self):
        y = mod._make_yaml()
        assert y.sequence_indent == 4
        assert y.sequence_dash_offset == 2


# ---------------------------------------------------------------------------
# main (integration-like)
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_source_dir(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            mod.main(["--source-dir", "/nonexistent/path"])
        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_no_workflow_files(self, tmp_path, capsys):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        mod.main(
            ["--source-dir", str(source_dir), "--output-dir", str(tmp_path / "out")]
        )
        assert "no workflow files" in capsys.readouterr().err

    def test_end_to_end_local(self, tmp_path):
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / "output"

        action_dir = tmp_path / "my-action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: my-action
            inputs:
              msg:
                default: world
            runs:
              using: composite
              steps:
                - name: greet
                  run: echo ${{ inputs.msg }}
        """)
        )

        (source_dir / "ci.yaml").write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - name: greet
                    uses: ./my-action
                    with:
                      msg: hello
        """)
        )

        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            mod.main(
                [
                    "--source-dir",
                    str(source_dir),
                    "--output-dir",
                    str(output_dir),
                ]
            )

        output_file = output_dir / "ci.yaml"
        assert output_file.exists()
        content = output_file.read_text()
        assert "echo hello" in content
        assert "uses:" not in content.split("\n", 2)[-1]  # no uses: in YAML body

        # Verify no trailing whitespace
        for i, line in enumerate(content.split("\n"), 1):
            assert line == line.rstrip(), f"Line {i} has trailing whitespace: {line!r}"
