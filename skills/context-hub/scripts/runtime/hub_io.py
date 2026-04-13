from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .hub_paths import template_path


def load_template(name: str) -> str:
    path = template_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Missing template: {path}")
    return path.read_text(encoding="utf-8")


def render_template(template_text: str, mapping: dict[str, str]) -> str:
    rendered = template_text
    for key, value in mapping.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def safe_write_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)
