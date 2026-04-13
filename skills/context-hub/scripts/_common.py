#!/usr/bin/env python3

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from runtime.hub_io import load_template, render_template, safe_write_text
from yaml_compat import safe_dump, safe_load


def normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise ValueError("值不能为空")
    return slug


def today_iso() -> str:
    return date.today().isoformat()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def unique_preserving_order(values):
    seen = set()
    unique = []
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def load_yaml_file(path: Path, default):
    if not path.exists():
        return default
    content = safe_load(path.read_text(encoding="utf-8"))
    return default if content is None else content


def save_yaml_file(path: Path, data) -> None:
    safe_write_text(path, safe_dump(data, allow_unicode=True, sort_keys=False))


def render_template_text(template: str, mapping: dict[str, str]) -> str:
    return render_template(template, mapping)


def parse_repo_entry(entry: str) -> dict[str, str]:
    if "|" in entry:
        parts = [part.strip() for part in entry.split("|")]
    else:
        parts = entry.split()

    if len(parts) < 2:
        raise ValueError(
            f"仓库条目格式错误: {entry}. 期望 name|url|domain|owner 或空格分隔的同等格式"
        )

    name = normalize_slug(parts[0])
    url = parts[1].strip()
    domain = normalize_slug(parts[2]) if len(parts) >= 3 and parts[2].strip() else "shared"
    owner = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else "待填写"
    return {
        "name": name,
        "url": url,
        "domain": domain,
        "owner": owner,
    }


def parse_test_source_entry(entry: str) -> dict[str, str]:
    if "|" in entry:
        parts = [part.strip() for part in entry.split("|")]
    else:
        parts = entry.split()

    if len(parts) < 2:
        raise ValueError(
            f"测试源条目格式错误: {entry}. 期望 name|url|type 或空格分隔的同等格式"
        )

    source_type = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else "other"
    return {
        "name": parts[0].strip(),
        "url": parts[1].strip(),
        "type": source_type,
    }


def guess_service_type(name: str, repo_url: str) -> str:
    signal = f"{name} {repo_url}".lower()
    if any(token in signal for token in ("web", "ui", "frontend", "console")):
        return "frontend"
    if "gateway" in signal:
        return "gateway"
    if "bff" in signal:
        return "bff"
    return "backend"


def build_domains_payload(repos: list[dict[str, str]]) -> dict:
    domains = {}
    for repo in repos:
        domain_name = repo["domain"]
        domain = domains.setdefault(
            domain_name,
            {
                "description": "待填写",
                "owner": repo["owner"],
                "capabilities": [],
            },
        )
        if domain["owner"] == "待填写" and repo["owner"] != "待填写":
            domain["owner"] = repo["owner"]
    return {"domains": domains}


def build_llms_text(
    project_name: str,
    summary: str,
    domains_payload: dict,
    system_payload: dict,
    testing_sources_payload: dict,
) -> str:
    domains = (domains_payload or {}).get("domains") or {}
    domain_lines = []
    if domains:
        for domain_name, domain_info in domains.items():
            capability_names = [
                capability.get("name", "unknown")
                for capability in domain_info.get("capabilities", [])
            ]
            capability_text = ", ".join(capability_names) if capability_names else "暂无能力目录"
            domain_lines.append(f"- {domain_name}: {capability_text}")
    else:
        domain_lines.append("- 暂无业务域")

    services = (system_payload or {}).get("services") or {}
    service_lines = []
    if services:
        for service_name, service_info in services.items():
            service_lines.append(
                f"- {service_name}: {service_info.get('type', 'unknown')} / {service_info.get('repo', '待补充')}"
            )
    else:
        service_lines.append("- 暂无服务清单")

    sources = (testing_sources_payload or {}).get("sources") or []
    source_lines = []
    if sources:
        for source in sources:
            source_lines.append(f"- {source.get('name', 'unknown')}: {source.get('type', 'other')}")
    else:
        source_lines.append("- 暂无测试源")

    template = load_template("llms.txt")
    return render_template(
        template,
        {
            "project_name": project_name,
            "summary": summary or "项目全局上下文入口",
            "domain_lines": "\n".join(domain_lines),
            "service_lines": "\n".join(service_lines),
            "source_lines": "\n".join(source_lines),
        },
    )


def build_identity_md(
    project_name: str,
    summary: str,
    repos: list[dict[str, str]],
    gitlab_url: str,
    ones_url: str,
    figma_url: str,
) -> str:
    domains = {}
    for repo in repos:
        domains.setdefault(repo["domain"], repo["owner"])

    domain_lines = []
    if domains:
        for domain_name, owner in domains.items():
            domain_lines.append(f"| {domain_name} | 待填写 | {owner} |")
    else:
        domain_lines.append("| shared | 待填写 | 待填写 |")

    template = load_template("identity.md")
    return render_template(
        template,
        {
            "project_name": project_name,
            "summary": summary or "待补充项目简介",
            "domain_rows": "\n".join(domain_lines),
            "gitlab_url": gitlab_url or "待填写",
            "ones_url": ones_url or "待填写",
            "figma_url": figma_url or "待填写",
        },
    )
