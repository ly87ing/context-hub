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
