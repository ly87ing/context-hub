#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

from _common import save_yaml_file
from update_llms_txt import refresh_llms_txt
from yaml_compat import YAMLError, safe_load


SYSTEM_EXPORT_NAME = "system-fragment.yaml"
TESTING_EXPORT_NAME = "testing-fragment.yaml"
DOMAIN_EXPORT_NAME = "domains-fragment.yaml"
DOMAIN_TEAM_IDS = ("product",)
SYSTEM_TEAM_IDS = ("engineering",)
TESTING_TEAM_IDS = ("qa",)
METADATA_FIELDS = (
    "maintained_by",
    "source_system",
    "source_ref",
    "visibility",
    "last_synced_at",
    "confidence",
)


class UnsupportedExportSchemaError(ValueError):
    pass


class ExportConflictError(ValueError):
    pass


def extract_metadata(payload: dict) -> dict:
    return {
        field: payload[field]
        for field in METADATA_FIELDS
        if field in payload and payload[field] not in ("", None)
    }


def merge_metadata(record: dict, metadata: dict) -> dict:
    merged = dict(record or {})
    for field, value in metadata.items():
        merged.setdefault(field, value)
    return merged


def parse_scalar(value: str):
    text = value.strip()
    if text in ("{}", "[]"):
        return {} if text == "{}" else []
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if text.lower() in ("null", "none"):
        return None
    return text


def parse_minimal_export_yaml(text: str) -> dict:
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))

    payload: dict = {}
    index = 0
    while index < len(lines):
        indent, content = lines[index]
        if indent != 0 or ":" not in content:
            index += 1
            continue

        key, remainder = content.split(":", 1)
        key = key.strip()
        remainder = remainder.strip()

        if remainder:
            payload[key] = parse_scalar(remainder)
            index += 1
            continue

        if key in ("services", "infrastructure", "domains"):
            container: dict[str, dict] = {}
            index += 1
            while index < len(lines):
                item_indent, item_content = lines[index]
                if item_indent < 2:
                    break
                if item_indent != 2 or ":" not in item_content:
                    index += 1
                    continue

                item_name, item_remainder = item_content.split(":", 1)
                item_name = item_name.strip()
                item_remainder = item_remainder.strip()
                item_payload: dict = {}
                if item_remainder:
                    item_payload["value"] = parse_scalar(item_remainder)
                    index += 1
                else:
                    index += 1
                    while index < len(lines):
                        field_indent, field_content = lines[index]
                        if field_indent <= 2:
                            break
                        if field_indent > 4:
                            raise UnsupportedExportSchemaError(
                                f"unsupported nested structure near '{field_content}'"
                            )
                        if field_indent == 4 and ":" in field_content:
                            field_name, field_value = field_content.split(":", 1)
                            if not field_value.strip():
                                raise UnsupportedExportSchemaError(
                                    f"unsupported nested mapping/list for '{field_name.strip()}'"
                                )
                            item_payload[field_name.strip()] = parse_scalar(field_value)
                        index += 1
                container[item_name] = item_payload
            payload[key] = container
            continue

        if key == "sources":
            sources: list[dict] = []
            index += 1
            while index < len(lines):
                item_indent, item_content = lines[index]
                if item_indent < 2:
                    break
                if item_indent != 2 or not item_content.startswith("- "):
                    index += 1
                    continue

                item_payload: dict = {}
                first_field = item_content[2:].strip()
                if first_field and ":" in first_field:
                    field_name, field_value = first_field.split(":", 1)
                    item_payload[field_name.strip()] = parse_scalar(field_value)
                index += 1
                while index < len(lines):
                    field_indent, field_content = lines[index]
                    if field_indent <= 2:
                        break
                    if field_indent > 4:
                        raise UnsupportedExportSchemaError(
                            f"unsupported nested structure near '{field_content}'"
                        )
                    if field_indent == 4 and ":" in field_content:
                        field_name, field_value = field_content.split(":", 1)
                        if not field_value.strip():
                            raise UnsupportedExportSchemaError(
                                f"unsupported nested mapping/list for '{field_name.strip()}'"
                            )
                        item_payload[field_name.strip()] = parse_scalar(field_value)
                    index += 1
                sources.append(item_payload)
            payload[key] = sources
            continue

        payload[key] = {}
        index += 1

    return payload


