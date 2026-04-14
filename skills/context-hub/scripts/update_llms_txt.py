#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path

from _common import load_yaml_file
from runtime.hub_io import load_template, render_template, safe_write_text


def parse_identity(identity_path: Path) -> tuple[str, str]:
    if not identity_path.exists():
        return "Context Hub", "项目全局上下文入口"

    content = identity_path.read_text(encoding="utf-8").splitlines()
    title = "Context Hub"
    summary = "项目全局上下文入口"

    for line in content:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    for line in content:
        if line.strip().startswith(">"):
            summary = re.sub(r"^\s*>\s*", "", line).strip()
            break

    return title, summary


def format_metadata_suffix(payload: dict) -> str:
    parts: list[str] = []
    maintained_by = payload.get("maintained_by")
    last_synced_at = payload.get("last_synced_at")

    if maintained_by:
        parts.append(f"maintained by {maintained_by}")
    if last_synced_at:
        parts.append(f"freshness: {last_synced_at}")

    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def build_domain_lines(domains_payload: dict) -> str:
    domains = (domains_payload or {}).get("domains") or {}
    if not domains:
        return "- 暂无业务域"

    lines = []
    for domain_name, domain_info in sorted(domains.items()):
        description = domain_info.get("description", "待补充")
        capability_names = [
            capability.get("name", "unknown")
            for capability in domain_info.get("capabilities", [])
        ]
        capability_text = ", ".join(capability_names) if capability_names else "暂无能力目录"
        lines.append(
            f"- {domain_name}: {description} / {capability_text}{format_metadata_suffix(domain_info)}"
        )
    return "\n".join(lines)


def build_service_lines(system_payload: dict) -> str:
    services = (system_payload or {}).get("services") or {}
    if not services:
        return "- 暂无服务清单"

    lines = []
    for service_name, service_info in sorted(services.items()):
        service_type = service_info.get("type", "unknown")
        repo = service_info.get("repo", "待补充")
        lines.append(
            f"- {service_name}: {service_type} / {repo}{format_metadata_suffix(service_info)}"
        )
    return "\n".join(lines)


def build_source_lines(testing_payload: dict) -> str:
    sources = (testing_payload or {}).get("sources") or []
    if not sources:
        return "- 暂无测试源"

    lines = []
    sorted_sources = sorted(sources, key=lambda item: item.get("name", ""))
    for source in sorted_sources:
        source_name = source.get("name", "unknown")
        source_type = source.get("type", "other")
        url = source.get("url")
        location = f" / {url}" if url else ""
        lines.append(
            f"- {source_name}: {source_type}{location}{format_metadata_suffix(source)}"
        )
    return "\n".join(lines)


def build_design_lines(design_payload: dict) -> str:
    sources = (design_payload or {}).get("sources") or []
    if not sources:
        return "- 暂无设计源"

    lines = []
    sorted_sources = sorted(sources, key=lambda item: item.get("name", ""))
    for source in sorted_sources:
        name = source.get("name", "unknown")
        capability = source.get("capability", "unknown")
        status = source.get("status", "unknown")
        figma = source.get("figma") or {}
        title = figma.get("file_title")
        suffix = f" / {title}" if title else ""
        lines.append(
            f"- {name}: {capability} / {status}{suffix}{format_metadata_suffix(source)}"
        )
    return "\n".join(lines)


def build_release_lines(release_payload: dict) -> str:
    releases = (release_payload or {}).get("releases") or []
    if not releases:
        return "- 暂无发布索引"

    lines = []
    for release in releases:
        capability_names = ", ".join(release.get("capabilities") or []) or "暂无 capability"
        lines.append(
            f"- {release.get('release', 'unassigned')} / {release.get('iteration', 'backlog')}: "
            f"{capability_names}"
        )
    return "\n".join(lines)


def render_llms_text(
    project_name: str,
    summary: str,
    domains_payload: dict,
    system_payload: dict,
    testing_payload: dict,
    design_payload: dict,
    release_payload: dict,
) -> str:
    template = load_template("llms.txt")
    return render_template(
        template,
        {
            "project_name": project_name,
            "summary": summary or "项目全局上下文入口",
            "domain_lines": build_domain_lines(domains_payload),
            "service_lines": build_service_lines(system_payload),
            "source_lines": build_source_lines(testing_payload),
            "design_lines": build_design_lines(design_payload),
            "release_lines": build_release_lines(release_payload),
        },
    )


def refresh_llms_txt(hub_root: Path) -> Path:
    hub_root = Path(hub_root).resolve()
    identity_path = hub_root / "IDENTITY.md"
    title, summary = parse_identity(identity_path)

    domains_payload = load_yaml_file(hub_root / "topology" / "domains.yaml", {"domains": {}})
    system_payload = load_yaml_file(
        hub_root / "topology" / "system.yaml",
        {"services": {}, "infrastructure": {}},
    )
    testing_payload = load_yaml_file(
        hub_root / "topology" / "testing-sources.yaml",
        {"sources": []},
    )
    design_payload = load_yaml_file(
        hub_root / "topology" / "design-sources.yaml",
        {"sources": []},
    )
    release_payload = load_yaml_file(
        hub_root / "topology" / "releases.yaml",
        {"releases": []},
    )

    llms_text = render_llms_text(
        title,
        summary,
        domains_payload,
        system_payload,
        testing_payload,
        design_payload,
        release_payload,
    )
    target = hub_root / ".context" / "llms.txt"
    safe_write_text(target, llms_text)
    return target


def main() -> int:
    hub_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    target = refresh_llms_txt(hub_root)
    print(f"✅ 已更新 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
