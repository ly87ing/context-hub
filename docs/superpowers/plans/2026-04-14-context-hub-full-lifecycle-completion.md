# Context Hub Full Lifecycle Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining `context-hub` control-plane and automation work so a team can use AI to maintain capability state, downstream coordination, design shared context, semantic consistency, and safe lifecycle automation end-to-end.

**Architecture:** Extend the current capability-local control plane (`source-summary.yaml`, `downstream-checklist.yaml`, `iteration-index.yaml`) with lifecycle state, semantic audit, remediation advice, and release aggregation. Keep all execution in local Python scripts, add design export/sync symmetry with existing engineering and QA flows, and make `refresh_context.py` the single safe automation orchestrator gated by consistency, stale, and semantic checks.

**Tech Stack:** Python 3 stdlib, existing workflow/runtime/adapters under `skills/context-hub/scripts/`, Markdown/YAML contracts, `unittest`, shell smoke commands

---

## Scope Check

This is a full completion plan from the current baseline, but it is still intentionally staged. Each phase must produce a working, testable software slice before moving to the next:

- Phase 3A: lifecycle state + release aggregation
- Phase 3B: maintenance remediation suggestions
- Phase 3C: semantic consistency engine
- Phase 3D: design structured export and sync
- Phase 3E: safe automation and workflow hardening

The plan does not introduce a web application, database, or global privileged service. All behavior remains file-contract-driven and locally executable.

## File Structure

### Create

- `skills/context-hub/scripts/runtime/lifecycle_state.py`
- `skills/context-hub/scripts/runtime/release_index.py`
- `skills/context-hub/scripts/runtime/semantic_consistency.py`
- `skills/context-hub/scripts/runtime/maintenance_advice.py`
- `skills/context-hub/scripts/sync_design_context.py`
- `skills/context-hub/scripts/check_semantic_consistency.py`
- `skills/context-hub/templates/design-fragment.yaml`
- `skills/context-hub/tests/test_semantic_consistency.py`
- `docs/superpowers/specs/2026-04-14-context-hub-full-lifecycle-completion-design.md`

### Modify

- `skills/context-hub/SKILL.md`
- `skills/context-hub/scripts/init_context_hub.py`
- `skills/context-hub/scripts/refresh_context.py`
- `skills/context-hub/scripts/check_consistency.py`
- `skills/context-hub/scripts/check_stale.py`
- `skills/context-hub/scripts/update_llms_txt.py`
- `skills/context-hub/scripts/integrations/figma_adapter.py`
- `skills/context-hub/scripts/workflows/pm_workflow.py`
- `skills/context-hub/scripts/workflows/design_workflow.py`
- `skills/context-hub/scripts/workflows/engineering_workflow.py`
- `skills/context-hub/scripts/workflows/qa_workflow.py`
- `skills/context-hub/scripts/workflows/maintenance_workflow.py`
- `skills/context-hub/tests/test_role_workflows.py`
- `skills/context-hub/tests/test_refresh_context.py`
- `skills/context-hub/tests/test_figma_adapter.py`
- `skills/context-hub/tests/test_check_consistency.py`
- `skills/context-hub/tests/test_check_stale.py`
- `skills/context-hub/tests/test_init_context_hub.py`
- `README.md`
- `docs/context-hub-specification.md`

### Responsibility Map

- `runtime/lifecycle_state.py`: derive per-role lifecycle state, blockers, and next-step hints
- `runtime/release_index.py`: aggregate capability iteration data into `topology/releases.yaml`
- `runtime/semantic_consistency.py`: deterministic cross-document rule checks
- `runtime/maintenance_advice.py`: map audit findings into role-scoped remediation suggestions
- `sync_design_context.py`: aggregate `teams/design/exports/design-fragment.yaml` into shared topology
- `check_semantic_consistency.py`: CLI entrypoint for semantic audit
- `workflows/*.py`: update capability-local control files on writes
- `refresh_context.py`: orchestrate sync + audit + safe automation
- `tests/*`: lock behavior with deterministic local fixtures

