from __future__ import annotations

import os
from collections.abc import Iterable, Mapping


class MissingCredentialsError(RuntimeError):
    def __init__(self, missing: Iterable[str]) -> None:
        self.missing = list(missing)
        joined = ", ".join(self.missing)
        super().__init__(f"missing required environment variables: {joined}")


def _environment(environ: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def read_env_value(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    value = _environment(environ).get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def discover_values(
    names: Iterable[str],
    environ: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    return {name: read_env_value(name, environ=environ) for name in names}


def missing_names(values: Mapping[str, str | None]) -> list[str]:
    return [name for name, value in values.items() if value is None]


def require_values(
    names: Iterable[str],
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    discovered = discover_values(names, environ=environ)
    missing = missing_names(discovered)
    if missing:
        raise MissingCredentialsError(missing)
    return {name: value for name, value in discovered.items() if value is not None}
