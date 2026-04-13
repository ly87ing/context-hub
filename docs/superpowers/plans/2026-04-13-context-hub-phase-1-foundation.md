# Context Hub Federated Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Phase 1 federated `context-hub` foundation that can initialize a shared hub, model team ownership boundaries, aggregate team exports into shared project context, and validate the repository contract without requiring global cross-team credentials.

**Architecture:** Introduce a small runtime layer under `skills/context-hub/scripts/` to own hub path resolution, template rendering, aggregation, validation, and safe git operations. Keep external integrations in adapter modules with preflight-only behavior in Phase 1, while refactoring existing CLI scripts to use the new runtime and the federated repository contract.

**Tech Stack:** Python 3 stdlib, existing script entrypoints, Markdown/YAML templates, `unittest`, shell smoke commands

---

## Scope Check

The approved spec covers three phases. This plan intentionally implements only `Phase 1: Orchestrator + Runtime 基线`, because it produces working, testable software on its own:

- shared hub initialization
- federated ownership contract
- local team-export aggregation
- llms refresh
- consistency / stale auditing
- credential preflight

The following are explicitly deferred to separate plans:

- `Phase 2`: real GitLab / ONES deep integration and topology scanning from source systems
- `Phase 3`: full PM / 设计 / 研发 / QA role workflow execution and acceptance automation

## File Structure

### Create

- `skills/context-hub/scripts/runtime/__init__.py`
- `skills/context-hub/scripts/runtime/hub_paths.py`
- `skills/context-hub/scripts/runtime/hub_io.py`
- `skills/context-hub/scripts/runtime/capability_ops.py`
- `skills/context-hub/scripts/runtime/commit_ops.py`
- `skills/context-hub/scripts/runtime/validation.py`
- `skills/context-hub/scripts/integrations/__init__.py`
- `skills/context-hub/scripts/integrations/credentials.py`
- `skills/context-hub/scripts/integrations/gitlab_adapter.py`
- `skills/context-hub/scripts/integrations/ones_adapter.py`
- `skills/context-hub/scripts/refresh_context.py`
- `skills/context-hub/scripts/bootstrap_credentials_check.py`
- `skills/context-hub/templates/identity.md`
- `skills/context-hub/templates/system.yaml`
- `skills/context-hub/templates/domains.yaml`
- `skills/context-hub/templates/testing-sources.yaml`
- `skills/context-hub/templates/ownership.yaml`
- `skills/context-hub/templates/llms.txt`
- `skills/context-hub/tests/test_support.py`
- `skills/context-hub/tests/test_init_context_hub.py`
- `skills/context-hub/tests/test_create_capability.py`
- `skills/context-hub/tests/test_refresh_context.py`
- `skills/context-hub/tests/test_credentials.py`
- `skills/context-hub/tests/test_check_consistency.py`
- `skills/context-hub/tests/test_check_stale.py`

### Modify

- `skills/context-hub/SKILL.md`
- `skills/context-hub/scripts/init_context_hub.py`
- `skills/context-hub/scripts/create_capability.py`
- `skills/context-hub/scripts/update_llms_txt.py`
- `skills/context-hub/scripts/sync_topology.py`
- `skills/context-hub/scripts/check_consistency.py`
- `skills/context-hub/scripts/check_stale.py`
- `skills/context-hub/scripts/_common.py`
- `README.md`
- `docs/context-hub-specification.md`

### Responsibility Map

- `runtime/*`: stable internal API used by CLI scripts and future role workflows
- `integrations/*`: credential discovery and source-system adapter preflight
- `refresh_context.py`: aggregate team exports into shared topology + llms outputs
- `templates/*`: repository contract files rendered during initialization
- `tests/*`: deterministic local verification with temporary directories only

## Task 1: Establish test harness and fixture helpers

**Files:**
- Create: `skills/context-hub/tests/test_support.py`
- Create: `skills/context-hub/tests/test_init_context_hub.py`
- Create: `skills/context-hub/tests/test_create_capability.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`

