"""Shared helpers for role workflows."""

from __future__ import annotations

from pathlib import Path

from runtime.validation import require_mutation_content_file, relative_path


ROLE_ALIASES = {
    "pm": "pm",
    "product": "pm",
    "ux": "design",
    "design": "design",
    "研发": "engineering",
    "engineering": "engineering",
    "qa": "qa",
}

ROLE_TARGET_DOCUMENTS = {
    "pm": "spec.md",
    "design": "design.md",
    "engineering": "architecture.md",
    "qa": "testing.md",
}


def _hub_path(hub_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return hub_root / path


def normalize_role(value: str) -> str:
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError("role 不能为空")
    normalized = ROLE_ALIASES.get(raw_value)
    if normalized is not None:
        return normalized
    normalized = ROLE_ALIASES.get(raw_value.lower())
    if normalized is not None:
        return normalized
    raise ValueError(f"unsupported role: {raw_value}")


def target_document_name(role: str) -> str:
    normalized_role = normalize_role(role)
    try:
        return ROLE_TARGET_DOCUMENTS[normalized_role]
    except KeyError as exc:
        raise ValueError(f"unsupported role: {role}") from exc


def build_workflow_result(
    hub_root: str | Path,
    *,
    role: str,
    target_file: str | Path,
    updated_paths: list[str | Path],
) -> dict:
    root = Path(hub_root)
    return {
        "role": normalize_role(role),
        "target_file": relative_path(Path(target_file), root),
        "updated_paths": [relative_path(Path(path), root) for path in updated_paths],
    }


def prepare_mutation_request(
    *,
    action: str,
    content_file: str | Path | None,
    target_file: str | Path,
    hub_root: str | Path,
) -> dict:
    normalized_action = str(action).strip().lower()
    resolved_content_file = require_mutation_content_file(normalized_action, content_file)
    root = Path(hub_root)
    return {
        "action": normalized_action,
        "content_file": None if resolved_content_file is None else _hub_path(root, resolved_content_file),
        "target_file": _hub_path(root, target_file),
        "hub_root": root,
    }