## Task 1: Establish failing tests for lifecycle state and release aggregation

**Files:**
- Create: `skills/context-hub/scripts/runtime/lifecycle_state.py`
- Create: `skills/context-hub/scripts/runtime/release_index.py`
- Modify: `skills/context-hub/tests/test_role_workflows.py`
- Modify: `skills/context-hub/tests/test_init_context_hub.py`
- Modify: `skills/context-hub/tests/test_check_consistency.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_role_workflows skills.context-hub.tests.test_init_context_hub skills.context-hub.tests.test_check_consistency -v`

- [ ] **Step 1: Write the failing lifecycle-state test**

```python
def test_run_pm_workflow_refreshes_lifecycle_state_after_spec_write(self):
    result = run_pm_workflow(...)
    payload = safe_load((capability_dir / "lifecycle-state.yaml").read_text())
    assert payload["roles"]["design"]["status"] == "needs_align"
```

- [ ] **Step 2: Write the failing aligned-role test**

```python
def test_design_workflow_marks_role_aligned_after_follow_up_write(self):
    ...
    assert payload["roles"]["design"]["status"] == "aligned"
```

- [ ] **Step 3: Write the failing release aggregation test**

```python
def test_refresh_release_index_aggregates_capability_currents(self):
    payload = safe_load((hub_dir / "topology" / "releases.yaml").read_text())
    assert payload["releases"][0]["capabilities"] == ["voting"]
```

- [ ] **Step 4: Write the failing init/consistency tests for new assets**

Run: `python3 -m unittest skills.context-hub.tests.test_init_context_hub skills.context-hub.tests.test_check_consistency -v`  
Expected: `FAIL` because `lifecycle_state.py`, `release_index.py`, `releases.yaml` contract do not exist yet

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/tests
git commit -m "test: define lifecycle state and release aggregation contract"
```

## Task 2: Implement lifecycle state writes and topology release aggregation

**Files:**
- Create: `skills/context-hub/scripts/runtime/lifecycle_state.py`
- Create: `skills/context-hub/scripts/runtime/release_index.py`
- Modify: `skills/context-hub/scripts/workflows/pm_workflow.py`
- Modify: `skills/context-hub/scripts/workflows/design_workflow.py`
- Modify: `skills/context-hub/scripts/workflows/engineering_workflow.py`
- Modify: `skills/context-hub/scripts/workflows/qa_workflow.py`
- Modify: `skills/context-hub/scripts/workflows/maintenance_workflow.py`
- Modify: `skills/context-hub/scripts/init_context_hub.py`
- Modify: `skills/context-hub/scripts/check_consistency.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_role_workflows skills.context-hub.tests.test_init_context_hub skills.context-hub.tests.test_check_consistency -v`

- [ ] **Step 1: Implement lifecycle-state payload builder**

```python
def build_lifecycle_state_payload(...):
    return {
        "capability": capability,
        "updated_at": ...,
        "roles": {
            "pm": {"status": "..."},
            "design": {"status": "..."},
            "engineering": {"status": "..."},
            "qa": {"status": "..."},
        },
        "next_role": "...",
    }
```

- [ ] **Step 2: Refresh lifecycle state from every mutating workflow**

```python
updated_paths.append(
    write_lifecycle_state(...)
)
```

- [ ] **Step 3: Implement release aggregation from `iteration-index.yaml`**

```python
def refresh_release_index(hub_root: Path) -> Path:
    ...
```

- [ ] **Step 4: Wire lifecycle/release artifacts into init and consistency contracts**

Run: `python3 -m unittest skills.context-hub.tests.test_role_workflows skills.context-hub.tests.test_init_context_hub skills.context-hub.tests.test_check_consistency -v`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/scripts/runtime skills/context-hub/scripts/workflows skills/context-hub/scripts/init_context_hub.py skills/context-hub/scripts/check_consistency.py skills/context-hub/tests
git commit -m "feat: add lifecycle state and release aggregation"
```

## Task 3: Upgrade maintenance workflow from audit-only to remediation suggestions

