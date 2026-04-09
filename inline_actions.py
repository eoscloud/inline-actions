#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 eos GmbH
"""Inline composite GitHub Actions into workflow files.

Gitea ACT runner has a bug where composite action steps are hidden.
This tool statically inlines composite action steps into workflow files
so that each step is visible in the runner output.
"""

from __future__ import annotations

import argparse
import copy
import re
import shutil
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import (
    FoldedScalarString,
    LiteralScalarString,
    ScalarString,
)

DEFAULT_INLINE_ACTIONS_DIR = ".github/inline-actions"


def _make_yaml() -> YAML:
    """Create a YAML instance configured for round-trip handling."""
    y = YAML()
    y.preserve_quotes = True
    y.width = 120
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _strip_trailing_whitespace(text: str) -> str:
    """Remove trailing whitespace from each line in *text*."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


# ---------------------------------------------------------------------------
# Remote uses: parsing
# ---------------------------------------------------------------------------


def parse_remote_uses(uses: str) -> tuple[str, str, str] | None:
    """Parse a remote URL-based uses: reference.

    Supports:
      https://host/owner/repo/path@ref
      https://host/owner/repo@ref       (path is empty)

    Returns (repo_url, subpath, ref) or None if not a URL-based reference.
    """
    if not uses.startswith("https://"):
        return None

    # Split off @ref
    if "@" not in uses:
        return None
    url_part, ref = uses.rsplit("@", 1)

    parsed = urlparse(url_part)
    # path segments: /owner/repo[/subpath...]
    segments = [s for s in parsed.path.strip("/").split("/") if s]
    if len(segments) < 2:
        return None

    owner, repo = segments[0], segments[1]
    subpath = "/".join(segments[2:])
    repo_url = f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}"
    return repo_url, subpath, ref


def repo_url_to_identifier(repo_url: str, ref: str) -> str:
    """Derive a stable, versioned identifier from a repo URL and ref.

    https://git.example.com/org/ci-actions @ main
      -> git.example.com/org/ci-actions@main
    """
    parsed = urlparse(repo_url)
    base = f"{parsed.netloc}{parsed.path}".rstrip("/")
    return f"{base}@{ref}"


def https_to_ssh(repo_url: str) -> str:
    """Convert https://host/owner/repo to git@host:owner/repo.git."""
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if not path.endswith(".git"):
        path += ".git"
    return f"git@{parsed.netloc}:{path}"


# ---------------------------------------------------------------------------
# Git clone cache
# ---------------------------------------------------------------------------


