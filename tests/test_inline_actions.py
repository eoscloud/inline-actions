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

    def test_record_with_revision(self):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "p1", "abc123")
        entry = tracker.entries["github.com/a/b@v1"]
        assert entry["revision"] == "abc123"

    def test_record_without_revision_omits_key(self):
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "p1")
        entry = tracker.entries["github.com/a/b@v1"]
        assert "revision" not in entry


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
        assert args.frozen is False

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

    def test_frozen_flag(self):
        args = mod.parse_args(["--frozen"])
        assert args.frozen is True


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

    # --- Pass 2: bare input references inside complex expressions ---

    def test_bare_input_in_complex_expression(self):
        result = mod.replace_expressions(
            "${{ inputs.enabled == 'true' && inputs.name || '' }}",
            {"enabled": "true", "name": "myapp"},
            "/p",
        )
        assert result == "${{ 'true' == 'true' && 'myapp' || '' }}"

    def test_bare_input_with_expression_value(self):
        result = mod.replace_expressions(
            "${{ inputs.ref == 'main' && inputs.tag || 'latest' }}",
            {"ref": "${{ github.ref }}", "tag": "v1"},
            "/p",
        )
        assert result == "${{ github.ref == 'main' && 'v1' || 'latest' }}"

    def test_bare_input_with_format_function(self):
        result = mod.replace_expressions(
            "${{ format('{0}/{1}', inputs.registry, inputs.image) }}",
            {"registry": "ghcr.io", "image": "myapp"},
            "/p",
        )
        assert result == "${{ format('{0}/{1}', 'ghcr.io', 'myapp') }}"

    def test_bare_input_mixed_with_standalone(self):
        result = mod.replace_expressions(
            "${{ inputs.a }} and ${{ inputs.b == 'true' && inputs.c || '' }}",
            {"a": "hello", "b": "true", "c": "world"},
            "/p",
        )
        assert result == "hello and ${{ 'true' == 'true' && 'world' || '' }}"

    def test_bare_input_value_with_single_quotes(self):
        result = mod.replace_expressions(
            "${{ inputs.msg == 'yes' }}",
            {"msg": "it's"},
            "/p",
        )
        assert result == "${{ 'it''s' == 'yes' }}"

    def test_bare_input_empty_value(self):
        result = mod.replace_expressions(
            "${{ inputs.x == '' }}",
            {"x": ""},
            "/p",
        )
        assert result == "${{ '' == '' }}"

    def test_bare_github_action_path_in_complex_expr(self):
        result = mod.replace_expressions(
            "${{ env.GITHUB_ACTION_PATH != '' && format('{0}/script.sh', env.GITHUB_ACTION_PATH) }}",
            {},
            "./actions/my-action",
        )
        assert (
            result
            == "${{ './actions/my-action' != '' && format('{0}/script.sh', './actions/my-action') }}"
        )

    def test_unknown_bare_input_preserved_in_complex_expr(self):
        result = mod.replace_expressions(
            "${{ inputs.unknown == 'true' }}",
            {},
            "/p",
        )
        assert result == "${{ inputs.unknown == 'true' }}"

    def test_implicit_expression_replaces_bare_inputs(self):
        """GitHub Actions `if:` conditions are implicit expressions."""
        result = mod.replace_expressions(
            "always() && inputs.image_ref != ''",
            {"image_ref": "${{ steps.build.outputs.ref }}"},
            "/p",
            implicit_expression=True,
        )
        assert result == "always() && steps.build.outputs.ref != ''"

    def test_implicit_expression_replaces_plain_value(self):
        result = mod.replace_expressions(
            "inputs.enabled == 'true'",
            {"enabled": "true"},
            "/p",
            implicit_expression=True,
        )
        assert result == "'true' == 'true'"

    def test_implicit_expression_preserves_unknown_inputs(self):
        result = mod.replace_expressions(
            "inputs.unknown == 'true'",
            {},
            "/p",
            implicit_expression=True,
        )
        assert result == "inputs.unknown == 'true'"

    def test_implicit_expression_replaces_github_action_path(self):
        result = mod.replace_expressions(
            "env.GITHUB_ACTION_PATH != ''",
            {},
            "./actions/my-action",
            implicit_expression=True,
        )
        assert result == "'./actions/my-action' != ''"

    def test_implicit_expression_false_does_not_replace_bare(self):
        """Without implicit_expression, bare inputs outside ${{ }} are untouched."""
        result = mod.replace_expressions(
            "always() && inputs.image_ref != ''",
            {"image_ref": "some-ref"},
            "/p",
            implicit_expression=False,
        )
        assert result == "always() && inputs.image_ref != ''"


