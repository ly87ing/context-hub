from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from test_support import ContextHubTestCase, run_script
from yaml_compat import safe_dump, safe_load


class CheckStaleTest(ContextHubTestCase):
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

    def write_export(self, team_id: str, filename: str, content: str) -> None:
        export_path = self.hub_dir / "teams" / team_id / "exports" / filename
        export_path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_stale_reports_export_freshness_from_last_synced_at(self) -> None:
        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-service
visibility: shared
last_synced_at: "2000-01-01T00:00:00Z"
confidence: high
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/meeting-control-service.git
""",
        )

        result = run_script("check_stale.py", "--warn-days", "30", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("teams/engineering/exports/system-fragment.yaml", output)
        self.assertIn("last_synced_at", output)

    def test_stale_returns_zero_for_clean_hub(self) -> None:
        result = run_script("check_stale.py", "--warn-days", "30", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)
        self.assertIn("没有 stale 或 blocking 问题", output)

    def test_stale_blocks_in_progress_capability_missing_role_file(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "product",
            "--status",
            "in-progress",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)
        (self.hub_dir / "capabilities" / "voting" / "testing.md").unlink()

        result = run_script("check_stale.py", "--warn-days", "30", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("voting", output)
        self.assertIn("testing.md", output)

    def test_stale_returns_two_when_warnings_and_blocking_errors_coexist(self) -> None:
        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-service
visibility: shared
last_synced_at: "2000-01-01T00:00:00Z"
confidence: high
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/meeting-control-service.git
""",
        )
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "product",
            "--status",
            "in-progress",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)
        (self.hub_dir / "capabilities" / "voting" / "testing.md").unlink()

        result = run_script("check_stale.py", "--warn-days", "30", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("已 stale", output)
        self.assertIn("缺少关键文件", output)

    def test_stale_warns_when_capability_ones_sync_is_outdated(self) -> None:
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
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        domains_path = self.hub_dir / "topology" / "domains.yaml"
        payload = safe_load(domains_path.read_text(encoding="utf-8"))
        payload["domains"]["product"]["capabilities"][0]["last_synced_at"] = "2000-01-01T00:00:00Z"
        domains_path.write_text(
            safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = run_script("check_stale.py", "--warn-days", "30", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("capability voting 已 stale", output)
