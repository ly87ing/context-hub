from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str = ""


class HttpError(RuntimeError):
    def __init__(
        self,
        message_or_response: str | HttpResponse,
        *,
        method: str | None = None,
        url: str | None = None,
        status: int | None = None,
    ) -> None:
        if isinstance(message_or_response, HttpResponse):
            response = message_or_response
            self.response = response
            self.method = method or ""
            self.url = url or response.url
            self.status = status if status is not None else response.status
            message = f"HTTP {self.status} for {self.method or 'REQUEST'} {self.url}".strip()
        else:
            self.response = None
            self.method = method or ""
            self.url = url or ""
            self.status = status
            message = message_or_response
        super().__init__(message)


class HttpRequestError(HttpError):
    pass


class HttpTimeoutError(HttpError):
    pass


class HttpStatusError(HttpError):
    pass


class HttpClientError(HttpStatusError):
    pass


class HttpUnauthorizedError(HttpClientError):
    pass


class HttpForbiddenError(HttpClientError):
    pass


class HttpNotFoundError(HttpClientError):
    pass


class HttpConflictError(HttpClientError):
    pass


class HttpServerError(HttpStatusError):
    pass


class RequestTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = 10.0,
    ) -> HttpResponse | tuple[int, Mapping[str, str], bytes | str]: ...


Transport = Callable[[HttpRequest], HttpResponse | tuple[int, Mapping[str, str], bytes | str]] | RequestTransport


def _default_transport(request: HttpRequest) -> HttpResponse:
    urllib_request = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method.upper(),
    )
    try:
        with urllib.request.urlopen(urllib_request, timeout=request.timeout) as handle:
            body = handle.read()
            status = int(getattr(handle, "status", handle.getcode()))
            headers = dict(handle.headers.items()) if handle.headers else {}
            return HttpResponse(status=status, headers=headers, body=body, url=request.url)
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        headers = dict(exc.headers.items()) if exc.headers else {}
        return HttpResponse(status=int(exc.code), headers=headers, body=body, url=request.url)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise HttpTimeoutError(
                f"HTTP request timed out: {request.method} {request.url}",
                method=request.method,
                url=request.url,
            ) from exc
        raise HttpRequestError(
            f"HTTP request failed: {request.method} {request.url}: {reason}",
            method=request.method,
            url=request.url,
        ) from exc


def _normalize_response(response: HttpResponse | tuple[int, Mapping[str, str], bytes | str]) -> HttpResponse:
    if isinstance(response, HttpResponse):
        return response
    status, headers, body = response
    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body
    return HttpResponse(status=int(status), headers=dict(headers), body=body_bytes)


def _invoke_transport(transport: Transport, request: HttpRequest) -> HttpResponse | tuple[int, Mapping[str, str], bytes | str]:
    if hasattr(transport, "request"):
        return transport.request(
            request.method,
            request.url,
            headers=request.headers,
            data=request.body,
            timeout=request.timeout,
        )
    return transport(request)


def _status_exception(status: int) -> type[HttpStatusError]:
    if status == 401:
        return HttpUnauthorizedError
    if status == 403:
        return HttpForbiddenError
    if status == 404:
        return HttpNotFoundError
    if status == 409:
        return HttpConflictError
    if 400 <= status < 500:
        return HttpClientError
    if 500 <= status < 600:
        return HttpServerError
    return HttpStatusError


def _raise_for_status(request: HttpRequest, response: HttpResponse) -> None:
    if response.status < 400:
        return
    exc_type = _status_exception(response.status)
    raise exc_type(
        f"HTTP {response.status} for {request.method} {request.url}",
        method=request.method,
        url=request.url,
        status=response.status,
    )


class HttpClient:
    def __init__(
        self,
        base_url: str = "",
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.transport = transport or _default_transport

    def _resolve_url(self, path: str) -> str:
        candidate = path.strip()
        if not candidate:
            return self.base_url
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate
        if not self.base_url:
            return candidate
        return urllib.parse.urljoin(self.base_url + "/", candidate.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        request = HttpRequest(
            method=method.upper(),
            url=self._resolve_url(path),
            headers={**self.headers, **dict(headers or {})},
            body=body,
            timeout=self.timeout,
        )
        response = _normalize_response(_invoke_transport(self.transport, request))
        if not response.url:
            response = HttpResponse(
                status=response.status,
                headers=response.headers,
                body=response.body,
                url=request.url,
            )
        _raise_for_status(request, response)
        return response

    def get(self, path: str, *, headers: Mapping[str, str] | None = None) -> HttpResponse:
        return self._request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        return self._request("POST", path, headers=headers, body=body)

    def get_json(self, path: str, *, headers: Mapping[str, str] | None = None) -> Any:
        response = self.get(path, headers=headers)
        text = response.body.decode("utf-8") if response.body else ""
        if not text:
            return None
        return json.loads(text)

    def get_text(self, path: str, *, headers: Mapping[str, str] | None = None) -> str:
        response = self.get(path, headers=headers)
        return response.body.decode("utf-8")

    def post_json(
        self,
        path: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        response = self.post(path, headers=request_headers, body=body)
        text = response.body.decode("utf-8") if response.body else ""
        if not text:
            return None
        return json.loads(text)
