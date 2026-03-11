# inline-actions

[![CI](https://github.com/eoscloud/inline-actions/actions/workflows/ci.yaml/badge.svg)](https://github.com/eoscloud/inline-actions/actions/workflows/ci.yaml)
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

## Installation

```bash
uv sync
```

## Usage

When run from the root of a consumer repo using the conventional directory layout, no arguments are needed:

```bash
uv run inline-actions
```

All arguments have sane defaults. Pass explicit values only when the conventional layout doesn't apply:

```bash
uv run inline-actions \
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
uv run inline-actions --git-ssh git.example.com
```

The option is repeatable — use multiple `--git-ssh` flags for different domains.

In both cases, the tool replaces each composite action step's `${{ inputs.X }}` with resolved values and `${{ env.GITHUB_ACTION_PATH }}` with the workspace-relative path.

### Metadata

When remote actions are used, the tool writes `.github/inline-actions/actions.yaml` alongside the generated workflows. This file acts as a lockfile: it records exactly which repositories at which versions must be checked out and where.

```yaml
github.com/tailscale/github-action@v3:
  url: https://github.com/tailscale/github-action
  ref: v3
  checkout_path: .github/inline-actions/github.com/tailscale/github-action@v3
github.com/tailscale/github-action@v2:
  url: https://github.com/tailscale/github-action
  ref: v2
  checkout_path: .github/inline-actions/github.com/tailscale/github-action@v2
```

The same repo may appear multiple times at different refs if different workflows pin to different versions. This metadata should be committed to the consumer repo and can be consumed by tooling to generate the required checkout steps.

## Expression Replacement

Only these patterns are replaced during inlining:

| Pattern | Replacement |
|---------|-------------|
| `${{ inputs.X }}` | Resolved from `with:` values or action input defaults |
| `${{ env.GITHUB_ACTION_PATH }}` | Workspace-relative path to the action directory |

All other expressions (`${{ github.* }}`, `${{ secrets.* }}`, `${{ steps.* }}`, etc.) are preserved as-is.

## Pre-commit Hook

This tool can be used as a [pre-commit](https://pre-commit.com/) hook in consumer repos.

Add to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/eoscloud/inline-actions
  rev: main  # or pin to a specific tag/commit
  hooks:
    - id: inline-actions
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

For workflows using local `uses: ./` references, the referenced actions must be present in the same repository.

## Development

This project was developed with AI assistance. Such assistance is reflected in the git history via `Co-Authored-By` commit trailers.

## Limitations

- **Nested composite actions** are not supported — only top-level composite action references are inlined
- **Step ID conflicts** are not automatically detected — ensure composite action step IDs don't conflict with workflow step IDs
