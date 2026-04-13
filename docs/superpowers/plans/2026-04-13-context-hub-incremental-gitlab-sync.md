# Context Hub Incremental GitLab Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repo-scoped GitLab incremental sync so webhook/CI can refresh exactly the matched service set in `topology/system.yaml` using repo URL + branch, while preserving existing nightly full-sync behavior and audit safety.

**Architecture:** Keep `refresh_context.py` as the orchestration entrypoint and extend `sync_topology.py` with a second incremental mode. Normalize repo URLs in shared GitLab helpers, match services by `host + path_with_namespace`, refresh every matched service in a monorepo-safe way, fail closed when `default_branch` is missing, and keep validation plus warning-blocked auto-commit unchanged.

**Tech Stack:** Python 3 stdlib, existing `refresh_context.py` / `sync_topology.py` CLI scripts, `unittest`, YAML fixtures, GitLab CI template

---

## Scope Check

This plan only implements GitLab incremental sync for the webhook path. It intentionally does not include:

- ONES behavior changes
- capability-to-repo back references
- Figma integration
- file-path-aware diff scanning

Those remain separate follow-up work.

## File Structure

### Modify

- `skills/context-hub/scripts/sync_topology.py`
- `skills/context-hub/scripts/refresh_context.py`
- `skills/context-hub/templates/gitlab-ci.yml`
- `skills/context-hub/tests/test_gitlab_sync.py`
- `skills/context-hub/tests/test_refresh_context.py`
- `README.md`
- `skills/context-hub/SKILL.md`
- `docs/context-hub-specification.md`

### Responsibility Map

- `sync_topology.py`: repo URL normalization, multi-service matching, branch gating, full vs incremental sync entrypoints
- `refresh_context.py`: webhook-facing orchestration, argument parsing, incremental dispatch, existing validation/commit policy
- `gitlab-ci.yml`: webhook and nightly parameter wiring
- `test_gitlab_sync.py`: normalization, match, skip, single-service refresh behavior
- `test_refresh_context.py`: orchestration and flag handoff behavior
- docs: user-facing contract for webhook inputs and branch gating

## Task 1: Add failing tests for repo URL normalization, result contract, and monorepo-safe incremental sync

**Files:**
- Modify: `skills/context-hub/tests/test_gitlab_sync.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`

- [ ] **Step 1: Write the failing normalization test**

```python
def test_normalize_repo_url_treats_https_and_ssh_as_same_repo(self):
    self.assertEqual(
        normalize_repo_url("https://itgitlab.xylink.com/group/service.git"),
        normalize_repo_url("git@itgitlab.xylink.com:group/service.git"),
    )
```

- [ ] **Step 2: Write the failing incremental match test**

```python
def test_sync_topology_incremental_updates_only_matching_service(self):
    result = sync_system_topology(self.hub_dir, repo_url="git@itgitlab.xylink.com:group/service.git", branch="main")
    self.assertEqual(result["synced_services"], ["meeting-control-service"])
```

- [ ] **Step 3: Write the failing branch skip test**

```python
def test_sync_topology_incremental_skips_non_default_branch(self):
    result = sync_system_topology(self.hub_dir, repo_url="https://itgitlab.xylink.com/group/service.git", branch="feature/x")
    self.assertEqual(result["synced_services"], [])
    self.assertIn("default_branch", result["reason"])
```

- [ ] **Step 3.5: Write the failing monorepo match test**

```python
def test_sync_topology_incremental_refreshes_all_services_for_same_repo(self):
    result = sync_system_topology(self.hub_dir, repo_url="git@itgitlab.xylink.com:group/mono.git", branch="main")
    self.assertEqual(sorted(result["matched_services"]), ["api-service", "worker-service"])
```

- [ ] **Step 4: Write the failing no-match and missing-default-branch tests**

```python
def test_sync_topology_incremental_skips_when_repo_matches_no_service(self):
    result = sync_system_topology(self.hub_dir, repo_url="git@itgitlab.xylink.com:group/unknown.git", branch="main")
    self.assertEqual(result["matched_services"], [])
    self.assertEqual(result["synced_services"], [])

def test_sync_topology_incremental_skips_when_default_branch_missing(self):
    result = sync_system_topology(self.hub_dir, repo_url="git@itgitlab.xylink.com:group/service.git", branch="main")
    self.assertIn("default_branch", result["reason"])
```

