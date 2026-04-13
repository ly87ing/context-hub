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
        self.assertIn("Phase 1", result.stdout)
        self.assertIn("deep scan deferred", result.stdout)

        system_payload = safe_load((self.hub_dir / "topology" / "system.yaml").read_text(encoding="utf-8"))
        self.assertIn("meeting-control-bff", system_payload["services"])
        self.assertIn("legacy-console", system_payload["services"])
        self.assertIn("shared-redis", system_payload["infrastructure"])

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
