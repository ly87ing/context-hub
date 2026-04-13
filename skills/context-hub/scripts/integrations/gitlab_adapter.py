from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlparse

from integrations.credentials import discover_values, missing_names, require_values
from runtime.http_client import HttpClient, Transport


@dataclass(frozen=True)
class GitLabInstance:
    name: str
    base_url: str
    token_var: str


GITLAB_INSTANCES: dict[str, GitLabInstance] = {
    "gitlab": GitLabInstance(
        name="gitlab",
        base_url="https://gitlab.xylink.com",
        token_var="GITLAB_ACCESS_TOKEN",
    ),
    "itgitlab": GitLabInstance(
        name="itgitlab",
        base_url="https://itgitlab.xylink.com",
        token_var="ITGITLAB_ACCESS_TOKEN",
    ),
    "xygitlab": GitLabInstance(
        name="xygitlab",
        base_url="http://xygitlab.xylink.com",
        token_var="XYGITLAB_ACCESS_TOKEN",
    ),
}
DEFAULT_GITLAB_INSTANCE = "gitlab"
HOST_TO_INSTANCE = {
    urlparse(instance.base_url).hostname: instance
    for instance in GITLAB_INSTANCES.values()
}
SSH_REPO_PATTERN = re.compile(r"^(?P<user>[^@]+)@(?P<host>[^:]+):(?P<path>.+)$")


def normalize_repo_url(gitlab_url: str) -> dict[str, str]:
    normalized = str(gitlab_url or "").strip()
    if not normalized:
        raise ValueError("missing GitLab repo URL")

    ssh_match = SSH_REPO_PATTERN.match(normalized)
    if ssh_match:
        host = ssh_match.group("host").strip().lower()
        project_path = ssh_match.group("path").strip().lstrip("/")
    else:
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"invalid GitLab repo URL: {gitlab_url}")
        host = str(parsed.hostname or "").strip().lower()
        project_path = parsed.path.strip().lstrip("/")

    if project_path.endswith(".git"):
        project_path = project_path[:-4]
    project_path = project_path.rstrip("/")
    if not host or not project_path:
        raise ValueError(f"invalid GitLab repo URL: {gitlab_url}")

    return {
        "host": host,
        "path_with_namespace": project_path,
    }


def _extract_hostname(gitlab_url: str | None) -> str | None:
    if gitlab_url is None:
        return None
    normalized = gitlab_url.strip()
    if not normalized:
        return None

    parsed = urlparse(normalized)
    if parsed.hostname:
        return parsed.hostname.lower()

    try:
        return normalize_repo_url(normalized)["host"]
    except ValueError:
        pass

    candidate = normalized.split("/", 1)[0]
    host = candidate.split(":", 1)[0].strip().lower()
    return host or None


def resolve_gitlab_instance(gitlab_url: str | None = None) -> GitLabInstance | None:
    hostname = _extract_hostname(gitlab_url)
    if hostname is None:
        return GITLAB_INSTANCES[DEFAULT_GITLAB_INSTANCE]
    return HOST_TO_INSTANCE.get(hostname)


def build_api_base(gitlab_url: str | GitLabInstance | None = None) -> str:
    if isinstance(gitlab_url, GitLabInstance):
        source = gitlab_url.base_url
    elif gitlab_url:
        source = gitlab_url
    else:
        source = GITLAB_INSTANCES[DEFAULT_GITLAB_INSTANCE].base_url
    parsed = urlparse(str(source).strip())
    if parsed.scheme and parsed.netloc:
        base = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base = str(source).strip().split("/", 1)[0]
    return base.rstrip("/") + "/api/v4"


def extract_project_path(gitlab_url: str) -> str:
    return normalize_repo_url(gitlab_url)["path_with_namespace"]


def _project_identifier(project: Mapping[str, object]) -> str:
    for key in ("id", "path_with_namespace", "full_path"):
        value = project.get(key)
        if value not in (None, ""):
            return quote(str(value), safe="")
    raise ValueError("project identifier missing")


def _resolve_token(
    instance: GitLabInstance,
    *,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
) -> str:
    if token:
        return token
    return require_values((instance.token_var,), environ=environ)[instance.token_var]


