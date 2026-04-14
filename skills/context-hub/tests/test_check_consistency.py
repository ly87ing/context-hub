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
import runtime.validation as validation_module
import yaml_compat
from runtime.validation import load_yaml_mapping
from yaml_compat import safe_dump, safe_load


class CheckConsistencyTest(ContextHubTestCase):
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

    def test_consistency_reports_missing_team_export_metadata(self) -> None:
        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-service
visibility: shared
confidence: high
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/meeting-control-service.git
""",
        )

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("teams/engineering/exports/system-fragment.yaml", output)
        self.assertIn("last_synced_at", output)

    def test_consistency_fails_when_workflow_asset_is_missing(self) -> None:
        workflow_path = self.hub_dir / "scripts" / "workflows" / "pm_workflow.py"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text('"""temporary workflow placeholder."""\n', encoding="utf-8")
        workflow_path.unlink()

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("scripts/workflows/pm_workflow.py", output)
        self.assertIn("不存在", output)

    def test_consistency_fails_when_runtime_asset_is_missing(self) -> None:
        runtime_path = self.hub_dir / "scripts" / "runtime" / "iteration_index.py"
        self.assertTrue(runtime_path.exists())
        runtime_path.unlink()

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("scripts/runtime/iteration_index.py", output)
        self.assertIn("不存在", output)

    def test_consistency_returns_zero_for_clean_hub(self) -> None:
        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)
        self.assertIn("全部通过", output)

    def test_consistency_warns_when_llms_missing_freshness_and_ownership_markers(self) -> None:
        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-service
visibility: shared
last_synced_at: "2026-04-13T09:30:00Z"
confidence: high
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/meeting-control-service.git
""",
        )
        (self.hub_dir / ".context" / "llms.txt").write_text(
            "# meeting-control\n\n## 服务清单\n- meeting-control-service: backend\n",
            encoding="utf-8",
        )

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn(".context/llms.txt", output)
        self.assertIn("freshness", output)
        self.assertIn("ownership", output)

    def test_consistency_fails_when_ownership_teams_are_empty(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "product",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        ownership_path = self.hub_dir / "topology" / "ownership.yaml"
        ownership_payload = safe_load(ownership_path.read_text(encoding="utf-8"))
        ownership_payload["teams"] = {}
        ownership_path.write_text(
            safe_dump(ownership_payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("topology/ownership.yaml", output)
        self.assertIn("teams", output)

    def test_consistency_returns_two_when_errors_and_warnings_coexist(self) -> None:
        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-service
visibility: shared
confidence: high
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/meeting-control-service.git
""",
        )
        (self.hub_dir / ".context" / "llms.txt").write_text(
            "# meeting-control\n\n## 服务清单\n- meeting-control-service: backend\n",
            encoding="utf-8",
        )

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("缺少 export metadata", output)
        self.assertIn("⚠️  警告:", output)

    def test_consistency_warns_when_capability_missing_source_summary(self) -> None:
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

        result = run_script("check_consistency.py", cwd=self.hub_dir)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("capabilities/voting/ 缺少 source-summary.yaml", output)

    def test_validation_rejects_ownership_yaml_without_yaml_parser(self) -> None:
        ownership_path = self.hub_dir / "topology" / "ownership.yaml"
        ownership_path.write_text(
            "\n".join(
                [
                    "project_id: meeting-control",
                    "project_name: meeting-control",
                    "teams:",
                    "  engineering:",
                    "    visibility: shared",
                    "    exports_dir: teams/engineering/exports",
                    "capabilities: {}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        original_yaml = validation_module.yaml_compat._yaml
        yaml_compat._yaml = None
        validation_module.yaml_compat._yaml = None
        try:
            with self.assertRaisesRegex(ValueError, "PyYAML|fallback|标准 YAML parser"):
                load_yaml_mapping(ownership_path)
        finally:
            yaml_compat._yaml = original_yaml
            validation_module.yaml_compat._yaml = original_yaml
