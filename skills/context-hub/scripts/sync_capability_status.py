#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from _common import save_yaml_file, utc_now_iso
from integrations import ones_adapter
from runtime.capability_ops import iter_capability_records, update_capability_record
from runtime.hub_io import safe_write_text
from runtime.validation import load_yaml_mapping, resolve_hub_root
from yaml_compat import safe_dump


def normalize_status_category(task_summary: dict[str, object]) -> str:
    status = task_summary.get("status")
    if isinstance(status, dict):
        category = str(status.get("category") or "").strip()
        if category:
            return category
        name = str(status.get("name") or "").strip()
    else:
        name = str(status or "").strip()

    if any(token in name for token in ("进行", "处理中", "开发中")):
        return "in_progress"
    if any(token in name for token in ("完成", "已上线", "已关闭")):
        return "done"
    return "to_do"


def derive_capability_status(task_summaries: list[dict[str, object]]) -> str:
    categories = [normalize_status_category(summary) for summary in task_summaries]
    if "in_progress" in categories:
        return "in-progress"
    if categories and all(category == "done" for category in categories):
        return "stable"
    return "planned"


def build_acceptance_summary(task_summaries: list[dict[str, object]]) -> str:
    if not task_summaries:
        return "未同步到 ONES 任务"
    parts = []
    for task in task_summaries:
        name = str(task.get("name") or task.get("uuid") or task.get("number") or "unknown")
        status = task.get("status")
        status_name = str(status.get("name") or status.get("category") or "unknown") if isinstance(status, dict) else "unknown"
        parts.append(f"{name}({status_name})")
    return "，".join(parts)


def build_source_summary(
    capability_name: str,
    domain_name: str,
    task_refs: list[str],
    task_summaries: list[dict[str, object]],
    *,
    last_synced_at: str,
) -> dict[str, object]:
    source_ref = ",".join(task_refs)
    status = derive_capability_status(task_summaries)
    return {
        "capability": capability_name,
        "domain": domain_name,
        "source_system": "ones",
        "source_ref": source_ref,
        "last_synced_at": last_synced_at,
        "status": status,
        "items": task_summaries,
        "acceptance_summary": build_acceptance_summary(task_summaries),
    }


def load_domains_payload(hub_root: Path) -> dict:
    domains_path = hub_root / "topology" / "domains.yaml"
    if not domains_path.exists():
        return {"domains": {}}
    return load_yaml_mapping(domains_path)


def write_source_summary(capability_dir: Path, payload: dict[str, object]) -> Path:
    summary_path = capability_dir / "source-summary.yaml"
    safe_write_text(summary_path, safe_dump(payload, allow_unicode=True, sort_keys=False))
    return summary_path


def sync_capability_statuses(hub_root: Path, *, team_uuid: str | None = None) -> list[Path]:
    hub_root = Path(hub_root).resolve()
    domains_path = hub_root / "topology" / "domains.yaml"
    domains_payload = load_domains_payload(hub_root)
    domains = domains_payload.setdefault("domains", {})
    synced_paths: list[Path] = []

    for domain_name, capability_name, capability in iter_capability_records(domains_payload):
        ones_tasks = capability.get("ones_tasks") or []
        if not isinstance(ones_tasks, list) or not ones_tasks:
            continue

        task_refs = [str(task_ref).strip() for task_ref in ones_tasks if str(task_ref).strip()]
        if not task_refs:
            continue
        task_summaries: list[dict[str, object]] = []
        for task_ref in task_refs:
            task_info = ones_adapter.get_task_info(task_ref, team_uuid=team_uuid)
            task_summaries.append(ones_adapter.summarize_task(task_info))

        capability_path = str(capability.get("path") or f"capabilities/{capability_name}/").strip().rstrip("/")
        capability_dir = hub_root / capability_path
        capability_dir.mkdir(parents=True, exist_ok=True)
        last_synced_at = utc_now_iso()
        source_ref = ",".join(task_refs)
        status = derive_capability_status(task_summaries)
        summary_payload = build_source_summary(
            capability_name,
            domain_name,
            task_refs,
            task_summaries,
            last_synced_at=last_synced_at,
        )
        summary_path = write_source_summary(capability_dir, summary_payload)
        update_capability_record(
            capability,
            status=status,
            last_synced_at=last_synced_at,
            source_ref=source_ref,
        )
        synced_paths.append(summary_path)

    if synced_paths:
        save_yaml_file(domains_path, domains_payload)
    return synced_paths


def sync_capability_status(hub_root: Path) -> list[Path]:
    return sync_capability_statuses(hub_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步 capability 的 ONES 状态摘要")
    parser.add_argument("--hub", default=".", help="context-hub 根目录")
    parser.add_argument("--ones-team", default="", help="可选的 ONES team UUID override")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    try:
        sync_capability_statuses(hub_root, team_uuid=args.ones_team or None)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    print("ONES capability sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
