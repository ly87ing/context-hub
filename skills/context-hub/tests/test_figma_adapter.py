from __future__ import annotations

from pathlib import Path
import sys
import unittest

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from test_support import ContextHubTestCase


class FakeTransport:
    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers=None, data=None, timeout=10):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "data": data,
                "timeout": timeout,
            }
        )
        response = self.responses[(method, url)]
        if callable(response):
            return response(method=method, url=url, headers=headers, data=data, timeout=timeout)
        return response


class FigmaAdapterTest(unittest.TestCase):
    def test_parse_figma_reference_extracts_file_key_and_node_id(self) -> None:
        from integrations import figma_adapter

        parsed = figma_adapter.parse_figma_reference(
            "https://www.figma.com/design/FILE123/Voting?node-id=12-34"
        )

        self.assertEqual(parsed.file_key, "FILE123")
        self.assertEqual(parsed.node_id, "12:34")

    def test_probe_figma_reference_blocks_blank_url(self) -> None:
        from integrations import figma_adapter

        result = figma_adapter.probe_figma_reference("")

        self.assertEqual(result.status, "blocked")
        self.assertIn("figma_url", result.reason)

    def test_probe_figma_reference_reports_ok_for_reachable_url(self) -> None:
        from integrations import figma_adapter
        from runtime.http_client import HttpResponse

        url = "https://www.figma.com/design/FILE123/Voting?node-id=12-34"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=b"ok",
                    url=url,
                )
            }
        )

        result = figma_adapter.probe_figma_reference(url, transport=transport)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.file_key, "FILE123")

    def test_probe_figma_reference_rejects_non_figma_host(self) -> None:
        from integrations import figma_adapter

        result = figma_adapter.probe_figma_reference(
            "https://evil.example/design/FILE123/Voting?node-id=12-34"
        )

        self.assertEqual(result.status, "blocked")
        self.assertIn("figma host", result.reason)

    def test_probe_figma_reference_blocks_http_error_with_parsed_reference(self) -> None:
        from integrations import figma_adapter
        from runtime.http_client import HttpResponse

        url = "https://www.figma.com/design/FILE123/Voting?node-id=12-34"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=404,
                    headers={},
                    body=b"not found",
                    url=url,
                )
            }
        )

        result = figma_adapter.probe_figma_reference(url, transport=transport)

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.file_key, "FILE123")
        self.assertEqual(result.node_id, "12:34")
