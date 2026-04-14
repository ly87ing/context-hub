#!/usr/bin/env python3

"""Design workflow skeleton."""

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
from integrations.figma_adapter import probe_figma_reference
from runtime.capability_ops import capability_target_document_path
from runtime.hub_io import safe_write_text
from runtime.http_client import Transport
from runtime.validation import resolve_hub_root
from workflows.common import build_workflow_result, prepare_mutation_request


def _find_capability_dir(hub_root: Path, capability: str) -> Path:
    return hub_root / "capabilities" / capability


def _require_existing_capability(capability_dir: Path, capability_name: str) -> None:
    if capability_dir.exists():
        return
    raise ValueError(
        f"design workflow 需已有 capability 或 PM 先建: {capability_name}"
    )


def run_design_workflow(
    *,
    hub_root: str | Path,
    capability: str,
    action: str,
    content_file: str | Path | None = None,
    figma_url: str | None = None,
    transport: Transport | None = None,
) -> dict:
    root = Path(hub_root).resolve()
    capability_name = normalize_slug(capability)
    capability_dir = _find_capability_dir(root, capability_name)
    _require_existing_capability(capability_dir, capability_name)
    target_file = capability_target_document_path(capability_dir, "design")
    request = prepare_mutation_request(
        role="design",
        action=action,
        capability=capability_name,
        content_file=content_file,
        target_file=target_file,
        hub_root=root,
    )

    used_sources: list[str | Path] = [request["content_file"]]
    warnings: list[str] = []
    live_status = "fallback_to_hub"

    normalized_figma_url = str(figma_url or "").strip()
    if normalized_figma_url:
        probe_result = probe_figma_reference(
            normalized_figma_url,
            transport=transport,
        )
        if probe_result.status == "ok":
            live_status = "live_ok"
            used_sources.append(normalized_figma_url)
        else:
            warnings.append("未实时校验 Figma 引用，已回退到 hub 内已有上下文")
    else:
        warnings.append("未实时校验 Figma 引用，已回退到 hub 内已有上下文")

    safe_write_text(request["target_file"], request["content_file"].read_text(encoding="utf-8"))

    deduped_sources: list[str | Path] = []
    seen_sources: set[str] = set()
    for source in used_sources:
        key = str(source)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        deduped_sources.append(source)

    return build_workflow_result(
        root,
        role="design",
        action=request["action"],
        capability=capability_name,
        target_file=request["target_file"],
        used_sources=deduped_sources,
        live_status=live_status,
        warnings=warnings,
        updated_paths=[request["target_file"]],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 Design workflow skeleton")
    parser.add_argument("--hub", default=".", help="context-hub 根目录")
    parser.add_argument("--capability", required=True, help="capability slug")
    parser.add_argument("--action", required=True, choices=("create", "align", "extend", "revise"))
    parser.add_argument("--content-file", default="", help="输入草稿文件")
    parser.add_argument("--figma-url", default="", help="可选的 Figma URL")
    parser.add_argument("--output-format", default="text", choices=("text", "json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hub_root = resolve_hub_root(__file__, args.hub)
    try:
        result = run_design_workflow(
            hub_root=hub_root,
            capability=args.capability,
            action=args.action,
            content_file=args.content_file or None,
            figma_url=args.figma_url or None,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Design workflow complete: {result['capability']} -> {result['target_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
