#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import save_yaml_file
from integrations.figma_adapter import probe_figma_reference
from yaml_compat import YAMLError, safe_load


DESIGN_EXPORT_NAME = "design-fragment.yaml"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="aggregate design exports into topology/design-sources.yaml")
    parser.add_argument("hub", nargs="?", default=None, help="hub root directory, defaults to current working directory")
    parser.add_argument("--hub", dest="hub_flag", default=None, help="hub root directory, same as positional hub")
    return parser.parse_args()


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
                        raise UnsupportedExportSchemaError(f"unsupported nested structure near '{field_content}'")
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


def load_yaml_payload(path: Path) -> dict:
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
    payload = load_yaml_payload(path)
    return default if payload is None else payload


def merge_record(existing: dict | None, updates: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_record(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_named_list(existing: list[dict], updates: list[dict], *, key_field: str) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in existing or []:
        if not isinstance(item, dict):
            raise UnsupportedExportSchemaError(f"existing record must be a mapping for '{key_field}'")
        item_key = item.get(key_field)
        if not item_key:
            raise UnsupportedExportSchemaError(f"missing '{key_field}' in existing record")
        merged[str(item_key)] = dict(item)
    for item in updates or []:
        if not isinstance(item, dict):
            raise UnsupportedExportSchemaError(f"export record must be a mapping for '{key_field}'")
        item_key = item.get(key_field)
        if not item_key:
            raise UnsupportedExportSchemaError(f"missing '{key_field}' in export record")
        merged[str(item_key)] = merge_record(merged.get(str(item_key)), item)
    return [merged[name] for name in sorted(merged)]


def normalize_design_source(source: dict) -> dict:
    normalized = dict(source or {})
    figma_url = str(normalized.get("figma_url") or (normalized.get("figma") or {}).get("url") or "").strip()
    if not figma_url:
        return normalized

    probe_result = probe_figma_reference(figma_url)
    if probe_result.summary is not None:
        figma_block = {
            "url": probe_result.summary.file.url,
            "file_key": probe_result.summary.file.file_key,
            "file_title": probe_result.summary.file.file_title,
            "selection_kind": probe_result.summary.selection.kind,
        }
        if probe_result.summary.selection.node_id:
            figma_block["node_id"] = probe_result.summary.selection.node_id
    else:
        figma_block = {"url": figma_url}

    normalized["figma_url"] = figma_url
    normalized["figma"] = merge_record(
        normalized.get("figma") if isinstance(normalized.get("figma"), dict) else {},
        figma_block,
    )
    normalized["probe_status"] = probe_result.status
    if probe_result.reason:
        normalized["probe_reason"] = probe_result.reason
    return normalized


def load_design_export(hub_root: Path) -> dict:
    export_path = hub_root / "teams" / "design" / "exports" / DESIGN_EXPORT_NAME
    if not export_path.exists():
        return {}
    return load_yaml_payload(export_path)


def merge_design_payload(existing_payload: dict, export_payload: dict) -> dict:
    merged = dict(existing_payload or {})
    merged = merge_metadata(merged, extract_metadata(export_payload))

    export_sources = export_payload.get("sources") or []
    normalized_sources = [normalize_design_source(source) for source in export_sources]
    merged["sources"] = merge_named_list(
        (merged.get("sources") or []),
        normalized_sources,
        key_field="name",
    )

    for key, value in export_payload.items():
        if key in METADATA_FIELDS or key == "sources" or value in ("", None, [], {}):
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_record(merged[key], value)
        else:
            merged.setdefault(key, value)
    return merged


def sync_design_sources(hub_root: Path) -> Path:
    hub_root = Path(hub_root).resolve()
    topology_dir = hub_root / "topology"
    topology_dir.mkdir(parents=True, exist_ok=True)

    design_path = topology_dir / "design-sources.yaml"
    existing_payload = load_topology_payload(design_path, {"sources": []})
    export_payload = load_design_export(hub_root)
    design_payload = merge_design_payload(existing_payload, export_payload)
    save_yaml_file(design_path, design_payload)
    return design_path


def sync_design_context(hub_root: Path) -> Path:
    return sync_design_sources(hub_root)


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub_flag or args.hub or ".").resolve()
    try:
        result = sync_design_sources(hub_root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Design topology sync complete: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
