from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from runtime.hub_paths import role_intake_template_path
from runtime.capability_ops import capability_target_document_path
from test_support import ContextHubTestCase, run_script
from workflows.common import build_workflow_result, normalize_role, prepare_mutation_request, target_document_name
from yaml_compat import safe_dump
from integrations.credentials import MissingCredentialsError
from yaml_compat import safe_load


class RoleWorkflowContractTest(ContextHubTestCase):
    def test_normalize_role_and_target_document_name_contract(self) -> None:
        self.assertEqual(normalize_role("PM"), "pm")
        self.assertEqual(normalize_role("ux"), "design")
        self.assertEqual(normalize_role("设计"), "design")
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
        used_sources = [
            self.hub_dir / "topology" / "domains.yaml",
            "capabilities/meeting-control/spec-source.md",
        ]

        result = build_workflow_result(
            self.hub_dir,
            role="PM",
            action="create",
            capability="meeting-control",
            target_file=target_file,
            used_sources=used_sources,
            live_status="live_ok",
            updated_paths=updated_paths,
        )

        self.assertEqual(result["role"], "pm")
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["capability"], "meeting-control")
        self.assertEqual(result["target_file"], "capabilities/meeting-control/spec.md")
        self.assertEqual(
            result["used_sources"],
            [
                "topology/domains.yaml",
                "capabilities/meeting-control/spec-source.md",
            ],
        )
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

    def test_build_workflow_result_preserves_uri_like_used_sources(self) -> None:
        result = build_workflow_result(
            self.hub_dir,
            role="pm",
            action="align",
            capability="voting",
            target_file=self.hub_dir / "capabilities" / "voting" / "spec.md",
            used_sources=["ones://task/TASK-42"],
            live_status="live_ok",
            updated_paths=[self.hub_dir / "capabilities" / "voting" / "spec.md"],
        )

        self.assertEqual(result["used_sources"], ["ones://task/TASK-42"])

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

    def test_prepare_mutation_request_returns_success_contract(self) -> None:
        request = prepare_mutation_request(
            role="pm",
            action="extend",
            capability="meeting-control",
            content_file="capabilities/meeting-control/spec-source.md",
            target_file="capabilities/meeting-control/spec.md",
            hub_root=self.hub_dir,
        )

        self.assertEqual(request["role"], "pm")
        self.assertEqual(request["action"], "extend")
        self.assertEqual(request["capability"], "meeting-control")
        self.assertEqual(request["content_file"], self.hub_dir / "capabilities" / "meeting-control" / "spec-source.md")
        self.assertEqual(request["target_file"], self.hub_dir / "capabilities" / "meeting-control" / "spec.md")
        self.assertEqual(request["hub_root"], self.hub_dir)
        self.assertIsInstance(request["hub_root"], Path)

    def test_capability_target_document_path_uses_role_contract(self) -> None:
        capability_dir = self.hub_dir / "capabilities" / "meeting-control"
        self.assertEqual(
            capability_target_document_path(capability_dir, "设计"),
            capability_dir / "design.md",
        )