class TestValueToExpr:
    def test_plain_string(self):
        assert mod._value_to_expr("hello") == "'hello'"

    def test_expression_value(self):
        assert mod._value_to_expr("${{ github.ref }}") == "github.ref"

    def test_empty_string(self):
        assert mod._value_to_expr("") == "''"

    def test_string_with_single_quotes(self):
        assert mod._value_to_expr("it's") == "'it''s'"

    def test_expression_with_whitespace(self):
        assert mod._value_to_expr("${{  github.sha  }}") == "github.sha"

    def test_partial_expression_treated_as_literal(self):
        assert (
            mod._value_to_expr("prefix-${{ github.sha }}")
            == "'prefix-${{ github.sha }}'"
        )


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
        result, mapping = mod.inline_composite_steps(action, step, "/ws/path")
        assert len(result) == 1
        assert result[0]["run"] == "echo hello"
        assert mapping == {}

    def test_input_replacement(self):
        action = self._make_action(
            [{"run": "echo ${{ inputs.msg }}"}],
            inputs={"msg": {"default": "default_msg"}},
        )
        step = {"uses": "./action", "with": {"msg": "custom"}}
        result, mapping = mod.inline_composite_steps(action, step, "/ws")
        assert result[0]["run"] == "echo custom"

    def test_action_path_replacement(self):
        action = self._make_action([{"run": "${{ env.GITHUB_ACTION_PATH }}/run.sh"}])
        step = {"uses": "./action"}
        result, mapping = mod.inline_composite_steps(action, step, "my/action")
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
        result, mapping = mod.inline_composite_steps(action, {"uses": "./a"}, "/p")
        assert len(result) == 3

    def test_default_inputs_used(self):
        action = self._make_action(
            [{"run": "echo ${{ inputs.x }}"}],
            inputs={"x": {"default": "fallback"}},
        )
        step = {"uses": "./a"}
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["run"] == "echo fallback"

    def test_if_condition_bare_inputs_replaced(self):
        """if: conditions are implicit expressions — bare inputs.X must be substituted."""
        action = self._make_action(
            [
                {
                    "name": "cleanup",
                    "if": "always() && inputs.image_ref != ''",
                    "run": "echo ${{ inputs.image_ref }}",
                }
            ],
            inputs={"image_ref": {"required": True}},
        )
        step = {
            "uses": "./a",
            "with": {"image_ref": "${{ steps.build.outputs.ref }}"},
        }
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["if"] == "always() && steps.build.outputs.ref != ''"
        assert result[0]["run"] == "echo ${{ steps.build.outputs.ref }}"

    def test_if_condition_plain_value_replaced(self):
        action = self._make_action(
            [{"name": "s1", "if": "inputs.enabled == 'true'", "run": "echo go"}],
            inputs={"enabled": {"default": "false"}},
        )
        step = {"uses": "./a", "with": {"enabled": "true"}}
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["if"] == "'true' == 'true'"

    def test_mangles_ids_when_step_has_id(self):
        action = self._make_action(
            [{"name": "s1", "id": "internal", "run": "echo hi"}],
        )
        action["outputs"] = {
            "result": {
                "description": "The result",
                "value": "${{ steps.internal.outputs.result }}",
            }
        }
        step = {"uses": "./a", "id": "build"}
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["id"] == "build--internal"
        assert mapping == {
            "steps.build.outputs.result": "steps.build--internal.outputs.result"
        }

    def test_no_mangling_without_step_id(self):
        action = self._make_action(
            [{"name": "s1", "id": "internal", "run": "echo hi"}],
        )
        step = {"uses": "./a"}
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["id"] == "internal"
        assert mapping == {}

    def test_mangles_internal_cross_references(self):
        action = self._make_action(
            [
                {"name": "s1", "id": "first", "run": "echo one"},
                {
                    "name": "s2",
                    "id": "second",
                    "run": "echo ${{ steps.first.outputs.val }}",
                },
            ],
        )
        step = {"uses": "./a", "id": "build"}
        result, mapping = mod.inline_composite_steps(action, step, "/p")
        assert result[0]["id"] == "build--first"
        assert result[1]["id"] == "build--second"
        assert result[1]["run"] == "echo ${{ steps.build--first.outputs.val }}"


# ---------------------------------------------------------------------------
# parse_output_mapping
# ---------------------------------------------------------------------------


