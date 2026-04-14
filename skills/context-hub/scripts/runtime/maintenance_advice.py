from __future__ import annotations

from pathlib import Path

from .downstream_checklist import list_pending_downstream_roles, load_downstream_checklist
from .validation import relative_path, target_document_name


def _issue_key(issue: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(issue.get("role") or "").strip(),
        str(issue.get("code") or "").strip(),
        str(issue.get("document") or "").strip(),
    )


def _append_unique(records: list[dict[str, object]], record: dict[str, object]) -> None:
    key = _issue_key(record)
    for existing in records:
        if _issue_key(existing) == key:
            return
    records.append(record)


def build_maintenance_advice(
    hub_root: str | Path,
    *,
    capability_dir: Path,
    lifecycle_payload: dict[str, object] | None,
    semantic_payload: dict[str, object] | None,
) -> dict[str, object]:
    root = Path(hub_root).resolve()
    checklist_payload = load_downstream_checklist(capability_dir)
    live_pending_roles = list_pending_downstream_roles(capability_dir, checklist_payload)
    if checklist_payload is not None:
        pending_roles = list(live_pending_roles)
    else:
        pending_roles = list(lifecycle_payload.get("pending_roles") or []) if lifecycle_payload else []

    blocking_issues: list[dict[str, object]] = []
    suggested_repairs: list[dict[str, object]] = []
    pending_documents: list[str] = []
    blockers: list[str] = []

    for role in pending_roles:
        document_name = target_document_name(role)
        document_path = capability_dir / document_name
        if not document_path.exists():
            reason = f"{document_name} 缺失，需先补齐基础文档"
            issue = {
                "severity": "blocking",
                "role": role,
                "code": "missing_document",
                "document": document_name,
                "message": reason,
            }
            action = "create"
        else:
            reason = f"{document_name} 落后于最新 spec 变更"
            issue = {
                "severity": "warning",
                "role": role,
                "code": "pending_align",
                "document": document_name,
                "message": reason,
            }
            action = "align"

        _append_unique(blocking_issues, issue)
        _append_unique(
            suggested_repairs,
            {
                "role": role,
                "action": action,
                "document": document_name,
                "reason": reason,
                "path": relative_path(document_path, root),
            },
        )
        if document_name not in pending_documents:
            pending_documents.append(document_name)
        if issue["severity"] == "blocking" and document_name not in blockers:
            blockers.append(document_name)

    for raw_issue in (semantic_payload or {}).get("issues") or []:
        if not isinstance(raw_issue, dict):
            continue
        suggested_role = str(raw_issue.get("suggested_role") or "").strip().lower()
        if not suggested_role:
            continue
        document_name = target_document_name(suggested_role)
        issue = {
            "severity": str(raw_issue.get("severity") or "warning").strip().lower(),
            "role": suggested_role,
            "code": str(raw_issue.get("rule_id") or "semantic_issue").strip(),
            "document": document_name,
            "message": str(raw_issue.get("message") or "").strip(),
        }
        _append_unique(blocking_issues, issue)
        _append_unique(
            suggested_repairs,
            {
                "role": suggested_role,
                "action": "align",
                "document": document_name,
                "reason": str(raw_issue.get("message") or "").strip(),
                "path": relative_path(capability_dir / document_name, root),
            },
        )
        if issue["severity"] in {"blocking", "error"} and issue["message"] not in blockers:
            blockers.append(issue["message"])

    next_role = None
    lifecycle_next_role = str((lifecycle_payload or {}).get("next_role") or "").strip() or None
    if pending_roles or blocking_issues:
        next_role = lifecycle_next_role
    if next_role is None and pending_roles:
        next_role = pending_roles[0]
    if next_role is None and blocking_issues:
        next_role = str(blocking_issues[0]["role"])

    next_action = None
    if next_role is not None:
        next_action = "audit" if next_role == "maintenance" else "align"

    return {
        "pending_roles": pending_roles,
        "pending": pending_documents,
        "blockers": blockers,
        "blocking_issues": blocking_issues,
        "suggested_repairs": suggested_repairs,
        "next_role": next_role,
        "next_action": next_action,
    }