**Files:**
- Create: `skills/context-hub/scripts/runtime/maintenance_advice.py`
- Modify: `skills/context-hub/scripts/workflows/maintenance_workflow.py`
- Modify: `skills/context-hub/tests/test_role_workflows.py`
- Modify: `skills/context-hub/tests/test_check_stale.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_role_workflows skills.context-hub.tests.test_check_stale -v`

- [ ] **Step 1: Write the failing remediation test**

```python
def test_maintenance_workflow_returns_suggested_repairs_for_pending_roles(self):
    result = run_maintenance_workflow(...)
    assert result["suggested_repairs"][0]["role"] == "design"
```

- [ ] **Step 2: Write the failing blocker mapping test**

```python
def test_maintenance_workflow_surfaces_blocking_issues(self):
    assert result["blocking_issues"][0]["severity"] == "blocking"
```

- [ ] **Step 3: Implement rule-based advice builder**

```python
def build_maintenance_advice(...):
    return [{"role": role, "action": "align", "reason": "..."}]
```

- [ ] **Step 4: Keep missing-file warnings and new remediation fields consistent**

Run: `python3 -m unittest skills.context-hub.tests.test_role_workflows skills.context-hub.tests.test_check_stale -v`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/scripts/runtime/maintenance_advice.py skills/context-hub/scripts/workflows/maintenance_workflow.py skills/context-hub/tests
git commit -m "feat: add maintenance remediation suggestions"
```

## Task 4: Introduce semantic consistency contracts and CLI

**Files:**
- Create: `skills/context-hub/scripts/runtime/semantic_consistency.py`
- Create: `skills/context-hub/scripts/check_semantic_consistency.py`
- Create: `skills/context-hub/tests/test_semantic_consistency.py`
- Modify: `skills/context-hub/scripts/check_consistency.py`
- Modify: `skills/context-hub/scripts/check_stale.py`
- Modify: `skills/context-hub/tests/test_check_consistency.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_semantic_consistency skills.context-hub.tests.test_check_consistency -v`

- [ ] **Step 1: Write the failing rule test for spec/source-summary drift**

```python
def test_semantic_consistency_flags_spec_status_conflict(self):
    result = audit_capability_semantics(...)
    assert result["issues"][0]["rule_id"] == "spec_status_conflict"
```

- [ ] **Step 2: Write the failing rule test for design/testing drift**

```python
def test_semantic_consistency_flags_missing_test_coverage_for_design_state(self):
    ...
```

- [ ] **Step 3: Implement deterministic rule engine and YAML writer**

```python
def audit_capability_semantics(...):
    return {"status": "...", "issues": [...]}
```

- [ ] **Step 4: Add a CLI wrapper and optional consistency hook**

Run: `python3 -m unittest skills.context-hub.tests.test_semantic_consistency skills.context-hub.tests.test_check_consistency -v`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/scripts/runtime/semantic_consistency.py skills/context-hub/scripts/check_semantic_consistency.py skills/context-hub/tests skills/context-hub/scripts/check_consistency.py
git commit -m "feat: add semantic consistency audit"
```

## Task 5: Add structured design exports and design sync

**Files:**
- Create: `skills/context-hub/templates/design-fragment.yaml`
- Create: `skills/context-hub/scripts/sync_design_context.py`
- Modify: `skills/context-hub/scripts/integrations/figma_adapter.py`
- Modify: `skills/context-hub/scripts/refresh_context.py`
- Modify: `skills/context-hub/scripts/init_context_hub.py`
- Modify: `skills/context-hub/tests/test_figma_adapter.py`
- Modify: `skills/context-hub/tests/test_refresh_context.py`
- Modify: `skills/context-hub/tests/test_init_context_hub.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_figma_adapter skills.context-hub.tests.test_refresh_context skills.context-hub.tests.test_init_context_hub -v`

- [ ] **Step 1: Write the failing design export aggregation test**

```python
def test_refresh_context_aggregates_design_exports_into_design_sources(self):
    ...
    assert (hub_dir / "topology" / "design-sources.yaml").exists()
```

- [ ] **Step 2: Write the failing figma structured probe test**