def build_client(
    gitlab_url: str | GitLabInstance | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> HttpClient:
    instance = gitlab_url if isinstance(gitlab_url, GitLabInstance) else resolve_gitlab_instance(gitlab_url)
    if instance is None:
        raise ValueError(f"unsupported GitLab instance: {gitlab_url}")
    return HttpClient(
        base_url=build_api_base(instance),
        headers={"PRIVATE-TOKEN": _resolve_token(instance, environ=environ, token=token)},
        timeout=timeout,
        transport=transport,
    )


def lookup_project(
    gitlab_url: str,
    *,
    client: HttpClient | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    instance = resolve_gitlab_instance(gitlab_url)
    if instance is None:
        raise ValueError(f"unsupported GitLab instance: {gitlab_url}")
    resolved_client = client or build_client(
        instance,
        environ=environ,
        token=token,
        transport=transport,
        timeout=timeout,
    )
    path = extract_project_path(gitlab_url)
    return dict(resolved_client.get_json(f"/projects/{quote(path, safe='')}") or {})


def get_default_branch(project: Mapping[str, object]) -> str:
    branch = str(project.get("default_branch") or "").strip()
    if not branch:
        raise ValueError("project default_branch missing")
    return branch


def get_tree(
    project: Mapping[str, object],
    *,
    client: HttpClient | None = None,
    gitlab_url: str | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
    ref: str | None = None,
    path: str | None = None,
    recursive: bool = True,
    per_page: int = 100,
) -> list[dict[str, object]]:
    resolved_client = client or build_client(
        gitlab_url,
        environ=environ,
        token=token,
        transport=transport,
        timeout=timeout,
    )
    params: list[tuple[str, str]] = [("ref", ref or get_default_branch(project))]
    if path:
        params.append(("path", path))
    if recursive:
        params.append(("recursive", "true"))
    params.append(("per_page", str(per_page)))

    items: list[dict[str, object]] = []
    page = 1
    while True:
        query = urlencode(params + [("page", str(page))])
        response = resolved_client.get(
            f"/projects/{_project_identifier(project)}/repository/tree?{query}"
        )
        payload = response.body.decode("utf-8") if response.body else "[]"
        records = [dict(item) for item in json.loads(payload or "[]")]
        items.extend(records)
        next_page = str(response.headers.get("X-Next-Page", "")).strip()
        if not next_page:
            break
        page = int(next_page)
    return items


def get_file_raw(
    project: Mapping[str, object],
    file_path: str,
    *,
    client: HttpClient | None = None,
    gitlab_url: str | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
    ref: str | None = None,
) -> str:
    resolved_client = client or build_client(
        gitlab_url,
        environ=environ,
        token=token,
        transport=transport,
        timeout=timeout,
    )
    query = f"?ref={quote(ref or get_default_branch(project), safe='')}"
    response = resolved_client.get_text(
        f"/projects/{_project_identifier(project)}/repository/files/{quote(file_path, safe='')}/raw{query}"
    )
    return response


def get_commit_changed_files(
    gitlab_url: str,
    commit_sha: str,
    *,
    client: HttpClient | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> list[str]:
    commit = str(commit_sha or "").strip()
    if not commit:
        raise ValueError("missing commit SHA")

    resolved_client = client or build_client(
        gitlab_url,
        environ=environ,
        token=token,
        transport=transport,
        timeout=timeout,
    )
    project_identifier = quote(normalize_repo_url(gitlab_url)["path_with_namespace"], safe="")
    response = resolved_client.get(
        f"/projects/{project_identifier}/repository/commits/{quote(commit, safe='')}/diff"
    )
    payload = response.body.decode("utf-8") if response.body else "[]"
    records = json.loads(payload or "[]")
    if not isinstance(records, list):
        raise ValueError("commit diff payload must be a JSON array")

    changed_files: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        for key in ("old_path", "new_path"):
            path = record.get(key)
            if not path:
                continue
            path_str = str(path)
            if path_str in seen:
                continue
            seen.add(path_str)
            changed_files.append(path_str)
    return changed_files


def preflight_gitlab(
    gitlab_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    instance = resolve_gitlab_instance(gitlab_url)
    if instance is None:
        return {
            "ok": False,
            "reason": "unsupported_instance",
            "input": gitlab_url or "",
            "missing": [],
        }

    missing = missing_names(discover_values((instance.token_var,), environ=environ))
    return {
        "ok": not missing,
        "instance": instance.name,
        "base_url": instance.base_url,
        "token_var": instance.token_var,
        "missing": missing,
    }
