from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from runtime.hub_io import load_template, render_template
from test_support import ContextHubTestCase, run_script


class InitContextHubTest(ContextHubTestCase):
    def test_template_render_produces_ownership_seed(self) -> None:
        template_text = load_template("ownership.yaml")

        rendered = render_template(
            template_text,
            {
                "project_id": "meeting-control",
                "project_name": "meeting-control",
            },
        )

        self.assertIn("teams:", rendered)
        self.assertIn("engineering:", rendered)

    def test_init_creates_federated_layout(self) -> None:
        result = run_script(
            "init_context_hub.py",
            "--output",
            str(self.hub_dir),
            "--name",
            "meeting-control",
            "--id",
            "meeting-control",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((self.hub_dir / "topology" / "ownership.yaml").exists())
        self.assertTrue((self.hub_dir / "teams" / "product" / "exports").exists())
        self.assertTrue((self.hub_dir / "teams" / "design" / "exports").exists())
        self.assertTrue((self.hub_dir / "teams" / "engineering" / "exports").exists())
        self.assertTrue((self.hub_dir / "teams" / "qa" / "exports").exists())
        self.assertTrue((self.hub_dir / "topology" / "design-sources.yaml").exists())
        self.assertTrue((self.hub_dir / "topology" / "releases.yaml").exists())
        self.assertTrue((self.hub_dir / "scripts" / "sync_capability_status.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "sync_design_context.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "check_semantic_consistency.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "commit_ops.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "iteration_index.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "lifecycle_state.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "release_index.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "semantic_consistency.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "runtime" / "maintenance_advice.py").exists())

    def test_init_copies_workflow_skeleton_assets(self) -> None:
        result = run_script(
            "init_context_hub.py",
            "--output",
            str(self.hub_dir),
            "--name",
            "meeting-control",
            "--id",
            "meeting-control",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((self.hub_dir / "scripts" / "workflows" / "common.py").exists())
        self.assertTrue((self.hub_dir / "scripts" / "workflows" / "pm_workflow.py").exists())
        self.assertTrue((self.hub_dir / "templates" / "role-intake" / "pm.md").exists())
        self.assertTrue((self.hub_dir / "templates" / "design-fragment.yaml").exists())

    def test_init_dry_run_reports_actions_without_writing(self) -> None:
        result = run_script(
            "init_context_hub.py",
            "--output",
            str(self.hub_dir),
            "--name",
            "meeting-control",
            "--id",
            "meeting-control",
            "--dry-run",
            "--auto-commit",
            "--auto-push",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse((self.hub_dir / "IDENTITY.md").exists())
        self.assertFalse((self.hub_dir / "topology" / "ownership.yaml").exists())
        self.assertFalse((self.hub_dir / "teams").exists())
        self.assertIn("DRY-RUN", result.stdout)
        self.assertIn("DRY-RUN target hub auto-commit requested", result.stdout)
        self.assertIn("DRY-RUN target hub auto-push requested", result.stdout)
