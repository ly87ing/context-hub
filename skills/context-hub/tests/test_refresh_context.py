from __future__ import annotations

import sys
from unittest.mock import patch
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
for path in (THIS_DIR, SCRIPTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import refresh_context
from test_support import ContextHubTestCase, run_script
from yaml_compat import safe_load


class RefreshContextTest(ContextHubTestCase):
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

    def test_refresh_context_aggregates_team_exports_and_updates_llms(self) -> None:
        self.write_export(
            "product",
            "domains-fragment.yaml",
            """
maintained_by: product
source_system: ones
source_ref: PRD-123
visibility: shared
last_synced_at: "2026-04-13T08:45:00Z"
confidence: high
domains:
  meeting-workflow:
    description: Meeting lifecycle orchestration
    owner: product
    capabilities: []
""",
        )

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
    domain: shared
    owner: engineering
infrastructure:
  kafka-main:
    type: kafka
    owner: platform
""",
        )

        self.write_export(
            "qa",
            "testing-fragment.yaml",
            """
maintained_by: qa
source_system: ones
source_ref: QA-automation
visibility: shared
last_synced_at: "2026-04-13T10:00:00Z"
confidence: medium
sources:
  - name: regression-suite
    type: playwright
    url: https://qa.example.com/regression-suite
""",
        )

        result = run_script("refresh_context.py", str(self.hub_dir))

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        system_payload = safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))
        self.assertIn("services", system_payload)
        self.assertIn("meeting-control-service", system_payload["services"])
        self.assertEqual(
            system_payload["services"]["meeting-control-service"]["repo"],
            "https://git.example.com/meeting-control-service.git",
        )

        testing_payload = safe_load(
            (self.hub_dir / "topology" / "testing-sources.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            testing_payload["sources"][0]["name"],
            "regression-suite",
        )

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text(encoding="utf-8"))
        self.assertIn("domains", domains_payload)
        self.assertIn("meeting-workflow", domains_payload["domains"])
        self.assertEqual(
            domains_payload["domains"]["meeting-workflow"]["owner"],
            "product",
        )

        llms_text = (self.hub_dir / ".context" / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("regression-suite", llms_text)
        self.assertIn("meeting-workflow", llms_text)
        self.assertIn("maintained by product", llms_text)
        self.assertIn("maintained by engineering", llms_text)
        self.assertIn("maintained by qa", llms_text)
        self.assertIn("freshness: 2026-04-13T08:45:00Z", llms_text)
        self.assertIn("freshness: 2026-04-13T10:00:00Z", llms_text)

    def test_refresh_context_aggregates_design_exports_and_release_index(self) -> None:
        draft_path = self.workdir / "pm-refresh-design-draft.md"
        draft_path.write_text("# voting spec\n", encoding="utf-8")
        pm_result = run_script(
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
            "--iteration",
            "Sprint 12",
            "--release",
            "2026.04",
            "--output-format",
            "json",
        )
        self.assertEqual(pm_result.returncode, 0, msg=pm_result.stderr)

        self.write_export(
            "design",
            "design-fragment.yaml",
            """
maintained_by: design
source_system: figma
source_ref: design-fragment.yaml
visibility: shared
last_synced_at: "2026-04-13T10:15:00Z"
confidence: medium
sources:
  - name: voting-flow
    capability: voting
    figma_url: https://www.figma.com/design/FILE123/Voting?node-id=12-34
    status: active
""",
        )

        result = run_script("refresh_context.py", str(self.hub_dir), "--sync-design")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)

        design_payload = safe_load((self.hub_dir / "topology" / "design-sources.yaml").read_text(encoding="utf-8"))
        self.assertEqual(design_payload["sources"][0]["name"], "voting-flow")
        self.assertEqual(design_payload["sources"][0]["figma"]["file_key"], "FILE123")

        release_payload = safe_load((self.hub_dir / "topology" / "releases.yaml").read_text(encoding="utf-8"))
        self.assertEqual(release_payload["releases"][0]["release"], "2026.04")
        self.assertEqual(release_payload["releases"][0]["iteration"], "Sprint 12")
        self.assertEqual(release_payload["releases"][0]["capabilities"], ["voting"])

        llms_text = (self.hub_dir / ".context" / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("## 设计源", llms_text)
        self.assertIn("voting-flow", llms_text)
        self.assertIn("## 迭代 / Release", llms_text)
        self.assertIn("2026.04 / Sprint 12", llms_text)

    def test_sync_topology_aggregates_engineering_exports_without_gitlab_scan(self) -> None:
        (self.hub_dir / "topology" / "system.yaml").write_text(
            """
services:
  legacy-console:
    type: frontend
    repo: https://git.example.com/legacy-console.git
    maintained_by: design
infrastructure:
  shared-redis:
    type: redis
    owner: platform
""".strip()
            + "\n",
            encoding="utf-8",
        )

        self.write_export(
            "engineering",
            "system-fragment.yaml",
            """
maintained_by: engineering
source_system: gitlab
source_ref: group/meeting-control-bff
visibility: shared
last_synced_at: "2026-04-13T11:00:00Z"
confidence: high
services:
  meeting-control-bff:
    type: bff
    repo: https://git.example.com/meeting-control-bff.git
""",
        )

        result = run_script("sync_topology.py", "--hub", str(self.hub_dir))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("GitLab topology sync complete", result.stdout)

        system_payload = safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))
        self.assertIn("meeting-control-bff", system_payload["services"])
        self.assertIn("legacy-console", system_payload["services"])
        self.assertIn("shared-redis", system_payload["infrastructure"])

    def test_run_refresh_workflow_dry_run_skips_side_effects(self) -> None:
        with (
            patch.object(refresh_context, "refresh_shared_context") as refresh_mock,
            patch.object(refresh_context, "run_gitlab_sync") as gitlab_mock,
            patch.object(refresh_context, "run_ones_sync") as ones_mock,
            patch.object(refresh_context, "auto_commit_and_push") as commit_mock,
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
                sync_ones=True,
                dry_run=True,
                auto_commit=True,
                auto_push=True,
            )

        self.assertEqual(result["warnings"], ["dry-run: skipped writes"])
        self.assertFalse(result["committed"])
        refresh_mock.assert_not_called()
        gitlab_mock.assert_not_called()
        ones_mock.assert_not_called()
        commit_mock.assert_not_called()

    def test_run_refresh_workflow_skips_commit_when_sync_warnings_exist(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ) as refresh_mock,
            patch.object(refresh_context, "run_gitlab_sync", side_effect=ValueError("gitlab unavailable")) as gitlab_mock,
            patch.object(refresh_context, "run_ones_sync", return_value=[self.hub_dir / "capabilities" / "voting" / "source-summary.yaml"]) as ones_mock,
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path) as llms_mock,
            patch.object(refresh_context, "auto_commit_and_push", return_value=True) as commit_mock,
            patch.object(refresh_context, "run_validation_checks", return_value=[]) as validate_mock,
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
                sync_ones=True,
                ones_team="TEAM-UUID",
                auto_commit=True,
                auto_push=True,
            )

        refresh_mock.assert_called_once_with(self.hub_dir.resolve())
        gitlab_mock.assert_called_once_with(
            self.hub_dir.resolve(),
            repo_url=None,
            branch=None,
            commit_sha=None,
        )
        ones_mock.assert_called_once_with(self.hub_dir.resolve(), team_uuid="TEAM-UUID")
        llms_mock.assert_called_once_with(self.hub_dir.resolve())
        validate_mock.assert_called_once_with(self.hub_dir.resolve())
        commit_mock.assert_not_called()
        self.assertFalse(result["committed"])
        self.assertEqual(result["outputs"]["llms"], llms_path)
        self.assertIn("gitlab unavailable", result["warnings"])

    def test_run_refresh_workflow_runs_validation_before_commit(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        summary_path = self.hub_dir / "capabilities" / "voting" / "source-summary.yaml"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ) as refresh_mock,
            patch.object(refresh_context, "run_gitlab_sync", return_value=topology_dir / "system.yaml") as gitlab_mock,
            patch.object(refresh_context, "run_ones_sync", return_value=[summary_path]) as ones_mock,
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path) as llms_mock,
            patch.object(refresh_context, "run_validation_checks", return_value=[]) as validate_mock,
            patch.object(refresh_context, "auto_commit_and_push", return_value=True) as commit_mock,
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
                sync_ones=True,
                auto_commit=True,
            )

        refresh_mock.assert_called_once_with(self.hub_dir.resolve())
        gitlab_mock.assert_called_once_with(
            self.hub_dir.resolve(),
            repo_url=None,
            branch=None,
            commit_sha=None,
        )
        ones_mock.assert_called_once_with(self.hub_dir.resolve(), team_uuid=None)
        llms_mock.assert_called_once_with(self.hub_dir.resolve())
        validate_mock.assert_called_once_with(self.hub_dir.resolve())
        commit_mock.assert_called_once_with(
            self.hub_dir.resolve(),
            message="chore: refresh context hub",
            push=False,
            paths=[
                topology_dir / "domains.yaml",
                topology_dir / "system.yaml",
                topology_dir / "testing-sources.yaml",
                llms_path,
                self.hub_dir.resolve() / "topology" / "releases.yaml",
                summary_path,
            ],
        )
        self.assertTrue(result["committed"])

    def test_run_refresh_workflow_runs_design_sync_release_index_and_semantic_audit(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        design_path = topology_dir / "design-sources.yaml"
        release_path = topology_dir / "releases.yaml"
        semantic_path = self.hub_dir / "capabilities" / "voting" / "semantic-consistency.yaml"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(refresh_context, "run_design_sync", return_value=design_path) as design_mock,
            patch.object(refresh_context, "run_release_sync", return_value=release_path) as release_mock,
            patch.object(
                refresh_context,
                "run_semantic_audit",
                return_value={"paths": [semantic_path], "warnings": []},
            ) as semantic_mock,
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path),
            patch.object(refresh_context, "run_validation_checks", return_value=[]),
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_design=True,
            )

        design_mock.assert_called_once_with(self.hub_dir.resolve())
        release_mock.assert_called_once_with(self.hub_dir.resolve())
        semantic_mock.assert_called_once_with(self.hub_dir.resolve())
        self.assertEqual(result["outputs"]["design"], design_path)
        self.assertEqual(result["outputs"]["releases"], release_path)
        self.assertEqual(result["semantic_paths"], [semantic_path])

    def test_run_refresh_workflow_skips_commit_when_semantic_audit_reports_warnings(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        design_path = topology_dir / "design-sources.yaml"
        release_path = topology_dir / "releases.yaml"
        semantic_path = self.hub_dir / "capabilities" / "voting" / "semantic-consistency.yaml"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(refresh_context, "run_design_sync", return_value=design_path),
            patch.object(refresh_context, "run_release_sync", return_value=release_path),
            patch.object(
                refresh_context,
                "run_semantic_audit",
                return_value={
                    "paths": [semantic_path],
                    "warnings": ["semantic audit: testing.md 未覆盖 design 状态"],
                },
            ),
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path),
            patch.object(refresh_context, "run_validation_checks", return_value=[]),
            patch.object(refresh_context, "auto_commit_and_push", return_value=True) as commit_mock,
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_design=True,
                auto_commit=True,
            )

        commit_mock.assert_not_called()
        self.assertFalse(result["committed"])
        self.assertIn("semantic audit", result["warnings"][0])
        self.assertIn("auto-commit skipped", result["warnings"][-1])

    def test_run_refresh_workflow_threads_repo_branch_and_commit_to_gitlab_sync(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        gitlab_result = {
            "mode": "incremental",
            "decision": "scan",
            "reason_code": "",
            "changed_files": ["pyproject.toml"],
            "matched_services": ["meeting-control-service"],
            "synced_services": ["meeting-control-service"],
            "reason": "",
            "system_path": topology_dir / "system.yaml",
        }
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(refresh_context, "run_gitlab_sync", return_value=gitlab_result) as gitlab_mock,
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path),
            patch.object(refresh_context, "run_validation_checks", return_value=[]),
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
                gitlab_url="git@itgitlab.xylink.com:group/meeting-control-service.git",
                gitlab_branch="main",
                gitlab_commit="abc123",
            )

        gitlab_mock.assert_called_once_with(
            self.hub_dir.resolve(),
            repo_url="git@itgitlab.xylink.com:group/meeting-control-service.git",
            branch="main",
            commit_sha="abc123",
        )
        self.assertEqual(result["outputs"]["system"], topology_dir / "system.yaml")
        self.assertEqual(result["warnings"], [])

    def test_run_refresh_workflow_propagates_incremental_gitlab_changed_files_errors(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(
                refresh_context,
                "run_gitlab_sync",
                side_effect=ValueError("unable to read changed files"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "unable to read changed files"):
                refresh_context.run_refresh_workflow(
                    self.hub_dir,
                    sync_gitlab=True,
                    gitlab_url="git@itgitlab.xylink.com:group/meeting-control-service.git",
                    gitlab_branch="main",
                    gitlab_commit="abc123",
                )

    def test_run_refresh_workflow_does_not_turn_incremental_skip_reason_into_warning(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(
                refresh_context,
                "run_gitlab_sync",
                return_value={
                    "mode": "incremental",
                    "decision": "skip",
                    "reason_code": "no_topology_signal",
                    "reason": "docs-only changes",
                    "changed_files": ["README.md"],
                    "matched_services": ["meeting-control-service"],
                    "synced_services": [],
                    "system_path": topology_dir / "system.yaml",
                },
            ),
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path),
            patch.object(refresh_context, "run_validation_checks", return_value=[]),
        ):
            result = refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
                gitlab_url="git@itgitlab.xylink.com:group/meeting-control-service.git",
                gitlab_branch="main",
                gitlab_commit="abc123",
            )

        self.assertEqual(result["warnings"], [])

    def test_run_refresh_workflow_without_gitlab_url_keeps_full_sync_path(self) -> None:
        topology_dir = self.hub_dir / "topology"
        llms_path = self.hub_dir / ".context" / "llms.txt"
        with (
            patch.object(
                refresh_context,
                "refresh_shared_context",
                return_value={
                    "domains": topology_dir / "domains.yaml",
                    "system": topology_dir / "system.yaml",
                    "testing": topology_dir / "testing-sources.yaml",
                    "llms": llms_path,
                },
            ),
            patch.object(refresh_context, "run_gitlab_sync", return_value=topology_dir / "system.yaml") as gitlab_mock,
            patch.object(refresh_context, "refresh_llms_txt", return_value=llms_path),
            patch.object(refresh_context, "run_validation_checks", return_value=[]),
        ):
            refresh_context.run_refresh_workflow(
                self.hub_dir,
                sync_gitlab=True,
            )

        gitlab_mock.assert_called_once_with(
            self.hub_dir.resolve(),
            repo_url=None,
            branch=None,
            commit_sha=None,
        )

    def test_refresh_context_rejects_incremental_gitlab_sync_without_branch(self) -> None:
        result = run_script(
            "refresh_context.py",
            str(self.hub_dir),
            "--sync-gitlab",
            "--gitlab-url",
            "git@itgitlab.xylink.com:group/meeting-control-service.git",
            "--gitlab-commit",
            "abc123",
        )

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gitlab-branch", output)

    def test_refresh_context_rejects_incremental_gitlab_sync_without_commit(self) -> None:
        result = run_script(
            "refresh_context.py",
            str(self.hub_dir),
            "--sync-gitlab",
            "--gitlab-url",
            "git@itgitlab.xylink.com:group/meeting-control-service.git",
            "--gitlab-branch",
            "main",
        )

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gitlab-commit", output)

    def test_refresh_context_dry_run_does_not_claim_files_refreshed(self) -> None:
        result = run_script("refresh_context.py", str(self.hub_dir), "--dry-run")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)
        self.assertIn("DRY-RUN", output)
        self.assertNotIn("✅ 已刷新", output)

    def test_refresh_context_preserves_existing_topology_fields(self) -> None:
        (self.hub_dir / "topology" / "domains.yaml").write_text(
            """
domains:
  meeting-workflow:
    description: Existing domain description
    owner: product
    status: active
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (self.hub_dir / "topology" / "system.yaml").write_text(
            """
services:
  meeting-control-service:
    type: backend
    repo: https://git.example.com/old.git
    status: active
    notes: keep-me
  legacy-audit:
    type: backend
    repo: https://git.example.com/legacy-audit.git
infrastructure:
  shared-kafka:
    type: kafka
    owner: platform
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (self.hub_dir / "topology" / "testing-sources.yaml").write_text(
            """
sources:
  - name: regression-suite
    type: manual
    owner: qa
    notes: keep-existing
  - name: smoke-suite
    type: api
""".strip()
            + "\n",
            encoding="utf-8",
        )

        self.write_export(
            "product",
            "domains-fragment.yaml",
            """
maintained_by: product
source_system: ones
source_ref: PRD-456
visibility: shared
last_synced_at: "2026-04-13T08:45:00Z"
confidence: high
domains:
  meeting-workflow:
    maintained_by: product
    description: Updated domain description
""",
        )
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
    repo: https://git.example.com/new.git
""",
        )
        self.write_export(
            "qa",
            "testing-fragment.yaml",
            """
maintained_by: qa
source_system: ones
source_ref: QA-automation
visibility: shared
last_synced_at: "2026-04-13T10:00:00Z"
confidence: medium
sources:
  - name: regression-suite
    type: playwright
""",
        )

        result = run_script("refresh_context.py", str(self.hub_dir))

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        domains_payload = safe_load((self.hub_dir / "topology" / "domains.yaml").read_text(encoding="utf-8"))
        self.assertEqual(domains_payload["domains"]["meeting-workflow"]["status"], "active")
        self.assertEqual(
            domains_payload["domains"]["meeting-workflow"]["description"],
            "Updated domain description",
        )

        system_payload = safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))
        self.assertEqual(system_payload["services"]["meeting-control-service"]["type"], "backend")
        self.assertEqual(system_payload["services"]["meeting-control-service"]["notes"], "keep-me")
        self.assertEqual(
            system_payload["services"]["meeting-control-service"]["repo"],
            "https://git.example.com/new.git",
        )
        self.assertIn("legacy-audit", system_payload["services"])
        self.assertIn("shared-kafka", system_payload["infrastructure"])

        testing_payload = safe_load(
            (self.hub_dir / "topology" / "testing-sources.yaml").read_text(encoding="utf-8")
        )
        sources = {source["name"]: source for source in testing_payload["sources"]}
        self.assertEqual(sources["regression-suite"]["owner"], "qa")
        self.assertEqual(sources["regression-suite"]["notes"], "keep-existing")
        self.assertEqual(sources["regression-suite"]["type"], "playwright")
        self.assertIn("smoke-suite", sources)

    def test_refresh_context_fails_on_unsupported_export_schema(self) -> None:
        self.write_export(
            "product",
            "domains-fragment.yaml",
            """
maintained_by: product
source_system: ones
source_ref: PRD-789
visibility: shared
last_synced_at: "2026-04-13T08:45:00Z"
confidence: high
domains:
  meeting-workflow:
    description: Meeting lifecycle orchestration
    capabilities:
      - name: voting
        status: planned
""",
        )

        result = run_script("refresh_context.py", str(self.hub_dir))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported", result.stderr.lower())

    def test_refresh_context_fails_on_conflicting_service_exports(self) -> None:
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
        self.write_export(
            "qa",
            "system-fragment.yaml",
            """
maintained_by: qa
source_system: ones
source_ref: QA-shadow
visibility: shared
last_synced_at: "2026-04-13T10:00:00Z"
confidence: medium
services:
  meeting-control-service:
    type: mock
    repo: https://git.example.com/mock-meeting-control-service.git
""",
        )

        result = run_script("refresh_context.py", str(self.hub_dir))

        self.assertNotEqual(result.returncode, 0)
        error_text = f"{result.stderr}\n{result.stdout}".lower()
        self.assertIn("conflict", error_text)
        self.assertIn("meeting-control-service", error_text)