class TestParseOutputMapping:
    def test_basic_mapping(self):
        action = {
            "outputs": {
                "url": {
                    "description": "Artifact URL",
                    "value": "${{ steps.set-output.outputs.url }}",
                },
            }
        }
        result = mod.parse_output_mapping(action, "build")
        assert result == {
            "steps.build.outputs.url": "steps.build--set-output.outputs.url"
        }

    def test_multiple_outputs(self):
        action = {
            "outputs": {
                "url": {"value": "${{ steps.set-output.outputs.url }}"},
                "checksum": {"value": "${{ steps.set-output.outputs.checksum }}"},
            }
        }
        result = mod.parse_output_mapping(action, "build")
        assert result == {
            "steps.build.outputs.url": "steps.build--set-output.outputs.url",
            "steps.build.outputs.checksum": "steps.build--set-output.outputs.checksum",
        }

    def test_no_outputs(self):
        assert mod.parse_output_mapping({}, "build") == {}
        assert mod.parse_output_mapping({"outputs": None}, "build") == {}

    def test_skips_non_dict_spec(self):
        action = {"outputs": {"url": "plain string"}}
        assert mod.parse_output_mapping(action, "build") == {}

    def test_skips_non_string_value(self):
        action = {"outputs": {"url": {"value": 42}}}
        assert mod.parse_output_mapping(action, "build") == {}

    def test_warns_on_unparseable_expression(self, capsys):
        action = {"outputs": {"url": {"value": "some-literal-value"}}}
        result = mod.parse_output_mapping(action, "build")
        assert result == {}
        assert "warning: cannot parse output expression" in capsys.readouterr().err

    def test_complex_expression_with_embedded_step_ref(self):
        """Step refs embedded in complex expressions (ternary, format, etc.) are parsed."""
        action = {
            "outputs": {
                "full_url": {
                    "value": "${{ inputs.enabled == 'true' && format('{0}://{1}/{2}', inputs.scheme, inputs.host, steps.meta.outputs.path) || '' }}",
                },
            }
        }
        result = mod.parse_output_mapping(action, "build")
        assert result == {
            "steps.build.outputs.full_url": "steps.build--meta.outputs.path",
            "steps.build.outputs.path": "steps.build--meta.outputs.path",
        }

    def test_maps_internal_output_name_when_different(self):
        """When declared name != internal output name, both are mapped."""
        action = {
            "outputs": {
                "image_tags": {"value": "${{ steps.meta.outputs.tags }}"},
            }
        }
        result = mod.parse_output_mapping(action, "build-image")
        assert result == {
            "steps.build-image.outputs.image_tags": "steps.build-image--meta.outputs.tags",
            "steps.build-image.outputs.tags": "steps.build-image--meta.outputs.tags",
        }

    def test_no_duplicate_when_names_match(self):
        """When declared name == internal output name, only one entry is created."""
        action = {
            "outputs": {
                "tags": {"value": "${{ steps.meta.outputs.tags }}"},
            }
        }
        result = mod.parse_output_mapping(action, "build")
        assert result == {
            "steps.build.outputs.tags": "steps.build--meta.outputs.tags",
        }

    def test_warns_on_conflicting_internal_names(self, capsys):
        """When two outputs have different declared names but same internal name, warn."""
        action = {
            "outputs": {
                "image_tags": {"value": "${{ steps.meta.outputs.result }}"},
                "image_labels": {"value": "${{ steps.meta.outputs.result }}"},
            }
        }
        result = mod.parse_output_mapping(action, "step")
        # Both declared outputs should be mapped
        assert "steps.step.outputs.image_tags" in result
        assert "steps.step.outputs.image_labels" in result
        # The internal name 'result' is added by the first output, the
        # second output's attempt to add it should warn
        assert "conflicting internal output name" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# mangle_step_ids
# ---------------------------------------------------------------------------


