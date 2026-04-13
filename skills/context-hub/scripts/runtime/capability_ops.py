from __future__ import annotations

from pathlib import Path

from yaml_compat import YAMLError, safe_load

from .hub_io import load_template, render_template


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