- [ ] **Step 1: Write the failing initialization test**

```python
def test_init_creates_federated_layout(self):
    result = run_script(
        "init_context_hub.py",
        "--output", str(self.hub_dir),
        "--name", "会议控制平台",
        "--id", "meeting-control",
    )
    self.assertEqual(result.returncode, 0)
    self.assertTrue((self.hub_dir / "topology" / "ownership.yaml").exists())
    self.assertTrue((self.hub_dir / "teams" / "engineering" / "exports").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_init_context_hub.py' -v`  
Expected: `FAIL` because `ownership.yaml` and `teams/*/exports` do not exist yet

- [ ] **Step 3: Add reusable test helpers**

```python
def run_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    script = SCRIPTS_DIR / script_name
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )
```

- [ ] **Step 4: Add a second failing capability test**

```python
def test_create_capability_updates_domains_and_ownership(self):
    ...
    self.assertIn("voting", domains_text)
    self.assertIn("voting", ownership_text)
```

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/tests
git commit -m "test: add context-hub phase1 harness"
```

## Task 2: Introduce repository contract templates and runtime path/io layer

**Files:**
- Create: `skills/context-hub/scripts/runtime/__init__.py`
- Create: `skills/context-hub/scripts/runtime/hub_paths.py`
- Create: `skills/context-hub/scripts/runtime/hub_io.py`
- Create: `skills/context-hub/templates/identity.md`
- Create: `skills/context-hub/templates/system.yaml`
- Create: `skills/context-hub/templates/domains.yaml`
- Create: `skills/context-hub/templates/testing-sources.yaml`
- Create: `skills/context-hub/templates/ownership.yaml`
- Create: `skills/context-hub/templates/llms.txt`
- Modify: `skills/context-hub/scripts/_common.py`
- Test: `skills/context-hub/tests/test_init_context_hub.py`

- [ ] **Step 1: Write the failing runtime template test**

```python
def test_template_render_produces_ownership_seed(self):
    template_text = load_template("ownership.yaml")
    rendered = render_template(template_text, {"project_id": "meeting-control"})
    self.assertIn("teams:", rendered)
    self.assertIn("engineering:", rendered)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_init_context_hub.py' -v`  
Expected: `FAIL` with missing helper or missing template loader

- [ ] **Step 3: Implement focused runtime utilities**

```python
def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent

def template_path(name: str) -> Path:
    return skill_root() / "templates" / name

def render_template(template_text: str, mapping: dict[str, str]) -> str:
    ...
```

- [ ] **Step 4: Move inline contract text into templates**

```yaml
teams:
  product:
    visibility: shared
    exports_dir: teams/product/exports
  engineering:
    visibility: shared
    exports_dir: teams/engineering/exports
```

- [ ] **Step 5: Run tests to verify template rendering works**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_init_context_hub.py' -v`  
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add skills/context-hub/scripts/runtime skills/context-hub/templates skills/context-hub/scripts/_common.py skills/context-hub/tests
git commit -m "feat: add runtime path and template layer"
```

## Task 3: Refactor initialization and capability creation around the federated contract

**Files:**
- Modify: `skills/context-hub/scripts/init_context_hub.py`
- Modify: `skills/context-hub/scripts/create_capability.py`
- Create: `skills/context-hub/scripts/runtime/capability_ops.py`
- Test: `skills/context-hub/tests/test_init_context_hub.py`
- Test: `skills/context-hub/tests/test_create_capability.py`

- [ ] **Step 1: Write the failing dry-run and ownership tests**

```python
def test_init_dry_run_reports_actions_without_writing(self):
    result = run_script("init_context_hub.py", "--output", str(self.hub_dir), "--name", "会议", "--id", "meeting", "--dry-run")
    self.assertEqual(result.returncode, 0)
    self.assertFalse((self.hub_dir / "IDENTITY.md").exists())
    self.assertIn("DRY-RUN", result.stdout)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*capability*.py' -v`  
