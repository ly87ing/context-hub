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

    def test_get_commit_changed_files_reads_gitlab_commit_diff(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files
        from runtime.http_client import HttpResponse

        commit = "abc123"
        repo_url = "git@itgitlab.xylink.com:group/meeting-control-service.git"
        url = (
            "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/"
            f"repository/commits/{commit}/diff"
        )
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        [
                            {
                                "old_path": "pyproject.toml",
                                "new_path": "pyproject.toml",
                                "deleted_file": False,
                                "renamed_file": False,
                            },
                            {
                                "old_path": "openapi.yaml",
                                "new_path": "openapi.yaml",
                                "deleted_file": False,
                                "renamed_file": False,
                            },
                        ]
                    ).encode("utf-8"),
                    url=url,
                )
            }
        )

        paths = get_commit_changed_files(
            repo_url,
            commit,
            environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            transport=transport,
        )

        self.assertEqual(paths, ["pyproject.toml", "openapi.yaml"])

    def test_get_commit_changed_files_keeps_old_and_new_paths_for_rename(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files
        from runtime.http_client import HttpResponse

        transport = FakeTransport(
            {
                (
                    "GET",
                    "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff",
                ): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        [
                            {
                                "old_path": "old/openapi.yaml",
                                "new_path": "contracts/openapi.yaml",
                                "deleted_file": False,
                                "renamed_file": True,
                            }
                        ]
                    ).encode("utf-8"),
                    url="https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff",
                )
            }
        )

        paths = get_commit_changed_files(
            "git@itgitlab.xylink.com:group/meeting-control-service.git",
            "abc123",
            environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            transport=transport,
        )

        self.assertEqual(
            paths,
            ["old/openapi.yaml", "contracts/openapi.yaml"],
        )

    def test_get_commit_changed_files_handles_empty_commit_diff_array(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files
        from runtime.http_client import HttpResponse

        url = "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=b"[]",
                    url=url,
                )
            }
        )

        paths = get_commit_changed_files(
            "https://itgitlab.xylink.com/group/meeting-control-service.git",
            "abc123",
            environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            transport=transport,
        )

        self.assertEqual(paths, [])

    def test_get_commit_changed_files_rejects_non_array_diff_payload(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files
        from runtime.http_client import HttpResponse

        url = "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps({"message": "not an array"}).encode("utf-8"),
                    url=url,
                )
            }
        )

        with self.assertRaises(ValueError):
            get_commit_changed_files(
                "https://itgitlab.xylink.com/group/meeting-control-service.git",
                "abc123",
                environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
                transport=transport,
            )

    def test_get_commit_changed_files_rejects_blank_commit_sha(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files

        with self.assertRaises(ValueError):
            get_commit_changed_files(
                "https://itgitlab.xylink.com/group/meeting-control-service.git",
                "",
                environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            )

    def test_get_commit_changed_files_keeps_old_path_for_deleted_file(self) -> None:
        from integrations.gitlab_adapter import get_commit_changed_files
        from runtime.http_client import HttpResponse

        transport = FakeTransport(
            {
                (
                    "GET",
                    "https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff",
                ): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        [
                            {
                                "old_path": "pyproject.toml",
                                "new_path": "pyproject.toml",
                                "deleted_file": True,
                                "renamed_file": False,
                            }
                        ]
                    ).encode("utf-8"),
                    url="https://itgitlab.xylink.com/api/v4/projects/group%2Fmeeting-control-service/repository/commits/abc123/diff",
                )
            }
        )

        paths = get_commit_changed_files(
            "git@itgitlab.xylink.com:group/meeting-control-service.git",
            "abc123",
            environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
            transport=transport,
        )

        self.assertEqual(paths, ["pyproject.toml"])


