from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from _common import load_yaml_file, normalize_slug, render_template_text, save_yaml_file, today_iso
from yaml_compat import YAMLError, safe_load

from .hub_io import load_template, render_template
from .validation import target_document_name


DEFAULT_MAINTAINED_BY = "product"
DEFAULT_CONTRIBUTORS = ["design", "engineering", "qa"]
REQUIRED_CAPABILITY_FILES = ("spec.md", "design.md", "architecture.md", "testing.md")


def parse_ownership_contract(text: str) -> dict:
    payload = {"teams": {}, "capabilities": {}}
    current_team = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if not line.startswith(" "):
            current_team = None
            if ": " in line:
                key, value = line.split(": ", 1)
                payload[key] = value
            continue
        if line.startswith("  ") and line.strip().endswith(":") and not line.startswith("    "):
            current_team = line.strip()[:-1]
            payload["teams"][current_team] = {}
            continue
        if current_team and line.startswith("    ") and ": " in line:
            key, value = line.strip().split(": ", 1)
            payload["teams"][current_team][key] = value
    return payload


def coerce_ownership_payload(text: str) -> dict:
    try:
        payload = safe_load(text)
    except YAMLError:
        payload = parse_ownership_contract(text)
    if payload is None:
        payload = {}
    payload.setdefault("teams", {})
    payload.setdefault("capabilities", {})
    return payload


def build_initial_ownership_payload(project_id: str, project_name: str) -> dict:
    template_text = load_template("ownership.yaml")
    rendered = render_template(
        template_text,
        {
            "project_id": project_id,
            "project_name": project_name,
        },
    )
    return coerce_ownership_payload(rendered)


def load_ownership_payload(
    path: Path,
    *,
    project_id: str = "unknown",
    project_name: str = "unknown",
) -> dict:
    if path.exists():
        payload = coerce_ownership_payload(path.read_text(encoding="utf-8"))
    else:
        payload = build_initial_ownership_payload(project_id, project_name)
    return payload


def ensure_capability_ownership(
    ownership_payload: dict,
    capability_name: str,
    domain: str,
    *,
    maintained_by: str = DEFAULT_MAINTAINED_BY,
    contributors: list[str] | None = None,
) -> dict:
    capability_entry = ownership_payload.setdefault("capabilities", {}).setdefault(
        capability_name,
        {},
    )
    capability_entry["domain"] = domain
    capability_entry["maintained_by"] = maintained_by
    capability_entry["contributors"] = list(contributors or DEFAULT_CONTRIBUTORS)
    return capability_entry


def normalize_task_refs(task_refs: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for ref in task_refs or []:
        value = str(ref).strip()
        if value:
            normalized.append(value)
    return normalized


def ensure_capability_record(
    domain_payload: dict,
    capability_name: str,
    title: str,
    status: str,
    *,
    ones_tasks: list[str] | None = None,
) -> dict:
    for capability in domain_payload.get("capabilities", []):
        if capability.get("name") == capability_name:
            raise ValueError(f"能力 {capability_name} 已存在")

    capability_entry = {
        "name": capability_name,
        "description": title,
        "path": f"capabilities/{capability_name}/",
        "status": status,
    }
    capability_entry["ones_tasks"] = normalize_task_refs(ones_tasks)
    domain_payload.setdefault("capabilities", []).append(capability_entry)
    return capability_entry


def iter_capability_records(domains_payload: dict):
    for domain_name, domain_info in (domains_payload.get("domains") or {}).items():
        if not isinstance(domain_info, dict):
            continue
        for capability in domain_info.get("capabilities") or []:
            if not isinstance(capability, dict):
                continue
            capability_name = capability.get("name")
            if not capability_name:
                continue
            yield domain_name, capability_name, capability


def update_capability_record(
    capability_record: dict,
    *,
    status: str | None = None,
    last_synced_at: str | None = None,
    source_ref: str | None = None,
) -> dict:
    if status not in (None, ""):
        capability_record["status"] = status
    if last_synced_at not in (None, ""):
        capability_record["last_synced_at"] = last_synced_at
    if source_ref not in (None, ""):
        capability_record["source_ref"] = source_ref
    return capability_record


def capability_target_document_path(capability_dir: str | Path, role: str) -> Path:
    return Path(capability_dir) / target_document_name(role)


def load_capability_template_map(template_root: Path) -> dict[str, str]:
    mapping = {}
    for name in REQUIRED_CAPABILITY_FILES:
        template_path = template_root / name
        if not template_path.exists():
            raise FileNotFoundError(f"缺少模板文件: {template_path}")
        mapping[name] = template_path.read_text(encoding="utf-8")
    return mapping


def ensure_domain_record(domains_payload: dict, domain: str) -> dict:
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


def render_capability_documents(
    capability_dir: Path,
    template_map: dict[str, str],
    title: str,
    ones_tasks: list[str],
) -> list[Path]:
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

    updated_paths: list[Path] = []
    for filename, template in template_map.items():
        rendered = render_template_text(template, replacements)
        document_path = capability_dir / filename
        document_path.write_text(rendered, encoding="utf-8")
        updated_paths.append(document_path)
    return updated_paths


def bootstrap_pm_capability(
    hub_root: str | Path,
    capability_name: str,
    domain: str,
    *,
    title: str | None = None,
    status: str = "planned",
    maintained_by: str = DEFAULT_MAINTAINED_BY,
    ones_tasks: list[str] | None = None,
) -> list[Path]:
    root = Path(hub_root).resolve()
    normalized_capability_name = normalize_slug(capability_name)
    normalized_domain = normalize_slug(domain)
    capability_dir = root / "capabilities" / normalized_capability_name
    if capability_dir.exists():
        return []

    template_root = root / "capabilities" / "_templates"
    template_map = load_capability_template_map(template_root)
    capability_title = (title or normalized_capability_name).strip() or normalized_capability_name
    task_refs = normalize_task_refs(ones_tasks)

    updated_paths = render_capability_documents(capability_dir, template_map, capability_title, task_refs)

    domains_path = root / "topology" / "domains.yaml"
    domains_payload = load_yaml_file(domains_path, {"domains": {}})
    domain_payload = ensure_domain_record(domains_payload, normalized_domain)
    ensure_capability_record(
        domain_payload,
        normalized_capability_name,
        capability_title,
        status,
        ones_tasks=task_refs,
    )
    save_yaml_file(domains_path, domains_payload)

    ownership_path = root / "topology" / "ownership.yaml"
    ownership_payload = load_ownership_payload(
        ownership_path,
        project_id=root.name,
        project_name=root.name,
    )
    ensure_capability_ownership(
        ownership_payload,
        normalized_capability_name,
        normalized_domain,
        maintained_by=maintained_by,
    )
    save_yaml_file(ownership_path, ownership_payload)

    updated_paths.extend([domains_path, ownership_path])

    update_script = root / "scripts" / "update_llms_txt.py"
    if update_script.exists():
        subprocess.run(
            [sys.executable, str(update_script), str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        updated_paths.append(root / ".context" / "llms.txt")

    return updated_paths