Expected: `FAIL` because `--dry-run` and ownership sync are unsupported

- [ ] **Step 3: Refactor `init_context_hub.py` to create the federated layout**

```python
TEAM_EXPORTS = ("product", "design", "engineering", "qa")

for team_id in TEAM_EXPORTS:
    (output_dir / "teams" / team_id / "exports").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Refactor `create_capability.py` to update ownership metadata**

```python
def ensure_capability_ownership(ownership_payload: dict, capability_name: str, domain: str) -> None:
    ownership_payload.setdefault("capabilities", {})[capability_name] = {
        "domain": domain,
        "maintained_by": "product",
        "contributors": ["design", "engineering", "qa"],
    }
```

- [ ] **Step 5: Add `--dry-run`, `--auto-commit`, and `--auto-push` flags but keep push disabled by default**

Run: `python3 skills/context-hub/scripts/init_context_hub.py --help`  
Expected: usage output includes the new flags

- [ ] **Step 6: Run targeted tests**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_init_context_hub.py' -v`  
Expected: `OK`

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_create_capability.py' -v`  
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/scripts/init_context_hub.py skills/context-hub/scripts/create_capability.py skills/context-hub/scripts/runtime/capability_ops.py skills/context-hub/tests
git commit -m "feat: refactor hub initialization for federated contract"
```

## Task 4: Add credential discovery and adapter preflight

**Files:**
- Create: `skills/context-hub/scripts/integrations/__init__.py`
- Create: `skills/context-hub/scripts/integrations/credentials.py`
- Create: `skills/context-hub/scripts/integrations/gitlab_adapter.py`
- Create: `skills/context-hub/scripts/integrations/ones_adapter.py`
- Create: `skills/context-hub/scripts/bootstrap_credentials_check.py`
- Create: `skills/context-hub/tests/test_credentials.py`

- [ ] **Step 1: Write the failing credential resolution tests**

```python
def test_gitlab_instance_resolution_uses_known_host_mapping(self):
    adapter = resolve_gitlab_instance("https://gitlab.xylink.com/team/repo")
    self.assertEqual(adapter.token_var, "GITLAB_ACCESS_TOKEN")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_credentials.py' -v`  
Expected: `FAIL` because the adapter modules do not exist yet

- [ ] **Step 3: Implement safe credential discovery without printing values**

```python
def read_env_value(name: str) -> str:
    return os.environ.get(name, "")

def require_values(names: list[str]) -> tuple[bool, list[str]]:
    missing = [name for name in names if not read_env_value(name)]
    return not missing, missing
```

- [ ] **Step 4: Implement GitLab / ONES preflight-only adapters**

```python
def gitlab_preflight(target_url: str | None = None) -> dict[str, str]:
    instance = resolve_gitlab_instance(target_url)
    ok, missing = require_values([instance.token_var])
    return {"ok": str(ok).lower(), "missing": ",".join(missing)}
```

- [ ] **Step 5: Add CLI bootstrap command**

Run: `python3 skills/context-hub/scripts/bootstrap_credentials_check.py --help`  
Expected: usage output lists `--gitlab-url` and `--check-ones`

- [ ] **Step 6: Re-run credential tests**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_credentials.py' -v`  
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/scripts/integrations skills/context-hub/scripts/bootstrap_credentials_check.py skills/context-hub/tests/test_credentials.py
git commit -m "feat: add shared credential preflight"
```

## Task 5: Aggregate team exports into shared topology and llms outputs

**Files:**
- Create: `skills/context-hub/scripts/refresh_context.py`
- Modify: `skills/context-hub/scripts/update_llms_txt.py`
- Modify: `skills/context-hub/scripts/sync_topology.py`
- Create: `skills/context-hub/tests/test_refresh_context.py`

- [ ] **Step 1: Write the failing aggregation test**

```python
def test_refresh_context_merges_engineering_and_qa_exports(self):
    write_export("engineering", "system-fragment.yaml", "services: ...")
    write_export("qa", "testing-fragment.yaml", "sources: ...")
    result = run_script("refresh_context.py", str(self.hub_dir))
    self.assertEqual(result.returncode, 0)
    self.assertIn("meeting-control-service", (self.hub_dir / "topology" / "system.yaml").read_text())
    self.assertIn("功能测试", (self.hub_dir / ".context" / "llms.txt").read_text())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `FAIL` because no aggregation script exists