```python
def test_probe_figma_reference_returns_page_and_node_summary(self):
    ...
```

- [ ] **Step 3: Implement `design-fragment.yaml` contract and design sync script**

```python
def sync_design_sources(hub_root: Path) -> Path:
    ...
```

- [ ] **Step 4: Extend `figma_adapter.py` without breaking lightweight fallback**

Run: `python3 -m unittest skills.context-hub.tests.test_figma_adapter skills.context-hub.tests.test_refresh_context skills.context-hub.tests.test_init_context_hub -v`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/templates/design-fragment.yaml skills/context-hub/scripts/sync_design_context.py skills/context-hub/scripts/integrations/figma_adapter.py skills/context-hub/scripts/refresh_context.py skills/context-hub/tests
git commit -m "feat: add design structured sync"
```

## Task 6: Orchestrate semantic audit, release index, design sync, and safe automation in `refresh_context.py`

**Files:**
- Modify: `skills/context-hub/scripts/refresh_context.py`
- Modify: `skills/context-hub/scripts/update_llms_txt.py`
- Modify: `skills/context-hub/tests/test_refresh_context.py`
- Test: `python3 -m unittest skills.context-hub.tests.test_refresh_context -v`

- [ ] **Step 1: Write the failing orchestration test**

```python
def test_run_refresh_workflow_runs_release_index_and_semantic_audit_before_commit(self):
    ...
```

- [ ] **Step 2: Write the failing block-on-semantic-errors test**

```python
def test_run_refresh_workflow_skips_commit_when_semantic_audit_blocks(self):
    ...
```

- [ ] **Step 3: Thread new flags and orchestration stages through refresh**

```python
run_refresh_workflow(..., sync_design=True, semantic_audit=True)
```

- [ ] **Step 4: Keep dry-run and existing skip contracts stable**

Run: `python3 -m unittest skills.context-hub.tests.test_refresh_context -v`  
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/scripts/refresh_context.py skills/context-hub/scripts/update_llms_txt.py skills/context-hub/tests/test_refresh_context.py
git commit -m "feat: orchestrate lifecycle completion automation"
```

## Task 7: Final contract docs, smoke validation, and repository integration

**Files:**
- Modify: `README.md`
- Modify: `docs/context-hub-specification.md`
- Modify: `skills/context-hub/SKILL.md`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`
- Test: `git diff --check -- README.md docs/context-hub-specification.md skills/context-hub/SKILL.md`

- [ ] **Step 1: Update user-facing commands and contract documentation**

```md
- lifecycle-state.yaml
- semantic-consistency.yaml
- topology/design-sources.yaml
- topology/releases.yaml
```

- [ ] **Step 2: Run targeted smoke flows**

Run:

```bash
python3 skills/context-hub/scripts/init_context_hub.py --output /tmp/context-hub-full --name "会议控制平台" --id meeting-control
python3 skills/context-hub/scripts/create_capability.py --hub /tmp/context-hub-full --name voting --domain meeting
python3 skills/context-hub/scripts/workflows/pm_workflow.py --hub /tmp/context-hub-full --capability voting --action revise --iteration "Sprint 12" --release "2026.04" --content-file /tmp/spec.md --output-format json
python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-full --sync-gitlab --sync-ones --sync-design
```

Expected: exit code `0`, new control-plane files exist, no validation blockers

- [ ] **Step 3: Run full suite**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`  
Expected: `OK`

- [ ] **Step 4: Run doc diff check**

Run: `git diff --check -- README.md docs/context-hub-specification.md skills/context-hub/SKILL.md`  
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add README.md docs/context-hub-specification.md skills/context-hub/SKILL.md
git commit -m "docs: describe full lifecycle completion contract"
```

## Recommended Execution Order

1. Task 1-2: establish lifecycle/release control plane first
2. Task 3: make maintenance actionable
3. Task 4: add semantic consistency before deeper automation
4. Task 5: add design structured sync symmetry
5. Task 6: wire all pieces into `refresh_context.py`
6. Task 7: finish docs, smoke tests, and branch integration
