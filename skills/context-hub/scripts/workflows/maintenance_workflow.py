#!/usr/bin/env python3

"""Maintenance workflow skeleton."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from _common import normalize_slug
from runtime.lifecycle_state import load_lifecycle_state
from runtime.maintenance_advice import build_maintenance_advice
from runtime.validation import REQUIRED_CAPABILITY_FILES, load_yaml_mapping, relative_path, resolve_hub_root, target_document_name


NEXT_ROLE_BY_DOCUMENT = {
    "spec.md": "pm",
    "design.md": "design",
    "architecture.md": "engineering",
    "testing.md": "qa",
}


def _iter_capability_dirs(hub_root: Path, capability: str | None) -> list[Path]:
    if capability:
        capability_dir = hub_root / "capabilities" / normalize_slug(capability)
        return [capability_dir]

    capability_root = hub_root / "capabilities"
    if not capability_root.exists():
        return []
    return sorted(
        path
        for path in capability_root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


DOCUMENT_BY_ROLE = {
    "pm": "spec.md",
    "design": "design.md",
    "engineering": "architecture.md",
    "qa": "testing.md",
}


def _load_semantic_payload(capability_dir: Path) -> dict[str, object] | None:
    path = capability_dir / "semantic-consistency.yaml"
    if not path.exists():
        return None
    return load_yaml_mapping(path)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _append_unique_dict(records: list[dict[str, object]], record: dict[str, object]) -> None:
    if record not in records:
        records.append(record)


def run_maintenance_workflow(hub_root: str | Path, *, capability: str | None = None) -> dict[str, object]:
    root = Path(hub_root).resolve()
    warnings: list[str] = []
    next_role: str | None = None
    next_action: str | None = None
    pending_roles: list[str] = []
    pending: list[str] = []
    blockers: list[str] = []
    blocking_issues: list[dict[str, object]] = []
    suggested_repairs: list[dict[str, object]] = []

    capability_dirs = _iter_capability_dirs(root, capability)
    if capability and not capability_dirs[0].exists():
        warnings.append(f"{relative_path(capability_dirs[0], root)}/ 不存在")
        next_role = "pm"
        next_action = "create"

    for capability_dir in capability_dirs:
        if not capability_dir.exists():
            continue
        for filename in REQUIRED_CAPABILITY_FILES:
            document_path = capability_dir / filename
            if document_path.exists():
                continue
            warnings.append(f"{relative_path(document_path, root)} 不存在")
            role_name = NEXT_ROLE_BY_DOCUMENT.get(filename)
            if role_name:
                _append_unique(pending_roles, role_name)
                _append_unique(pending, filename)
                _append_unique(blockers, filename)
                _append_unique_dict(
                    suggested_repairs,
                    {
                        "role": role_name,
                        "action": "create",
                        "document": filename,
                        "reason": f"{filename} 缺失，需先补齐基础文档",
                        "path": relative_path(document_path, root),
                    },
                )
                _append_unique_dict(
                    blocking_issues,
                    {
                        "severity": "blocking",
                        "role": role_name,
                        "code": "missing_document",
                        "document": filename,
                        "message": f"{filename} 缺失，阻塞 downstream 协作",
                    },
                )
                if next_role is None:
                    next_role = role_name
                    next_action = "create"

        lifecycle_payload = load_lifecycle_state(capability_dir)
        semantic_payload = _load_semantic_payload(capability_dir)
        advice = build_maintenance_advice(
            root,
            capability_dir=capability_dir,
            lifecycle_payload=lifecycle_payload,
            semantic_payload=semantic_payload,
        )

        for role_name in advice["pending_roles"]:
            _append_unique(pending_roles, role_name)
            if role_name in DOCUMENT_BY_ROLE:
                warnings.append(
                    f"{relative_path(capability_dir / DOCUMENT_BY_ROLE[role_name], root)} 落后于最新上下文，建议 {role_name} 执行 align"
                )
        for document_name in advice["pending"]:
            _append_unique(pending, document_name)
        for blocker in advice["blockers"]:
            _append_unique(blockers, blocker)
        for issue in advice["blocking_issues"]:
            _append_unique_dict(blocking_issues, issue)
            message = str(issue.get("message") or "").strip()
            if message:
                warnings.append(message)
        for repair in advice["suggested_repairs"]:
            _append_unique_dict(suggested_repairs, repair)

        if next_role is None and advice.get("next_role"):
            next_role = str(advice["next_role"])
            next_action = str(advice.get("next_action") or "align")

    result: dict[str, object] = {
        "role": "maintenance",
        "action": "audit",
        "capability": None if capability is None else normalize_slug(capability),
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "suggested_repairs": suggested_repairs,
        "updated_paths": [],
    }
    if pending_roles:
        result["pending_roles"] = pending_roles
    if pending:
        result["pending"] = pending
    if blockers:
        result["blockers"] = blockers
    if next_role is not None:
        result["next_role"] = next_role
        result["next_action"] = next_action or "align"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 maintenance workflow skeleton")
    parser.add_argument("--hub", default=".", help="context-hub 根目录")
    parser.add_argument("--capability", default="", help="可选的 capability slug")
    parser.add_argument("--output-format", default="text", choices=("text", "json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    result = run_maintenance_workflow(
        hub_root,
        capability=args.capability or None,
    )

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        capability_suffix = f" ({result['capability']})" if result["capability"] else ""
        print(f"Maintenance workflow audit complete{capability_suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
