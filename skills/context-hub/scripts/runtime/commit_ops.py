from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def normalize_paths(repo_root: Path, paths: list[Path] | None = None) -> list[str]:
    repo_root = Path(repo_root).resolve()
    normalized: list[str] = []
    for raw_path in paths or []:
        try:
            relative = Path(raw_path).resolve().relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if relative and relative not in normalized:
            normalized.append(relative)
    return normalized


def has_changes(repo_root: Path, *, paths: list[Path] | None = None) -> bool:
    command = ["git", "status", "--short"]
    normalized_paths = normalize_paths(repo_root, paths)
    if normalized_paths:
        command.extend(["--", *normalized_paths])
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def auto_commit_and_push(
    repo_root: Path,
    *,
    message: str,
    push: bool = False,
    paths: list[Path] | None = None,
) -> bool:
    repo_root = Path(repo_root).resolve()
    if not is_git_repo(repo_root):
        return False
    normalized_paths = normalize_paths(repo_root, paths)
    if not has_changes(repo_root, paths=paths):
        return False

    if normalized_paths:
        subprocess.run(["git", "add", "--", *normalized_paths], cwd=str(repo_root), check=True)
    else:
        subprocess.run(["git", "add", "."], cwd=str(repo_root), check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(repo_root), check=True)
    if push:
        subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(repo_root), check=True)
    return True
