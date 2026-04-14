from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from runtime.http_client import HttpClient, HttpError, Transport


FIGMA_HOST = "www.figma.com"
FIGMA_ALLOWED_HOSTS = {FIGMA_HOST, "figma.com"}


@dataclass(frozen=True)
class FigmaReference:
    url: str
    file_key: str
    node_id: str | None = None


@dataclass(frozen=True)
class FigmaProbeResult:
    status: str
    reason: str = ""
    file_key: str | None = None
    node_id: str | None = None
    url: str = ""


def parse_figma_reference(figma_url: str) -> FigmaReference:
    normalized = str(figma_url or "").strip()
    if not normalized:
        raise ValueError("missing figma_url")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid figma_url: {figma_url}")
    host = str(parsed.hostname or "").lower()
    if host not in FIGMA_ALLOWED_HOSTS:
        raise ValueError(f"invalid figma host: {parsed.netloc}")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2 or segments[0] not in {"design", "file"}:
        raise ValueError(f"invalid figma_url: {figma_url}")

    file_key = segments[1].strip()
    if not file_key:
        raise ValueError(f"invalid figma_url: {figma_url}")

    query = parse_qs(parsed.query)
    node_id_value = query.get("node-id", [None])[0]
    node_id = node_id_value.replace("-", ":") if node_id_value else None

    return FigmaReference(url=normalized, file_key=file_key, node_id=node_id)


def probe_figma_reference(
    figma_url: str,
    *,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> FigmaProbeResult:
    normalized = str(figma_url or "").strip()
    if not normalized:
        return FigmaProbeResult(status="blocked", reason="missing figma_url")

    try:
        reference = parse_figma_reference(normalized)
    except ValueError as exc:
        return FigmaProbeResult(status="blocked", reason=str(exc))

    client = HttpClient(timeout=timeout, transport=transport)
    try:
        response = client.get(reference.url)
    except HttpError as exc:
        return FigmaProbeResult(
            status="blocked",
            reason=str(exc),
            file_key=reference.file_key,
            node_id=reference.node_id,
            url=reference.url,
        )

    return FigmaProbeResult(
        status="ok",
        reason="",
        file_key=reference.file_key,
        node_id=reference.node_id,
        url=response.url or reference.url,
    )


__all__ = [
    "FIGMA_HOST",
    "FIGMA_ALLOWED_HOSTS",
    "FigmaProbeResult",
    "FigmaReference",
    "parse_figma_reference",
    "probe_figma_reference",
]