- [ ] **Step 5: Write the failing result-contract test**

```python
def test_sync_topology_incremental_returns_system_path_in_result(self):
    result = sync_system_topology(self.hub_dir, repo_url="git@itgitlab.xylink.com:group/service.git", branch="main")
    self.assertEqual(result["mode"], "incremental")
    self.assertEqual(result["system_path"], (self.hub_dir / "topology" / "system.yaml").resolve())
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: `FAIL` because URL normalization and incremental entrypoints do not exist yet

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/tests/test_gitlab_sync.py
git commit -m "test: define incremental gitlab sync behavior"
```

## Task 2: Implement shared repo normalization, multi-service matching, result contract, and branch gating in `sync_topology.py`

**Files:**
- Modify: `skills/context-hub/scripts/sync_topology.py`
- Test: `skills/context-hub/tests/test_gitlab_sync.py`

- [ ] **Step 1: Add a shared normalization helper in the GitLab integration layer**

```python
def normalize_repo_url(repo_url: str) -> dict[str, str]:
    # return {"host": "...", "path_with_namespace": "..."}
```

- [ ] **Step 2: Reuse the helper for service matching**

```python
def find_services_by_repo(services: dict[str, dict], repo_url: str) -> list[tuple[str, dict]]:
    ...
```

- [ ] **Step 3: Add branch gating**

```python
def should_sync_service_for_branch(service: dict[str, object], branch: str | None) -> tuple[bool, str]:
    ...
```

- [ ] **Step 4: Make missing `default_branch` fail closed**

```python
if not service.get("default_branch"):
    return False, "default_branch missing"
```

- [ ] **Step 5: Return an explicit incremental result object**

```python
{
    "mode": "incremental",
    "matched_services": [...],
    "synced_services": [...],
    "reason": "...",
    "system_path": system_path,
}
```

- [ ] **Step 6: Add repo-scoped sync logic without breaking full sync**

```python
def sync_services_for_repo(hub_root: Path, repo_url: str, branch: str | None) -> dict[str, object]:
    ...
```

- [ ] **Step 7: Keep full sync as the default path**

```python
def sync_system_topology(hub_root: Path, *, repo_url: str | None = None, branch: str | None = None):
    if repo_url:
        return sync_services_for_repo(...)
    return sync_all_services(...)
```

- [ ] **Step 8: Run tests to verify green**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add skills/context-hub/scripts/sync_topology.py skills/context-hub/tests/test_gitlab_sync.py
git commit -m "feat: add repo-scoped gitlab topology sync"
```

## Task 3: Extend `refresh_context.py` to orchestrate webhook incremental sync

**Files:**
- Modify: `skills/context-hub/scripts/refresh_context.py`
- Modify: `skills/context-hub/tests/test_refresh_context.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`

- [ ] **Step 1: Write the failing orchestration test**

```python
def test_run_refresh_workflow_passes_repo_url_and_branch_to_incremental_gitlab_sync(self):
    result = run_refresh_workflow(
        self.hub_dir,
        sync_gitlab=True,
        gitlab_url="git@itgitlab.xylink.com:group/service.git",
        gitlab_branch="main",
    )
```

- [ ] **Step 2: Write the failing skip-path test**

```python
def test_run_refresh_workflow_keeps_validations_when_incremental_gitlab_sync_skips(self):
    ...
```

- [ ] **Step 2.5: Write the failing missing-branch CLI test**

```python
def test_refresh_context_rejects_incremental_gitlab_sync_without_branch(self):
    result = run_script("refresh_context.py", str(self.hub_dir), "--sync-gitlab", "--gitlab-url", "git@itgitlab.xylink.com:group/service.git")
    self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 2.6: Write the failing invalid-repo-url test**

```python
def test_refresh_context_rejects_invalid_gitlab_repo_url(self):
    result = run_script("refresh_context.py", str(self.hub_dir), "--sync-gitlab", "--gitlab-url", "not-a-repo-url", "--gitlab-branch", "main")
    self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 2.7: Write the failing full-sync regression test**

```python
def test_run_refresh_workflow_without_gitlab_url_keeps_full_sync_path(self):
    ...
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `FAIL` because `gitlab_url` and `gitlab_branch` are not yet threaded through

