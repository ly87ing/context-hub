from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from _common import normalize_slug, save_yaml_file, utc_now_iso

from .iteration_index import DEFAULT_ITERATION, DEFAULT_RELEASE, load_iteration_index
from .validation import load_yaml_mapping, relative_path


SPEC_STATUS_KEYWORDS = ("status", "状态")
SPEC_ITERATION_KEYWORDS = ("iteration", "迭代")
SPEC_RELEASE_KEYWORDS = ("release", "版本")
DESIGN_STATE_KEYWORDS = ("状态矩阵", "state matrix", "status matrix")
ARCHITECTURE_SERVICE_KEYWORDS = ("涉及的服务", "services")
TESTING_REFERENCE_KEYWORDS = ("环境要求", "数据准备", "test environment")


def semantic_consistency_path(capability_dir: str | Path) -> Path:
    return Path(capability_dir) / "semantic-consistency.yaml"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _normalize_status(value: object) -> str:
    text = _normalize_text(str(value))
    text = text.replace("_", "-")
    return re.sub(r"-{2,}", "-", text)


def _is_placeholder(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return True
    if "{" in text or "}" in text:
        return True
    return text.lower() in {
        "待填写",
        "待补充",
        "暂无",
        "unknown",
        "tbd",
        "service/team",
        "服务/中间件",
        "需要真实环境 or 可 mock",
    }


def _split_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|") if cell.strip()]


def _first_table_cell(line: str) -> str | None:
    if not line.strip().startswith("|"):
        return None
    cells = _split_table_cells(line)
    if not cells:
        return None
    first = cells[0]
    if first.startswith(":") or set(first) <= {"-", ":"}:
        return None
    return first


def _heading_match(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _iter_markdown_lines(text: str):
    stack: list[str] = []
    for raw_line in text.splitlines():
        heading = _heading_match(raw_line)
        if heading:
            level, title = heading
            stack = stack[: level - 1] + [title]
            yield "heading", list(stack), raw_line
            continue
        yield "line", list(stack), raw_line


def _section_active(stack: list[str], keywords: Iterable[str]) -> bool:
    lowered_stack = [entry.lower() for entry in stack]
    return any(any(keyword.lower() in title for title in lowered_stack) for keyword in keywords)


def _collect_section_values(
    text: str,
    section_keywords: Iterable[str],
    *,
    include_bullets: bool = False,
    include_inline_refs: bool = False,
    header_skip_values: Iterable[str] = (),
) -> list[str]:
    header_skip = {str(value).strip().lower() for value in header_skip_values}
    values: list[str] = []
    for kind, stack, raw_line in _iter_markdown_lines(text):
        if kind != "line" or not _section_active(stack, section_keywords):
            continue
        stripped = raw_line.strip()
        if not stripped:
            continue

        candidate: str | None = None
        if stripped.startswith("|"):
            candidate = _first_table_cell(stripped)
        elif include_bullets and stripped.startswith("- "):
            candidate = stripped[2:].strip()
        elif include_inline_refs:
            inline_match = re.search(
                r"(?:source|env|environment|来源|环境)\s*[:：]\s*([^\s,，;；|]+)",
                stripped,
                flags=re.IGNORECASE,
            )
            if inline_match:
                candidate = inline_match.group(1).strip()

        if not candidate:
            continue
        lowered_candidate = candidate.strip().lower()
        if lowered_candidate in header_skip or _is_placeholder(candidate):
            continue
        values.append(candidate.strip())
    return values


def _extract_section_scalar(text: str, section_keywords: Iterable[str]) -> str | None:
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        heading = _heading_match(raw_line)
        if not heading:
            continue
        _, title = heading
        if not any(keyword.lower() in title.lower() for keyword in section_keywords):
            continue
        for following in lines[index + 1 :]:
            if _heading_match(following):
                break
            stripped = following.strip()
            if not stripped:
                continue
            if stripped.startswith("|"):
                candidate = _first_table_cell(stripped)
            elif stripped.startswith("- "):
                candidate = stripped[2:].strip()
            else:
                candidate = stripped
            if not candidate or _is_placeholder(candidate):
                continue
            return candidate.strip()
    return None


def _unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _load_mapping_or_default(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    payload = load_yaml_mapping(path)
    return payload if payload is not None else dict(default)


def _iter_capability_dirs(hub_root: Path, capability: str | None = None) -> list[Path]:
    capability_root = hub_root / "capabilities"
    if capability is not None:
        capability_dir = capability_root / normalize_slug(capability)
        if not capability_dir.exists():
            raise ValueError(f"capability 不存在: {normalize_slug(capability)}")
        return [capability_dir]
    if not capability_root.exists():
        return []
    return sorted(
        path
        for path in capability_root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


def _issue(
    *,
    rule_id: str,
    severity: str,
    capability: str,
    message: str,
    source_files: list[str],
    suggested_role: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "capability": capability,
        "message": message,
        "source_files": source_files,
        "suggested_role": suggested_role,
        "evidence": evidence,
    }


def _check_spec_source_summary_status(capability_dir: Path) -> list[dict[str, object]]:
    spec_path = capability_dir / "spec.md"
    summary_path = capability_dir / "source-summary.yaml"
    if not spec_path.exists() or not summary_path.exists():
        return []

    spec_status = _extract_section_scalar(spec_path.read_text(encoding="utf-8"), SPEC_STATUS_KEYWORDS)
    summary_payload = load_yaml_mapping(summary_path)
    summary_status = summary_payload.get("status")
    if spec_status in ("", None) or summary_status in ("", None):
        return []

    normalized_spec_status = _normalize_status(spec_status)
    normalized_summary_status = _normalize_status(summary_status)
    if normalized_spec_status == normalized_summary_status:
        return []

    return [
        _issue(
            rule_id="spec-source-summary-status",
            severity="warning",
            capability=capability_dir.name,
            message=f"spec 状态 {normalized_spec_status} 与 source-summary 状态 {normalized_summary_status} 不一致",
            source_files=[
                relative_path(spec_path, capability_dir.parent.parent),
                relative_path(summary_path, capability_dir.parent.parent),
            ],
            suggested_role="pm",
            evidence={
                "spec_status": normalized_spec_status,
                "source_summary_status": normalized_summary_status,
            },
        )
    ]


def _check_design_testing_state_coverage(capability_dir: Path) -> list[dict[str, object]]:
    design_path = capability_dir / "design.md"
    testing_path = capability_dir / "testing.md"
    if not design_path.exists() or not testing_path.exists():
        return []

    design_states = _unique_preserving_order(
        _collect_section_values(
            design_path.read_text(encoding="utf-8"),
            DESIGN_STATE_KEYWORDS,
            include_bullets=True,
            header_skip_values=("状态", "state", "description", "描述", "进入条件", "退出条件"),
        )
    )
    if not design_states:
        return []

    testing_text = testing_path.read_text(encoding="utf-8").lower()
    missing_states: list[str] = []
    for state in design_states:
        normalized_state = _normalize_text(state)
        if re.search(rf"(?<!\w){re.escape(normalized_state)}(?!\w)", testing_text) is None:
            missing_states.append(state)
    if not missing_states:
        return []

    return [
        _issue(
            rule_id="design-testing-state-coverage",
            severity="blocking",
            capability=capability_dir.name,
            message=f"testing.md 未覆盖 design.md 中的关键状态: {', '.join(missing_states)}",
            source_files=[
                relative_path(design_path, capability_dir.parent.parent),
                relative_path(testing_path, capability_dir.parent.parent),
            ],
            suggested_role="qa",
            evidence={
                "design_states": design_states,
                "missing_states": missing_states,
            },
        )
    ]


def _check_architecture_system_services(capability_dir: Path, system_services: set[str]) -> list[dict[str, object]]:
    architecture_path = capability_dir / "architecture.md"
    if not architecture_path.exists():
        return []

    services = _unique_preserving_order(
        _collect_section_values(
            architecture_path.read_text(encoding="utf-8"),
            ARCHITECTURE_SERVICE_KEYWORDS,
            include_bullets=True,
            header_skip_values=("服务", "service", "变更类型", "说明", "备注"),
        )
    )
    missing_services = [service for service in services if _normalize_text(service) not in system_services]
    if not missing_services:
        return []

    return [
        _issue(
            rule_id="architecture-system-service-reference",
            severity="blocking",
            capability=capability_dir.name,
            message=f"architecture.md 引用了 system.yaml 中不存在的服务: {', '.join(missing_services)}",
            source_files=[
                relative_path(architecture_path, capability_dir.parent.parent),
                "topology/system.yaml",
            ],
            suggested_role="engineering",
            evidence={
                "architecture_services": services,
                "missing_services": missing_services,
            },
        )
    ]


def _check_testing_sources(capability_dir: Path, testing_source_names: set[str]) -> list[dict[str, object]]:
    testing_path = capability_dir / "testing.md"
    if not testing_path.exists():
        return []

    references = _unique_preserving_order(
        _collect_section_values(
            testing_path.read_text(encoding="utf-8"),
            TESTING_REFERENCE_KEYWORDS,
            include_bullets=True,
            include_inline_refs=True,
            header_skip_values=(
                "依赖",
                "服务/中间件",
                "需要真实环境 or 可 mock",
                "source",
                "env",
                "environment",
                "环境",
                "数据准备",
                "测试环境",
                "来源",
            ),
        )
    )
    missing_sources = [
        reference for reference in references if _normalize_text(reference) not in testing_source_names
    ]
    if not missing_sources:
        return []

    return [
        _issue(
            rule_id="testing-sources-reference",
            severity="blocking",
            capability=capability_dir.name,
            message=f"testing.md 引用了 testing-sources.yaml 中不存在的 source/env: {', '.join(missing_sources)}",
            source_files=[
                relative_path(testing_path, capability_dir.parent.parent),
                "topology/testing-sources.yaml",
            ],
            suggested_role="qa",
            evidence={
                "testing_references": references,
                "missing_sources": missing_sources,
            },
        )
    ]


def _check_iteration_index_alignment(capability_dir: Path) -> list[dict[str, object]]:
    spec_path = capability_dir / "spec.md"
    if not spec_path.exists():
        return []
    iteration_index = load_iteration_index(capability_dir)
    if not iteration_index:
        return []

    spec_text = spec_path.read_text(encoding="utf-8")
    spec_iteration = _extract_section_scalar(spec_text, SPEC_ITERATION_KEYWORDS)
    spec_release = _extract_section_scalar(spec_text, SPEC_RELEASE_KEYWORDS)
    current = iteration_index.get("current") or {}
    current_iteration = str(current.get("iteration") or DEFAULT_ITERATION).strip() or DEFAULT_ITERATION
    current_release = str(current.get("release") or DEFAULT_RELEASE).strip() or DEFAULT_RELEASE

    issues: list[dict[str, object]] = []
    if spec_iteration and _normalize_text(spec_iteration) != _normalize_text(current_iteration):
        issues.append(
            _issue(
                rule_id="spec-iteration-index-drift",
                severity="warning",
                capability=capability_dir.name,
                message=f"spec.md 中的 iteration {spec_iteration} 与 iteration-index 当前值 {current_iteration} 不一致",
                source_files=[
                    relative_path(spec_path, capability_dir.parent.parent),
                    relative_path(capability_dir / "iteration-index.yaml", capability_dir.parent.parent),
                ],
                suggested_role="pm",
                evidence={
                    "spec_iteration": spec_iteration,
                    "current_iteration": current_iteration,
                },
            )
        )
    if spec_release and _normalize_text(spec_release) != _normalize_text(current_release):
        issues.append(
            _issue(
                rule_id="spec-release-index-drift",
                severity="warning",
                capability=capability_dir.name,
                message=f"spec.md 中的 release {spec_release} 与 iteration-index 当前值 {current_release} 不一致",
                source_files=[
                    relative_path(spec_path, capability_dir.parent.parent),
                    relative_path(capability_dir / "iteration-index.yaml", capability_dir.parent.parent),
                ],
                suggested_role="pm",
                evidence={
                    "spec_release": spec_release,
                    "current_release": current_release,
                },
            )
        )
    return issues


def audit_capability_semantics(hub_root: str | Path, capability: str) -> dict[str, object]:
    root = Path(hub_root).resolve()
    capability_dir = root / "capabilities" / normalize_slug(capability)
    if not capability_dir.exists():
        raise ValueError(f"capability 不存在: {normalize_slug(capability)}")

    system_payload = _load_mapping_or_default(root / "topology" / "system.yaml", {"services": {}})
    testing_payload = _load_mapping_or_default(root / "topology" / "testing-sources.yaml", {"sources": []})
    system_services = {
        _normalize_text(service_name)
        for service_name in (system_payload.get("services") or {}).keys()
    }
    testing_source_names = {
        _normalize_text(source.get("name") or "")
        for source in (testing_payload.get("sources") or [])
        if isinstance(source, dict)
    }

    issues: list[dict[str, object]] = []
    for checker in (
        _check_spec_source_summary_status(capability_dir),
        _check_design_testing_state_coverage(capability_dir),
        _check_architecture_system_services(capability_dir, system_services),
        _check_testing_sources(capability_dir, testing_source_names),
        _check_iteration_index_alignment(capability_dir),
    ):
        issues.extend(checker)

    blocking_issue_count = sum(
        1 for issue in issues if str(issue.get("severity") or "").strip().lower() in {"blocking", "error"}
    )
    warning_issue_count = len(issues) - blocking_issue_count
    status = "pass"
    if blocking_issue_count:
        status = "fail"
    elif warning_issue_count:
        status = "warn"

    return {
        "capability": capability_dir.name,
        "audited_at": utc_now_iso(),
        "status": status,
        "issues": issues,
        "blocking_issue_count": blocking_issue_count,
        "warning_issue_count": warning_issue_count,
        "summary": {
            "issue_count": len(issues),
            "error_count": blocking_issue_count,
            "warning_count": warning_issue_count,
        },
    }


def build_semantic_consistency_audit(
    hub_root: str | Path,
    capability: str | None = None,
) -> dict[str, object]:
    root = Path(hub_root).resolve()
    if capability is not None:
        payload = audit_capability_semantics(root, capability)
        return {
            "generated_at": payload["audited_at"],
            "scope": {"hub": str(root), "capability": payload["capability"]},
            "status": payload["status"],
            "summary": payload["summary"],
            "issues": payload["issues"],
        }

    issues: list[dict[str, object]] = []
    blocking_issue_count = 0
    warning_issue_count = 0
    for capability_dir in _iter_capability_dirs(root):
        payload = audit_capability_semantics(root, capability_dir.name)
        issues.extend(payload["issues"])
        blocking_issue_count += int(payload["blocking_issue_count"])
        warning_issue_count += int(payload["warning_issue_count"])

    status = "pass"
    if blocking_issue_count:
        status = "fail"
    elif warning_issue_count:
        status = "warn"

    return {
        "generated_at": utc_now_iso(),
        "scope": {"hub": str(root), "capability": None},
        "status": status,
        "summary": {
            "issue_count": len(issues),
            "error_count": blocking_issue_count,
            "warning_count": warning_issue_count,
        },
        "issues": issues,
    }


def write_semantic_consistency_audit(payload: dict[str, object], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_yaml_file(path, payload)
    return path

