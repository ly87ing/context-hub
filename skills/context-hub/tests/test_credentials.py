from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from test_support import ContextHubTestCase


ALL_CREDENTIAL_VARS = (
    "GITLAB_ACCESS_TOKEN",
    "ITGITLAB_ACCESS_TOKEN",
    "XYGITLAB_ACCESS_TOKEN",
    "ONES_TOKEN",
    "ONES_USER_UUID",
    "ONES_TEAM_UUID",
)


class CredentialsTest(ContextHubTestCase):
    def run_bootstrap(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        script_path = SCRIPTS_DIR / "bootstrap_credentials_check.py"
        run_env = os.environ.copy()
        for key in ALL_CREDENTIAL_VARS:
            run_env.pop(key, None)
        if env:
            run_env.update(env)
        return subprocess.run(
            [sys.executable, str(script_path), *args],
            cwd=str(self.workdir),
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_require_values_reports_missing_names_without_values(self) -> None:
        try:
            from integrations.credentials import MissingCredentialsError, require_values
        except ModuleNotFoundError as exc:
            self.fail(f"missing credentials module: {exc}")

        with self.assertRaises(MissingCredentialsError) as ctx:
            require_values(
                ("GITLAB_ACCESS_TOKEN", "ONES_TOKEN"),
                environ={
                    "GITLAB_ACCESS_TOKEN": "secret-token",
                },
            )

        self.assertEqual(ctx.exception.missing, ["ONES_TOKEN"])
        self.assertNotIn("secret-token", str(ctx.exception))

    def test_gitlab_url_resolves_instance_and_token_var(self) -> None:
        try:
            from integrations.gitlab_adapter import build_api_base, preflight_gitlab
        except ModuleNotFoundError as exc:
            self.fail(f"missing gitlab adapter: {exc}")

        result = preflight_gitlab(
            "https://itgitlab.xylink.com/group/project",
            environ={
                "ITGITLAB_ACCESS_TOKEN": "it-secret-token",
            },
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "instance": "itgitlab",
                "base_url": "https://itgitlab.xylink.com",
                "token_var": "ITGITLAB_ACCESS_TOKEN",
                "missing": [],
            },
        )
        self.assertEqual(build_api_base(result["base_url"]), "https://itgitlab.xylink.com/api/v4")
        self.assertNotIn("it-secret-token", json.dumps(result, sort_keys=True))

    def test_gitlab_url_reports_unsupported_instance_for_unknown_host(self) -> None:
        try:
            from integrations.gitlab_adapter import preflight_gitlab
        except ModuleNotFoundError as exc:
            self.fail(f"missing gitlab adapter: {exc}")

        result = preflight_gitlab(
            "https://unknown-gitlab.example.com/group/project",
            environ={
                "GITLAB_ACCESS_TOKEN": "default-secret-token",
            },
        )

        self.assertEqual(
            result,
            {
                "ok": False,
                "reason": "unsupported_instance",
                "input": "https://unknown-gitlab.example.com/group/project",
                "missing": [],
            },
        )
        self.assertNotIn("default-secret-token", json.dumps(result, sort_keys=True))

    def test_ones_preflight_reports_missing_names_without_values(self) -> None:
        try:
            from integrations.ones_adapter import preflight_ones
        except ModuleNotFoundError as exc:
            self.fail(f"missing ones adapter: {exc}")

        result = preflight_ones(
            environ={
                "ONES_TOKEN": "ones-secret-token",
                "ONES_USER_UUID": "user-uuid-value",
            }
        )

        self.assertEqual(
            result,
            {
                "ok": False,
                "missing": ["ONES_TEAM_UUID"],
                "required": ["ONES_TOKEN", "ONES_USER_UUID", "ONES_TEAM_UUID"],
            },
        )
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("ones-secret-token", rendered)
        self.assertNotIn("user-uuid-value", rendered)

    def test_bootstrap_cli_supports_gitlab_url_and_ones_check(self) -> None:
        result = self.run_bootstrap(
            "--gitlab-url",
            "http://xygitlab.xylink.com/group/project",
            "--check-ones",
            env={
                "XYGITLAB_ACCESS_TOKEN": "xy-secret-token",
                "ONES_TOKEN": "ones-secret-token",
            },
        )

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload,
            {
                "gitlab": {
                    "ok": True,
                    "instance": "xygitlab",
                    "base_url": "http://xygitlab.xylink.com",
                    "token_var": "XYGITLAB_ACCESS_TOKEN",
                    "missing": [],
                },
                "ones": {
                    "ok": False,
                    "missing": ["ONES_USER_UUID", "ONES_TEAM_UUID"],
                    "required": ["ONES_TOKEN", "ONES_USER_UUID", "ONES_TEAM_UUID"],
                },
            },
        )
        self.assertNotIn("xy-secret-token", result.stdout)
        self.assertNotIn("ones-secret-token", result.stdout)

    def test_bootstrap_cli_reports_unsupported_gitlab_url(self) -> None:
        result = self.run_bootstrap(
            "--gitlab-url",
            "https://unknown-gitlab.example.com/group/project",
            env={
                "GITLAB_ACCESS_TOKEN": "default-secret-token",
            },
        )

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload,
            {
                "gitlab": {
                    "ok": False,
                    "reason": "unsupported_instance",
                    "input": "https://unknown-gitlab.example.com/group/project",
                    "missing": [],
                }
            },
        )
        self.assertNotIn("default-secret-token", result.stdout)

    def test_gitlab_http_error_does_not_leak_token(self) -> None:
        try:
            from integrations.gitlab_adapter import lookup_project
            from runtime.http_client import HttpUnauthorizedError, HttpResponse
        except ModuleNotFoundError as exc:
            self.fail(f"missing adapter/runtime module: {exc}")

        class FakeTransport:
            def request(self, method: str, url: str, *, headers=None, data=None, timeout=10):
                return HttpResponse(
                    status=401,
                    headers={},
                    body=b'{"message":"401 Unauthorized","token":"leaky-token-123"}',
                    url=url,
                )

        with self.assertRaises(HttpUnauthorizedError) as ctx:
            lookup_project(
                "https://gitlab.xylink.com/group/project.git",
                environ={"GITLAB_ACCESS_TOKEN": "default-secret-token"},
                transport=FakeTransport(),
            )

        self.assertNotIn("default-secret-token", str(ctx.exception))
        self.assertNotIn("leaky-token-123", str(ctx.exception))

    def test_ones_http_error_does_not_leak_token(self) -> None:
        try:
            from integrations.ones_adapter import get_task_info
            from runtime.http_client import HttpUnauthorizedError, HttpResponse
        except ModuleNotFoundError as exc:
            self.fail(f"missing adapter/runtime module: {exc}")

        class FakeTransport:
            def request(self, method: str, url: str, *, headers=None, data=None, timeout=10):
                return HttpResponse(
                    status=401,
                    headers={},
                    body=b'{"message":"401 Unauthorized","token":"leaky-token-456"}',
                    url=url,
                )

        with self.assertRaises(HttpUnauthorizedError) as ctx:
            get_task_info(
                "TASK-42",
                environ={
                    "ONES_TOKEN": "ones-secret-token",
                    "ONES_USER_UUID": "user-2",
                    "ONES_TEAM_UUID": "TEAM-2",
                },
                transport=FakeTransport(),
            )

        rendered = str(ctx.exception)
        self.assertNotIn("ones-secret-token", rendered)
        self.assertNotIn("user-2", rendered)
        self.assertNotIn("leaky-token-456", rendered)

    def test_http_client_maps_timeout_to_semantic_exception(self) -> None:
        try:
            from runtime.http_client import HttpClient, HttpTimeoutError
        except ModuleNotFoundError as exc:
            self.fail(f"missing runtime module: {exc}")

        with patch(
            "runtime.http_client.urllib.request.urlopen",
            side_effect=urllib.error.URLError(socket.timeout("timed out")),
        ):
            with self.assertRaises(HttpTimeoutError) as ctx:
                HttpClient().get("https://gitlab.xylink.com/api/v4/projects")

        self.assertIn("timed out", str(ctx.exception))
