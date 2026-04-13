from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from urllib.parse import urlparse

from integrations.credentials import discover_values, missing_names


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


def _extract_hostname(gitlab_url: str | None) -> str | None:
    if gitlab_url is None:
        return None
    normalized = gitlab_url.strip()
    if not normalized:
        return None

    parsed = urlparse(normalized)
    if parsed.hostname:
        return parsed.hostname.lower()

    candidate = normalized.split("/", 1)[0]
    host = candidate.split(":", 1)[0].strip().lower()
    return host or None


def resolve_gitlab_instance(gitlab_url: str | None = None) -> GitLabInstance | None:
    hostname = _extract_hostname(gitlab_url)
    if hostname is None:
        return GITLAB_INSTANCES[DEFAULT_GITLAB_INSTANCE]
    return HOST_TO_INSTANCE.get(hostname)


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