- [ ] **Step 4: Extend CLI parsing and workflow signature**

```python
parser.add_argument("--gitlab-url", default="")
parser.add_argument("--gitlab-branch", default="")
```

- [ ] **Step 5: Reject webhook incremental mode when branch is missing**

```python
if sync_gitlab and gitlab_url and not gitlab_branch:
    raise ValueError("gitlab incremental sync requires --gitlab-branch")
```

- [ ] **Step 6: Reject invalid repo URL before dispatch**

```python
if gitlab_url:
    gitlab_adapter.normalize_repo_url(gitlab_url)
```

- [ ] **Step 7: Dispatch to full or incremental sync based on presence of `gitlab_url`**

```python
if sync_gitlab:
    gitlab_result = run_gitlab_sync(hub_root, repo_url=gitlab_url or None, branch=gitlab_branch or None)
    outputs["system"] = gitlab_result["system_path"] if isinstance(gitlab_result, dict) else gitlab_result
```

- [ ] **Step 8: Preserve existing validation and warning-blocked commit behavior**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add skills/context-hub/scripts/refresh_context.py skills/context-hub/tests/test_refresh_context.py
git commit -m "feat: route webhook gitlab sync through refresh workflow"
```

## Task 4: Wire webhook parameters in GitLab CI and document the new contract

**Files:**
- Modify: `skills/context-hub/templates/gitlab-ci.yml`
- Modify: `README.md`
- Modify: `skills/context-hub/SKILL.md`
- Modify: `docs/context-hub-specification.md`

- [ ] **Step 1: Update the webhook job to pass repo URL and branch**

```yaml
script:
  - python3 scripts/refresh_context.py . --sync-gitlab --gitlab-url "$TRIGGER_REPO" --gitlab-branch "$TRIGGER_BRANCH" --auto-commit --auto-push
```

- [ ] **Step 1.5: Tighten webhook rules to require both repo and branch**

```yaml
rules:
  - if: $TRIGGER_REPO && $TRIGGER_BRANCH
```

- [ ] **Step 2: Leave nightly full sync unchanged except for wording**

```yaml
script:
  - python3 scripts/refresh_context.py . --sync-gitlab --sync-ones --auto-commit --auto-push
```

- [ ] **Step 3: Update docs to state**

```text
- webhook accepts full repo URL in HTTPS or SSH form
- branch gating follows each service's default_branch
- missing default_branch skips and waits for nightly full sync
- repo mismatch or branch mismatch produces skip, not hard failure
- same repo can map to multiple services
```

- [ ] **Step 4: Run a focused smoke verification**

Run:

```bash
python3 skills/context-hub/scripts/init_context_hub.py --output /tmp/context-hub-demo --name "Demo" --id demo
python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-demo --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main --dry-run
```

Expected: `DRY-RUN` output and no crash

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/templates/gitlab-ci.yml README.md skills/context-hub/SKILL.md docs/context-hub-specification.md
git commit -m "docs: document incremental gitlab sync contract"
```

## Task 5: Run full verification and prepare integration handoff

**Files:**
- Modify if needed: any files touched above

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`  
Expected: `OK`

- [ ] **Step 2: Run compile verification**

Run: `python3 -m py_compile skills/context-hub/scripts/sync_topology.py skills/context-hub/scripts/refresh_context.py skills/context-hub/scripts/integrations/gitlab_adapter.py`  
Expected: no output

- [ ] **Step 3: Run an end-to-end smoke flow**

Run:

```bash
python3 skills/context-hub/scripts/init_context_hub.py --output /tmp/context-hub-incremental-smoke --name "Smoke" --id smoke
python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-incremental-smoke --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main --dry-run
python3 skills/context-hub/scripts/check_consistency.py --hub /tmp/context-hub-incremental-smoke
python3 skills/context-hub/scripts/check_stale.py --hub /tmp/context-hub-incremental-smoke --warn-days 30
```

Expected: no crash; `dry-run` message present; consistency/stale checks complete

- [ ] **Step 4: Push the branch**

```bash
git push origin main
```

- [ ] **Step 5: Record any remaining deferred items**

```text
- repo-to-capability linkage still deferred
- changed-files-aware narrowing still deferred
- webhook event parser still external to hub
```
