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
from yaml_compat import safe_load


class CreateCapabilityTest(ContextHubTestCase):
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

    def test_create_capability_updates_domains_and_ownership(self) -> None:
        result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "product",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        domains_path = self.hub_dir / "topology" / "domains.yaml"
        domains_payload = safe_load(domains_path.read_text())
        self.assertIn("domains", domains_payload)
        self.assertIn("product", domains_payload["domains"])

        product_domain = domains_payload["domains"]["product"]
        self.assertEqual(product_domain["description"], "待填写")
        self.assertEqual(product_domain["owner"], "待填写")
        self.assertEqual(len(product_domain["capabilities"]), 1)
        self.assertEqual(
            product_domain["capabilities"][0],
            {
                "name": "voting",
                "description": "voting",
                "path": "capabilities/voting/",
                "status": "planned",
                "ones_tasks": [],
            },
        )

        ownership_path = self.hub_dir / "topology" / "ownership.yaml"
        self.assertTrue(ownership_path.exists())
        ownership_payload = safe_load(ownership_path.read_text())
        self.assertIn("capabilities", ownership_payload)
        self.assertIn("voting", ownership_payload["capabilities"])
        self.assertEqual(
            ownership_payload["capabilities"]["voting"]["domain"],
            "product",
        )
        self.assertEqual(
            ownership_payload["capabilities"]["voting"]["maintained_by"],
            "product",
        )
        self.assertEqual(
            ownership_payload["capabilities"]["voting"]["contributors"],
            ["design", "engineering", "qa"],
        )

    def test_create_capability_persists_ones_tasks_in_domains_and_spec(self) -> None:
        result = run_script(
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

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text())
        capability = domains_payload["domains"]["product"]["capabilities"][0]
        self.assertEqual(capability["ones_tasks"], ["TASK-1", "TASK-2"])

        spec_path = self.hub_dir / "capabilities" / "voting" / "spec.md"
        spec_text = spec_path.read_text(encoding="utf-8")
        self.assertIn("ONES 关联", spec_text)
        self.assertIn("TASK-1", spec_text)
        self.assertIn("TASK-2", spec_text)

    def test_create_capability_allows_maintainer_override(self) -> None:
        result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "test-automation",
            "--domain",
            "qa",
            "--maintained-by",
            "qa",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        ownership_path = self.hub_dir / "topology" / "ownership.yaml"
        ownership_payload = safe_load(ownership_path.read_text())
        self.assertEqual(
            ownership_payload["capabilities"]["test-automation"]["domain"],
            "qa",
        )
        self.assertEqual(
            ownership_payload["capabilities"]["test-automation"]["maintained_by"],
            "qa",
        )
        self.assertEqual(
            ownership_payload["capabilities"]["test-automation"]["contributors"],
            ["design", "engineering", "qa"],
        )