class GitActionResolver:
    """Clones remote repos on demand and caches them in a temporary directory."""

    def __init__(self, cache_dir: Path, git_ssh_domains: set[str] | None = None):
        self._cache_dir = cache_dir
        self._git_ssh_domains = git_ssh_domains or set()
        # (repo_url, ref) -> local clone path
        self._cloned: dict[tuple[str, str], Path] = {}

    def resolve(
        self, repo_url: str, subpath: str, ref: str, revision: str | None = None
    ) -> Path | None:
        """Clone (if needed) and return the action directory on disk.

        When *revision* is given the clone is pinned to that exact commit
        instead of whatever the *ref* currently points to.
        """
        clone_dir = self._ensure_cloned(repo_url, ref, revision)
        action_dir = clone_dir / subpath if subpath else clone_dir
        for name in ("action.yml", "action.yaml"):
            if (action_dir / name).is_file():
                return action_dir
        print(
            f"  warning: no action.yml found at {subpath or '.'} in {repo_url}@{ref}",
            file=sys.stderr,
        )
        return None

    def get_head_revision(self, repo_url: str, ref: str) -> str | None:
        """Return the HEAD commit SHA for a previously-cloned repo."""
        key = (repo_url, ref)
        clone_dir = self._cloned.get(key)
        if clone_dir is None:
            return None
        result = subprocess.run(
            ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _ensure_cloned(
        self, repo_url: str, ref: str, revision: str | None = None
    ) -> Path:
        key = (repo_url, ref)
        if key in self._cloned:
            return self._cloned[key]

        host = urlparse(repo_url).netloc
        use_ssh = host in self._git_ssh_domains
        clone_url = https_to_ssh(repo_url) if use_ssh else repo_url
        # Use a stable directory name based on the repo URL and ref
        safe_name = re.sub(r"[^\w.-]", "_", f"{repo_url}_{ref}")
        clone_dir = self._cache_dir / safe_name

        if not clone_dir.exists():
            if revision:
                self._clone_at_revision(clone_url, clone_dir, revision)
            else:
                self._clone_at_ref(clone_url, clone_dir, ref)

        self._cloned[key] = clone_dir
        return clone_dir

    def _clone_at_ref(self, clone_url: str, clone_dir: Path, ref: str) -> None:
        print(f"  cloning {clone_url} (ref: {ref})...")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth=1",
                    f"--branch={ref}",
                    "--single-branch",
                    clone_url,
                    str(clone_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"error: git clone failed for {clone_url}@{ref}:\n{e.stderr}",
                file=sys.stderr,
            )
            sys.exit(1)

    def _clone_at_revision(
        self, clone_url: str, clone_dir: Path, revision: str
    ) -> None:
        print(f"  cloning {clone_url} (revision: {revision})...")
        try:
            clone_dir.mkdir(parents=True, exist_ok=True)
            for cmd in [
                ["git", "init", str(clone_dir)],
                [
                    "git",
                    "-C",
                    str(clone_dir),
                    "remote",
                    "add",
                    "origin",
                    clone_url,
                ],
                [
                    "git",
                    "-C",
                    str(clone_dir),
                    "fetch",
                    "--depth=1",
                    "origin",
                    revision,
                ],
                ["git", "-C", str(clone_dir), "checkout", "FETCH_HEAD"],
            ]:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                )
        except subprocess.CalledProcessError as e:
            print(
                f"error: git clone failed for {clone_url} at revision {revision}:\n{e.stderr}",
                file=sys.stderr,
            )
            sys.exit(1)


# ---------------------------------------------------------------------------
# Remote action tracking
# ---------------------------------------------------------------------------