- [ ] **Step 3: Implement export aggregation**

```python
def merge_export_payloads(hub_root: Path) -> dict[str, dict]:
    return {
        "system": merge_system_exports(...),
        "testing": merge_testing_exports(...),
        "domains": merge_domain_exports(...),
    }
```

- [ ] **Step 4: Re-scope `sync_topology.py` for Phase 1**

```python
def main():
    parser.add_argument("--from-exports", action="store_true", default=True)
    ...
```

`sync_topology.py` should stop pretending to do full GitLab deep scan in Phase 1. It should aggregate engineering-owned export fragments locally and clearly mark deep source scanning as deferred.

- [ ] **Step 5: Update `update_llms_txt.py` to include ownership and freshness markers**

Expected llms lines:

```text
- meeting-control: voting (maintained by product, freshness: 2026-04-13)
- meeting-control-service: backend / maintained by engineering
```

- [ ] **Step 6: Run tests**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/scripts/refresh_context.py skills/context-hub/scripts/update_llms_txt.py skills/context-hub/scripts/sync_topology.py skills/context-hub/tests/test_refresh_context.py
git commit -m "feat: aggregate team exports into shared context"
```

## Task 6: Expand consistency and stale auditing for the federated contract

**Files:**
- Create: `skills/context-hub/scripts/runtime/validation.py`
- Modify: `skills/context-hub/scripts/check_consistency.py`
- Modify: `skills/context-hub/scripts/check_stale.py`
- Create: `skills/context-hub/tests/test_check_consistency.py`
- Create: `skills/context-hub/tests/test_check_stale.py`

- [ ] **Step 1: Write the failing federated audit tests**

```python
def test_consistency_reports_missing_team_export_metadata(self):
    write_text(self.hub_dir / "teams" / "engineering" / "exports" / "system-fragment.yaml", "services: {}")
    result = run_script("check_consistency.py", cwd=self.hub_dir)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("last_synced_at", result.stdout + result.stderr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_check_*.py' -v`  
Expected: `FAIL` because current validators do not understand team exports or freshness

- [ ] **Step 3: Centralize validation rules**

```python
REQUIRED_EXPORT_FIELDS = ("maintained_by", "source_system", "visibility", "last_synced_at", "confidence")
```

- [ ] **Step 4: Extend `check_consistency.py`**

Add checks for:

- `topology/ownership.yaml`
- `teams/<team>/exports/` directory presence
- export metadata completeness
- capability -> ownership -> domain cross references
- `.context/llms.txt` freshness markers

- [ ] **Step 5: Extend `check_stale.py`**

Add checks for:

- stale exports by `last_synced_at`
- `in-progress` capabilities missing role artifacts
- stale shared summaries that can block downstream roles

- [ ] **Step 6: Run tests**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_check_*.py' -v`  
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/scripts/runtime/validation.py skills/context-hub/scripts/check_consistency.py skills/context-hub/scripts/check_stale.py skills/context-hub/tests/test_check_consistency.py skills/context-hub/tests/test_check_stale.py
git commit -m "feat: audit federated hub consistency and staleness"
```

## Task 7: Rewrite the skill and docs to match the new runtime contract

**Files:**
- Modify: `skills/context-hub/SKILL.md`
- Modify: `README.md`
- Modify: `docs/context-hub-specification.md`
- Test: `rg -n "联邦|ownership|teams/.*/exports|refresh_context|bootstrap_credentials_check" skills/context-hub/SKILL.md README.md docs/context-hub-specification.md`

- [ ] **Step 1: Write the failing documentation expectation**

```text
SKILL.md must explain:
- federated ownership model
- permission-aware fallback
- team exports aggregation
- credential reuse from gitlab / ones conventions
```

- [ ] **Step 2: Run the doc grep check and confirm it fails**

Run: `rg -n "联邦|ownership|teams/.*/exports|refresh_context|bootstrap_credentials_check" skills/context-hub/SKILL.md README.md docs/context-hub-specification.md`  
Expected: missing matches in at least one file

- [ ] **Step 3: Rewrite `SKILL.md` as the Phase 1 orchestrator**

It must document:

- intent categories
- read order
- permission downgrade rules
- write targets
- post-write validation
- when to use team exports versus real-time source reads

- [ ] **Step 4: Update `README.md` and `docs/context-hub-specification.md`**

Document:

- the federated model
- Phase 1 boundaries
- exact local commands for init / refresh / audit / credential preflight

- [ ] **Step 5: Re-run the grep check**

Run: `rg -n "联邦|ownership|teams/.*/exports|refresh_context|bootstrap_credentials_check" skills/context-hub/SKILL.md README.md docs/context-hub-specification.md`  
Expected: all three files return relevant matches

- [ ] **Step 6: Commit**

```bash
git add skills/context-hub/SKILL.md README.md docs/context-hub-specification.md
git commit -m "docs: align context-hub skill with federated runtime"
```

## Task 8: End-to-end Phase 1 smoke verification

**Files:**
- Test: `skills/context-hub/tests/test_*.py`
- Test: temporary hub under `/tmp/context-hub-phase1-smoke`

- [ ] **Step 1: Run the full unittest suite**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`  
Expected: `OK`

- [ ] **Step 2: Run initialization smoke**

Run:

```bash
python3 skills/context-hub/scripts/init_context_hub.py \
  --output /tmp/context-hub-phase1-smoke \
  --name "会议控制平台" \
  --id meeting-control \
  --summary "面向会议控制场景的全局上下文仓库" \
  --repo "meeting-control-service|https://gitlab.xylink.com/meeting/mc-service|meeting-control|team-core"
```

Expected: exit code `0`, generated `topology/ownership.yaml`, `teams/*/exports`, `.context/llms.txt`

- [ ] **Step 3: Run capability creation smoke**

Run:

```bash
python3 /tmp/context-hub-phase1-smoke/scripts/create_capability.py \
  --hub /tmp/context-hub-phase1-smoke \
  --name voting \
  --title "投票功能" \
  --domain meeting-control
```

Expected: exit code `0`, updates both `topology/domains.yaml` and `topology/ownership.yaml`

- [ ] **Step 4: Run refresh and audits**

Run:

```bash
python3 /tmp/context-hub-phase1-smoke/scripts/refresh_context.py /tmp/context-hub-phase1-smoke
python3 /tmp/context-hub-phase1-smoke/scripts/check_consistency.py
python3 /tmp/context-hub-phase1-smoke/scripts/check_stale.py
```

Expected:

- `refresh_context.py` exits `0`
- `check_consistency.py` exits `0`
- `check_stale.py` exits `0` or `1` with only documented freshness warnings

- [ ] **Step 5: Record follow-up gaps for Phase 2 / 3**

Create a short section at the end of `README.md` or `docs/context-hub-specification.md` listing:

- GitLab deep scan still pending
- ONES summary sync still pending
- role-specific workflow executors still pending

- [ ] **Step 6: Commit**

```bash
git add README.md docs/context-hub-specification.md
git commit -m "chore: verify context-hub phase1 foundation"
```

## Review Notes

- This plan intentionally does not add a global bot identity.
- This plan intentionally keeps Figma at “stable reference + index” instead of deep sync.
- `sync_topology.py` is repurposed in Phase 1 to aggregate engineering-owned exports rather than directly crawl GitLab.
- `Phase 2` must add real GitLab / ONES data acquisition after this baseline is stable.
