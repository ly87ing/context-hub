"""Shared helpers for role workflows."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from runtime.validation import normalize_role, relative_path, require_mutation_content_file, target_document_name


def _hub_path(hub_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return hub_root / path


def _serialize_result_ref(value: str | Path, hub_root: Path) -> str:
    if isinstance(value, Path):
        return relative_path(value, hub_root)

    text = str(value)
    parsed = urlparse(text)
    if parsed.scheme and "://" in text:
        return text
    return relative_path(Path(text), hub_root)


def build_workflow_result(
    hub_root: str | Path,
    *,
    role: str,
    action: str,
    capability: str,
    target_file: str | Path,
    used_sources: list[str | Path] | None,
    live_status: str,
    updated_paths: list[str | Path],
    warnings: list[str] | None = None,
) -> dict:
    root = Path(hub_root)
    return {
        "role": normalize_role(role),
        "action": str(action).strip().lower(),
        "capability": str(capability).strip(),
        "target_file": _serialize_result_ref(target_file, root),
        "used_sources": [_serialize_result_ref(source, root) for source in (used_sources or [])],
        "live_status": str(live_status).strip(),
        "warnings": list(warnings or []),
        "updated_paths": [_serialize_result_ref(path, root) for path in updated_paths],
    }


def prepare_mutation_request(
    *,
    role: str,
    action: str,
    capability: str,
    content_file: str | Path | None,
    target_file: str | Path,
    hub_root: str | Path,
) -> dict:
    normalized_action = str(action).strip().lower()
    resolved_content_file = require_mutation_content_file(normalized_action, content_file)
    root = Path(hub_root)
    return {
        "role": normalize_role(role),
        "action": normalized_action,
        "capability": str(capability).strip(),
        "content_file": None if resolved_content_file is None else _hub_path(root, resolved_content_file),
        "target_file": _hub_path(root, target_file),
        "hub_root": root,
    }
