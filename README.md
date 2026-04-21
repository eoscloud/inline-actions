# inline-actions

[![CI](https://github.com/eoscloud/inline-actions/actions/workflows/ci.yaml/badge.svg)](https://github.com/eoscloud/inline-actions/actions/workflows/ci.yaml)
[![codecov](https://codecov.io/gh/eoscloud/inline-actions/graph/badge.svg)](https://codecov.io/gh/eoscloud/inline-actions)
[![pre-commit](https://github.com/eoscloud/inline-actions/actions/workflows/pre-commit.yaml/badge.svg)](https://github.com/eoscloud/inline-actions/actions/workflows/pre-commit.yaml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/eoscloud/inline-actions)](https://github.com/eoscloud/inline-actions/blob/main/LICENSE)

Statically inlines composite GitHub Actions into workflow files.

## Overview

**inline-actions** pre-processes workflow files by replacing `uses:` references to composite actions — both local paths and remote Git repository URLs — with the action's individual steps.

It exists as a workaround for a combination of long-standing bugs in Gitea and its ACT runner that cause composite action sub-steps to be invisible in the UI and their output to be hidden, making CI pipelines difficult to debug:

- [go-gitea/gitea#24604](https://github.com/go-gitea/gitea/issues/24604) — root cause: Gitea pre-parses workflow steps statically before execution, making composite action sub-steps structurally invisible to the UI
- [go-gitea/gitea#31397](https://github.com/go-gitea/gitea/issues/31397) — composite action steps show incorrect status (first step immediately "success", remaining steps "skip")
- [gitea/act_runner#567](https://gitea.com/gitea/act_runner/issues/567) — act_runner does not correctly track composite sub-step results
- [gitea/act_runner#809](https://gitea.com/gitea/act_runner/issues/809) — act_runner does not emit structured log markers needed for the Gitea UI to display composite sub-steps

## Directory Convention

In consumer repos:

| Directory | Purpose |
|-----------|---------|
| `.github/workflow-sources/` | Workflows written as if composite actions work natively (the "source of truth") |
| `.github/workflows/` | **Generated** output with composite actions inlined (committed to repo, used by runner) |

## Getting Started

Follow these steps to start using inline-actions in a repository:

1. **Create the source directory** for your workflow files:

   ```bash
   mkdir -p .github/workflow-sources
   ```

2. **Move your existing workflows** from `.github/workflows/` to `.github/workflow-sources/`, or write new ones there. These source files are the ones you edit — they can reference composite actions via `uses:` as usual.

3. **Run inline-actions** from the repository root to generate the output workflows:

   ```bash
   uvx --from git+https://github.com/eoscloud/inline-actions inline-actions
   ```

   This reads every `*.yml`/`*.yaml` file in `.github/workflow-sources/`, inlines any composite action references, and writes the result to `.github/workflows/`. If remote actions are used, a lock file (`.github/inline-actions/actions.yaml`) and vendored action sources are created as well.

4. **Commit the results** — the generated workflows, the lock file (if created), and the vendored action sources should all be committed:

   ```bash
   git add .github/workflows/ .github/inline-actions/
   git commit -m "chore: add inlined workflows"
   ```

5. **Set up the pre-commit hook** (optional but recommended) so workflows are re-generated automatically on commit. See [Pre-commit Hook](#pre-commit-hook) for details.

From here on, edit only the files in `.github/workflow-sources/` and let inline-actions regenerate `.github/workflows/`.

## Usage

`inline-actions` is published as a Python package and can be run directly via [`uvx`](https://docs.astral.sh/uv/guides/tools/) without installing it first:

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions
```

When run from the root of a consumer repo using the conventional directory layout, no arguments are needed. All arguments have sane defaults — pass explicit values only when the conventional layout doesn't apply:

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions \
  --source-dir /path/to/consumer/.github/workflow-sources \
  --output-dir /path/to/consumer/.github/workflows
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--source-dir DIR` | `.github/workflow-sources` | Directory containing workflow source files |
| `--output-dir DIR` | `.github/workflows` | Directory to write generated workflows |
| `--git-ssh DOMAIN` | | Use SSH (`git@host:path`) instead of HTTPS when cloning from this domain (repeatable) |
| `--git-cache-dir DIR` | temporary directory | Directory to cache cloned repos |
| `--no-vendor` | | Disable vendoring of remote action sources (see [Vendoring](#vendoring)) |
| `--frozen` | | Use exact revisions from the lock file instead of resolving refs (see [Lock File](#lock-file)) |

### Local Actions

`uses: ./path/to/action` references are resolved against the repository root (current working directory). The referenced action must be present in the same repository:

```yaml
- name: Build
  uses: ./.github/actions/build
  with:
    target: release
```

### Remote Actions

Given a workflow source with a remote URL-based action reference (Gitea/GitHub style):

```yaml
- name: connect to tailscale
  uses: https://github.com/tailscale/github-action@v3
  with:
    oauth-client-id: ${{ secrets.TAILSCALE_CLIENT_ID }}
    oauth-secret: ${{ secrets.TAILSCALE_SECRET }}
    tags: tag:ci
```

The tool clones the repo, reads the `action.yml`, and inlines the steps. The checkout path for `GITHUB_ACTION_PATH` replacement is derived automatically from the URL, including the ref so that different versions coexist:

```
https://github.com/tailscale/github-action@v3
  -> .github/inline-actions/github.com/tailscale/github-action@v3
```

If the Git server requires SSH authentication, add `--git-ssh DOMAIN` to clone via SSH for that domain:

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions --git-ssh git.example.com
```

The option is repeatable — use multiple `--git-ssh` flags for different domains.

In both cases, the tool replaces each composite action step's `${{ inputs.X }}` with resolved values and `${{ env.GITHUB_ACTION_PATH }}` with the workspace-relative path.

### Lock File

When remote actions are used, the tool writes `.github/inline-actions/actions.yaml` — the **lock file**. It records the exact repository URL, ref, checkout path, and the **pinned revision** (commit SHA) for every remote action:

```yaml
github.com/tailscale/github-action@v3:
  url: https://github.com/tailscale/github-action
  ref: v3
  checkout_path: .github/inline-actions/github.com/tailscale/github-action@v3
  revision: abc123def456789...
```

The same repo may appear multiple times at different refs if different workflows pin to different versions. The lock file should be committed to the consumer repo.

#### Frozen mode

Pass `--frozen` to use the **exact revision** recorded in the lock file instead of whatever the ref (e.g. `v3`) currently points to. This guarantees reproducible builds — the vendored code and generated workflows will be identical across runs, even if the upstream tag has moved.

When vendored action sources already exist at their expected checkout paths (under `.github/inline-actions/`) and their revision marker matches the locked revision, `--frozen` reuses them directly **without any network access**. This makes frozen mode safe to use in CI environments that lack Git credentials for remote repositories.

> **Important:** In frozen mode only the *existence* of the vendored directory and its revision marker are checked, not the actual file contents. If you manually modify vendored files without changing the revision marker, `--frozen` will silently use the modified versions. To restore correct vendored sources, run without `--frozen` to re-clone and re-vendor from the upstream repository.

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions --frozen
```

`--frozen` requires an existing lock file with `revision` entries for all remote actions. If an action is missing or has no revision, inline-actions exits with an error.

#### Updating revisions

To update the lock file with the latest commits that the refs point to, run **without** `--frozen`:

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions
```

This resolves each ref to its current commit SHA and writes the updated revisions to the lock file. Review the diff and commit the result.

### Vendoring

By default, inline-actions copies ("vendors") remote action sources into the repository at their expected checkout paths under `.github/inline-actions/`. This means the generated workflows work out of the box — no additional checkout steps are needed at CI time.

If you prefer not to vendor action sources (e.g. to keep the repository smaller), pass `--no-vendor`:

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions --no-vendor
```

When vendoring is disabled, inline-actions will print a notice listing each remote action, its URL, ref, and the path where it must be available at runtime. You are responsible for ensuring these repositories are checked out at the correct paths before the generated workflows run. The metadata file `.github/inline-actions/actions.yaml` contains this information in machine-readable form.

## Expression Replacement

Only these patterns are replaced during inlining:

| Pattern | Replacement |
|---------|-------------|
| `${{ inputs.X }}` | Resolved from `with:` values or action input defaults |
| `${{ env.GITHUB_ACTION_PATH }}` | Workspace-relative path to the action directory |

All other expressions (`${{ github.* }}`, `${{ secrets.* }}`, etc.) are preserved as-is.

## Step ID Mangling & Output Mapping

When a workflow step has an `id:` and uses a composite action, inline-actions mangles the internal step IDs to avoid collisions and rewrites output references so downstream steps can still access them.

### Step ID mangling

Internal step IDs are prefixed with `{workflow-step-id}--`:

```yaml
# Source workflow
- name: Build
  id: build
  uses: ./actions/producer

# If the action has a step with id: set-output, after inlining:
- name: build artifact
  id: build--set-output   # mangled
  shell: bash
  run: echo "url=..." >> "$GITHUB_OUTPUT"
```

Internal cross-references between steps within the same action are also updated to use the mangled IDs.

When the workflow step has no `id:`, internal step IDs are left unchanged (there are no output references to rewrite).

### Output mapping

The action's `outputs` section declares how internal step outputs map to action-level outputs:

```yaml
# action.yml
outputs:
  url:
    value: ${{ steps.set-output.outputs.url }}
```

After inlining, downstream references like `${{ steps.build.outputs.url }}` are rewritten to `${{ steps.build--set-output.outputs.url }}`, matching the mangled internal step ID. This happens automatically for all steps in the same job.

## Pre-commit Hook

This tool can be used as a [pre-commit](https://pre-commit.com/) hook in consumer repos.

The hook runs with `--frozen` by default, so it uses the exact revisions from the committed lock file rather than resolving refs to their latest commits. This ensures pre-commit runs are reproducible and don't silently pull in upstream changes.

Add to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/eoscloud/inline-actions
  rev: main  # or pin to a specific tag/commit
  hooks:
    - id: inline-actions
```

To ensure that there are no conflicts with possible other pre-commit hooks, also add follwing line on top to `.pre-commit-config.yaml`:

```yaml
exclude: ^\.github/inline-actions/
```

When using the conventional `.github/workflow-sources` → `.github/workflows` layout, no `args` are needed. Add them only as required:

```yaml
- repo: https://github.com/eoscloud/inline-actions
  rev: main
  hooks:
    - id: inline-actions
      args:
        - --git-ssh=git.example.com
```

To disable vendoring in the pre-commit hook:

```yaml
- repo: https://github.com/eoscloud/inline-actions
  rev: main
  hooks:
    - id: inline-actions
      args:
        - --no-vendor
```

To update the lock file with fresh revisions, run inline-actions directly (without `--frozen`):

```bash
uvx --from git+https://github.com/eoscloud/inline-actions inline-actions
```

Then commit the updated lock file and vendored sources.

For workflows using local `uses: ./` references, the referenced actions must be present in the same repository.

## Development

This project was developed with AI assistance. Such assistance is reflected in the git history via `Co-Authored-By` commit trailers.

### Running Tests

Unit tests:

```bash
uv run pytest
```

Integration tests:

```bash
uv run pytest integration-tests/ -v --no-cov
```

Integration test cases live under `integration-tests/`. Each subdirectory is a self-contained test case with the following structure:

```
integration-tests/<case-name>/
├── actions/              # local composite actions (optional)
├── workflow-sources/     # input workflow files
└── expected/
    └── workflows/        # expected output after inlining
```

The test runner discovers cases automatically, runs `inline-actions` from the case directory, and diffs the output against `expected/workflows/`.

To add a new test case, create a new subdirectory following this layout. Generate the expected output with:

```bash
cd integration-tests/<case-name>
uv run --project ../.. inline-actions --source-dir workflow-sources --output-dir expected/workflows
```

## Limitations

- **Nested composite actions** are not supported — only top-level composite action references are inlined