class RemoteActionTracker:
    """Tracks remote actions used during inlining for metadata generation."""

    def __init__(self) -> None:
        # identifier (host/owner/repo@ref) -> {url, ref, checkout_path}
        self._entries: dict[str, dict[str, str]] = {}

    def record(
        self,
        repo_url: str,
        ref: str,
        checkout_path: str,
        revision: str | None = None,
    ) -> None:
        identifier = repo_url_to_identifier(repo_url, ref)
        entry: dict[str, str] = {
            "url": repo_url,
            "ref": ref,
            "checkout_path": checkout_path,
        }
        if revision is not None:
            entry["revision"] = revision
        self._entries[identifier] = entry

    @property
    def entries(self) -> dict[str, dict[str, str]]:
        return dict(self._entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inline composite actions into GitHub Actions workflow files.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(".github/workflow-sources"),
        help="Directory containing workflow source files (default: .github/workflow-sources)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".github/workflows"),
        help="Directory to write generated workflows (default: .github/workflows)",
    )
    parser.add_argument(
        "--git-ssh",
        action="append",
        default=[],
        metavar="DOMAIN",
        help=(
            "Use SSH (git@host:path) instead of HTTPS when cloning from "
            "this domain (repeatable). E.g. --git-ssh git.example.com"
        ),
    )
    parser.add_argument(
        "--git-cache-dir",
        type=Path,
        default=None,
        help=("Directory to cache cloned repos. Defaults to a temporary directory."),
    )
    parser.add_argument(
        "--no-vendor",
        action="store_true",
        default=False,
        help=(
            "Disable vendoring of remote action sources. When set, remote "
            "action sources will NOT be copied into the repository. You must "
            "ensure they are checked out at the expected paths before running "
            "the generated workflows."
        ),
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        default=False,
        help=(
            "Use exact revisions from the existing lock file instead of "
            "resolving refs to their current commits. Requires revision "
            "entries in the lock file for all remote actions used. "
            "An empty or missing lock file is allowed when no remote "
            "actions are referenced. "
            "Run without --frozen to update revisions."
        ),
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Action resolution (local + remote)
# ---------------------------------------------------------------------------


def resolve_action_dir(uses: str) -> tuple[Path, str] | None:
    """Resolve a local `uses:` value to (action_dir_on_disk, workspace_relative_path).

    Resolves `uses: ./path` against the current working directory (repo root).
    Returns None if the uses value is not a local composite action reference.
    """
    if not uses.startswith("./"):
        return None

    rel_path = uses.removeprefix("./")
    action_dir = Path.cwd() / rel_path
    for name in ("action.yml", "action.yaml"):
        if (action_dir / name).is_file():
            return action_dir, rel_path

    return None


def resolve_remote_action(
    uses: str,
    git_resolver: GitActionResolver,
    tracker: RemoteActionTracker,
    inline_actions_dir: str = DEFAULT_INLINE_ACTIONS_DIR,
    locked_entries: dict[str, dict[str, str]] | None = None,
) -> tuple[Path, str] | None:
    """Resolve a URL-based `uses:` to (action_dir_on_disk, workspace_relative_path).

    When *locked_entries* is provided (``--frozen`` mode), the clone is pinned
    to the exact revision recorded in the lock file.

    Returns None if the uses value is not a remote URL reference or
    if it cannot be resolved.
    """
    parsed = parse_remote_uses(str(uses))
    if parsed is None:
        return None

    repo_url, subpath, ref = parsed
    identifier = repo_url_to_identifier(repo_url, ref)

    # Determine revision: locked or fresh
    revision = None
    if locked_entries is not None:
        locked = locked_entries.get(identifier)
        if locked is None:
            print(
                f"error: {identifier} not found in lock file "
                f"(--frozen requires all remote actions to be locked). "
                f"Run without --frozen to update the lock file.",
                file=sys.stderr,
            )
            sys.exit(1)
        revision = locked.get("revision")
        if revision is None:
            print(
                f"error: {identifier} has no revision in lock file. "
                f"Run without --frozen to update the lock file.",
                file=sys.stderr,
            )
            sys.exit(1)

    action_dir = git_resolver.resolve(repo_url, subpath, ref, revision)
    if action_dir is None:
        return None

    # If not frozen, resolve the fresh revision from the clone
    if revision is None:
        revision = git_resolver.get_head_revision(repo_url, ref)
        if revision is None:
            print(
                f"error: failed to determine revision for {identifier}. "
                f"The lock file would be incomplete.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Derive workspace-relative checkout path from repo URL + ref
    checkout_base = f"{inline_actions_dir}/{identifier}"
    workspace_path = f"{checkout_base}/{subpath}" if subpath else checkout_base

    tracker.record(repo_url, ref, checkout_base, revision)

    return action_dir, workspace_path


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def load_action(action_dir: Path) -> dict:
    """Load and parse an action.yml from the given directory."""
    y = _make_yaml()
    for name in ("action.yml", "action.yaml"):
        path = action_dir / name
        if path.is_file():
            with open(path) as f:
                return y.load(f)
    raise FileNotFoundError(f"No action.yml found in {action_dir}")


def resolve_inputs(action: dict, with_values: dict | None) -> dict[str, str]:
    """Merge caller-provided `with:` values with action input defaults."""
    inputs_def = action.get("inputs") or {}
    with_values = with_values or {}
    resolved: dict[str, str] = {}

    for name, spec in inputs_def.items():
        if name in with_values:
            resolved[name] = str(with_values[name])
        elif isinstance(spec, dict) and "default" in spec:
            resolved[name] = str(spec["default"])

    return resolved


def replace_expressions(value: str, inputs: dict[str, str], action_path: str) -> str:
    """Replace ${{ inputs.X }} and ${{ env.GITHUB_ACTION_PATH }} in a string.

    Preserves ruamel.yaml scalar string types (FoldedScalarString, etc.).
    """
    original_type = type(value)

    def replace_input(match: re.Match) -> str:
        name = match.group(1)
        return inputs.get(name, match.group(0))

    result = re.sub(r"\$\{\{\s*inputs\.(\w+)\s*\}\}", replace_input, str(value))
    result = re.sub(
        r"\$\{\{\s*env\.GITHUB_ACTION_PATH\s*\}\}",
        action_path,
        result,
    )

    # Pass 2: replace bare inputs.X / env.GITHUB_ACTION_PATH inside complex
    # expressions (e.g. ${{ inputs.x == 'true' && inputs.y || '' }}).
    action_path_expr = _value_to_expr(action_path)

    def _replace_expr_block(block_match: re.Match) -> str:
        block = block_match.group(0)

        def _replace_bare_input(m: re.Match) -> str:
            name = m.group(1)
            if name in inputs:
                return _value_to_expr(inputs[name])
            return m.group(0)

        block = _BARE_INPUT_RE.sub(_replace_bare_input, block)
        block = _BARE_GITHUB_ACTION_PATH_RE.sub(action_path_expr, block)
        return block

    result = re.sub(r"\$\{\{.*?\}\}", _replace_expr_block, result)

    # Preserve the scalar string style from ruamel.yaml
    if isinstance(value, FoldedScalarString):
        return FoldedScalarString(result)
    if isinstance(value, LiteralScalarString):
        return LiteralScalarString(result)
    if isinstance(value, ScalarString):
        return original_type(result)
    return result


def replace_expressions_in_value(value, inputs: dict[str, str], action_path: str):
    """Recursively replace expressions in a YAML value (str, dict, list)."""
    if isinstance(value, str):
        return replace_expressions(value, inputs, action_path)
    if isinstance(value, dict):
        return {
            k: replace_expressions_in_value(v, inputs, action_path)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            replace_expressions_in_value(item, inputs, action_path) for item in value
        ]
    return value


# ---------------------------------------------------------------------------
# Step ID mangling & output mapping
# ---------------------------------------------------------------------------

# Pattern matching bare inputs.X references (for complex expressions)
_BARE_INPUT_RE = re.compile(r"inputs\.(\w+)")

# Pattern matching bare env.GITHUB_ACTION_PATH references (for complex expressions)
_BARE_GITHUB_ACTION_PATH_RE = re.compile(r"env\.GITHUB_ACTION_PATH")


def _value_to_expr(value: str) -> str:
    """Convert a resolved input value to its GitHub Actions expression-context form.

    If the value is a pure expression like ``${{ expr }}``, return the inner
    ``expr``.  Otherwise return the value as a single-quoted string literal,
    escaping embedded single quotes by doubling them (GHA expression syntax).
    """
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", value)
    if m:
        return m.group(1)
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


# Pattern matching ${{ steps.X.outputs.Y }} expressions (standalone only)
_STEP_OUTPUT_RE = re.compile(
    r"\$\{\{\s*steps\.([a-zA-Z_][\w-]*)\.outputs\.([a-zA-Z_][\w-]*)\s*\}\}"
)

# Pattern matching steps.X.outputs.Y references anywhere (including inside
# complex expressions like ${{ cond && steps.X.outputs.Y || '' }})
_BARE_STEP_OUTPUT_RE = re.compile(
    r"steps\.([a-zA-Z_][\w-]*)\.outputs\.([a-zA-Z_][\w-]*)"
)


def parse_output_mapping(action: dict, workflow_step_id: str) -> dict[str, str]:
    """Build a mapping from workflow-level output refs to mangled internal refs.

    Given an action with outputs like:
        url: ${{ steps.set-output.outputs.url }}
    and workflow_step_id='build', returns:
        {"steps.build.outputs.url": "steps.build--set-output.outputs.url"}

    When the declared output name differs from the internal output name,
    an additional mapping is created for the internal name.  This handles
    runtimes (e.g. Gitea ACT) where composite action step outputs leak
    through under their original names.
    """
    outputs = action.get("outputs") or {}
    mapping: dict[str, str] = {}

    for output_name, spec in outputs.items():
        if not isinstance(spec, dict):
            continue
        value = spec.get("value", "")
        if not isinstance(value, str):
            continue
        m = _BARE_STEP_OUTPUT_RE.search(value)
        if m is None:
            print(
                f"  warning: cannot parse output expression for '{output_name}': {value}",
                file=sys.stderr,
            )
            continue
        internal_step_id = m.group(1)
        internal_output_name = m.group(2)
        # Map steps.{workflow_step_id}.outputs.{output_name}
        #   -> steps.{workflow_step_id}--{internal_step_id}.outputs.{internal_output_name}
        from_ref = f"steps.{workflow_step_id}.outputs.{output_name}"
        to_ref = f"steps.{workflow_step_id}--{internal_step_id}.outputs.{internal_output_name}"
        mapping[from_ref] = to_ref

        # Also map the internal output name when it differs from the declared
        # name, so references using the leaked internal name are rewritten too.
        if internal_output_name != output_name:
            internal_from_ref = (
                f"steps.{workflow_step_id}.outputs.{internal_output_name}"
            )
            if internal_from_ref not in mapping:
                mapping[internal_from_ref] = to_ref
            else:
                print(
                    f"  warning: conflicting internal output name "
                    f"'{internal_output_name}' for step '{workflow_step_id}' "
                    f"(already mapped by another output)",
                    file=sys.stderr,
                )

    return mapping


def mangle_step_ids(steps: list[dict], prefix: str) -> list[dict]:
    """Prefix all step IDs with ``{prefix}--`` and update internal cross-references."""
    # Collect original IDs that will be mangled
    original_ids: set[str] = set()
    for step in steps:
        step_id = step.get("id")
        if step_id:
            original_ids.add(str(step_id))

    # Build internal ref mapping: steps.X.outputs.Y -> steps.prefix--X.outputs.Y
    id_mapping: dict[str, str] = {}
    for oid in original_ids:
        id_mapping[oid] = f"{prefix}--{oid}"

    mangled: list[dict] = []
    for step in steps:
        new_step = dict(step)
        # Mangle the id field
        step_id = new_step.get("id")
        if step_id and str(step_id) in id_mapping:
            new_step["id"] = id_mapping[str(step_id)]

        # Rewrite internal cross-references in all values
        if id_mapping:
            for key in list(new_step.keys()):
                if key == "id":
                    continue
                new_step[key] = _rewrite_internal_refs_in_value(
                    new_step[key], id_mapping
                )

        mangled.append(new_step)

    return mangled


def _rewrite_internal_refs_in_value(value, id_mapping: dict[str, str]):
    """Rewrite ${{ steps.X.outputs.Y }} where X is in id_mapping."""
    if isinstance(value, str):
        return _rewrite_internal_refs(value, id_mapping)
    if isinstance(value, dict):
        return {
            k: _rewrite_internal_refs_in_value(v, id_mapping) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_internal_refs_in_value(item, id_mapping) for item in value]
    return value


def _rewrite_internal_refs(value: str, id_mapping: dict[str, str]) -> str:
    """Rewrite step output references in a string where the step ID is in id_mapping."""
    original_type = type(value)

    def replace_match(m: re.Match) -> str:
        step_id = m.group(1)
        if step_id in id_mapping:
            return m.group(0).replace(
                f"steps.{step_id}.outputs.", f"steps.{id_mapping[step_id]}.outputs."
            )
        return m.group(0)

    result = _BARE_STEP_OUTPUT_RE.sub(replace_match, str(value))

    if isinstance(value, FoldedScalarString):
        return FoldedScalarString(result)
    if isinstance(value, LiteralScalarString):
        return LiteralScalarString(result)
    if isinstance(value, ScalarString):
        return original_type(result)
    return result


def rewrite_step_output_refs(value: str, mapping: dict[str, str]) -> str:
    """Replace ${{ steps.X.outputs.Y }} using the output mapping.

    Preserves ruamel.yaml scalar string types.
    """
    original_type = type(value)

    def replace_match(m: re.Match) -> str:
        ref = f"steps.{m.group(1)}.outputs.{m.group(2)}"
        if ref in mapping:
            return m.group(0).replace(ref, mapping[ref])
        return m.group(0)

    result = _BARE_STEP_OUTPUT_RE.sub(replace_match, str(value))

    if isinstance(value, FoldedScalarString):
        return FoldedScalarString(result)
    if isinstance(value, LiteralScalarString):
        return LiteralScalarString(result)
    if isinstance(value, ScalarString):
        return original_type(result)
    return result


def rewrite_step_output_refs_in_value(value, mapping: dict[str, str]):
    """Recursively rewrite step output references in a YAML value."""
    if isinstance(value, str):
        return rewrite_step_output_refs(value, mapping)
    if isinstance(value, dict):
        return {
            k: rewrite_step_output_refs_in_value(v, mapping) for k, v in value.items()
        }
    if isinstance(value, list):
        return [rewrite_step_output_refs_in_value(item, mapping) for item in value]
    return value


# ---------------------------------------------------------------------------
# Inlining
# ---------------------------------------------------------------------------


def inline_composite_steps(
    action: dict, step: dict, workspace_rel_path: str
) -> tuple[list[dict], dict[str, str]]:
    """Expand a composite action's steps, replacing expressions.

    Returns (inlined_steps, output_mapping).
    """
    inputs = resolve_inputs(action, step.get("with"))
    action_steps = action.get("runs", {}).get("steps", [])
    inlined: list[dict] = []

    for action_step in action_steps:
        new_step = copy.deepcopy(action_step)
        for key in list(new_step.keys()):
            new_step[key] = replace_expressions_in_value(
                new_step[key],
                inputs,
                workspace_rel_path,
            )
        inlined.append(new_step)

    # Mangle step IDs and build output mapping if the workflow step has an id
    workflow_step_id = step.get("id")
    output_mapping: dict[str, str] = {}
    if workflow_step_id:
        workflow_step_id = str(workflow_step_id)
        inlined = mangle_step_ids(inlined, workflow_step_id)
        output_mapping = parse_output_mapping(action, workflow_step_id)

    return inlined, output_mapping


def inline_step(
    step: dict,
    git_resolver: GitActionResolver | None,
    tracker: RemoteActionTracker,
    inline_actions_dir: str = DEFAULT_INLINE_ACTIONS_DIR,
    locked_entries: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Inline a single step if it uses a composite action, else return as-is."""
    uses = step.get("uses")
    if not uses or not isinstance(uses, str):
        return [step], {}

    uses_str = str(uses)

    # Try local resolution first
    resolved = resolve_action_dir(uses_str)

    # Try remote resolution
    if resolved is None and git_resolver is not None:
        resolved = resolve_remote_action(
            uses_str, git_resolver, tracker, inline_actions_dir, locked_entries
        )

    if resolved is None:
        return [step], {}

    action_dir, workspace_rel_path = resolved
    action = load_action(action_dir)

    if action.get("runs", {}).get("using") != "composite":
        return [step], {}

    return inline_composite_steps(action, step, workspace_rel_path)


def process_workflow(
    workflow: dict,
    git_resolver: GitActionResolver | None,
    tracker: RemoteActionTracker,
    inline_actions_dir: str = DEFAULT_INLINE_ACTIONS_DIR,
    locked_entries: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Process a workflow, inlining all composite action references."""
    workflow = copy.deepcopy(workflow)
    jobs = workflow.get("jobs", {})

    for job_name, job in jobs.items():
        steps = job.get("steps", [])
        new_steps: list[dict] = []
        accumulated_mapping: dict[str, str] = {}

        # Phase 1: Inline all steps and accumulate output mappings
        for step in steps:
            inlined_steps, mapping = inline_step(
                step, git_resolver, tracker, inline_actions_dir, locked_entries
            )
            new_steps.extend(inlined_steps)
            accumulated_mapping.update(mapping)

        # Phase 2: Rewrite output references using accumulated mapping
        if accumulated_mapping:
            rewritten_steps: list[dict] = []
            for s in new_steps:
                rewritten = {}
                for key, val in s.items():
                    rewritten[key] = rewrite_step_output_refs_in_value(
                        val, accumulated_mapping
                    )
                rewritten_steps.append(rewritten)
            new_steps = rewritten_steps

        job["steps"] = new_steps

        # Phase 3: Rewrite job-level outputs that reference mangled step IDs
        job_outputs = job.get("outputs")
        if accumulated_mapping and job_outputs:
            job["outputs"] = {
                k: rewrite_step_output_refs_in_value(v, accumulated_mapping)
                for k, v in job_outputs.items()
            }

    return workflow


# ---------------------------------------------------------------------------
# Metadata / lock file
# ---------------------------------------------------------------------------


def load_lock_file(output_dir: Path) -> dict[str, dict[str, str]]:
    """Load the existing lock file (.github/inline-actions/actions.yaml).

    Returns a dict mapping identifier to entry, or an empty dict if the
    file does not exist.
    """
    inline_actions_dir = output_dir.parent / "inline-actions"
    lock_file = inline_actions_dir / "actions.yaml"
    if not lock_file.exists():
        return {}
    y = _make_yaml()
    with open(lock_file) as f:
        data = y.load(f)
    if data is None:
        return {}
    return {str(k): dict(v) for k, v in data.items()}


def write_metadata(output_dir: Path, tracker: RemoteActionTracker) -> None:
    """Write .github/inline-actions/actions.yaml with remote action metadata.

    This file acts as a lockfile: it records exactly which repositories
    at which refs must be checked out (and where) for the generated
    workflows to function at runtime.  The same repo may appear more
    than once if different workflows reference different versions.
    """
    entries = tracker.entries
    if not entries:
        return

    # Derive .github/inline-actions/ from .github/workflows/
    inline_actions_dir = output_dir.parent / "inline-actions"
    inline_actions_dir.mkdir(parents=True, exist_ok=True)

    metadata_file = inline_actions_dir / "actions.yaml"

    y = _make_yaml()
    buf = StringIO()
    y.dump(dict(sorted(entries.items())), buf)

    header = (
        "# Auto-generated by inline-actions. Do not edit manually.\n"
        "#\n"
        "# This file records which remote repositories at which versions\n"
        "# are used by inlined workflows.  Each entry must be checked out\n"
        "# at the listed checkout_path for the generated workflows to work.\n"
    )

    yaml_content = _strip_trailing_whitespace(buf.getvalue())

    with open(metadata_file, "w") as f:
        f.write(header)
        f.write(yaml_content)

    print(f"  metadata -> {metadata_file}")


# ---------------------------------------------------------------------------
# Vendoring
# ---------------------------------------------------------------------------


def vendor_actions(
    git_resolver: GitActionResolver, tracker: RemoteActionTracker
) -> None:
    """Copy cloned remote action sources into the repository.

    For each tracked remote action, copies the cloned source tree into
    the checkout_path recorded in the tracker, so that the generated
    workflows can reference these files at runtime without additional
    checkout steps.
    """
    entries = tracker.entries
    if not entries:
        return

    for identifier, entry in sorted(entries.items()):
        checkout_path = Path(entry["checkout_path"])
        repo_url = entry["url"]
        ref = entry["ref"]

        # Look up the clone directory from the resolver
        key = (repo_url, ref)
        clone_dir = git_resolver._cloned.get(key)
        if clone_dir is None:
            print(
                f"  warning: no cached clone for {identifier}, skipping vendor",
                file=sys.stderr,
            )
            continue

        # Remove existing vendored copy and replace with fresh one
        if checkout_path.exists():
            shutil.rmtree(checkout_path)
        checkout_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the clone, excluding the .git directory
        shutil.copytree(clone_dir, checkout_path, ignore=shutil.ignore_patterns(".git"))
        print(f"  vendored {identifier} -> {checkout_path}")


def print_no_vendor_notice(tracker: RemoteActionTracker) -> None:
    """Print information about required checkouts when vendoring is disabled."""
    entries = tracker.entries
    if not entries:
        return

    print()
    print(
        "WARNING: Vendoring is disabled (--no-vendor). The generated workflows "
        "reference remote action files that are NOT included in the repository."
    )
    print(
        "You must ensure the following repositories are checked out at the "
        "listed paths before the workflows run:"
    )
    print()
    for identifier, entry in sorted(entries.items()):
        print(f"  {identifier}")
        print(f"    url: {entry['url']}")
        print(f"    ref: {entry['ref']}")
        print(f"    path: {entry['checkout_path']}")
    print()
    print(
        "The metadata file .github/inline-actions/actions.yaml contains this "
        "information in machine-readable form."
    )


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def generate_header(source_rel_path: str) -> str:
    """Generate the auto-generated file header comment."""
    return (
        f"# NOTE: This file is auto-generated by inline-actions. "
        f"Do not edit manually.\n"
        f"# Source: {source_rel_path}\n"
    )


def process_file(
    source_file: Path,
    source_dir: Path,
    source_dir_rel: Path | str,
    output_dir: Path,
    git_resolver: GitActionResolver | None,
    tracker: RemoteActionTracker,
    inline_actions_dir: str = DEFAULT_INLINE_ACTIONS_DIR,
    locked_entries: dict[str, dict[str, str]] | None = None,
) -> None:
    """Process a single workflow file."""
    y = _make_yaml()

    with open(source_file) as f:
        workflow = y.load(f)

    if not isinstance(workflow, dict):
        print(
            f"  skipping {source_file.name}: not a valid workflow",
            file=sys.stderr,
        )
        return

    processed = process_workflow(
        workflow, git_resolver, tracker, inline_actions_dir, locked_entries
    )

    rel_path = source_file.relative_to(source_dir)
    source_ref = f"{source_dir_rel}/{rel_path}"
    header = generate_header(source_ref)

    output_file = output_dir / rel_path
    output_file.parent.mkdir(parents=True, exist_ok=True)

    buf = StringIO()
    y.dump(processed, buf)
    yaml_content = _strip_trailing_whitespace(buf.getvalue())

    with open(output_file, "w") as f:
        f.write(header)
        f.write(yaml_content)

    print(f"  {source_file.name} -> {output_file}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    source_dir: Path = args.source_dir
    output_dir: Path = args.output_dir

    try:
        source_dir_rel: Path | str = source_dir.resolve().relative_to(
            Path.cwd().resolve()
        )
    except ValueError:
        source_dir_rel = source_dir

    if not source_dir.is_dir():
        print(
            f"error: source directory does not exist: {source_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Set up git resolver (always available; clones on demand)
    cache_dir = args.git_cache_dir
    if cache_dir is None:
        cache_dir = Path(tempfile.mkdtemp(prefix="inline-actions-"))
    git_resolver = GitActionResolver(cache_dir, git_ssh_domains=set(args.git_ssh))
    tracker = RemoteActionTracker()

    source_files = sorted(source_dir.glob("*.yml")) + sorted(source_dir.glob("*.yaml"))
    if not source_files:
        print(
            f"warning: no workflow files found in {source_dir}",
            file=sys.stderr,
        )
        return

    # Derive inline-actions directory from output directory
    inline_actions_dir = str(output_dir.parent / "inline-actions")

    # Load lock file when --frozen
    locked_entries: dict[str, dict[str, str]] | None = None
    if args.frozen:
        locked_entries = load_lock_file(output_dir)

    print(f"Processing {len(source_files)} workflow(s):")
    for source_file in source_files:
        process_file(
            source_file,
            source_dir,
            source_dir_rel,
            output_dir,
            git_resolver,
            tracker,
            inline_actions_dir,
            locked_entries,
        )

    write_metadata(output_dir, tracker)

    if args.no_vendor:
        print_no_vendor_notice(tracker)
    else:
        vendor_actions(git_resolver, tracker)

    print("Done.")


if __name__ == "__main__":
    main()
