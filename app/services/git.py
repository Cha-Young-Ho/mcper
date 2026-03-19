"""Read local Git metadata for branch-based MCP prompts."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GitContext:
    """Snapshot of repo identity and branches."""

    repo_url: str
    current_branch: str
    default_base_branch: str


def _run_git(args: list[str], cwd: Path | None, timeout_sec: float = 5.0) -> str | None:
    """Run a git subcommand; return stripped stdout or None on failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def get_git_context(repo_root: Path | str | None = None) -> GitContext:
    """
    Extract remote URL, current branch, and configured default base branch.

    Uses ``GIT_DEFAULT_BASE_BRANCH`` (default ``main``) when the base cannot
    be inferred from the repo. Missing git binary or non-repo paths yield
    ``Unknown`` placeholders so callers can still render a prompt.
    """
    env_base = os.environ.get("GIT_DEFAULT_BASE_BRANCH", "main").strip() or "main"
    cwd: Path | None
    if repo_root is None:
        env_root = os.environ.get("GIT_REPO_ROOT")
        cwd = Path(env_root).resolve() if env_root else None
    else:
        cwd = Path(repo_root).resolve()

    repo_url = _run_git(["config", "--get", "remote.origin.url"], cwd) or "Unknown"
    current = _run_git(["branch", "--show-current"], cwd) or "Unknown"

    return GitContext(
        repo_url=repo_url,
        current_branch=current,
        default_base_branch=env_base,
    )
