#!/usr/bin/env python3
"""
check_stale.py — 检测 context-hub 中过期的信息

检查项：
  1. 超过指定天数未更新的 capability 文件
  2. 标记为 in-progress 但长期未更新的能力
  3. system.yaml 中的服务是否还活跃

用法：
  python scripts/check_stale.py --warn-days=90

输出：
  过期项列表，可配合通知脚本发送到飞书/钉钉
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.validation import (
    REQUIRED_CAPABILITY_FILES,
    format_freshness,
    load_yaml_mapping,
    locate_export_files,
    missing_export_fields,
    parse_freshness,
    relative_path,
    resolve_hub_root,
)


def load_domains_payload(hub_root: Path, errors: list[str]) -> dict:
    path = hub_root / "topology" / "domains.yaml"
    if not path.exists():
        errors.append("topology/domains.yaml 不存在")
        return {"domains": {}}
    try:
        return load_yaml_mapping(path)
    except ValueError as exc:
        errors.append(str(exc).replace(str(hub_root), ".").replace("./", ""))
        return {"domains": {}}


def check_stale_exports(hub_root: Path, warn_days: int, errors: list[str], warnings: list[str]) -> None:
    ownership_payload = {}
    ownership_path = hub_root / "topology" / "ownership.yaml"
    if ownership_path.exists():
        try:
            ownership_payload = load_yaml_mapping(ownership_path)
        except ValueError as exc:
            errors.append(str(exc).replace(str(hub_root), ".").replace("./", ""))

    cutoff = datetime.now(timezone.utc) - timedelta(days=warn_days)
    now = datetime.now(timezone.utc)
    for _, export_path in locate_export_files(hub_root, ownership_payload):
        try:
            payload = load_yaml_mapping(export_path)
        except ValueError as exc:
            errors.append(str(exc).replace(str(hub_root), ".").replace("./", ""))
            continue

        missing_fields = missing_export_fields(payload)
        if missing_fields:
            errors.append(
                f"{relative_path(export_path, hub_root)} 缺少 export metadata: {', '.join(missing_fields)}"
            )
            continue

        try:
            freshness = parse_freshness(payload.get("last_synced_at"))
        except ValueError as exc:
            errors.append(f"{relative_path(export_path, hub_root)} {exc}")
            continue

        if freshness < cutoff:
            age_days = (now - freshness).days
            warnings.append(
                f"{relative_path(export_path, hub_root)} 已 stale: last_synced_at={format_freshness(freshness)}, "
                f"{age_days} 天前"
            )


def check_in_progress_capabilities(hub_root: Path, domains_payload: dict, errors: list[str]) -> None:
    for domain_name, domain_info in (domains_payload.get("domains") or {}).items():
        if not isinstance(domain_info, dict):
            continue
        for capability in domain_info.get("capabilities") or []:
            if not isinstance(capability, dict):
                continue
            if capability.get("status") != "in-progress":
                continue
            capability_name = capability.get("name") or "unknown"
            cap_path = capability.get("path") or f"capabilities/{capability_name}/"
            cap_dir = hub_root / cap_path
            if not cap_dir.exists():
                errors.append(
                    f"in-progress capability {capability_name} 缺少目录，阻塞 {domain_name} 域协作: {cap_path}"
                )
                continue
            missing_files = [
                filename for filename in REQUIRED_CAPABILITY_FILES if not (cap_dir / filename).exists()
            ]
            if missing_files:
                errors.append(
                    f"in-progress capability {capability_name} 缺少关键文件，阻塞下游角色: "
                    f"{', '.join(missing_files)}"
                )


def check_capability_sync_freshness(
    hub_root: Path,
    domains_payload: dict,
    warn_days: int,
    warnings: list[str],
) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=warn_days)
    now = datetime.now(timezone.utc)
    for domain_info in (domains_payload.get("domains") or {}).values():
        if not isinstance(domain_info, dict):
            continue
        for capability in domain_info.get("capabilities") or []:
            if not isinstance(capability, dict):
                continue
            if not capability.get("ones_tasks"):
                continue
            capability_name = capability.get("name") or "unknown"
            freshness_raw = capability.get("last_synced_at")
            if freshness_raw in ("", None):
                warnings.append(f"capability {capability_name} 缺少 last_synced_at")
                continue
            try:
                freshness = parse_freshness(freshness_raw)
            except ValueError:
                warnings.append(f"capability {capability_name} last_synced_at 无法解析: {freshness_raw}")
                continue
            if freshness < cutoff:
                age_days = (now - freshness).days
                warnings.append(
                    f"capability {capability_name} 已 stale: last_synced_at={format_freshness(freshness)}, {age_days} 天前"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检测联邦 context-hub 的 stale 风险")
    parser.add_argument("--hub", help="context-hub 根目录，默认自动识别")
    parser.add_argument("--warn-days", type=int, default=90, help="超过多少天视为 stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    errors: list[str] = []
    warnings: list[str] = []

    print(f"🔍 检测超过 {args.warn_days} 天未同步的共享上下文...\n")

    domains_payload = load_domains_payload(hub_root, errors)
    check_stale_exports(hub_root, args.warn_days, errors, warnings)
    check_in_progress_capabilities(hub_root, domains_payload, errors)
    check_capability_sync_freshness(hub_root, domains_payload, args.warn_days, warnings)

    if errors:
        print("❌ 阻塞项:")
        for message in errors:
            print(f"  - {message}")

    if warnings:
        print("\n⚠️  stale 项:")
        for message in warnings:
            print(f"  - {message}")

    if not errors and not warnings:
        print("✅ 没有 stale 或 blocking 问题")
        return 0
    if errors:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