class TestMangleStepIds:
    def test_prefixes_ids(self):
        steps = [{"id": "a", "run": "echo"}, {"id": "b", "run": "echo"}]
        result = mod.mangle_step_ids(steps, "build")
        assert result[0]["id"] == "build--a"
        assert result[1]["id"] == "build--b"

    def test_steps_without_ids_unchanged(self):
        steps = [{"name": "no id", "run": "echo"}]
        result = mod.mangle_step_ids(steps, "build")
        assert "id" not in result[0]
        assert result[0]["run"] == "echo"

    def test_rewrites_internal_cross_references(self):
        steps = [
            {"id": "first", "run": "echo one"},
            {"id": "second", "run": "echo ${{ steps.first.outputs.val }}"},
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert result[1]["run"] == "echo ${{ steps.pfx--first.outputs.val }}"

    def test_preserves_non_matching_refs(self):
        steps = [
            {"id": "a", "run": "echo ${{ steps.external.outputs.val }}"},
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert result[0]["run"] == "echo ${{ steps.external.outputs.val }}"

    def test_rewrites_in_nested_values(self):
        steps = [
            {"id": "a", "run": "echo"},
            {
                "name": "b",
                "env": {"URL": "${{ steps.a.outputs.url }}"},
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert result[1]["env"]["URL"] == "${{ steps.pfx--a.outputs.url }}"

    def test_rewrites_in_list_values(self):
        steps = [
            {"id": "a", "run": "echo"},
            {
                "name": "b",
                "args": ["${{ steps.a.outputs.url }}", "literal"],
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert result[1]["args"] == ["${{ steps.pfx--a.outputs.url }}", "literal"]

    def test_rewrites_folded_scalar_refs(self):
        steps = [
            {"id": "a", "run": "echo"},
            {
                "id": "b",
                "run": FoldedScalarString("echo ${{ steps.a.outputs.url }}\n"),
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert isinstance(result[1]["run"], FoldedScalarString)
        assert "steps.pfx--a.outputs.url" in str(result[1]["run"])

    def test_rewrites_literal_scalar_refs(self):
        steps = [
            {"id": "a", "run": "echo"},
            {
                "id": "b",
                "run": LiteralScalarString("echo ${{ steps.a.outputs.url }}\n"),
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert isinstance(result[1]["run"], LiteralScalarString)
        assert "steps.pfx--a.outputs.url" in str(result[1]["run"])

    def test_rewrites_single_quoted_scalar_refs(self):
        steps = [
            {"id": "a", "run": "echo"},
            {
                "id": "b",
                "run": SingleQuotedScalarString("echo ${{ steps.a.outputs.url }}"),
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert isinstance(result[1]["run"], SingleQuotedScalarString)
        assert "steps.pfx--a.outputs.url" in str(result[1]["run"])

    def test_rewrites_embedded_refs_in_complex_expressions(self):
        """Step refs inside complex ${{ }} expressions are mangled."""
        steps = [
            {"id": "meta", "run": "echo version=1.0 >> $GITHUB_OUTPUT"},
            {
                "id": "b",
                "run": "echo ${{ inputs.flag == 'true' && steps.meta.outputs.version || '' }}",
            },
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert (
            result[1]["run"]
            == "echo ${{ inputs.flag == 'true' && steps.pfx--meta.outputs.version || '' }}"
        )

    def test_non_string_values_passthrough(self):
        steps = [
            {"id": "a", "timeout": 30, "continue-on-error": True},
        ]
        result = mod.mangle_step_ids(steps, "pfx")
        assert result[0]["timeout"] == 30
        assert result[0]["continue-on-error"] is True


# ---------------------------------------------------------------------------
# rewrite_step_output_refs
# ---------------------------------------------------------------------------


class TestRewriteStepOutputRefs:
    def test_basic_rewrite(self):
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        result = mod.rewrite_step_output_refs("${{ steps.build.outputs.url }}", mapping)
        assert result == "${{ steps.build--internal.outputs.url }}"

    def test_no_match_preserved(self):
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        result = mod.rewrite_step_output_refs("${{ steps.other.outputs.val }}", mapping)
        assert result == "${{ steps.other.outputs.val }}"

    def test_preserves_folded_scalar(self):
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        value = FoldedScalarString("${{ steps.build.outputs.url }}")
        result = mod.rewrite_step_output_refs(value, mapping)
        assert isinstance(result, FoldedScalarString)
        assert str(result) == "${{ steps.build--internal.outputs.url }}"

    def test_preserves_literal_scalar(self):
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        value = LiteralScalarString("${{ steps.build.outputs.url }}")
        result = mod.rewrite_step_output_refs(value, mapping)
        assert isinstance(result, LiteralScalarString)

    def test_preserves_single_quoted_scalar(self):
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        value = SingleQuotedScalarString("${{ steps.build.outputs.url }}")
        result = mod.rewrite_step_output_refs(value, mapping)
        assert isinstance(result, SingleQuotedScalarString)

    def test_rewrites_embedded_ref_in_complex_expression(self):
        """Step refs inside complex expressions are rewritten."""
        mapping = {"steps.build.outputs.url": "steps.build--internal.outputs.url"}
        result = mod.rewrite_step_output_refs(
            "${{ inputs.flag == 'true' && steps.build.outputs.url || '' }}",
            mapping,
        )
        assert (
            result
            == "${{ inputs.flag == 'true' && steps.build--internal.outputs.url || '' }}"
        )

    def test_multiple_refs_in_one_string(self):
        mapping = {
            "steps.build.outputs.url": "steps.build--s.outputs.url",
            "steps.build.outputs.checksum": "steps.build--s.outputs.checksum",
        }
        result = mod.rewrite_step_output_refs(
            "${{ steps.build.outputs.url }} ${{ steps.build.outputs.checksum }}",
            mapping,
        )
        assert (
            result
            == "${{ steps.build--s.outputs.url }} ${{ steps.build--s.outputs.checksum }}"
        )


# ---------------------------------------------------------------------------
# rewrite_step_output_refs_in_value
# ---------------------------------------------------------------------------


class TestRewriteStepOutputRefsInValue:
    def _mapping(self):
        return {"steps.build.outputs.url": "steps.build--s.outputs.url"}

    def test_string(self):
        result = mod.rewrite_step_output_refs_in_value(
            "${{ steps.build.outputs.url }}", self._mapping()
        )
        assert result == "${{ steps.build--s.outputs.url }}"

    def test_dict(self):
        result = mod.rewrite_step_output_refs_in_value(
            {"env": "${{ steps.build.outputs.url }}"}, self._mapping()
        )
        assert result == {"env": "${{ steps.build--s.outputs.url }}"}

    def test_list(self):
        result = mod.rewrite_step_output_refs_in_value(
            ["${{ steps.build.outputs.url }}"], self._mapping()
        )
        assert result == ["${{ steps.build--s.outputs.url }}"]

    def test_non_string_passthrough(self):
        assert mod.rewrite_step_output_refs_in_value(42, self._mapping()) == 42
        assert mod.rewrite_step_output_refs_in_value(True, self._mapping()) is True


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

    def test_rewrites_output_refs_after_inlining(self, tmp_path):
        """Output references are rewritten to use mangled step IDs."""
        action_dir = tmp_path / "producer"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: producer
            outputs:
              url:
                value: ${{ steps.set-output.outputs.url }}
            runs:
              using: composite
              steps:
                - name: produce
                  id: set-output
                  run: echo "url=http://example.com" >> "$GITHUB_OUTPUT"
        """)
        )
        workflow = {
            "jobs": {
                "deploy": {
                    "steps": [
                        {
                            "name": "build",
                            "id": "build",
                            "uses": f"./{action_dir.relative_to(tmp_path)}",
                        },
                        {
                            "name": "use output",
                            "run": "echo ${{ steps.build.outputs.url }}",
                        },
                    ]
                }
            }
        }
        tracker = mod.RemoteActionTracker()
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.process_workflow(workflow, None, tracker)
        steps = result["jobs"]["deploy"]["steps"]
        # First step should have mangled ID
        assert steps[0]["id"] == "build--set-output"
        # Second step should have rewritten output reference
        assert steps[1]["run"] == "echo ${{ steps.build--set-output.outputs.url }}"

    def test_rewrites_job_level_outputs(self, tmp_path):
        """Job-level outputs referencing inlined step IDs are rewritten."""
        action_dir = tmp_path / "producer"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: producer
            outputs:
              url:
                value: ${{ steps.set-output.outputs.url }}
              checksum:
                value: ${{ steps.set-output.outputs.checksum }}
            runs:
              using: composite
              steps:
                - name: produce
                  id: set-output
                  run: echo "url=http://example.com" >> "$GITHUB_OUTPUT"
        """)
        )
        workflow = {
            "jobs": {
                "build": {
                    "outputs": {
                        "url": "${{ steps.build.outputs.url }}",
                        "checksum": "${{ steps.build.outputs.checksum }}",
                    },
                    "steps": [
                        {
                            "name": "build",
                            "id": "build",
                            "uses": f"./{action_dir.relative_to(tmp_path)}",
                        },
                    ],
                },
                "deploy": {
                    "needs": ["build"],
                    "steps": [
                        {
                            "name": "use output",
                            "run": "echo ${{ needs.build.outputs.url }}",
                        },
                    ],
                },
            }
        }
        tracker = mod.RemoteActionTracker()
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.process_workflow(workflow, None, tracker)
        # Job-level outputs should reference mangled step IDs
        job_outputs = result["jobs"]["build"]["outputs"]
        assert job_outputs["url"] == "${{ steps.build--set-output.outputs.url }}"
        assert (
            job_outputs["checksum"] == "${{ steps.build--set-output.outputs.checksum }}"
        )
        # needs references in the other job should be left untouched
        deploy_step = result["jobs"]["deploy"]["steps"][0]
        assert deploy_step["run"] == "echo ${{ needs.build.outputs.url }}"

    def test_rewrites_internal_output_names_in_job_outputs(self, tmp_path):
        """Job outputs referencing internal output names (not declared names) are rewritten."""
        action_dir = tmp_path / "producer"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: producer
            outputs:
              image_tags:
                value: ${{ steps.meta.outputs.tags }}
            runs:
              using: composite
              steps:
                - name: set metadata
                  id: meta
                  run: echo "tags=sha-abc" >> "$GITHUB_OUTPUT"
        """)
        )
        workflow = {
            "jobs": {
                "build": {
                    "outputs": {
                        "image-tags": "${{ steps.build-image.outputs.tags }}",
                    },
                    "steps": [
                        {
                            "name": "build image",
                            "id": "build-image",
                            "uses": f"./{action_dir.relative_to(tmp_path)}",
                        },
                    ],
                },
                "deploy": {
                    "needs": ["build"],
                    "steps": [
                        {
                            "name": "deploy",
                            "run": "echo ${{ needs.build.outputs.image-tags }}",
                        },
                    ],
                },
            }
        }
        tracker = mod.RemoteActionTracker()
        with patch("inline_actions.Path.cwd", return_value=tmp_path):
            result = mod.process_workflow(workflow, None, tracker)
        # Job output should be rewritten using internal name mapping
        job_outputs = result["jobs"]["build"]["outputs"]
        assert (
            job_outputs["image-tags"] == "${{ steps.build-image--meta.outputs.tags }}"
        )
        # needs references should be untouched
        deploy_step = result["jobs"]["deploy"]["steps"][0]
        assert deploy_step["run"] == "echo ${{ needs.build.outputs.image-tags }}"


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

    def test_frozen_uses_locked_revision(self, tmp_path):
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = action_dir
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "locked_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1", resolver, tracker, locked_entries=locked
        )
        assert result is not None
        # Resolver should be called with the locked revision
        resolver.resolve.assert_called_once_with(
            "https://github.com/owner/repo", "", "v1", "locked_sha"
        )
        # Tracker should record the locked revision
        assert tracker.entries["github.com/owner/repo@v1"]["revision"] == "locked_sha"

    def test_frozen_missing_entry_exits(self):
        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()
        locked = {}  # empty lock file
        with pytest.raises(SystemExit) as exc_info:
            mod.resolve_remote_action(
                "https://github.com/owner/repo@v1",
                resolver,
                tracker,
                locked_entries=locked,
            )
        assert exc_info.value.code == 1

    def test_frozen_missing_revision_exits(self):
        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()
        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": "path",
            }
        }
        with pytest.raises(SystemExit) as exc_info:
            mod.resolve_remote_action(
                "https://github.com/owner/repo@v1",
                resolver,
                tracker,
                locked_entries=locked,
            )
        assert exc_info.value.code == 1

    def test_records_fresh_revision(self, tmp_path):
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = action_dir
        resolver.get_head_revision.return_value = "fresh_sha_abc"
        tracker = mod.RemoteActionTracker()

        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1", resolver, tracker
        )
        assert result is not None
        assert (
            tracker.entries["github.com/owner/repo@v1"]["revision"] == "fresh_sha_abc"
        )

    def test_fresh_revision_none_exits(self, tmp_path):
        """When get_head_revision returns None the lock file would lack a
        revision, breaking a later --frozen run.  The code must abort."""
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        (action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = action_dir
        resolver.get_head_revision.return_value = None
        tracker = mod.RemoteActionTracker()

        with pytest.raises(SystemExit) as exc_info:
            mod.resolve_remote_action(
                "https://github.com/owner/repo@v1", resolver, tracker
            )
        assert exc_info.value.code == 1

    def test_frozen_uses_vendored_path(self, tmp_path):
        vendored_dir = (
            tmp_path / ".github" / "inline-actions" / "github.com" / "owner" / "repo@v1"
        )
        vendored_dir.mkdir(parents=True)
        (vendored_dir / "action.yml").write_text("name: test\n")
        (vendored_dir / ".inline-actions-revision").write_text("locked_sha\n")

        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "locked_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / ".github" / "inline-actions"),
            locked_entries=locked,
        )
        assert result is not None
        assert result[0] == vendored_dir
        resolver.resolve.assert_not_called()
        assert tracker.entries["github.com/owner/repo@v1"]["revision"] == "locked_sha"

    def test_frozen_uses_vendored_path_with_subpath(self, tmp_path):
        vendored_base = (
            tmp_path / ".github" / "inline-actions" / "github.com" / "owner" / "repo@v1"
        )
        vendored_base.mkdir(parents=True)
        (vendored_base / ".inline-actions-revision").write_text("locked_sha\n")
        subpath_dir = vendored_base / "actions" / "my-action"
        subpath_dir.mkdir(parents=True)
        (subpath_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "locked_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo/actions/my-action@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / ".github" / "inline-actions"),
            locked_entries=locked,
        )
        assert result is not None
        assert result[0] == subpath_dir
        resolver.resolve.assert_not_called()

    def test_frozen_falls_back_when_not_vendored(self, tmp_path):
        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = fake_action_dir
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "locked_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / "nonexistent"),
            locked_entries=locked,
        )
        assert result is not None
        resolver.resolve.assert_called_once()

    def test_frozen_falls_back_when_revision_mismatch(self, tmp_path):
        vendored_dir = (
            tmp_path / ".github" / "inline-actions" / "github.com" / "owner" / "repo@v1"
        )
        vendored_dir.mkdir(parents=True)
        (vendored_dir / "action.yml").write_text("name: test\n")
        (vendored_dir / ".inline-actions-revision").write_text("old_sha\n")

        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = fake_action_dir
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "new_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / ".github" / "inline-actions"),
            locked_entries=locked,
        )
        assert result is not None
        resolver.resolve.assert_called_once()

    def test_frozen_falls_back_when_no_marker(self, tmp_path):
        vendored_dir = (
            tmp_path / ".github" / "inline-actions" / "github.com" / "owner" / "repo@v1"
        )
        vendored_dir.mkdir(parents=True)
        (vendored_dir / "action.yml").write_text("name: test\n")
        # No .inline-actions-revision file written

        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = fake_action_dir
        tracker = mod.RemoteActionTracker()

        locked = {
            "github.com/owner/repo@v1": {
                "url": "https://github.com/owner/repo",
                "ref": "v1",
                "checkout_path": ".github/inline-actions/github.com/owner/repo@v1",
                "revision": "locked_sha",
            }
        }
        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / ".github" / "inline-actions"),
            locked_entries=locked,
        )
        assert result is not None
        resolver.resolve.assert_called_once()

    def test_non_frozen_ignores_vendored_path(self, tmp_path):
        vendored_dir = (
            tmp_path / ".github" / "inline-actions" / "github.com" / "owner" / "repo@v1"
        )
        vendored_dir.mkdir(parents=True)
        (vendored_dir / "action.yml").write_text("name: test\n")
        (vendored_dir / ".inline-actions-revision").write_text("some_sha\n")

        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text("name: test\n")

        resolver = MagicMock()
        resolver.resolve.return_value = fake_action_dir
        resolver.get_head_revision.return_value = "fresh_sha"
        tracker = mod.RemoteActionTracker()

        result = mod.resolve_remote_action(
            "https://github.com/owner/repo@v1",
            resolver,
            tracker,
            inline_actions_dir=str(tmp_path / ".github" / "inline-actions"),
            locked_entries=None,
        )
        assert result is not None
        resolver.resolve.assert_called_once()


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

    def test_includes_revision(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", "p1", "abc123def456")

        mod.write_metadata(output_dir, tracker)

        metadata_file = tmp_path / ".github" / "inline-actions" / "actions.yaml"
        y = YAML()
        data = y.load(metadata_file)
        assert data["github.com/a/b@v1"]["revision"] == "abc123def456"


# ---------------------------------------------------------------------------
# load_lock_file
# ---------------------------------------------------------------------------


class TestLoadLockFile:
    def test_loads_existing(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        inline_dir = tmp_path / ".github" / "inline-actions"
        inline_dir.mkdir(parents=True)
        (inline_dir / "actions.yaml").write_text(
            textwrap.dedent("""\
            github.com/a/b@v1:
              url: https://github.com/a/b
              ref: v1
              checkout_path: .github/inline-actions/github.com/a/b@v1
              revision: abc123
        """)
        )
        entries = mod.load_lock_file(output_dir)
        assert "github.com/a/b@v1" in entries
        assert entries["github.com/a/b@v1"]["revision"] == "abc123"

    def test_returns_empty_when_missing(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        assert mod.load_lock_file(output_dir) == {}

    def test_returns_empty_for_empty_file(self, tmp_path):
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        inline_dir = tmp_path / ".github" / "inline-actions"
        inline_dir.mkdir(parents=True)
        (inline_dir / "actions.yaml").write_text("")
        assert mod.load_lock_file(output_dir) == {}


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

    def test_resolve_passes_revision(self, tmp_path):
        """When revision is given, it is forwarded to _ensure_cloned."""
        clone_dir = tmp_path / "clone"
        clone_dir.mkdir()
        (clone_dir / "action.yml").write_text("name: test\n")

        resolver = mod.GitActionResolver(tmp_path)
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        result = resolver.resolve("https://github.com/a/b", "", "v1", "abc123")
        assert result == clone_dir

    def test_get_head_revision_returns_none_for_unknown(self):
        resolver = mod.GitActionResolver(Path("/tmp"))
        assert resolver.get_head_revision("https://github.com/a/b", "v1") is None


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

    def test_writes_revision_marker(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clone_dir = tmp_path / "cache" / "clone"
        clone_dir.mkdir(parents=True)
        (clone_dir / "action.yml").write_text("name: test\n")
        (clone_dir / ".git").mkdir()
        (clone_dir / ".git" / "config").write_text("gitconfig\n")

        resolver = mod.GitActionResolver(tmp_path / "cache")
        resolver._cloned[("https://github.com/a/b", "v1")] = clone_dir

        tracker = mod.RemoteActionTracker()
        tracker.record(
            "https://github.com/a/b", "v1", str(tmp_path / "vendor" / "a"), "abc123"
        )

        mod.vendor_actions(resolver, tracker)

        marker = tmp_path / "vendor" / "a" / ".inline-actions-revision"
        assert marker.read_text() == "abc123\n"

    def test_already_vendored_no_clone_skips_silently(self, tmp_path, capsys):
        checkout_path = tmp_path / "vendor" / "a"
        checkout_path.mkdir(parents=True)
        (checkout_path / "action.yml").write_text("name: test\n")

        resolver = mod.GitActionResolver(tmp_path / "cache")
        # No entries in _cloned

        tracker = mod.RemoteActionTracker()
        tracker.record("https://github.com/a/b", "v1", str(checkout_path))

        mod.vendor_actions(resolver, tracker)

        assert "warning" not in capsys.readouterr().err


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

    def test_end_to_end_remote_records_revision(self, tmp_path):
        """Non-frozen mode must record a fresh revision in the lock file."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)

        # Create a workflow that references a remote action
        (source_dir / "ci.yaml").write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - name: my-step
                    uses: https://github.com/owner/repo@v1
        """)
        )

        # Create a fake action directory for the mock resolver
        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: test
            runs:
              using: composite
              steps:
                - name: hello
                  run: echo hello
        """)
        )

        with patch("inline_actions.GitActionResolver") as MockResolver:
            mock_instance = MockResolver.return_value
            mock_instance.resolve.return_value = fake_action_dir
            mock_instance.get_head_revision.return_value = "fresh_sha_999"

            mod.main(
                [
                    "--source-dir",
                    str(source_dir),
                    "--output-dir",
                    str(output_dir),
                    "--no-vendor",
                ]
            )

        # Verify the output actions.yaml contains a revision
        lock_file = tmp_path / ".github" / "inline-actions" / "actions.yaml"
        assert lock_file.exists()
        y = YAML()
        data = y.load(lock_file)
        assert data["github.com/owner/repo@v1"]["revision"] == "fresh_sha_999"

    def test_frozen_end_to_end_preserves_revision(self, tmp_path):
        """In frozen mode, the output actions.yaml must contain the locked revision."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)

        # Create a lock file with a specific revision
        inline_dir = tmp_path / ".github" / "inline-actions"
        inline_dir.mkdir(parents=True)
        (inline_dir / "actions.yaml").write_text(
            textwrap.dedent("""\
            github.com/owner/repo@v1:
              url: https://github.com/owner/repo
              ref: v1
              checkout_path: .github/inline-actions/github.com/owner/repo@v1
              revision: abc123deadbeef
        """)
        )

        # Create a workflow that references the remote action
        (source_dir / "ci.yaml").write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - name: my-step
                    uses: https://github.com/owner/repo@v1
        """)
        )

        # Create a fake action directory for the mock resolver
        fake_action_dir = tmp_path / "fake-clone"
        fake_action_dir.mkdir()
        (fake_action_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: test
            runs:
              using: composite
              steps:
                - name: hello
                  run: echo hello
        """)
        )

        with patch("inline_actions.GitActionResolver") as MockResolver:
            mock_instance = MockResolver.return_value
            mock_instance.resolve.return_value = fake_action_dir

            mod.main(
                [
                    "--source-dir",
                    str(source_dir),
                    "--output-dir",
                    str(output_dir),
                    "--frozen",
                    "--no-vendor",
                ]
            )

            # Verify the resolver was called with the locked revision
            mock_instance.resolve.assert_called_once()
            call_args = mock_instance.resolve.call_args
            assert call_args[0][3] == "abc123deadbeef"  # revision argument

        # Verify the output actions.yaml preserves the revision
        output_lock = inline_dir / "actions.yaml"
        assert output_lock.exists()
        y = YAML()
        data = y.load(output_lock)
        assert data["github.com/owner/repo@v1"]["revision"] == "abc123deadbeef"

    def test_frozen_without_lock_file_succeeds_no_remote(self, tmp_path):
        """--frozen with no lock file is fine when no remote actions are used."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "ci.yaml").write_text("name: CI\non: push\njobs: {}\n")
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)

        # Should not raise
        mod.main(
            [
                "--source-dir",
                str(source_dir),
                "--output-dir",
                str(output_dir),
                "--frozen",
            ]
        )

    def test_frozen_with_empty_lock_file_succeeds_no_remote(self, tmp_path):
        """--frozen with empty lock file is fine when no remote actions are used."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "ci.yaml").write_text("name: CI\non: push\njobs: {}\n")
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        inline_dir = tmp_path / ".github" / "inline-actions"
        inline_dir.mkdir(parents=True)
        (inline_dir / "actions.yaml").write_text("")

        # Should not raise
        mod.main(
            [
                "--source-dir",
                str(source_dir),
                "--output-dir",
                str(output_dir),
                "--frozen",
            ]
        )

    def test_frozen_without_lock_file_exits_with_remote(self, tmp_path, capsys):
        """--frozen without lock file must fail when a remote action is referenced."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "ci.yaml").write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - name: remote
                    uses: https://github.com/owner/repo@v1
        """)
        )
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)

        with patch("inline_actions.GitActionResolver"):
            with pytest.raises(SystemExit) as exc_info:
                mod.main(
                    [
                        "--source-dir",
                        str(source_dir),
                        "--output-dir",
                        str(output_dir),
                        "--frozen",
                    ]
                )
            assert exc_info.value.code == 1
            assert "not found in lock file" in capsys.readouterr().err

    def test_frozen_end_to_end_uses_vendored_no_clone(self, tmp_path):
        """In frozen mode, if vendored sources are present with a matching
        revision marker, no git clone should be performed at all."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        output_dir = tmp_path / ".github" / "workflows"
        output_dir.mkdir(parents=True)
        inline_dir = tmp_path / ".github" / "inline-actions"
        inline_dir.mkdir(parents=True)

        # Write the lock file
        (inline_dir / "actions.yaml").write_text(
            textwrap.dedent("""\
            github.com/owner/repo@v1:
              url: https://github.com/owner/repo
              ref: v1
              checkout_path: .github/inline-actions/github.com/owner/repo@v1
              revision: abc123deadbeef
        """)
        )

        # Create the vendored action with a matching revision marker
        vendored_dir = inline_dir / "github.com" / "owner" / "repo@v1"
        vendored_dir.mkdir(parents=True)
        (vendored_dir / "action.yml").write_text(
            textwrap.dedent("""\
            name: test
            runs:
              using: composite
              steps:
                - name: hello
                  run: echo hello
        """)
        )
        (vendored_dir / ".inline-actions-revision").write_text("abc123deadbeef\n")

        # Create a workflow referencing the remote action
        (source_dir / "ci.yaml").write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - name: my-step
                    uses: https://github.com/owner/repo@v1
        """)
        )

        with (
            patch.object(mod.GitActionResolver, "_clone_at_revision") as mock_clone_rev,
            patch.object(mod.GitActionResolver, "_clone_at_ref") as mock_clone_ref,
        ):
            mod.main(
                [
                    "--source-dir",
                    str(source_dir),
                    "--output-dir",
                    str(output_dir),
                    "--frozen",
                ]
            )
            mock_clone_rev.assert_not_called()
            mock_clone_ref.assert_not_called()

        output_file = output_dir / "ci.yaml"
        assert output_file.exists()
        assert "echo hello" in output_file.read_text()
