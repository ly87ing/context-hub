#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import (
    load_yaml_file,
    normalize_slug,
    unique_preserving_order,
    render_template_text,
    save_yaml_file,
    today_iso,
)
from runtime.capability_ops import (
    DEFAULT_MAINTAINED_BY,
    ensure_capability_ownership,
    ensure_capability_record,
    load_ownership_payload,
)


REQUIRED_FILES = ("spec.md", "design.md", "architecture.md", "testing.md")


def load_template_map(template_root: Path) -> dict[str, str]:
    mapping = {}
    for name in REQUIRED_FILES:
        template_path = template_root / name
        if not template_path.exists():
            raise FileNotFoundError(f"缺少模板文件: {template_path}")
        mapping[name] = template_path.read_text()
    return mapping


def ensure_domain(domains_payload: dict, domain: str) -> dict:
    domains = domains_payload.setdefault("domains", {})
    return domains.setdefault(
        domain,
        {
            "description": "待填写",
            "owner": "待填写",
            "capabilities": [],
        },
    )


def render_ones_tasks_section(ones_tasks: list[str]) -> str:
    if not ones_tasks:
        return "- 暂无关联 ONES 工单"
    return "\n".join(f"- {task_ref}" for task_ref in ones_tasks)


def render_capability_files(
    capability_dir: Path,
    template_map: dict[str, str],
    title: str,
    ones_tasks: list[str],
) -> None:
    replacements = {
        "能力名称": title,
        "date": today_iso(),
        "description": "待填写",
        "link": "待补充",
        "service": "待补充",
        "branch": "main",
        "commit-hash": "待补充",
        "service/team": "待补充",
        "ones_tasks_section": render_ones_tasks_section(ones_tasks),
    }
    capability_dir.mkdir(parents=True, exist_ok=False)

    for filename, template in template_map.items():
        rendered = render_template_text(template, replacements)
        (capability_dir / filename).write_text(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description="为 context-hub 创建新的 capability 目录")
    parser.add_argument("--hub", default=".", help="context-hub 根目录")
    parser.add_argument("--name", required=True, help="能力名，建议英文 slug")
    parser.add_argument("--title", help="能力显示名称，默认使用 name")
    parser.add_argument("--domain", required=True, help="所属业务域")
    parser.add_argument(
        "--status",
        default="planned",
        choices=("planned", "in-progress", "stable", "deprecated"),
        help="能力状态",
    )
    parser.add_argument(
        "--maintained-by",
        default=DEFAULT_MAINTAINED_BY,
        help="capability maintained_by，默认保持 product",
    )
    parser.add_argument(
        "--ones-task",
        action="append",
        default=[],
        help="关联的 ONES 工单引用，可重复",
    )
    args = parser.parse_args()

    hub_root = Path(args.hub).resolve()
    capability_name = normalize_slug(args.name)
    domain_name = normalize_slug(args.domain)
    capability_title = args.title.strip() if args.title else capability_name
    maintained_by = normalize_slug(args.maintained_by)
    ones_tasks = unique_preserving_order(task.strip() for task in args.ones_task if task.strip())

    template_root = hub_root / "capabilities" / "_templates"
    template_map = load_template_map(template_root)

    capability_dir = hub_root / "capabilities" / capability_name
    if capability_dir.exists():
        raise SystemExit(f"❌ 能力目录已存在: {capability_dir}")

    render_capability_files(capability_dir, template_map, capability_title, ones_tasks)

    domains_path = hub_root / "topology" / "domains.yaml"
    domains_payload = load_yaml_file(domains_path, {"domains": {}})
    domain_payload = ensure_domain(domains_payload, domain_name)
    ensure_capability_record(
        domain_payload,
        capability_name,
        capability_title,
        args.status,
        ones_tasks=ones_tasks,
    )
    save_yaml_file(domains_path, domains_payload)

    ownership_path = hub_root / "topology" / "ownership.yaml"
    ownership_payload = load_ownership_payload(
        ownership_path,
        project_id=hub_root.name,
        project_name=hub_root.name,
    )
    ensure_capability_ownership(
        ownership_payload,
        capability_name,
        domain_name,
        maintained_by=maintained_by,
    )
    save_yaml_file(ownership_path, ownership_payload)

    update_script = Path(__file__).with_name("update_llms_txt.py")
    if update_script.exists():
        subprocess.run([sys.executable, str(update_script), str(hub_root)], check=True)

    print(f"✅ 已创建能力目录: {capability_dir}")
    print(f"✅ 已更新业务域索引: {domains_path}")
    print(f"✅ 已更新能力归属: {ownership_path}")
    print("✅ 已刷新 .context/llms.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