class PMWorkflowTest(ContextHubTestCase):
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

    def test_pm_create_bootstraps_missing_capability_and_writes_spec_from_draft(self) -> None:
        draft_path = self.workdir / "pm-draft.md"
        draft_text = "# Voting draft\n\n- collect requirements\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        result = run_script(
            "workflows/pm_workflow.py",
            "--hub",
            str(self.hub_dir),
            "--capability",
            "voting",
            "--action",
            "create",
            "--domain",
            "meeting",
            "--content-file",
            str(draft_path),
            "--output-format",
            "json",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["role"], "pm")
        self.assertEqual(payload["live_status"], "fallback_to_hub")

        spec_path = self.hub_dir / "capabilities" / "voting" / "spec.md"
        self.assertTrue(spec_path.exists())
        self.assertEqual(spec_path.read_text(encoding="utf-8"), draft_text)

    def test_pm_create_normalizes_capability_and_domain_slug(self) -> None:
        draft_path = self.workdir / "pm-slug-draft.md"
        draft_text = "# Voting Board draft\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        result = run_script(
            "workflows/pm_workflow.py",
            "--hub",
            str(self.hub_dir),
            "--capability",
            "Voting Board",
            "--action",
            "create",
            "--domain",
            "Meeting Ops",
            "--content-file",
            str(draft_path),
            "--output-format",
            "json",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["capability"], "voting-board")
        self.assertEqual(payload["target_file"], "capabilities/voting-board/spec.md")
        self.assertTrue((self.hub_dir / "capabilities" / "voting-board" / "spec.md").exists())

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text(encoding="utf-8"))
        self.assertIn("meeting-ops", domains_payload["domains"])
        capability_entry = domains_payload["domains"]["meeting-ops"]["capabilities"][0]
        self.assertEqual(capability_entry["name"], "voting-board")
        self.assertEqual(capability_entry["path"], "capabilities/voting-board/")

    def test_run_pm_workflow_align_returns_live_ok_when_ones_lookup_succeeds(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
            "--ones-task",
            "TASK-42",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        draft_path = self.workdir / "align-draft.md"
        draft_path.write_text("# aligned spec\n", encoding="utf-8")

        from workflows.pm_workflow import run_pm_workflow

        with patch(
            "workflows.pm_workflow.ones_adapter.get_task_info",
            return_value={"uuid": "TASK-42", "number": 42, "name": "Voting"},
        ):
            result = run_pm_workflow(
                hub_root=self.hub_dir,
                capability="voting",
                action="align",
                domain="meeting",
                content_file=draft_path,
                task_ref="TASK-42",
            )

        self.assertEqual(result["role"], "pm")
        self.assertEqual(result["live_status"], "live_ok")
        self.assertIn("ones://task/TASK-42", result["used_sources"])

    def test_run_pm_workflow_align_falls_back_to_hub_when_ones_lookup_fails(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
            "--ones-task",
            "TASK-99",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        summary_path = self.hub_dir / "capabilities" / "voting" / "source-summary.yaml"
        summary_path.write_text(
            safe_dump(
                {
                    "capability": "voting",
                    "domain": "meeting",
                    "source_system": "ones",
                    "source_ref": "TASK-99",
                    "last_synced_at": "2026-04-13T12:00:00Z",
                    "status": "planned",
                    "items": [{"uuid": "TASK-99", "name": "Voting"}],
                    "acceptance_summary": "Voting(planned)",
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        draft_path = self.workdir / "fallback-align-draft.md"
        draft_path.write_text("# fallback spec\n", encoding="utf-8")

        from workflows.pm_workflow import run_pm_workflow

        with patch(
            "workflows.pm_workflow.ones_adapter.get_task_info",
            side_effect=ValueError("missing credentials"),
        ):
            result = run_pm_workflow(
                hub_root=self.hub_dir,
                capability="voting",
                action="align",
                domain="meeting",
                content_file=draft_path,
                task_ref="TASK-99",
            )

        self.assertEqual(result["role"], "pm")
        self.assertEqual(result["live_status"], "fallback_to_hub")
        self.assertIn("未实时校验", result["warnings"][0])

    def test_run_pm_workflow_align_falls_back_to_hub_on_missing_credentials_error(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
            "--ones-task",
            "TASK-77",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        summary_path = self.hub_dir / "capabilities" / "voting" / "source-summary.yaml"
        summary_path.write_text(
            safe_dump(
                {
                    "capability": "voting",
                    "domain": "meeting",
                    "source_system": "ones",
                    "source_ref": "TASK-77",
                    "last_synced_at": "2026-04-13T12:00:00Z",
                    "status": "planned",
                    "items": [{"uuid": "TASK-77", "name": "Voting"}],
                    "acceptance_summary": "Voting(planned)",
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        draft_path = self.workdir / "credentials-fallback-align-draft.md"
        draft_path.write_text("# fallback spec via credentials error\n", encoding="utf-8")

        from workflows.pm_workflow import run_pm_workflow

        with patch(
            "workflows.pm_workflow.ones_adapter.get_task_info",
            side_effect=MissingCredentialsError(["ONES_TOKEN"]),
        ):
            result = run_pm_workflow(
                hub_root=self.hub_dir,
                capability="voting",
                action="align",
                domain="meeting",
                content_file=draft_path,
                task_ref="TASK-77",
            )

        self.assertEqual(result["live_status"], "fallback_to_hub")
        self.assertIn("未实时校验", result["warnings"][0])


class DesignWorkflowTest(ContextHubTestCase):
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

    def test_run_design_workflow_align_returns_live_ok_when_figma_probe_succeeds(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        draft_path = self.workdir / "design-align-draft.md"
        draft_text = "# voting design\n\n- align states\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        from runtime.http_client import HttpResponse
        from workflows.design_workflow import run_design_workflow

        def transport(request):
            return HttpResponse(status=200, headers={}, body=b"ok", url=request.url)

        result = run_design_workflow(
            hub_root=self.hub_dir,
            capability="voting",
            action="align",
            content_file=draft_path,
            figma_url="https://www.figma.com/design/FILE123/Voting?node-id=12-34",
            transport=transport,
        )

        self.assertEqual(result["role"], "design")
        self.assertEqual(result["live_status"], "live_ok")
        self.assertIn(str(draft_path), result["used_sources"])
        self.assertIn(
            "https://www.figma.com/design/FILE123/Voting?node-id=12-34",
            result["used_sources"],
        )

        design_path = self.hub_dir / "capabilities" / "voting" / "design.md"
        self.assertEqual(design_path.read_text(encoding="utf-8"), draft_text)

    def test_run_design_workflow_align_falls_back_to_hub_without_live_figma_validation(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        draft_path = self.workdir / "design-fallback-draft.md"
        draft_text = "# fallback design\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        from workflows.design_workflow import run_design_workflow

        result = run_design_workflow(
            hub_root=self.hub_dir,
            capability="voting",
            action="align",
            content_file=draft_path,
            figma_url=None,
        )

        self.assertEqual(result["live_status"], "fallback_to_hub")
        self.assertIn("未实时校验", result["warnings"][0])

        design_path = self.hub_dir / "capabilities" / "voting" / "design.md"
        self.assertEqual(design_path.read_text(encoding="utf-8"), draft_text)

    def test_run_design_workflow_align_falls_back_to_hub_when_figma_probe_is_blocked(self) -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            "voting",
            "--domain",
            "meeting",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

        draft_path = self.workdir / "design-blocked-draft.md"
        draft_text = "# blocked fallback design\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        from workflows.design_workflow import run_design_workflow

        result = run_design_workflow(
            hub_root=self.hub_dir,
            capability="voting",
            action="align",
            content_file=draft_path,
            figma_url="https://example.com/design/FILE123/Voting?node-id=12-34",
        )

        self.assertEqual(result["live_status"], "fallback_to_hub")
        self.assertIn("未实时校验", result["warnings"][0])

        design_path = self.hub_dir / "capabilities" / "voting" / "design.md"
        self.assertEqual(design_path.read_text(encoding="utf-8"), draft_text)

    def test_run_design_workflow_requires_existing_capability(self) -> None:
        draft_path = self.workdir / "design-missing-capability-draft.md"
        draft_text = "# missing capability design\n"
        draft_path.write_text(draft_text, encoding="utf-8")

        from workflows.design_workflow import run_design_workflow

        with self.assertRaisesRegex(ValueError, "需已有 capability 或 PM 先建"):
            run_design_workflow(
                hub_root=self.hub_dir,
                capability="missing-voting",
                action="align",
                content_file=draft_path,
                figma_url=None,
            )

        self.assertFalse((self.hub_dir / "capabilities" / "missing-voting" / "design.md").exists())
