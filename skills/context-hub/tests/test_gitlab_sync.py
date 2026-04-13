from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

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


class SyncTopologyTest(ContextHubTestCase):
    def write_system_yaml(self, content: str) -> None:
        topology_dir = self.hub_dir / "topology"
        topology_dir.mkdir(parents=True, exist_ok=True)
        (topology_dir / "system.yaml").write_text(content.strip() + "\n", encoding="utf-8")

    def load_system_yaml(self) -> dict:
        from yaml_compat import safe_load

        return safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))

    def test_sync_topology_deep_scans_gitlab_repo_and_preserves_manual_fields(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://gitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    notes: keep-this
    visibility: shared
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }
        tree = [
            {"path": "pyproject.toml", "type": "blob"},
            {"path": "src/meeting_control/app.py", "type": "blob"},
        ]
        pyproject = """
[project]
name = "meeting-control-service"
dependencies = [
  "fastapi>=0.110",
  "httpx>=0.27",
  "redis>=5.0",
]
"""

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", return_value=project) as lookup_project,
            patch("sync_topology.gitlab_adapter.get_tree", return_value=tree) as get_tree,
            patch("sync_topology.gitlab_adapter.get_file_raw", return_value=pyproject) as get_file_raw,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            system_path = sync_system_topology(self.hub_dir)

        self.assertEqual(system_path, (self.hub_dir / "topology" / "system.yaml").resolve())
        self.assertEqual(lookup_project.call_count, 1)
        self.assertEqual(get_tree.call_count, 1)
        self.assertEqual(get_file_raw.call_count, 1)

        system_payload = self.load_system_yaml()
        service = system_payload["services"]["meeting-control-service"]
        self.assertEqual(service["repo"], "https://gitlab.xylink.com/group/meeting-control-service.git")
        self.assertEqual(service["owner"], "platform")
        self.assertEqual(service["notes"], "keep-this")
        self.assertEqual(service["visibility"], "shared")
        self.assertEqual(service["source_system"], "gitlab")
        self.assertEqual(service["source_ref"], "group/meeting-control-service")
        self.assertEqual(service["last_synced_at"], "2026-04-13T12:00:00Z")
        self.assertEqual(service["confidence"], "high")
        self.assertEqual(service["default_branch"], "main")
        self.assertEqual(service["lang"], "python")
        self.assertEqual(service["framework"], "fastapi")
        self.assertEqual(service["provides"], ["api"])
        self.assertEqual(service["depends_on"], ["httpx", "redis"])

    def test_sync_topology_skips_unsupported_repo_without_crashing(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  internal-console:
    repo: https://github.com/example/internal-console.git
    owner: platform
    notes: keep-this
    visibility: shared
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
  meeting-control-service:
    repo: https://gitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }

        def lookup_project(repo_url: str, **kwargs):
            if "github.com" in repo_url:
                raise ValueError("unsupported GitLab instance")
            return project

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", side_effect=lookup_project),
            patch("sync_topology.gitlab_adapter.get_tree", return_value=[]),
            patch("sync_topology.gitlab_adapter.get_file_raw", return_value=""),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            sync_system_topology(self.hub_dir)

        system_payload = self.load_system_yaml()
        self.assertEqual(system_payload["services"]["internal-console"]["repo"], "https://github.com/example/internal-console.git")
        self.assertEqual(system_payload["services"]["internal-console"]["lang"], "unknown")
        self.assertEqual(system_payload["services"]["meeting-control-service"]["source_system"], "gitlab")

    def test_sync_topology_skips_missing_credentials_without_crashing(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://gitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", side_effect=ValueError("missing GitLab credentials")),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            sync_system_topology(self.hub_dir)

        system_payload = self.load_system_yaml()
        service = system_payload["services"]["meeting-control-service"]
        self.assertEqual(service["repo"], "https://gitlab.xylink.com/group/meeting-control-service.git")
        self.assertEqual(service["lang"], "unknown")
        self.assertNotIn("source_system", service)

    def test_sync_topology_prefers_first_recognized_framework_when_multiple_key_files_exist(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://gitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }
        tree = [
            {"path": "pyproject.toml", "type": "blob"},
            {"path": "package.json", "type": "blob"},
        ]

        def get_file_raw(project_payload, file_path: str, **kwargs):
            if file_path == "pyproject.toml":
                return """
[project]
dependencies = [
  "fastapi>=0.110",
  "redis>=5.0",
]
"""
            if file_path == "package.json":
                return json.dumps(
                    {
                        "dependencies": {
                            "react": "^19.0.0",
                        }
                    }
                )
            return ""

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", return_value=project),
            patch("sync_topology.gitlab_adapter.get_tree", return_value=tree),
            patch("sync_topology.gitlab_adapter.get_file_raw", side_effect=get_file_raw),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            sync_system_topology(self.hub_dir)

        service = self.load_system_yaml()["services"]["meeting-control-service"]
        self.assertEqual(service["lang"], "python")
        self.assertEqual(service["framework"], "fastapi")
        self.assertEqual(service["depends_on"], ["redis"])
