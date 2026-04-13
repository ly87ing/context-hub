from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from integrations.credentials import discover_values, missing_names, require_values
from runtime.http_client import HttpClient, Transport


ONES_REQUIRED_VARS = ("ONES_TOKEN", "ONES_USER_UUID", "ONES_TEAM_UUID")
DEFAULT_ONES_HOST = "https://nones.xylink.com"


def _resolve_host(ones_url: str | None = None) -> str:
    source = (ones_url or DEFAULT_ONES_HOST).strip()
    parsed = urlparse(source)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return source.split("/", 1)[0]


def _resolve_team_uuid(
    team_uuid: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    if team_uuid and team_uuid.strip():
        return team_uuid.strip()
    return require_values(("ONES_TEAM_UUID",), environ=environ)["ONES_TEAM_UUID"]


def build_graphql_endpoint(
    team_uuid: str | None = None,
    *,
    ones_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    resolved_team_uuid = _resolve_team_uuid(team_uuid, environ=environ)
    return f"{_resolve_host(ones_url)}/project/api/project/team/{resolved_team_uuid}/items/graphql"


def build_rest_endpoint(
    path: str,
    *,
    team_uuid: str | None = None,
    ones_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    resolved_team_uuid = _resolve_team_uuid(team_uuid, environ=environ)
    normalized = path.lstrip("/")
    return f"{_resolve_host(ones_url)}/project/api/project/team/{resolved_team_uuid}/{normalized}"


def build_headers(
    *,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    user_uuid: str | None = None,
) -> dict[str, str]:
    if token and user_uuid:
        return {
            "ones-auth-token": token,
            "ones-user-id": user_uuid,
        }

    resolved = require_values(("ONES_TOKEN", "ONES_USER_UUID"), environ=environ)
    return {
        "ones-auth-token": token or resolved["ONES_TOKEN"],
        "ones-user-id": user_uuid or resolved["ONES_USER_UUID"],
    }


def build_client(
    *,
    team_uuid: str | None = None,
    ones_url: str | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    user_uuid: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> HttpClient:
    return HttpClient(
        headers=build_headers(environ=environ, token=token, user_uuid=user_uuid),
        timeout=timeout,
        transport=transport,
    )


def query_tasks(
    query: str,
    *,
    client: HttpClient | None = None,
    ones_url: str | None = None,
    token: str | None = None,
    user_uuid: str | None = None,
    team_uuid: str | None = None,
    environ: Mapping[str, str] | None = None,
    variables: Mapping[str, object] | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    resolved_client = client or build_client(
        team_uuid=team_uuid,
        ones_url=ones_url,
        environ=environ,
        token=token,
        user_uuid=user_uuid,
        transport=transport,
        timeout=timeout,
    )
    endpoint = build_graphql_endpoint(team_uuid, ones_url=ones_url, environ=environ)
    response = resolved_client.post_json(
        endpoint,
        {
            "query": query,
            "variables": dict(variables or {}),
        },
    )
    return dict(response or {})


def get_task_info(
    task_ref: str | int,
    *,
    client: HttpClient | None = None,
    ones_url: str | None = None,
    token: str | None = None,
    user_uuid: str | None = None,
    team_uuid: str | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    resolved_client = client or build_client(
        team_uuid=team_uuid,
        ones_url=ones_url,
        environ=environ,
        token=token,
        user_uuid=user_uuid,
        transport=transport,
        timeout=timeout,
    )
    endpoint = build_rest_endpoint(
        f"task/{task_ref}/info",
        team_uuid=team_uuid,
        ones_url=ones_url,
        environ=environ,
    )
    payload = resolved_client.get_json(endpoint)
    return dict(payload or {})


def _copy_mapping(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def summarize_task(task: Mapping[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key in ("uuid", "number", "name"):
        if key in task and task[key] not in ("", None):
            summary[key] = task[key]
    for key in ("status", "assign", "priority", "project"):
        copied = _copy_mapping(task.get(key))
        if copied:
            summary[key] = copied
    return summary


def preflight_ones(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    missing = missing_names(discover_values(ONES_REQUIRED_VARS, environ=environ))
    return {
        "ok": not missing,
        "missing": missing,
        "required": list(ONES_REQUIRED_VARS),
    }
