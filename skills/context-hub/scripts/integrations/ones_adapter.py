from __future__ import annotations

from collections.abc import Mapping

from integrations.credentials import discover_values, missing_names


ONES_REQUIRED_VARS = ("ONES_TOKEN", "ONES_USER_UUID", "ONES_TEAM_UUID")


def preflight_ones(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    missing = missing_names(discover_values(ONES_REQUIRED_VARS, environ=environ))
    return {
        "ok": not missing,
        "missing": missing,
        "required": list(ONES_REQUIRED_VARS),
    }
