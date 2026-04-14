from __future__ import annotations

from pathlib import Path

from _common import utc_now_iso
from yaml_compat import YAMLError, safe_dump, safe_load

from .hub_io import safe_write_text


INDEX_FILENAME = "iteration-index.yaml"
DEFAULT_ITERATION = "backlog"
DEFAULT_RELEASE = "unassigned"


def iteration_index_path(capability_dir: str | Path) -> Path:
    return Path(capability_dir) / INDEX_FILENAME


def load_iteration_index(capability_dir: str | Path) -> dict[str, object] | None:
    path = iteration_index_path(capability_dir)
    if not path.exists():
        return None
    try:
        payload = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _normalize_label(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_source_ref(value: object) -> str:
    return str(value or "").strip()


def _current_labels(existing_payload: dict[str, object] | None) -> tuple[str, str]:
    current = existing_payload.get("current") if isinstance(existing_payload, dict) else {}
    if not isinstance(current, dict):
        current = {}
    return (
        _normalize_label(current.get("iteration"), default=DEFAULT_ITERATION),
        _normalize_label(current.get("release"), default=DEFAULT_RELEASE),
    )


def _normalize_entry(raw_entry: object) -> dict[str, object] | None:
    if not isinstance(raw_entry, dict):
        return None
    iteration = _normalize_label(raw_entry.get("iteration"), default="")
    if not iteration:
        return None
    release = _normalize_label(raw_entry.get("release"), default=DEFAULT_RELEASE)
    updates = raw_entry.get("updates")
    try:
        normalized_updates = int(updates)
    except (TypeError, ValueError):
        normalized_updates = 0
    return {
        "iteration": iteration,
        "release": release,
        "first_seen_at": str(raw_entry.get("first_seen_at") or "").strip(),
        "last_updated_at": str(raw_entry.get("last_updated_at") or "").strip(),
        "last_action": str(raw_entry.get("last_action") or "").strip(),
        "source_ref": _normalize_source_ref(raw_entry.get("source_ref")),
        "updates": max(normalized_updates, 0),
    }


def build_iteration_index_payload(
    capability: str,
    *,
    action: str,
    iteration: str | None = None,
    release: str | None = None,
    source_ref: str | None = None,
    existing_payload: dict[str, object] | None = None,
    updated_at: str | None = None,
) -> dict[str, object]:
    now = str(updated_at or utc_now_iso()).strip() or utc_now_iso()
    current_iteration, current_release = _current_labels(existing_payload or {})
    resolved_iteration = _normalize_label(iteration, default=current_iteration)
    resolved_release = _normalize_label(release, default=current_release)
    resolved_source_ref = _normalize_source_ref(source_ref)

    entries: list[dict[str, object]] = []
    matched_current = False

    for raw_entry in (existing_payload or {}).get("entries") or []:
        entry = _normalize_entry(raw_entry)
        if entry is None:
            continue
        is_current = (
            entry["iteration"] == resolved_iteration
            and entry["release"] == resolved_release
            and not matched_current
        )
        if is_current:
            matched_current = True
            entries.append(
                {
                    "iteration": resolved_iteration,
                    "release": resolved_release,
                    "first_seen_at": str(entry["first_seen_at"] or now),
                    "last_updated_at": now,
                    "last_action": str(action).strip().lower(),
                    "source_ref": resolved_source_ref or entry["source_ref"],
                    "updates": int(entry["updates"]) + 1,
                    "status": "current",
                }
            )
            continue

        entries.append(
            {
                "iteration": entry["iteration"],
                "release": entry["release"],
                "first_seen_at": str(entry["first_seen_at"] or entry["last_updated_at"] or now),
                "last_updated_at": str(entry["last_updated_at"] or entry["first_seen_at"] or now),
                "last_action": str(entry["last_action"] or "").strip(),
                "source_ref": entry["source_ref"],
                "updates": max(int(entry["updates"]), 1),
                "status": "historical",
            }
        )

    if not matched_current:
        entries.append(
            {
                "iteration": resolved_iteration,
                "release": resolved_release,
                "first_seen_at": now,
                "last_updated_at": now,
                "last_action": str(action).strip().lower(),
                "source_ref": resolved_source_ref,
                "updates": 1,
                "status": "current",
            }
        )

    return {
        "capability": str(capability).strip(),
        "updated_at": now,
        "current": {
            "iteration": resolved_iteration,
            "release": resolved_release,
            "updated_at": now,
            "source_role": "pm",
            "source_action": str(action).strip().lower(),
            "source_ref": resolved_source_ref,
        },
        "entries": entries,
    }


def write_iteration_index(
    capability_dir: str | Path,
    *,
    capability: str,
    action: str,
    iteration: str | None = None,
    release: str | None = None,
    source_ref: str | None = None,
) -> Path:
    path = iteration_index_path(capability_dir)
    payload = build_iteration_index_payload(
        capability,
        action=action,
        iteration=iteration,
        release=release,
        source_ref=source_ref,
        existing_payload=load_iteration_index(capability_dir),
    )
    safe_write_text(path, safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path
