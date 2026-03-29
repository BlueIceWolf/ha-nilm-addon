"""Resolve the running add-on version from repository metadata."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict


_VERSION_LINE = re.compile(r'^\s*version\s*:\s*["\']?([^"\']+)["\']?\s*$')


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git_root() -> Path | None:
    current = _repo_root()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _read_git_head(repo_root: Path) -> str | None:
    head_path = repo_root / ".git" / "HEAD"
    try:
        head_value = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if head_value.startswith("ref:"):
        ref_name = head_value.split(" ", 1)[1].strip()
        ref_path = repo_root / ".git" / Path(ref_name)
        try:
            return ref_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            packed_refs = repo_root / ".git" / "packed-refs"
            try:
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("^"):
                        continue
                    commit, _, ref = line.partition(" ")
                    if ref.strip() == ref_name:
                        return commit.strip() or None
            except OSError:
                return None
            return None

    return head_value or None


@lru_cache(maxsize=1)
def get_app_version() -> str:
    """Return the add-on version declared in the root config file."""
    config_path = _repo_root() / "config.yaml"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            match = _VERSION_LINE.match(line)
            if match:
                return match.group(1).strip()
    except OSError:
        pass
    return "dev"


@lru_cache(maxsize=1)
def get_build_info() -> Dict[str, str]:
    """Return release version and git metadata for the running build."""
    git_root = _git_root()
    commit = _read_git_head(git_root) if git_root else None
    commit = commit or "unknown"
    short_commit = commit[:8] if commit != "unknown" else commit
    return {
        "version": get_app_version(),
        "git_commit": commit,
        "git_short_commit": short_commit,
    }