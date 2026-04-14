from __future__ import annotations

import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from runtime.hub_paths import role_intake_template_path
from test_support import ContextHubTestCase
from workflows.common import build_workflow_result, normalize_role, prepare_mutation_request, target_document_name


class RoleWorkflowContractTest(ContextHubTestCase):
    def test_normalize_role_and_target_document_name_contract(self) -> None:
        self.assertEqual(normalize_role("PM"), "pm")
        self.assertEqual(normalize_role("ux"), "design")
        self.assertEqual(normalize_role("研发"), "engineering")
        self.assertEqual(normalize_role("QA"), "qa")

        self.assertEqual(target_document_name("pm"), "spec.md")
        self.assertEqual(target_document_name("design"), "design.md")
        self.assertEqual(target_document_name("engineering"), "architecture.md")
        self.assertEqual(target_document_name("qa"), "testing.md")

    def test_build_workflow_result_returns_stable_json_contract(self) -> None:
        target_file = self.hub_dir / "capabilities" / "meeting-control" / "spec.md"
        updated_paths = [
            target_file,
            self.hub_dir / ".context" / "llms.txt",
        ]

        result = build_workflow_result(
            self.hub_dir,
            role="PM",
            action="create",
            capability="meeting-control",
            target_file=target_file,
            live_status="live_ok",
            updated_paths=updated_paths,
        )

        self.assertEqual(result["role"], "pm")
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["capability"], "meeting-control")
        self.assertEqual(result["target_file"], "capabilities/meeting-control/spec.md")
        self.assertEqual(result["live_status"], "live_ok")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            result["updated_paths"],
            [
                "capabilities/meeting-control/spec.md",
                ".context/llms.txt",
            ],
        )
        json.dumps(result, ensure_ascii=False, sort_keys=True)

    def test_role_intake_template_path_and_mutation_request_validation(self) -> None:
        self.assertEqual(
            role_intake_template_path(self.hub_dir, "pm"),
            self.hub_dir / "templates" / "role-intake" / "pm.md",
        )

        with self.assertRaisesRegex(ValueError, "content-file"):
            prepare_mutation_request(
                role="pm",
                action="extend",
                capability="meeting-control",
                content_file=None,
                target_file=self.hub_dir / "capabilities" / "meeting-control" / "spec.md",
                hub_root=self.hub_dir,
            )