class SyncTopologyTest(ContextHubTestCase):
    def write_system_yaml(self, content: str) -> None:
        topology_dir = self.hub_dir / "topology"
        topology_dir.mkdir(parents=True, exist_ok=True)
        (topology_dir / "system.yaml").write_text(content.strip() + "\n", encoding="utf-8")

    def load_system_yaml(self) -> dict:
        from yaml_compat import safe_load

        return safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))

    def write_single_gitlab_service_system_yaml(self, *, default_branch: str | None = "main") -> None:
        default_branch_line = (
            f"    default_branch: {default_branch}\n" if default_branch is not None else ""
        )
        self.write_system_yaml(
            f"""
services:
  meeting-control-service:
    repo: https://itgitlab.xylink.com/group/meeting-control-service.git
    owner: platform
{default_branch_line}    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {{}}
""",
        )

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

    def test_normalize_repo_url_treats_https_and_ssh_as_same_repo(self) -> None:
        from sync_topology import normalize_repo_url

        https_url = "https://itgitlab.xylink.com/group/meeting-control-service.git"
        ssh_url = "git@itgitlab.xylink.com:group/meeting-control-service.git"

        self.assertEqual(normalize_repo_url(https_url), normalize_repo_url(ssh_url))

    def test_sync_topology_incremental_returns_result_contract_for_matching_repo(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://itgitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    default_branch: main
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
        tree = [{"path": "pyproject.toml", "type": "blob"}]

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", return_value=project),
            patch("sync_topology.gitlab_adapter.get_tree", return_value=tree),
            patch("sync_topology.gitlab_adapter.get_file_raw", return_value="[project]\nname = 'meeting-control-service'\n"),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="git@itgitlab.xylink.com:group/meeting-control-service.git",
                branch="main",
            )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["matched_services"], ["meeting-control-service"])
        self.assertEqual(result["synced_services"], ["meeting-control-service"])
        self.assertEqual(result["system_path"], (self.hub_dir / "topology" / "system.yaml").resolve())
        self.assertIn("reason", result)

    def test_sync_topology_incremental_skips_non_default_branch(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://itgitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    default_branch: main
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        with (
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.gitlab_adapter.get_tree") as get_tree,
            patch("sync_topology.gitlab_adapter.get_file_raw") as get_file_raw,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="feature/x",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["matched_services"], ["meeting-control-service"])
        self.assertEqual(result["synced_services"], [])
        self.assertIn("default_branch", str(result["reason"]))
        self.assertFalse(lookup_project.called)
        self.assertFalse(get_tree.called)
        self.assertFalse(get_file_raw.called)

    def test_sync_topology_incremental_refreshes_all_services_for_same_repo(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  api-service:
    repo: git@itgitlab.xylink.com:group/mono.git
    owner: platform
    default_branch: main
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
  worker-service:
    repo: https://itgitlab.xylink.com/group/mono.git
    owner: platform
    default_branch: main
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        project = {
            "id": 84,
            "path_with_namespace": "group/mono",
            "default_branch": "main",
        }
        tree = [{"path": "pyproject.toml", "type": "blob"}]

        with (
            patch("sync_topology.gitlab_adapter.lookup_project", return_value=project),
            patch("sync_topology.gitlab_adapter.get_tree", return_value=tree),
            patch("sync_topology.gitlab_adapter.get_file_raw", return_value="[project]\nname = 'mono'\n"),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="git@itgitlab.xylink.com:group/mono.git",
                branch="main",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertCountEqual(result["matched_services"], ["api-service", "worker-service"])
        self.assertCountEqual(result["synced_services"], ["api-service", "worker-service"])
        self.assertEqual(result["system_path"], (self.hub_dir / "topology" / "system.yaml").resolve())

    def test_sync_topology_incremental_skips_when_repo_matches_no_service(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: https://itgitlab.xylink.com/group/meeting-control-service.git
    owner: platform
    default_branch: main
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        with (
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.gitlab_adapter.get_tree") as get_tree,
            patch("sync_topology.gitlab_adapter.get_file_raw") as get_file_raw,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="git@itgitlab.xylink.com:group/unknown.git",
                branch="main",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["matched_services"], [])
        self.assertEqual(result["synced_services"], [])
        self.assertTrue(result["reason"])
        self.assertIn("match", str(result["reason"]).lower())
        self.assertFalse(lookup_project.called)
        self.assertFalse(get_tree.called)
        self.assertFalse(get_file_raw.called)

    def test_sync_topology_incremental_skips_when_default_branch_missing(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  meeting-control-service:
    repo: git@itgitlab.xylink.com:group/meeting-control-service.git
    owner: platform
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        with (
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.gitlab_adapter.get_tree") as get_tree,
            patch("sync_topology.gitlab_adapter.get_file_raw") as get_file_raw,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["matched_services"], ["meeting-control-service"])
        self.assertEqual(result["synced_services"], [])
        self.assertIn("default_branch", str(result["reason"]))
        self.assertFalse(lookup_project.called)
        self.assertFalse(get_tree.called)
        self.assertFalse(get_file_raw.called)

    def test_sync_topology_incremental_scan_worthy_commit_populates_changed_files(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml()

        project = {
            "id": 42,
            "path_with_namespace": "group/meeting-control-service",
            "default_branch": "main",
        }
        tree = [{"path": "pyproject.toml", "type": "blob"}]

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files", return_value=["pyproject.toml"]),
            patch("sync_topology.gitlab_adapter.lookup_project", return_value=project),
            patch("sync_topology.gitlab_adapter.get_tree", return_value=tree),
            patch("sync_topology.gitlab_adapter.get_file_raw", return_value="[project]\nname = 'meeting-control-service'\n"),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "scan")
        self.assertEqual(result["synced_services"], ["meeting-control-service"])
        self.assertEqual(result["changed_files"], ["pyproject.toml"])

    def test_sync_topology_incremental_scan_decision_skips_when_no_service_summary_is_produced(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml()

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files", return_value=["pyproject.toml"]),
            patch("sync_topology.scan_repo_summary", return_value=None),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["synced_services"], [])
        self.assertEqual(result["changed_files"], ["pyproject.toml"])
        self.assertIn("gitlab scan skipped", result["reason"])

    def test_sync_topology_incremental_docs_only_commit_skips_with_reason_code(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml()

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files", return_value=["README.md", "docs/usage.md"]),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_code"], "no_topology_signal")
        self.assertEqual(result["changed_files"], ["README.md", "docs/usage.md"])

    def test_sync_topology_incremental_empty_changed_files_skips_with_reason_code(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml()

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files", return_value=[]),
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_code"], "no_changed_files")
        self.assertEqual(result["reason"], "commit has no changed files")
        self.assertEqual(result["changed_files"], [])

    def test_sync_topology_incremental_branch_mismatch_skips_with_reason_code(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml()

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files") as get_commit_changed_files,
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="feature/x",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_code"], "branch_mismatch")
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(get_commit_changed_files.called)
        self.assertFalse(lookup_project.called)

    def test_sync_topology_incremental_missing_default_branch_skips_with_reason_code(self) -> None:
        from sync_topology import sync_system_topology

        self.write_single_gitlab_service_system_yaml(default_branch=None)

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files") as get_commit_changed_files,
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_code"], "missing_default_branch")
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(get_commit_changed_files.called)
        self.assertFalse(lookup_project.called)

    def test_sync_topology_incremental_no_matching_service_skips_with_reason_code(self) -> None:
        from sync_topology import sync_system_topology

        self.write_system_yaml(
            """
services:
  other-service:
    repo: https://itgitlab.xylink.com/group/other-service.git
    owner: platform
    default_branch: main
    lang: unknown
    framework: unknown
    provides: []
    depends_on: []
infrastructure: {}
""",
        )

        with (
            patch("sync_topology.gitlab_adapter.get_commit_changed_files") as get_commit_changed_files,
            patch("sync_topology.gitlab_adapter.lookup_project") as lookup_project,
            patch("sync_topology.utc_now_iso", return_value="2026-04-13T12:00:00Z"),
        ):
            result = sync_system_topology(
                self.hub_dir,
                repo_url="https://itgitlab.xylink.com/group/meeting-control-service.git",
                branch="main",
                commit_sha="abc123",
            )

        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(result["reason_code"], "no_matching_service")
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(get_commit_changed_files.called)
        self.assertFalse(lookup_project.called)
