#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

from _common import save_yaml_file, unique_preserving_order, utc_now_iso
from integrations import gitlab_adapter
from refresh_context import load_topology_payload, merge_system_exports, merge_system_payload


ENGINEERING_TEAM_IDS = ("engineering",)
MAX_RAW_FETCHES = 4
OPENAPI_FILENAMES = {"openapi.yaml", "openapi.yml", "swagger.yaml", "swagger.yml"}
KEY_FILE_PRIORITY = (
    "pyproject.toml",
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "requirements.txt",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 2: aggregate engineering exports and enrich topology/system.yaml from GitLab repos",
    )
    parser.add_argument(
        "hub",
        nargs="?",
        default=None,
        help="hub root directory, defaults to current working directory",
    )
    parser.add_argument(
        "--hub",
        dest="hub_flag",
        default=None,
        help="hub root directory, same as positional hub",
    )
    return parser.parse_args()


def normalize_dependency_name(raw: str) -> str:
    candidate = raw.strip().strip("\"'").split(";", 1)[0].strip()
    if not candidate:
        return ""
    candidate = re.split(r"[<>=~! \[]", candidate, maxsplit=1)[0]
    return candidate.strip().lower().replace("_", "-")


def detect_lang_from_tree(tree_paths: list[str]) -> str | None:
    lower_paths = {path.lower() for path in tree_paths}
    if "pyproject.toml" in lower_paths or "requirements.txt" in lower_paths:
        return "python"
    if "package.json" in lower_paths:
        if "tsconfig.json" in lower_paths or any(path.endswith((".ts", ".tsx")) for path in lower_paths):
            return "typescript"
        return "javascript"
    if "pom.xml" in lower_paths or "build.gradle" in lower_paths or "build.gradle.kts" in lower_paths:
        return "java"
    if "go.mod" in lower_paths:
        return "go"
    return None


def parse_python_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    try:
        payload = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError:
        return None, []

    names: list[str] = []
    project = payload.get("project") if isinstance(payload, dict) else {}
    if isinstance(project, dict):
        dependencies = project.get("dependencies") or []
        names.extend(
            normalize_dependency_name(item)
            for item in dependencies
            if isinstance(item, str)
        )
        optional_dependencies = project.get("optional-dependencies") or {}
        if isinstance(optional_dependencies, dict):
            for dependency_group in optional_dependencies.values():
                if isinstance(dependency_group, list):
                    names.extend(
                        normalize_dependency_name(item)
                        for item in dependency_group
                        if isinstance(item, str)
                    )

    tool = payload.get("tool") if isinstance(payload, dict) else {}
    poetry = tool.get("poetry") if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        poetry_dependencies = poetry.get("dependencies") or {}
        if isinstance(poetry_dependencies, dict):
            names.extend(
                normalize_dependency_name(key)
                for key in poetry_dependencies
                if normalize_dependency_name(key) != "python"
            )
        poetry_groups = poetry.get("group") or {}
        if isinstance(poetry_groups, dict):
            for group in poetry_groups.values():
                if isinstance(group, dict):
                    group_dependencies = group.get("dependencies") or {}
                    if isinstance(group_dependencies, dict):
                        names.extend(
                            normalize_dependency_name(key)
                            for key in group_dependencies
                            if normalize_dependency_name(key) != "python"
                        )

    names = [name for name in names if name]

    framework = None
    for candidate in ("fastapi", "django", "flask"):
        if candidate in names:
            framework = candidate
            break

    depends_on = [name for name in names if name != framework]
    return framework, unique_preserving_order(depends_on)


def parse_package_json_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, []
    dependencies = {}
    if isinstance(payload, dict):
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            value = payload.get(key)
            if isinstance(value, dict):
                dependencies.update(value)
    names = unique_preserving_order(normalize_dependency_name(name) for name in dependencies)
    framework = None
    for candidate in ("next", "react", "vue", "nestjs", "express"):
        if candidate in names:
            framework = candidate
            break
    depends_on = [name for name in names if name != framework]
    return framework, depends_on