def load_export_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        payload = safe_load(text)
    except YAMLError:
        payload = parse_minimal_export_yaml(text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"export payload must be a mapping: {path}")
    return payload


def load_topology_payload(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    payload = load_export_payload(path)
    return default if payload is None else payload


def iter_export_payloads(
    hub_root: Path,
    filename: str,
    team_ids: tuple[str, ...] | None = None,
) -> list[tuple[Path, dict]]:
    teams_dir = hub_root / "teams"
    if team_ids:
        export_paths = [
            teams_dir / team_id / "exports" / filename
            for team_id in team_ids
        ]
    else:
        export_paths = sorted(teams_dir.glob(f"*/exports/{filename}"))
    payloads: list[tuple[Path, dict]] = []
    for export_path in export_paths:
        if not export_path.exists():
            continue
        payloads.append((export_path, load_export_payload(export_path)))
    return payloads


def merge_record(existing: dict | None, updates: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_record(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_named_records(existing: dict, updates: dict) -> dict:
    merged = {name: dict(record) for name, record in (existing or {}).items()}
    for name, record in (updates or {}).items():
        merged[name] = merge_record(merged.get(name), record)
    return dict(sorted(merged.items()))


def merge_named_list(existing: list[dict], updates: list[dict], *, key_field: str) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in existing or []:
        item_key = item.get(key_field)
        if not item_key:
            raise UnsupportedExportSchemaError(f"missing '{key_field}' in existing record")
        merged[item_key] = dict(item)
    for item in updates or []:
        item_key = item.get(key_field)
        if not item_key:
            raise UnsupportedExportSchemaError(f"missing '{key_field}' in export record")
        merged[item_key] = merge_record(merged.get(item_key), item)
    return [merged[name] for name in sorted(merged)]


def detect_conflict(
    entity_kind: str,
    entity_name: str,
    current: dict,
    incoming: dict,
    current_source: Path,
    incoming_source: Path,
) -> None:
    if current != incoming:
        raise ExportConflictError(
            f"conflicting {entity_kind} '{entity_name}' between {current_source} and {incoming_source}"
        )


def merge_system_exports(hub_root: Path, team_ids: tuple[str, ...] | None = None) -> dict:
    services: dict[str, dict] = {}
    infrastructure: dict[str, dict] = {}
    service_sources: dict[str, Path] = {}
    infrastructure_sources: dict[str, Path] = {}

    for export_path, payload in iter_export_payloads(hub_root, SYSTEM_EXPORT_NAME, team_ids=team_ids):
        metadata = extract_metadata(payload)
        for service_name, service_info in (payload.get("services") or {}).items():
            merged_service = merge_metadata(service_info, metadata)
            if service_name in services:
                detect_conflict(
                    "service",
                    service_name,
                    services[service_name],
                    merged_service,
                    service_sources[service_name],
                    export_path,
                )
            services[service_name] = merged_service
            service_sources[service_name] = export_path
        for infra_name, infra_info in (payload.get("infrastructure") or {}).items():
            merged_infra = merge_metadata(infra_info, metadata)
            if infra_name in infrastructure:
                detect_conflict(
                    "infrastructure",
                    infra_name,
                    infrastructure[infra_name],
                    merged_infra,
                    infrastructure_sources[infra_name],
                    export_path,
                )
            infrastructure[infra_name] = merged_infra
            infrastructure_sources[infra_name] = export_path

    return {
        "services": dict(sorted(services.items())),
        "infrastructure": dict(sorted(infrastructure.items())),
    }


def merge_testing_exports(hub_root: Path, team_ids: tuple[str, ...] | None = None) -> dict:
    sources: list[dict] = []

    for _path, payload in iter_export_payloads(hub_root, TESTING_EXPORT_NAME, team_ids=team_ids):
        metadata = extract_metadata(payload)
        for source in payload.get("sources") or []:
            sources.append(merge_metadata(source, metadata))

    sorted_sources = sorted(sources, key=lambda item: item.get("name", ""))
    return {"sources": sorted_sources}


def merge_domain_exports(hub_root: Path, team_ids: tuple[str, ...] | None = None) -> dict:
    domains: dict[str, dict] = {}
    domain_sources: dict[str, Path] = {}

    for export_path, payload in iter_export_payloads(hub_root, DOMAIN_EXPORT_NAME, team_ids=team_ids):
        metadata = extract_metadata(payload)
        for domain_name, domain_info in (payload.get("domains") or {}).items():
            merged_domain = merge_metadata(domain_info, metadata)
            if domain_name in domains:
                detect_conflict(
                    "domain",
                    domain_name,
                    domains[domain_name],
                    merged_domain,
                    domain_sources[domain_name],
                    export_path,
                )
            domains[domain_name] = merged_domain
            domain_sources[domain_name] = export_path

    return {"domains": dict(sorted(domains.items()))}


def merge_system_payload(existing_payload: dict, export_payload: dict) -> dict:
    return {
        "services": merge_named_records(
            (existing_payload or {}).get("services") or {},
            (export_payload or {}).get("services") or {},
        ),
        "infrastructure": merge_named_records(
            (existing_payload or {}).get("infrastructure") or {},
            (export_payload or {}).get("infrastructure") or {},
        ),
    }


def merge_domain_payload(existing_payload: dict, export_payload: dict) -> dict:
    return {
        "domains": merge_named_records(
            (existing_payload or {}).get("domains") or {},
            (export_payload or {}).get("domains") or {},
        ),
    }


def merge_testing_payload(existing_payload: dict, export_payload: dict) -> dict:
    return {
        "sources": merge_named_list(
            (existing_payload or {}).get("sources") or [],
            (export_payload or {}).get("sources") or [],
            key_field="name",
        )
    }


def validate_export_conflicts(hub_root: Path) -> None:
    # Phase 1 仍按团队边界聚合，但在刷新前先检查是否存在跨 team 的重复导出冲突。
    merge_system_exports(hub_root)
    merge_domain_exports(hub_root)


def refresh_shared_context(hub_root: Path) -> dict[str, Path]:
    hub_root = Path(hub_root).resolve()
    topology_dir = hub_root / "topology"
    topology_dir.mkdir(parents=True, exist_ok=True)
    validate_export_conflicts(hub_root)

    domains_path = topology_dir / "domains.yaml"
    system_path = topology_dir / "system.yaml"
    testing_path = topology_dir / "testing-sources.yaml"

    existing_domains = load_topology_payload(domains_path, {"domains": {}})
    existing_system = load_topology_payload(system_path, {"services": {}, "infrastructure": {}})
    existing_testing = load_topology_payload(testing_path, {"sources": []})

    domains_payload = merge_domain_payload(
        existing_domains,
        merge_domain_exports(hub_root, team_ids=DOMAIN_TEAM_IDS),
    )
    system_payload = merge_system_payload(
        existing_system,
        merge_system_exports(hub_root, team_ids=SYSTEM_TEAM_IDS),
    )
    testing_payload = merge_testing_payload(
        existing_testing,
        merge_testing_exports(hub_root, team_ids=TESTING_TEAM_IDS),
    )

    save_yaml_file(domains_path, domains_payload)
    save_yaml_file(system_path, system_payload)
    save_yaml_file(testing_path, testing_payload)
    llms_path = refresh_llms_txt(hub_root)

    return {
        "domains": domains_path,
        "system": system_path,
        "testing": testing_path,
        "llms": llms_path,
    }


def main() -> int:
    hub_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    try:
        outputs = refresh_shared_context(hub_root)
    except (UnsupportedExportSchemaError, ExportConflictError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"✅ 已刷新 {outputs['domains']}")
    print(f"✅ 已刷新 {outputs['system']}")
    print(f"✅ 已刷新 {outputs['testing']}")
    print(f"✅ 已刷新 {outputs['llms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
