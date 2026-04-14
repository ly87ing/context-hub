#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from runtime.semantic_consistency import (
    audit_capability_semantics,
    build_semantic_consistency_audit,
    semantic_consistency_path,
    write_semantic_consistency_audit,
)
from runtime.validation import resolve_hub_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 context-hub 的 semantic consistency")
    parser.add_argument("--hub", help="context-hub 根目录，默认自动识别")
    parser.add_argument("--capability", help="只检查指定 capability")
    parser.add_argument("--output", default="", help="将审计 payload 写入指定 YAML 文件")
    return parser.parse_args()


def audit_hub_semantics(
    hub_root: str | Path,
    *,
    capability: str | None = None,
    output: str | Path | None = None,
) -> dict[str, object]:
    root = Path(hub_root).resolve()
    paths: list[Path] = []
    warnings: list[str] = []

    if capability:
        capability_payload = audit_capability_semantics(root, capability)
        target_path = Path(output) if output else semantic_consistency_path(root / "capabilities" / capability_payload["capability"])
        if not target_path.is_absolute():
            target_path = root / target_path
        paths.append(write_semantic_consistency_audit(capability_payload, target_path))
        warnings.extend(
            f"{capability_payload['capability']}: {issue['message']}"
            for issue in capability_payload["issues"]
        )
        audit_payload = build_semantic_consistency_audit(root, capability=capability_payload["capability"])
        return {"paths": paths, "warnings": warnings, "audit": audit_payload}

    hub_audit = build_semantic_consistency_audit(root)
    capability_root = root / "capabilities"
    if capability_root.exists():
        for capability_dir in sorted(path for path in capability_root.iterdir() if path.is_dir() and not path.name.startswith("_")):
            payload = audit_capability_semantics(root, capability_dir.name)
            paths.append(write_semantic_consistency_audit(payload, semantic_consistency_path(capability_dir)))
            warnings.extend(f"{capability_dir.name}: {issue['message']}" for issue in payload["issues"])
    return {"paths": paths, "warnings": warnings, "audit": hub_audit}


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    result = audit_hub_semantics(
        hub_root,
        capability=args.capability or None,
        output=args.output or None,
    )
    audit_payload = result["audit"]
    issue_count = int(audit_payload["summary"]["issue_count"])

    print(
        f"semantic consistency: {audit_payload['status']} "
        f"({issue_count} issues, scope={audit_payload['scope']['capability'] or 'hub'})"
    )
    for warning in result["warnings"]:
        print(f"- {warning}")

    if issue_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
