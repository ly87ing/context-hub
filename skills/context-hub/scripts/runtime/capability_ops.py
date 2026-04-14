from __future__ import annotations

from pathlib import Path

from yaml_compat import YAMLError, safe_load

from .hub_io import load_template, render_template
from .validation import target_document_name


DEFAULT_MAINTAINED_BY = "product"
DEFAULT_CONTRIBUTORS = ["design", "engineering", "qa"]


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
