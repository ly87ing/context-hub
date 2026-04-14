from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path

import yaml_compat
from yaml_compat import YAMLError


REQUIRED_EXPORT_FIELDS = (
    "maintained_by",
    "source_system",
    "source_ref",
    "visibility",
    "last_synced_at",
    "confidence",
)
DEFAULT_TEAM_EXPORT_DIRS = {
    "product": "teams/product/exports",
    "design": "teams/design/exports",
    "engineering": "teams/engineering/exports",
    "qa": "teams/qa/exports",
}
REQUIRED_CAPABILITY_FILES = ("spec.md", "design.md", "architecture.md", "testing.md")
FALLBACK_SCHEMA_FILENAMES = {
    "system.yaml",
    "domains.yaml",
    "testing-sources.yaml",
    "design-sources.yaml",
    "releases.yaml",
    "lifecycle-state.yaml",
    "semantic-consistency.yaml",
    "system-fragment.yaml",
    "design-fragment.yaml",
    "domains-fragment.yaml",
    "testing-fragment.yaml",
}
MUTATING_ACTIONS = {"create", "extend", "revise", "align"}
ROLE_ALIASES = {
    "pm": "pm",
    "product": "pm",
    "ux": "design",
    "design": "design",
    "设计": "design",
    "研发": "engineering",
    "engineering": "engineering",
    "qa": "qa",
}
ROLE_TARGET_DOCUMENTS = {
    "pm": "spec.md",
    "design": "design.md",
    "engineering": "architecture.md",
    "qa": "testing.md",
}


def default_hub_root(script_file: str | Path) -> Path:
    return Path(script_file).resolve().parent.parent


def looks_like_hub_root(path: Path) -> bool:
    path = Path(path).resolve()
    return (
        (path / "topology").is_dir()
        and (path / "capabilities").is_dir()
        and (path / "teams").is_dir()
        and (path / ".context").is_dir()
    )


def resolve_hub_root(
    script_file: str | Path,
    hub_root: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
) -> Path:
    if hub_root:
        return Path(hub_root).resolve()
    current = Path(cwd or Path.cwd()).resolve()
    if looks_like_hub_root(current):
        return current
    return default_hub_root(script_file)


def relative_path(path: Path, hub_root: Path) -> str:
    try:
        return path.resolve().relative_to(hub_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def normalize_role(value: str) -> str:
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError("role 不能为空")
    normalized = ROLE_ALIASES.get(raw_value)
    if normalized is not None:
        return normalized
    normalized = ROLE_ALIASES.get(raw_value.lower())
    if normalized is not None:
        return normalized
    raise ValueError(f"unsupported role: {raw_value}")


def target_document_name(role: str) -> str:
    normalized_role = normalize_role(role)
    try:
        return ROLE_TARGET_DOCUMENTS[normalized_role]
    except KeyError as exc:
        raise ValueError(f"unsupported role: {role}") from exc


def load_yaml_mapping(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"{path} 不存在") from exc
    try:
        payload = yaml_compat.safe_load(text)
    except YAMLError as exc:
        if yaml_compat._yaml is not None:
            raise ValueError(f"{path} YAML 格式错误: {exc}") from exc
        if not allows_minimal_yaml_fallback(path):
            raise ValueError(
                f"{path} 需要标准 YAML parser；当前环境不支持该文件的简化 fallback，请安装 PyYAML"
            ) from exc
        try:
            payload = parse_minimal_mapping(text)
        except ValueError as fallback_exc:
            raise ValueError(f"{path} YAML 格式错误: {exc}") from fallback_exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 YAML mapping")
    return payload


def allows_minimal_yaml_fallback(path: Path) -> bool:
    return path.name in FALLBACK_SCHEMA_FILENAMES


def parse_freshness(value) -> datetime:
    if value in ("", None):
        raise ValueError("last_synced_at 缺失")

    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("last_synced_at 缺失")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"last_synced_at 无法解析: {value}") from exc

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_freshness(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_team_export_dirs(
    hub_root: Path,
    ownership_payload: dict | None = None,
) -> list[tuple[str, Path]]:
    payload = ownership_payload or {}
    teams = payload.get("teams")
    export_dirs: list[tuple[str, Path]] = []

    if isinstance(teams, dict) and teams:
        for team_id in sorted(teams):
            team_info = teams.get(team_id) or {}
            if not isinstance(team_info, dict):
                export_dir = DEFAULT_TEAM_EXPORT_DIRS.get(team_id, f"teams/{team_id}/exports")
            else:
                export_dir = team_info.get("exports_dir") or DEFAULT_TEAM_EXPORT_DIRS.get(
                    team_id,
                    f"teams/{team_id}/exports",
                )
            export_dirs.append((team_id, hub_root / export_dir))
        return export_dirs

    for team_id, export_dir in DEFAULT_TEAM_EXPORT_DIRS.items():
        export_dirs.append((team_id, hub_root / export_dir))
    return export_dirs


def locate_export_files(
    hub_root: Path,
    ownership_payload: dict | None = None,
) -> list[tuple[str, Path]]:
    export_files: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for team_id, export_dir in iter_team_export_dirs(hub_root, ownership_payload):
        if not export_dir.exists():
            continue
        for pattern in ("*.yaml", "*.yml"):
            for export_path in sorted(export_dir.glob(pattern)):
                resolved = export_path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                export_files.append((team_id, export_path))
    return export_files


def missing_export_fields(payload: dict) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_EXPORT_FIELDS:
        if payload.get(field) in ("", None):
            missing.append(field)
    return missing


def require_mutation_content_file(action: str, content_file: str | Path | None) -> Path | None:
    normalized_action = str(action).strip().lower()
    if normalized_action in MUTATING_ACTIONS and content_file in (None, ""):
        raise ValueError(f"{normalized_action} action requires content-file")
    if content_file in (None, ""):
        return None
    return Path(content_file)


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


def parse_minimal_mapping(text: str) -> dict:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, stripped))

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
                item_payload: dict = {}
                if item_remainder.strip():
                    item_payload["value"] = parse_scalar(item_remainder)
                    index += 1
                else:
                    index += 1
                    while index < len(lines):
                        field_indent, field_content = lines[index]
                        if field_indent <= 2:
                            break
                        if field_indent != 4 or ":" not in field_content:
                            raise ValueError(f"不支持的 YAML 结构: {field_content}")
                        field_name, field_value = field_content.split(":", 1)
                        if not field_value.strip():
                            raise ValueError(f"不支持的嵌套字段: {field_name.strip()}")
                        item_payload[field_name.strip()] = parse_scalar(field_value)
                        index += 1
                container[item_name.strip()] = item_payload
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
                    if field_indent != 4 or ":" not in field_content:
                        raise ValueError(f"不支持的 YAML 结构: {field_content}")
                    field_name, field_value = field_content.split(":", 1)
                    if not field_value.strip():
                        raise ValueError(f"不支持的嵌套字段: {field_name.strip()}")
                    item_payload[field_name.strip()] = parse_scalar(field_value)
                    index += 1
                sources.append(item_payload)
            payload[key] = sources
            continue

        payload[key] = {}
        index += 1

    return payload
