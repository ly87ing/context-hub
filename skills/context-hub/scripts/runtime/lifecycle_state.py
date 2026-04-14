from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from _common import save_yaml_file, utc_now_iso

from .downstream_checklist import list_pending_downstream_roles, load_downstream_checklist
from .validation import relative_path, target_document_name


LIFECYCLE_STATE_FILENAME = "lifecycle-state.yaml"
ROLE_ORDER = ("pm", "design", "engineering", "qa")
ROLE_NEXT = {
    "pm": "design",
    "design": "engineering",
    "engineering": "qa",
    "qa": "maintenance",
}


def lifecycle_state_path(capability_dir: str | Path) -> Path:
    return Path(capability_dir) / LIFECYCLE_STATE_FILENAME


def load_lifecycle_state(capability_dir: str | Path) -> dict[str, object] | None:
    path = lifecycle_state_path(capability_dir)
    if not path.exists():
        return None
    from .validation import load_yaml_mapping

    return load_yaml_mapping(path)


def _normalize_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _load_semantic_payload(capability_dir: Path) -> dict[str, object] | None:
    path = capability_dir / "semantic-consistency.yaml"
    if not path.exists():
        return None
    from .validation import load_yaml_mapping

    return load_yaml_mapping(path)


def _semantic_blockers(capability_dir: Path) -> dict[str, list[str]]:
    payload = _load_semantic_payload(capability_dir)
    blockers: dict[str, list[str]] = {}
    if not payload:
        return blockers

    for raw_issue in payload.get("issues") or []:
        if not isinstance(raw_issue, dict):
            continue
        severity = str(raw_issue.get("severity") or "").strip().lower()
        suggested_role = str(raw_issue.get("suggested_role") or "").strip().lower()
        if not suggested_role or suggested_role not in ROLE_ORDER:
            continue
        if severity not in {"blocking", "error"}:
            continue
        blockers.setdefault(suggested_role, []).append(str(raw_issue.get("message") or "").strip())
    return blockers

def _role_updated_at(document_path: Path) -> str | None:
    if not document_path.exists():
        return None
    updated_at = datetime.fromtimestamp(document_path.stat().st_mtime, tz=timezone.utc)
    return updated_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_lifecycle_state_payload(
    hub_root: str | Path,
    *,
    capability: str,
    role: str,
    action: str,
    target_file: str | Path,
    live_status: str,
    warnings: list[str] | None = None,
    updated_paths: list[str | Path] | None = None,
) -> dict[str, object]:
    root = Path(hub_root).resolve()
    capability_name = str(capability).strip()
    capability_dir = root / "capabilities" / capability_name
    target_path = Path(target_file)
    previous_state = load_lifecycle_state(capability_dir) or {}

    checklist_payload = load_downstream_checklist(capability_dir)
    pending_roles = list_pending_downstream_roles(capability_dir, checklist_payload)
    semantic_blockers = _semantic_blockers(capability_dir)

    roles: dict[str, dict[str, object]] = {}
    pending_documents: list[str] = []
    blocking_reasons: list[str] = []

    for role_name in ROLE_ORDER:
        document_name = target_document_name(role_name)
        document_path = capability_dir / document_name
        role_blockers = _normalize_list(semantic_blockers.get(role_name))

        if not document_path.exists():
            status = "missing"
            pending_documents.append(document_name)
            blocking_reasons.append(document_name)
        elif role_name in pending_roles:
            status = "needs_align"
            pending_documents.append(document_name)
            blocking_reasons.append(document_name)
        elif role_blockers:
            status = "blocked"
            blocking_reasons.extend(role_blockers)
        else:
            status = "aligned"

        role_payload: dict[str, object] = {
            "document": document_name,
            "status": status,
        }
        if document_path.exists():
            role_payload["updated_at"] = _role_updated_at(document_path)
        if role_blockers:
            role_payload["blocking_issues"] = role_blockers
        roles[role_name] = role_payload

    normalized_role = str(role).strip().lower()
    next_role = None
    for role_name in ROLE_ORDER:
        role_status = str(roles[role_name]["status"])
        if role_status in {"missing", "needs_align", "blocked"}:
            next_role = role_name
            break
    if next_role is None:
        next_role = ROLE_NEXT.get(normalized_role, "maintenance")

    platform_status = "ready_for_review"
    if any(str(roles[role_name]["status"]) == "blocked" for role_name in ROLE_ORDER):
        platform_status = "blocked"
    elif pending_documents:
        platform_status = "in_progress"

    serialized_updates: list[str] = []
    for path in updated_paths or []:
        path_obj = Path(path)
        serialized_updates.append(
            relative_path(path_obj, root) if path_obj.is_absolute() else path_obj.as_posix()
        )

    return {
        "capability": capability_name,
        "current_role": normalized_role,
        "current_action": str(action).strip().lower(),
        "target_file": relative_path(target_path, root) if target_path.is_absolute() else target_path.as_posix(),
        "iteration_index": int(previous_state.get("iteration_index") or 0) + 1,
        "platform_status": platform_status,
        "roles": roles,
        "pending_roles": [role_name for role_name in ROLE_ORDER if str(roles[role_name]["status"]) == "needs_align"],
        "pending": _normalize_list(pending_documents),
        "blockers": _normalize_list(blocking_reasons),
        "next_role": next_role,
        "next_action": "audit" if next_role == "maintenance" else "align",
        "live_status": str(live_status).strip(),
        "warnings": list(warnings or []),
        "updated_paths": _normalize_list(serialized_updates),
        "updated_at": utc_now_iso(),
    }


def write_lifecycle_state(capability_dir: str | Path, payload: dict[str, object]) -> Path:
    path = lifecycle_state_path(capability_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_yaml_file(path, payload)
    return path


def refresh_lifecycle_state(
    hub_root: str | Path,
    *,
    capability: str,
    role: str,
    action: str,
    target_file: str | Path,
    live_status: str,
    warnings: list[str] | None = None,
    updated_paths: list[str | Path] | None = None,
) -> tuple[Path, dict[str, object]]:
    root = Path(hub_root).resolve()
    capability_dir = root / "capabilities" / capability
    payload = build_lifecycle_state_payload(
        root,
        capability=capability,
        role=role,
        action=action,
        target_file=target_file,
        live_status=live_status,
        warnings=warnings,
        updated_paths=updated_paths,
    )
    return write_lifecycle_state(capability_dir, payload), payload
