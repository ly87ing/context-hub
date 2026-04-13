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