def parse_requirements_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    names = [
        normalize_dependency_name(line)
        for line in raw_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    names = [name for name in names if name]
    framework = None
    for candidate in ("fastapi", "django", "flask"):
        if candidate in names:
            framework = candidate
            break
    return framework, [name for name in names if name != framework]


def parse_pom_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    lowered = raw_text.lower()
    depends_on = []
    if "spring-boot" in lowered:
        framework = "spring-boot"
    else:
        framework = None
    for candidate in ("kafka", "redis", "mysql", "postgresql", "mongodb"):
        if candidate in lowered:
            depends_on.append(candidate)
    return framework, unique_preserving_order(depends_on)


def parse_gradle_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    return parse_pom_metadata(raw_text)


def parse_go_metadata(raw_text: str) -> tuple[str | None, list[str]]:
    lowered = raw_text.lower()
    framework = "gin" if "github.com/gin-gonic/gin" in lowered else None
    depends_on = []
    for candidate in ("redis", "kafka", "mysql", "postgres"):
        if candidate in lowered:
            depends_on.append(candidate)
    return framework, unique_preserving_order(depends_on)


def infer_metadata_from_files(tree_paths: list[str], file_payloads: dict[str, str]) -> dict[str, object]:
    lang = detect_lang_from_tree(tree_paths)
    framework = None
    depends_on: list[str] = []
    provides: list[str] = []

    for path, payload in file_payloads.items():
        filename = Path(path).name.lower()
        if filename == "pyproject.toml":
            framework, depends_on = parse_python_metadata(payload)
        elif filename == "package.json":
            framework, depends_on = parse_package_json_metadata(payload)
        elif filename == "requirements.txt":
            framework, depends_on = parse_requirements_metadata(payload)
        elif filename == "pom.xml":
            framework, depends_on = parse_pom_metadata(payload)
        elif filename in {"build.gradle", "build.gradle.kts"}:
            framework, depends_on = parse_gradle_metadata(payload)
        elif filename == "go.mod":
            framework, depends_on = parse_go_metadata(payload)

    lower_paths = {path.lower() for path in tree_paths}
    if any(Path(path).name.lower() in OPENAPI_FILENAMES or path.lower().endswith(".proto") for path in tree_paths):
        provides.append("api")
    elif framework in {"fastapi", "django", "flask", "spring-boot", "express", "nestjs", "gin"}:
        provides.append("api")

    return {
        "lang": lang or "unknown",
        "framework": framework or "unknown",
        "depends_on": unique_preserving_order(depends_on),
        "provides": unique_preserving_order(provides),
    }


def candidate_files_for_fetch(tree_paths: list[str]) -> list[str]:
    lower_lookup = {path.lower(): path for path in tree_paths}
    selected: list[str] = []
    for filename in KEY_FILE_PRIORITY:
        original = lower_lookup.get(filename)
        if original:
            selected.append(original)
    return selected[:MAX_RAW_FETCHES]


def scan_repo_summary(service: dict[str, object]) -> dict[str, object] | None:
    repo_url = str(service.get("repo") or "").strip()
    if not repo_url:
        return None

    try:
        project = gitlab_adapter.lookup_project(repo_url)
        tree = gitlab_adapter.get_tree(project, gitlab_url=repo_url)
    except ValueError:
        return None

    tree_paths = [
        str(item.get("path", "")).strip()
        for item in tree
        if isinstance(item, dict) and str(item.get("type", "blob")) == "blob" and str(item.get("path", "")).strip()
    ]
    file_payloads: dict[str, str] = {}
    for file_path in candidate_files_for_fetch(tree_paths):
        try:
            file_payloads[file_path] = gitlab_adapter.get_file_raw(project, file_path, gitlab_url=repo_url)
        except ValueError:
            return None
        except Exception:
            continue

    inferred = infer_metadata_from_files(tree_paths, file_payloads)
    return {
        **inferred,
        "default_branch": gitlab_adapter.get_default_branch(project),
        "source_system": "gitlab",
        "source_ref": str(project.get("path_with_namespace") or project.get("full_path") or ""),
        "last_synced_at": utc_now_iso(),
        "confidence": "high" if inferred["framework"] != "unknown" else "medium",
    }


def merge_service_summary(existing: dict[str, object], summary: dict[str, object]) -> dict[str, object]:
    merged = dict(existing)
    for key in ("lang", "framework", "default_branch", "source_system", "source_ref", "last_synced_at", "confidence"):
        value = summary.get(key)
        if value not in ("", None):
            merged[key] = value
    for key in ("provides", "depends_on"):
        value = summary.get(key)
        if isinstance(value, list) and value:
            merged[key] = value
    return merged


def sync_system_topology(hub_root: Path) -> Path:
    hub_root = Path(hub_root).resolve()
    topology_dir = hub_root / "topology"
    topology_dir.mkdir(parents=True, exist_ok=True)

    system_path = topology_dir / "system.yaml"
    existing_payload = load_topology_payload(system_path, {"services": {}, "infrastructure": {}})
    export_payload = merge_system_exports(hub_root, team_ids=ENGINEERING_TEAM_IDS)
    system_payload = merge_system_payload(existing_payload, export_payload)

    services = system_payload.get("services") or {}
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        summary = scan_repo_summary(service)
        if summary is None:
            continue
        services[service_name] = merge_service_summary(service, summary)

    save_yaml_file(system_path, system_payload)
    return system_path


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub_flag or args.hub or ".").resolve()
    try:
        system_path = sync_system_topology(hub_root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"GitLab topology sync complete: {system_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
