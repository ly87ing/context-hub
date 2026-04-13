from __future__ import annotations

from pathlib import Path


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def template_dir() -> Path:
    return skill_root() / "templates"


def template_path(name: str) -> Path:
    return template_dir() / name
