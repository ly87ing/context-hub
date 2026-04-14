#!/usr/bin/env python3

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

from integrations import ones_adapter
from runtime.capability_ops import bootstrap_pm_capability, capability_target_document_path
from runtime.hub_io import safe_write_text
from runtime.validation import load_yaml_mapping, resolve_hub_root
from workflows.common import build_workflow_result, prepare_mutation_request


def _find_capability_dir(hub_root: Path, capability: str) -> Path:
    return hub_root / "capabilities" / capability


def _load_source_summary(summary_path: Path) -> dict[str, object] | None:
    if not summary_path.exists():
        return None
    return load_yaml_mapping(summary_path)


def _resolve_task_ref(task_ref: str | None, summary_payload: dict[str, object] | None) -> str | None:
    explicit = str(task_ref or "").strip()
    if explicit:
        return explicit
    if not summary_payload:
        return None
    source_ref = str(summary_payload.get("source_ref") or "").strip()
    if not source_ref:
        return None
    return source_ref.split(",", 1)[0].strip() or None


def run_pm_workflow(
    *,
    hub_root: str | Path,
    capability: str,
    action: str,
    domain: str | None = None,
    content_file: str | Path | None = None,
    task_ref: str | None = None,
) -> dict:
    root = Path(hub_root).resolve()
    capability_name = str(capability).strip()
    capability_dir = _find_capability_dir(root, capability_name)
    target_file = capability_target_document_path(capability_dir, "pm")
    request = prepare_mutation_request(
        role="pm",
        action=action,
        capability=capability_name,
        content_file=content_file,
        target_file=target_file,
        hub_root=root,
    )

    updated_paths: list[Path] = []
    used_sources: list[Path] = [request["content_file"]]
    warnings: list[str] = []
    live_status = "fallback_to_hub"

    if request["action"] == "create" and not capability_dir.exists():
        if not domain:
            raise ValueError("create action requires domain")
        updated_paths.extend(
            bootstrap_pm_capability(
                root,
                capability_name,
                domain,
                title=capability_name,
            )
        )

    summary_path = capability_dir / "source-summary.yaml"
    summary_payload = _load_source_summary(summary_path)
    resolved_task_ref = _resolve_task_ref(task_ref, summary_payload)

    if request["action"] == "align" and resolved_task_ref:
        try:
            task_info = ones_adapter.get_task_info(resolved_task_ref)
            used_sources.append(summary_path if summary_payload else request["content_file"])
            used_sources.append(Path(f"ones://task/{resolved_task_ref}"))
            warnings.extend([])
            if ones_adapter.summarize_task(task_info):
                live_status = "live_ok"
        except ValueError:
            if summary_payload:
                used_sources.append(summary_path)
            warnings.append("未实时校验 ONES 任务，已回退到 hub 内已有上下文")
            live_status = "fallback_to_hub"

    safe_write_text(request["target_file"], request["content_file"].read_text(encoding="utf-8"))
    updated_paths.append(request["target_file"])

    deduped_sources: list[Path] = []
    seen_sources: set[str] = set()
    for source in used_sources:
        key = str(source)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        deduped_sources.append(source)

    deduped_updates: list[Path] = []
    seen_updates: set[Path] = set()
    for path in updated_paths:
        resolved = Path(path)
        if resolved in seen_updates:
            continue
        seen_updates.add(resolved)
        deduped_updates.append(resolved)

    return build_workflow_result(
        root,
        role="pm",
        action=request["action"],
        capability=capability_name,
        target_file=request["target_file"],
        used_sources=deduped_sources,
        live_status=live_status,
        warnings=warnings,
        updated_paths=deduped_updates,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 PM workflow skeleton")
    parser.add_argument("--hub", default=".", help="context-hub 根目录")
    parser.add_argument("--capability", required=True, help="capability slug")
    parser.add_argument("--action", required=True, choices=("create", "align", "extend", "revise"))
    parser.add_argument("--domain", default="", help="业务域；create 时必填")
    parser.add_argument("--content-file", default="", help="输入草稿文件")
    parser.add_argument("--task-ref", default="", help="可选的 ONES task ref")
    parser.add_argument("--output-format", default="text", choices=("text", "json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    try:
        result = run_pm_workflow(
            hub_root=hub_root,
            capability=args.capability,
            action=args.action,
            domain=args.domain or None,
            content_file=args.content_file or None,
            task_ref=args.task_ref or None,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"PM workflow complete: {result['capability']} -> {result['target_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
