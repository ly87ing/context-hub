from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from yaml_compat import YAMLError, safe_dump, safe_load

from .hub_io import safe_write_text
from .validation import normalize_role, parse_freshness, target_document_name


CHECKLIST_FILENAME = "downstream-checklist.yaml"
DOWNSTREAM_ROLES = ("design", "engineering", "qa")


def downstream_checklist_path(capability_dir: str | Path) -> Path:
    return Path(capability_dir) / CHECKLIST_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_downstream_checklist_payload(
    capability: str,
    *,
    action: str,
    generated_at: str | None = None,
) -> dict[str, object]:
    items: list[dict[str, str]] = []
    for role in DOWNSTREAM_ROLES:
        items.append(
            {
                "role": role,
                "target_file": target_document_name(role),
                "status": "pending",
            }
        )

    return {
        "capability": str(capability).strip(),
        "generated_at": generated_at or _utc_now_iso(),
        "source": {
            "role": "pm",
            "action": str(action).strip().lower(),
            "target_file": "spec.md",
        },
        "items": items,
    }


def write_downstream_checklist(
    capability_dir: str | Path,
    *,
    capability: str,
    action: str,
) -> Path:
    path = downstream_checklist_path(capability_dir)
    payload = build_downstream_checklist_payload(capability, action=action)
    safe_write_text(
        path,
        safe_dump(payload, allow_unicode=True, sort_keys=False),
    )
    return path


def load_downstream_checklist(capability_dir: str | Path) -> dict[str, object] | None:
    path = downstream_checklist_path(capability_dir)
    if not path.exists():
        return None
    try:
        payload = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def list_pending_downstream_roles(
    capability_dir: str | Path,
    checklist_payload: dict[str, object] | None,
) -> list[str]:
    if not checklist_payload:
        return []

    try:
        refreshed_at = parse_freshness(checklist_payload.get("generated_at"))
    except ValueError:
        return []

    capability_path = Path(capability_dir)
    pending_roles: list[str] = []
    seen_roles: set[str] = set()

    for raw_item in checklist_payload.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        raw_role = str(raw_item.get("role") or "").strip()
        if not raw_role:
            continue
        try:
            role = normalize_role(raw_role)
        except ValueError:
            continue
        if role in seen_roles:
            continue

        target_file = str(raw_item.get("target_file") or target_document_name(role)).strip()
        if not target_file:
            continue

        document_path = capability_path / target_file
        if not document_path.exists():
            continue

        updated_at = datetime.fromtimestamp(document_path.stat().st_mtime, tz=timezone.utc)
        if updated_at >= refreshed_at:
            continue

        seen_roles.add(role)
        pending_roles.append(role)

    return pending_roles
