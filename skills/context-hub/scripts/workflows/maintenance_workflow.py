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
from runtime.downstream_checklist import list_pending_downstream_roles, load_downstream_checklist
from runtime.validation import REQUIRED_CAPABILITY_FILES, relative_path, resolve_hub_root, target_document_name


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


def run_maintenance_workflow(hub_root: str | Path, *, capability: str | None = None) -> dict[str, object]:
    root = Path(hub_root).resolve()
    warnings: list[str] = []
    next_role: str | None = None
    pending_roles: list[str] = []
    seen_pending_roles: set[str] = set()

    capability_dirs = _iter_capability_dirs(root, capability)
    if capability and not capability_dirs[0].exists():
        warnings.append(f"{relative_path(capability_dirs[0], root)}/ 不存在")
        next_role = "pm"

    for capability_dir in capability_dirs:
        if not capability_dir.exists():
            continue
        has_missing_documents = False
        for filename in REQUIRED_CAPABILITY_FILES:
            document_path = capability_dir / filename
            if document_path.exists():
                continue
            has_missing_documents = True
            warnings.append(f"{relative_path(document_path, root)} 不存在")
            if next_role is None:
                next_role = NEXT_ROLE_BY_DOCUMENT.get(filename)
        if has_missing_documents:
            continue

        checklist_payload = load_downstream_checklist(capability_dir)
        for role in list_pending_downstream_roles(capability_dir, checklist_payload):
            warnings.append(
                f"{relative_path(capability_dir / target_document_name(role), root)} 落后于最新 spec 变更，建议 {role} 执行 align"
            )
            if role not in seen_pending_roles:
                seen_pending_roles.add(role)
                pending_roles.append(role)
                if next_role is None:
                    next_role = role

    result: dict[str, object] = {
        "role": "maintenance",
        "action": "audit",
        "capability": None if capability is None else normalize_slug(capability),
        "warnings": warnings,
        "updated_paths": [],
    }
    if pending_roles:
        result["pending_roles"] = pending_roles
    if next_role is not None:
        result["next_role"] = next_role
        result["next_action"] = "align"
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
