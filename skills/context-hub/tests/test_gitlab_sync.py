from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


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


class GitLabAdapterTest(unittest.TestCase):
    def test_lookup_project_resolves_repo_url_to_project_api(self) -> None:
        from integrations.gitlab_adapter import lookup_project
        from runtime.http_client import HttpResponse

        url = "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        {
                            "id": 42,
                            "path_with_namespace": "group/meeting-control-service",
                            "default_branch": "main",
                        }
                    ).encode("utf-8"),
                    url=url,
                )
            }
        )

        project = lookup_project(
            "https://itgitlab.xylink.com/group/meeting-control-service.git",
            environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            transport=transport,
        )

        self.assertEqual(project["id"], 42)
        self.assertEqual(project["default_branch"], "main")
        self.assertEqual(transport.calls[0]["headers"]["PRIVATE-TOKEN"], "it-secret-token")
        self.assertNotIn("it-secret-token", json.dumps(project, sort_keys=True))

    def test_get_tree_uses_default_branch_and_follows_pagination(self) -> None:
        from integrations.gitlab_adapter import get_tree
        from runtime.http_client import HttpResponse

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }
        page1 = (
            "https://gitlab.xylink.com/api/v4/projects/42/repository/tree"
            "?ref=main&recursive=true&per_page=100&page=1"
        )
        page2 = (
            "https://gitlab.xylink.com/api/v4/projects/42/repository/tree"
            "?ref=main&recursive=true&per_page=100&page=2"
        )
        transport = FakeTransport(
            {
                ("GET", page1): HttpResponse(
                    status=200,
                    headers={"X-Next-Page": "2"},
                    body=json.dumps([{"path": "pom.xml", "type": "blob"}]).encode("utf-8"),
                    url=page1,
                ),
                ("GET", page2): HttpResponse(
                    status=200,
                    headers={"X-Next-Page": ""},
                    body=json.dumps([{"path": "src/main/resources/application.yml", "type": "blob"}]).encode("utf-8"),
                    url=page2,
                ),
            }
        )

        tree = get_tree(
            project,
            environ={"GITLAB_ACCESS_TOKEN": "default-secret-token"},
            transport=transport,
        )

        self.assertEqual(
            tree,
            [
                {"path": "pom.xml", "type": "blob"},
                {"path": "src/main/resources/application.yml", "type": "blob"},
            ],
        )
        self.assertEqual(len(transport.calls), 2)

    def test_get_file_raw_reads_text_from_repository(self) -> None:
        from integrations.gitlab_adapter import get_file_raw
        from runtime.http_client import HttpResponse

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }
        url = (
            "https://gitlab.xylink.com/api/v4/projects/42/repository/files/"
            "src%2Fmain%2Fresources%2Fapplication.yml/raw?ref=main"
        )
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=b"spring:\n  application:\n    name: meeting-control-service\n",
                    url=url,
                )
            }
        )

        payload = get_file_raw(
            project,
            "src/main/resources/application.yml",
            environ={"GITLAB_ACCESS_TOKEN": "default-secret-token"},
            transport=transport,
        )

        self.assertIn("meeting-control-service", payload)
