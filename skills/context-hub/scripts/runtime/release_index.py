from __future__ import annotations

from pathlib import Path

from _common import save_yaml_file, utc_now_iso

from .iteration_index import DEFAULT_ITERATION, DEFAULT_RELEASE, load_iteration_index
from .lifecycle_state import load_lifecycle_state
from .validation import relative_path


RELEASE_INDEX_FILENAME = "releases.yaml"


def release_index_path(hub_root: str | Path) -> Path:
    return Path(hub_root) / "topology" / RELEASE_INDEX_FILENAME


def _iter_capability_dirs(hub_root: Path) -> list[Path]:
    capability_root = hub_root / "capabilities"
    if not capability_root.exists():
        return []
    return sorted(
        path
        for path in capability_root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


def build_release_index(hub_root: str | Path) -> dict[str, object]:
    root = Path(hub_root).resolve()
    grouped: dict[tuple[str, str], dict[str, object]] = {}

    for capability_dir in _iter_capability_dirs(root):
        capability_name = capability_dir.name
        iteration_payload = load_iteration_index(capability_dir) or {}
        current_index = iteration_payload.get("current") or {}
        lifecycle_payload = load_lifecycle_state(capability_dir) or {}

        iteration = str(current_index.get("iteration") or DEFAULT_ITERATION).strip() or DEFAULT_ITERATION
        release = str(current_index.get("release") or DEFAULT_RELEASE).strip() or DEFAULT_RELEASE
        group_key = (release, iteration)

        entry = grouped.setdefault(
            group_key,
            {
                "release": release,
                "iteration": iteration,
                "capabilities": [],
                "items": [],
            },
        )
        entry["capabilities"].append(capability_name)
        entry["items"].append(
            {
                "capability": capability_name,
                "path": relative_path(capability_dir, root) + "/",
                "source_ref": current_index.get("source_ref") or "",
                "source_action": current_index.get("source_action") or "",
                "updated_at": current_index.get("updated_at") or lifecycle_payload.get("updated_at") or "",
                "platform_status": lifecycle_payload.get("platform_status") or "unknown",
                "current_role": lifecycle_payload.get("current_role") or "",
                "next_role": lifecycle_payload.get("next_role") or "",
                "pending_roles": list(lifecycle_payload.get("pending_roles") or []),
                "lifecycle_state": (
                    relative_path(capability_dir / "lifecycle-state.yaml", root)
                    if (capability_dir / "lifecycle-state.yaml").exists()
                    else ""
                ),
            }
        )

    releases = []
    for (_, _), payload in sorted(grouped.items(), key=lambda item: item[0]):
        payload["capabilities"] = sorted(set(payload["capabilities"]))
        payload["items"] = sorted(payload["items"], key=lambda item: str(item["capability"]))
        releases.append(payload)

    return {
        "generated_at": utc_now_iso(),
        "releases": releases,
    }


def write_release_index(hub_root: str | Path, payload: dict[str, object]) -> Path:
    path = release_index_path(hub_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_yaml_file(path, payload)
    return path


def refresh_release_index(hub_root: str | Path) -> tuple[Path, dict[str, object]]:
    payload = build_release_index(hub_root)
    return write_release_index(hub_root, payload), payload
