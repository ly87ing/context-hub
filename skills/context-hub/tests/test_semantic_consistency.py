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


class SemanticConsistencyTest(ContextHubTestCase):
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

    def create_capability(self, capability: str = "voting") -> None:
        create_result = run_script(
            "create_capability.py",
            "--hub",
            str(self.hub_dir),
            "--name",
            capability,
            "--domain",
            "meeting",
        )
        self.assertEqual(create_result.returncode, 0, msg=create_result.stderr)

    def test_reports_spec_source_summary_status_conflict(self) -> None:
        self.create_capability()
        capability_dir = self.hub_dir / "capabilities" / "voting"
        capability_dir.joinpath("spec.md").write_text(
            "# voting spec\n\n## Status\nplanned\n",
            encoding="utf-8",
        )
        capability_dir.joinpath("source-summary.yaml").write_text(
            safe_dump(
                {
                    "capability": "voting",
                    "domain": "meeting",
                    "source_system": "ones",
                    "source_ref": "TASK-1",
                    "last_synced_at": "2026-04-13T12:00:00Z",
                    "status": "stable",
                    "items": [],
                    "acceptance_summary": "stable",
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        from runtime.semantic_consistency import audit_capability_semantics

        payload = audit_capability_semantics(self.hub_dir, "voting")

        self.assertEqual(payload["warning_issue_count"], 1)
        self.assertEqual(payload["issues"][0]["rule_id"], "spec-source-summary-status")
        self.assertEqual(payload["issues"][0]["severity"], "warning")
        self.assertEqual(payload["issues"][0]["suggested_role"], "pm")

    def test_reports_design_states_missing_from_testing(self) -> None:
        self.create_capability()
        capability_dir = self.hub_dir / "capabilities" / "voting"
        capability_dir.joinpath("design.md").write_text(
            "\n".join(
                [
                    "# voting design",
                    "",
                    "## 页面与状态",
                    "",
                    "### 投票页",
                    "",
                    "#### 状态矩阵",
                    "| 状态 | 描述 | 进入条件 | 退出条件 |",
                    "|:--|:--|:--|:--|",
                    "| draft | 初稿 | 创建后 | review 完成后 |",
                    "| reviewed | 已评审 | review 完成后 | ready |",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        capability_dir.joinpath("testing.md").write_text(
            "\n".join(
                [
                    "# voting testing",
                    "",
                    "## 环境要求",
                    "| staging | 可 mock |",
                    "",
                    "## 数据准备",
                    "- draft",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (self.hub_dir / "topology" / "testing-sources.yaml").write_text(
            safe_dump(
                {
                    "sources": [
                        {"name": "staging", "url": "https://example.test", "type": "manual"},
                        {"name": "draft", "url": "https://example.test/draft", "type": "manual"},
                    ]
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        from runtime.semantic_consistency import audit_capability_semantics

        payload = audit_capability_semantics(self.hub_dir, "voting")

        self.assertEqual(payload["blocking_issue_count"], 1)
        self.assertEqual(payload["issues"][0]["rule_id"], "design-testing-state-coverage")
        self.assertEqual(payload["issues"][0]["suggested_role"], "qa")
        self.assertEqual(payload["issues"][0]["evidence"]["missing_states"], ["reviewed"])

    def test_reports_architecture_services_missing_from_system_yaml(self) -> None:
        self.create_capability()
        capability_dir = self.hub_dir / "capabilities" / "voting"
        capability_dir.joinpath("architecture.md").write_text(
            "\n".join(
                [
                    "# voting architecture",
                    "",
                    "## 涉及的服务",
                    "",
                    "| 服务 | 变更类型 | 说明 |",
                    "|:--|:--|:--|",
                    "| ghost-service | 修改逻辑 | 新的调用边界 |",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        from runtime.semantic_consistency import audit_capability_semantics

        payload = audit_capability_semantics(self.hub_dir, "voting")

        self.assertEqual(payload["blocking_issue_count"], 1)
        self.assertEqual(payload["issues"][0]["rule_id"], "architecture-system-service-reference")
        self.assertEqual(payload["issues"][0]["evidence"]["missing_services"], ["ghost-service"])

    def test_reports_testing_references_missing_from_testing_sources_yaml(self) -> None:
        self.create_capability()
        capability_dir = self.hub_dir / "capabilities" / "voting"
        capability_dir.joinpath("testing.md").write_text(
            "\n".join(
                [
                    "# voting testing",
                    "",
                    "## 环境要求",
                    "| staging-cluster | 真实环境 |",
                    "",
                    "## 数据准备",
                    "- nightly-smoke",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (self.hub_dir / "topology" / "testing-sources.yaml").write_text(
            safe_dump(
                {"sources": [{"name": "qa-lab", "url": "https://example.test", "type": "manual"}]},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        from runtime.semantic_consistency import audit_capability_semantics

        payload = audit_capability_semantics(self.hub_dir, "voting")

        self.assertEqual(payload["blocking_issue_count"], 1)
        self.assertEqual(payload["issues"][0]["rule_id"], "testing-sources-reference")
        self.assertEqual(
            payload["issues"][0]["evidence"]["missing_sources"],
            ["staging-cluster", "nightly-smoke"],
        )

    def test_cli_writes_capability_audit_payload(self) -> None:
        self.create_capability()
        output_path = self.hub_dir / "semantic-consistency.yaml"

        result = run_script(
            "check_semantic_consistency.py",
            "--hub",
            str(self.hub_dir),
            "--capability",
            "voting",
            "--output",
            str(output_path),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        self.assertTrue(output_path.exists())
        payload = safe_load(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["capability"], "voting")
        self.assertEqual(payload["blocking_issue_count"], 0)
