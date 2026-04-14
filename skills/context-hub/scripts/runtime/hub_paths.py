from __future__ import annotations

from pathlib import Path

from .validation import normalize_role


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def template_dir() -> Path:
    return skill_root() / "templates"


def template_path(name: str) -> Path:
    return template_dir() / name


def role_intake_dir(hub_root: str | Path) -> Path:
    return Path(hub_root) / "templates" / "role-intake"


def role_intake_template_path(hub_root: str | Path, role: str) -> Path:
    return role_intake_dir(hub_root) / f"{normalize_role(role)}.md"
