#!/usr/bin/env python3
"""
check_consistency.py — 检查 context-hub 内部一致性

检查项：
  1. 必需的 hub 文件、脚本、runtime/integrations 目录是否存在
  2. domains.yaml、ownership.yaml、capability 目录之间的 cross-reference 是否一致
  3. teams/*/exports/ 目录和 export metadata 是否完整
  4. topology 下的 YAML 文件是否可解析
  5. .context/llms.txt 是否包含共享索引以及 freshness/ownership 标记

用法：
  python scripts/check_consistency.py

退出码：
  0 — 全部通过
  1 — 有警告
  2 — 有错误
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime.validation import (
    REQUIRED_CAPABILITY_FILES,
    iter_team_export_dirs,
    load_yaml_mapping,
    locate_export_files,
    missing_export_fields,
    relative_path,
    resolve_hub_root,
)
from yaml_compat import YAMLError, safe_load


REQUIRED_ROOT_PATHS = [
    "IDENTITY.md",
    "topology/system.yaml",
    "topology/domains.yaml",
    "topology/testing-sources.yaml",
    "topology/ownership.yaml",
    "decisions/_index.md",
    "decisions/_template.md",
    ".context/llms.txt",
    "templates",
    "templates/llms.txt",
    "scripts/create_capability.py",
    "scripts/refresh_context.py",
    "scripts/bootstrap_credentials_check.py",
    "scripts/update_llms_txt.py",
    "scripts/check_consistency.py",
    "scripts/check_stale.py",
    "scripts/sync_topology.py",
    "scripts/sync_capability_status.py",
    "scripts/_common.py",
    "scripts/yaml_compat.py",
    "scripts/runtime",
    "scripts/runtime/__init__.py",
    "scripts/runtime/capability_ops.py",
    "scripts/runtime/commit_ops.py",
    "scripts/runtime/hub_io.py",
    "scripts/runtime/hub_paths.py",
    "scripts/runtime/validation.py",
    "scripts/integrations",
    "scripts/integrations/__init__.py",
    "scripts/integrations/credentials.py",
    "scripts/integrations/gitlab_adapter.py",
    "scripts/integrations/ones_adapter.py",
]
REQUIRED_TEMPLATE_FILES = ["spec.md", "design.md", "architecture.md", "testing.md"]


def append_yaml_error(errors: list[str], hub_root: Path, exc: ValueError) -> None:
    message = str(exc).replace(str(hub_root), ".").replace("./", "")
    errors.append(message)


def load_mapping_or_error(path: Path, hub_root: Path, errors: list[str], default: dict | None = None) -> dict:
    if not path.exists():
        errors.append(f"{relative_path(path, hub_root)} 不存在")
        return default or {}
    try:
        return load_yaml_mapping(path)
    except ValueError as exc:
        append_yaml_error(errors, hub_root, exc)
        return default or {}


def check_required_paths(hub_root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_ROOT_PATHS:
        if not (hub_root / relative).exists():
            errors.append(f"{relative} 不存在")


def check_template_files(hub_root: Path, errors: list[str]) -> None:
    template_dir = hub_root / "capabilities" / "_templates"
    if not template_dir.exists():
        errors.append("capabilities/_templates/ 不存在")
        return
    for filename in REQUIRED_TEMPLATE_FILES:
        if not (template_dir / filename).exists():
            errors.append(f"capabilities/_templates/{filename} 不存在")


def check_system_yaml(system_payload: dict, warnings: list[str]) -> None:
    services = system_payload.get("services") or {}
    for service_name, service_info in services.items():
        if not isinstance(service_info, dict):
            warnings.append(f"services.{service_name} 格式错误，应为字典")
            continue
        if not service_info.get("repo"):
            warnings.append(f"services.{service_name} 缺少 repo 字段")
        if not service_info.get("domain"):
            warnings.append(f"services.{service_name} 缺少 domain 字段")
        if not service_info.get("owner"):
            warnings.append(f"services.{service_name} 缺少 owner 字段")
        if not service_info.get("type"):
            warnings.append(f"services.{service_name} 缺少 type 字段")


def check_domains_yaml(hub_root: Path, domains_payload: dict, warnings: list[str]) -> None:
    domains = domains_payload.get("domains") or {}
    for domain_name, domain_info in domains.items():
        if not isinstance(domain_info, dict):
            warnings.append(f"domains.{domain_name} 格式错误，应为字典")
            continue
        if not domain_info.get("owner"):
            warnings.append(f"domains.{domain_name} 缺少 owner 字段")
        capabilities = domain_info.get("capabilities") or []
        for capability in capabilities:
            if not isinstance(capability, dict):
                warnings.append(f"domains.{domain_name} capability 条目格式错误")
                continue
            cap_path = capability.get("path", "")
            if not cap_path:
                warnings.append(f"domains.{domain_name}.capabilities.{capability.get('name', '?')} 缺少 path")
                continue
            full_path = hub_root / cap_path
            if not full_path.exists():
                warnings.append(
                    f"domains.{domain_name}.capabilities.{capability.get('name', '?')} 引用的路径 {cap_path} 不存在"
                )
                continue
            for required_file in REQUIRED_CAPABILITY_FILES:
                if not (full_path / required_file).exists():
                    warnings.append(f"{cap_path} 缺少 {required_file}")
            if capability.get("ones_tasks"):
                summary_path = full_path / "source-summary.yaml"
                if not summary_path.exists():
                    warnings.append(f"{cap_path} 缺少 source-summary.yaml")
                    continue
                try:
                    summary_payload = load_yaml_mapping(summary_path)
                except ValueError as exc:
                    warnings.append(str(exc).replace(str(hub_root), ".").replace("./", ""))
                    continue
                for field in ("source_system", "source_ref", "last_synced_at", "status", "items", "acceptance_summary"):
                    if summary_payload.get(field) in ("", None, []):
                        warnings.append(f"{cap_path}/source-summary.yaml 缺少 {field}")


def check_capability_directories(hub_root: Path, domains_payload: dict, warnings: list[str]) -> None:
    cap_root = hub_root / "capabilities"
    if not cap_root.exists():
        return

    indexed_paths = {
        capability.get("path", "").rstrip("/")
        for domain_info in (domains_payload.get("domains") or {}).values()
        if isinstance(domain_info, dict)
        for capability in (domain_info.get("capabilities") or [])
        if isinstance(capability, dict) and capability.get("path")
    }

    for cap_dir in sorted(cap_root.iterdir()):
        if not cap_dir.is_dir() or cap_dir.name.startswith("_"):
            continue
        relative_dir = relative_path(cap_dir, hub_root)
        if relative_dir not in indexed_paths:
            warnings.append(f"{relative_dir}/ 未在 topology/domains.yaml 中登记")


def check_decisions(hub_root: Path, warnings: list[str]) -> None:
    decisions_dir = hub_root / "decisions"
    if not decisions_dir.exists():
        warnings.append("decisions/ 目录不存在")
        return

    for md_file in decisions_dir.glob("[0-9]*.md"):
        content = md_file.read_text(encoding="utf-8")
        if "## Status" not in content:
            warnings.append(f"{md_file.name} 缺少 Status 字段")
        if "## Decision" not in content:
            warnings.append(f"{md_file.name} 缺少 Decision 字段")


def check_team_exports(hub_root: Path, ownership_payload: dict, errors: list[str]) -> list[tuple[str, Path, dict]]:
    export_records: list[tuple[str, Path, dict]] = []
    for team_id, export_dir in iter_team_export_dirs(hub_root, ownership_payload):
        if not export_dir.exists():
            errors.append(f"{relative_path(export_dir, hub_root)} 不存在")
            continue
        if not export_dir.is_dir():
            errors.append(f"{relative_path(export_dir, hub_root)} 不是目录")
            continue

    for team_id, export_path in locate_export_files(hub_root, ownership_payload):
        try:
            payload = load_yaml_mapping(export_path)
        except ValueError as exc:
            append_yaml_error(errors, hub_root, exc)
            continue

        missing_fields = missing_export_fields(payload)
        if missing_fields:
            errors.append(
                f"{relative_path(export_path, hub_root)} 缺少 export metadata: {', '.join(missing_fields)}"
            )
            continue
        export_records.append((team_id, export_path, payload))
    return export_records


def check_ownership_structure(ownership_payload: dict, errors: list[str]) -> set[str]:
    teams = ownership_payload.get("teams")
    if not isinstance(teams, dict):
        errors.append("topology/ownership.yaml 的 teams 必须是 mapping")
        return set()
    if not teams:
        errors.append("topology/ownership.yaml 的 teams 不能为空")
        return set()
    return set(teams.keys())


def check_capability_ownership_cross_refs(
    hub_root: Path,
    domains_payload: dict,
    ownership_payload: dict,
    team_ids: set[str],
    errors: list[str],
) -> None:
    domains = domains_payload.get("domains") or {}
    ownership_capabilities = ownership_payload.get("capabilities") or {}

    capability_domains: dict[str, str] = {}
    for domain_name, domain_info in domains.items():
        if not isinstance(domain_info, dict):
            continue
        for capability in domain_info.get("capabilities") or []:
            if not isinstance(capability, dict):
                continue
            cap_name = capability.get("name")
            if not cap_name:
                errors.append(f"domains.{domain_name} 存在缺少 name 的 capability 条目")
                continue
            capability_domains[cap_name] = domain_name
            ownership_entry = ownership_capabilities.get(cap_name)
            if not isinstance(ownership_entry, dict):
                errors.append(f"topology/ownership.yaml 缺少 capability {cap_name} 的归属定义")
                continue
            if ownership_entry.get("domain") != domain_name:
                errors.append(
                    f"capability {cap_name} 的 domain 不一致: domains.yaml={domain_name}, "
                    f"ownership.yaml={ownership_entry.get('domain')}"
                )
            maintained_by = ownership_entry.get("maintained_by")
            if maintained_by and maintained_by not in team_ids:
                errors.append(f"capability {cap_name} 的 maintained_by 未在 ownership teams 中定义: {maintained_by}")

    for cap_name, ownership_entry in ownership_capabilities.items():
        if not isinstance(ownership_entry, dict):
            errors.append(f"topology/ownership.yaml capability {cap_name} 格式错误，应为字典")
            continue
        if cap_name not in capability_domains:
            errors.append(f"topology/ownership.yaml capability {cap_name} 未在 topology/domains.yaml 中登记")
        domain_name = ownership_entry.get("domain")
        if domain_name and domain_name not in domains:
            errors.append(f"topology/ownership.yaml capability {cap_name} 引用了不存在的 domain: {domain_name}")
        cap_dir = hub_root / "capabilities" / cap_name
        if not cap_dir.exists():
            errors.append(f"topology/ownership.yaml capability {cap_name} 对应目录不存在: capabilities/{cap_name}")


def check_yaml_files(hub_root: Path, errors: list[str]) -> None:
    yaml_targets = [
        hub_root / "topology",
        hub_root / "teams",
    ]
    for base_dir in yaml_targets:
        if not base_dir.exists():
            continue
        for pattern in ("*.yaml", "*.yml"):
            for yaml_file in base_dir.rglob(pattern):
                if ".git" in yaml_file.parts:
                    continue
                try:
                    load_yaml_mapping(yaml_file)
                except ValueError as exc:
                    append_yaml_error(errors, hub_root, exc)


def check_llms_txt(
    hub_root: Path,
    export_records: list[tuple[str, Path, dict]],
    errors: list[str],
    warnings: list[str],
) -> None:
    llms_file = hub_root / ".context" / "llms.txt"
    if not llms_file.exists():
        errors.append(".context/llms.txt 不存在")
        return

    content = llms_file.read_text(encoding="utf-8").strip()
    if not content:
        warnings.append(".context/llms.txt 为空")
    if "## 业务域" not in content:
        warnings.append(".context/llms.txt 缺少业务域索引")
    if "## 服务清单" not in content:
        warnings.append(".context/llms.txt 缺少服务清单")

    needs_freshness = any(payload.get("last_synced_at") for _, _, payload in export_records)
    needs_ownership = any(payload.get("maintained_by") for _, _, payload in export_records)
    missing_markers: list[str] = []
    if needs_freshness and "freshness:" not in content:
        missing_markers.append("freshness")
    if needs_ownership and "maintained by " not in content:
        missing_markers.append("ownership")
    if missing_markers:
        warnings.append(f".context/llms.txt 缺少 freshness/ownership 标记: {', '.join(missing_markers)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 context-hub 内部一致性")
    parser.add_argument("--hub", help="context-hub 根目录，默认自动识别")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    errors: list[str] = []
    warnings: list[str] = []

    print("🔍 检查 context-hub 一致性...\n")

    check_required_paths(hub_root, errors)
    check_template_files(hub_root, errors)

    system_payload = load_mapping_or_error(hub_root / "topology" / "system.yaml", hub_root, errors, {"services": {}})
    domains_payload = load_mapping_or_error(hub_root / "topology" / "domains.yaml", hub_root, errors, {"domains": {}})
    ownership_payload = load_mapping_or_error(
        hub_root / "topology" / "ownership.yaml",
        hub_root,
        errors,
        {"teams": {}, "capabilities": {}},
    )
    team_ids = check_ownership_structure(ownership_payload, errors)

    check_system_yaml(system_payload, warnings)
    check_domains_yaml(hub_root, domains_payload, warnings)
    check_capability_directories(hub_root, domains_payload, warnings)
    check_decisions(hub_root, warnings)
    export_records = check_team_exports(hub_root, ownership_payload, errors)
    check_capability_ownership_cross_refs(hub_root, domains_payload, ownership_payload, team_ids, errors)
    check_llms_txt(hub_root, export_records, errors, warnings)
    check_yaml_files(hub_root, errors)

    if errors:
        print("❌ 错误:")
        for message in errors:
            print(f"  - {message}")

    if warnings:
        print("\n⚠️  警告:")
        for message in warnings:
            print(f"  - {message}")

    if not errors and not warnings:
        print("✅ 全部通过")
        return 0
    if errors:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
