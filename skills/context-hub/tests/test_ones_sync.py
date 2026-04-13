from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from test_support import ContextHubTestCase, run_script
from yaml_compat import safe_load


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


class OnesAdapterTest(unittest.TestCase):
    def test_query_tasks_uses_graphql_headers_and_team_uuid(self) -> None:
        from integrations.ones_adapter import query_tasks
        from runtime.http_client import HttpResponse

        url = "https://nones.xylink.com/project/api/project/team/TEAM-1/items/graphql"
        transport = FakeTransport(
            {
                ("POST", url): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        {
                            "data": {
                                "tasks": [
                                    {
                                        "uuid": "task-1",
                                        "number": 101,
                                        "name": "投票功能",
                                    }
                                ]
                            }
                        }
                    ).encode("utf-8"),
                    url=url,
                )
            }
        )

        payload = query_tasks(
            "query { tasks { uuid number name } }",
            environ={
                "ONES_TOKEN": "ones-secret-token",
                "ONES_USER_UUID": "user-1",
                "ONES_TEAM_UUID": "TEAM-1",
            },
            transport=transport,
        )

        self.assertEqual(payload["data"]["tasks"][0]["number"], 101)
        self.assertEqual(transport.calls[0]["headers"]["ones-auth-token"], "ones-secret-token")
        self.assertEqual(transport.calls[0]["headers"]["ones-user-id"], "user-1")
        self.assertNotIn("ones-secret-token", json.dumps(payload, sort_keys=True))

    def test_get_task_info_uses_rest_path(self) -> None:
        from integrations.ones_adapter import get_task_info
        from runtime.http_client import HttpResponse

        url = "https://nones.xylink.com/project/api/project/team/TEAM-2/task/TASK-42/info"
        transport = FakeTransport(
            {
                ("GET", url): HttpResponse(
                    status=200,
                    headers={},
                    body=json.dumps(
                        {
                            "uuid": "TASK-42",
                            "number": 42,
                            "name": "投票功能",
                            "status": {"name": "进行中", "category": "in_progress"},
                        }
                    ).encode("utf-8"),
                    url=url,
                )
            }
        )

        payload = get_task_info(
            "TASK-42",
            team_uuid="TEAM-2",
            environ={
                "ONES_TOKEN": "ones-secret-token",
                "ONES_USER_UUID": "user-2",
            },
            transport=transport,
        )

        self.assertEqual(payload["uuid"], "TASK-42")
        self.assertEqual(payload["status"]["category"], "in_progress")

    def test_summarize_task_returns_shared_summary(self) -> None:
        from integrations.ones_adapter import summarize_task

        summary = summarize_task(
            {
                "uuid": "TASK-42",
                "number": 42,
                "name": "投票功能",
                "status": {"name": "进行中", "category": "in_progress"},
                "assign": {"uuid": "u-1", "name": "张三"},
                "priority": {"value": "P1"},
                "project": {"uuid": "p-1", "name": "会议控制"},
            }
        )

        self.assertEqual(
            summary,
            {
                "uuid": "TASK-42",
                "number": 42,
                "name": "投票功能",
                "status": {"name": "进行中", "category": "in_progress"},
                "assign": {"uuid": "u-1", "name": "张三"},
                "priority": {"value": "P1"},
                "project": {"uuid": "p-1", "name": "会议控制"},
            },
        )


class OnesSyncTest(ContextHubTestCase):
    def setUp(self) -> None:
        super().setUp()
        init_result = run_script(
            "init_context_hub.py",
            "--output",
            str(self.hub_dir),
            "--name",
            "meeting-control",
            "--id",
            "meeting-control",
        )
        self.assertEqual(init_result.returncode, 0, msg=init_result.stderr)

    def test_sync_capability_status_writes_summary_and_updates_domains(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "product",
            "--ones-task",
            "TASK-1",
            "--ones-task",
            "TASK-2",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        from sync_capability_status import sync_capability_status

        with patch(
            "sync_capability_status.ones_adapter.get_task_info",
            side_effect=[
                {"uuid": "TASK-1", "number": 1, "name": "投票需求", "status": {"name": "进行中"}},
                {"uuid": "TASK-2", "number": 2, "name": "验收检查", "status": {"name": "待开始"}},
            ],
        ), patch("sync_capability_status.utc_now_iso", return_value="2026-04-13T12:00:00Z"):
            synced_paths = sync_capability_status(self.hub_dir)

        self.assertEqual(len(synced_paths), 1)
        summary_path = self.hub_dir / "capabilities" / "voting" / "source-summary.yaml"
        self.assertTrue(summary_path.exists())

        summary_payload = safe_load(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary_payload["capability"], "voting")
        self.assertEqual(summary_payload["domain"], "product")
        self.assertEqual(summary_payload["source_system"], "ones")
        self.assertEqual(summary_payload["source_ref"], "TASK-1,TASK-2")
        self.assertEqual(summary_payload["last_synced_at"], "2026-04-13T12:00:00Z")
        self.assertEqual(summary_payload["status"], "in-progress")
        self.assertEqual(summary_payload["items"][0]["uuid"], "TASK-1")
        self.assertEqual(summary_payload["items"][1]["uuid"], "TASK-2")
        self.assertIn("投票需求", summary_payload["acceptance_summary"])

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text(encoding="utf-8"))
        voting = domains_payload["domains"]["product"]["capabilities"][0]
        self.assertEqual(voting["status"], "in-progress")
        self.assertEqual(voting["last_synced_at"], "2026-04-13T12:00:00Z")
        self.assertEqual(voting["source_ref"], "TASK-1,TASK-2")
        self.assertEqual(voting["ones_tasks"], ["TASK-1", "TASK-2"])

    def test_sync_capability_status_skips_capabilities_without_ones_tasks(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "meeting-analytics",
            "--domain",
            "product",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text(encoding="utf-8"))
        meeting_analytics = domains_payload["domains"]["product"]["capabilities"][0]
        self.assertEqual(meeting_analytics["ones_tasks"], [])

        from sync_capability_status import sync_capability_status

        with patch("sync_capability_status.ones_adapter.get_task_info") as get_task_info, patch(
            "sync_capability_status.utc_now_iso",
            return_value="2026-04-13T12:00:00Z",
        ):
            synced_paths = sync_capability_status(self.hub_dir)

        self.assertEqual(synced_paths, [])
        self.assertFalse((self.hub_dir / "capabilities" / "meeting-analytics" / "source-summary.yaml").exists())
        get_task_info.assert_not_called()
