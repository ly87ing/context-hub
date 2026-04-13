# Context Hub Changed-Files GitLab Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add commit-driven changed-files gating to the existing repo-scoped GitLab incremental sync so webhook/CI only scans a repo when the current default-branch commit touches topology-relevant files.

**Architecture:** Keep `refresh_context.py` as the orchestration entrypoint, extend `integrations/gitlab_adapter.py` to read commit changed files from GitLab, and add a mechanical changed-files gate in `sync_topology.py` before any repo scan runs. Treat repo/branch/commit input and GitLab diff fetch failures as fatal errors, but treat “no matching service”, branch mismatch, empty changed files, and docs-only changes as informational skip results that do not become runtime warnings by themselves.

**Tech Stack:** Python 3 stdlib, existing GitLab adapter + runtime HTTP client, `unittest`, YAML fixtures, GitLab CI template

---

## Scope Check

This plan only implements commit-driven changed-files gating for the existing GitLab incremental sync path. It does not include:

- capability-level refresh decisions
- ONES behavior changes
- Figma integration
- semantic analysis of application code
- commit-range diff support

Those remain follow-up work and should not be pulled into this implementation.

## File Structure

### Modify

- `docs/superpowers/specs/2026-04-13-context-hub-changed-files-gitlab-sync-design.md`
- `skills/context-hub/scripts/integrations/gitlab_adapter.py`
- `skills/context-hub/scripts/sync_topology.py`
- `skills/context-hub/scripts/refresh_context.py`
- `skills/context-hub/templates/gitlab-ci.yml`
- `skills/context-hub/tests/test_gitlab_sync.py`
- `skills/context-hub/tests/test_refresh_context.py`
- `README.md`
- `skills/context-hub/SKILL.md`
- `docs/context-hub-specification.md`

### Responsibility Map

- `gitlab_adapter.py`: repo URL normalization reuse, commit changed-files API call, rename/delete path extraction
- `sync_topology.py`: scan-worthy pattern matching, structured incremental result contract, skip vs scan decisions
- `refresh_context.py`: CLI parameter enforcement, fatal error propagation, non-warning handling for informational skip results
- `gitlab-ci.yml`: webhook parameter wiring for `TRIGGER_COMMIT`
- `test_gitlab_sync.py`: adapter + topology gate behavior, rename/delete edges, structured result contract
- `test_refresh_context.py`: orchestration, CLI validation, fatal error propagation, skip non-warning behavior
- docs: user-facing webhook contract and changed-files gate semantics

## Task 1: Define failing tests for GitLab commit changed-files retrieval

**Files:**
- Modify: `skills/context-hub/tests/test_gitlab_sync.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`

- [ ] **Step 1: Add a failing adapter test for the commit diff endpoint**

```python
def test_get_commit_changed_files_reads_gitlab_commit_diff(self) -> None:
    paths = get_commit_changed_files(
        "git@itgitlab.xylink.com:group/meeting-control-service.git",
        "abc123",
        environ={"ITGITLAB_ACCESS_TOKEN": "it-secret-token"},
        transport=transport,
    )
    self.assertEqual(paths, ["pyproject.toml", "openapi.yaml"])
```

- [ ] **Step 2: Add a failing rename/delete extraction test**

```python
def test_get_commit_changed_files_keeps_old_and_new_paths_for_rename_and_delete(self) -> None:
    self.assertEqual(
        paths,
        ["old/openapi.yaml", "contracts/openapi.yaml", "pyproject.toml"],
    )
```

- [ ] **Step 3: Add a failing empty-result test**

```python
def test_get_commit_changed_files_returns_empty_list_when_diff_has_no_paths(self) -> None:
    self.assertEqual(paths, [])
```

- [ ] **Step 4: Run the targeted test file to verify red**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: `FAIL` because `get_commit_changed_files()` does not exist yet.

- [ ] **Step 5: Commit**

```bash
git add skills/context-hub/tests/test_gitlab_sync.py
git commit -m "test: define gitlab commit changed-files behavior"
```

## Task 2: Implement GitLab commit changed-files retrieval in the adapter

**Files:**
- Modify: `skills/context-hub/scripts/integrations/gitlab_adapter.py`
- Test: `skills/context-hub/tests/test_gitlab_sync.py`

- [ ] **Step 1: Add a helper to fetch commit diff metadata**

```python
def get_commit_changed_files(
    gitlab_url: str,
    commit_sha: str,
    *,
    client: HttpClient | None = None,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> list[str]:
    ...
```

- [ ] **Step 2: Reuse repo normalization and project lookup**

```python
project = lookup_project(gitlab_url, client=client, environ=environ, token=token, transport=transport, timeout=timeout)
```

- [ ] **Step 3: Extract changed paths conservatively for rename/delete**

```python
def extract_changed_paths(diff_item: Mapping[str, object]) -> list[str]:
    paths = []
    for key in ("old_path", "new_path"):
        value = str(diff_item.get(key) or "").strip()
        if value:
            paths.append(value)
    return unique_preserving_order(paths)
```

- [ ] **Step 4: Return deduplicated path strings only**

```python
changed_paths = unique_preserving_order(path for item in payload for path in extract_changed_paths(item))
return changed_paths
```

- [ ] **Step 5: Keep API failures fatal**

```python
if not commit_sha.strip():
    raise ValueError("gitlab incremental sync requires --gitlab-commit")
```

- [ ] **Step 6: Re-run the targeted adapter test file**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: adapter tests pass; topology gate tests may still fail.

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/scripts/integrations/gitlab_adapter.py skills/context-hub/tests/test_gitlab_sync.py
git commit -m "feat: fetch gitlab commit changed files"
```

## Task 3: Define failing tests for changed-files gate and structured incremental results

**Files:**
- Modify: `skills/context-hub/tests/test_gitlab_sync.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`

- [ ] **Step 1: Add a failing scan-worthy commit test**

```python
def test_incremental_sync_scans_repo_when_changed_files_hit_topology_patterns(self) -> None:
    result = sync_system_topology(
        self.hub_dir,
        repo_url="git@itgitlab.xylink.com:group/service.git",
        branch="main",
        commit_sha="abc123",
    )
    self.assertEqual(result["decision"], "scan")
    self.assertEqual(result["changed_files"], ["pyproject.toml"])
```

- [ ] **Step 2: Add a failing docs-only skip test**

```python
def test_incremental_sync_skips_docs_only_commit_without_warning_contract(self) -> None:
    self.assertEqual(result["decision"], "skip")
    self.assertEqual(result["reason_code"], "no_topology_signal")
    self.assertEqual(result["synced_services"], [])
```

- [ ] **Step 3: Add a failing empty-changed-files skip test**

```python
def test_incremental_sync_skips_when_commit_has_no_changed_files(self) -> None:
    self.assertEqual(result["reason_code"], "no_changed_files")
    self.assertEqual(result["reason"], "commit has no changed files")
```

- [ ] **Step 4: Add a failing branch-mismatch informational skip test**

```python
def test_incremental_sync_branch_mismatch_is_informational_skip(self) -> None:
    self.assertEqual(result["decision"], "skip")
    self.assertEqual(result["reason_code"], "branch_mismatch")
```

- [ ] **Step 5: Add a failing missing-default-branch informational skip test**

```python
def test_incremental_sync_missing_default_branch_is_informational_skip(self) -> None:
    self.assertEqual(result["decision"], "skip")
    self.assertEqual(result["reason_code"], "missing_default_branch")
```

- [ ] **Step 6: Add a failing no-service-match skip test**

```python
def test_incremental_sync_no_service_match_returns_skip_contract(self) -> None:
    self.assertEqual(result["decision"], "skip")
    self.assertEqual(result["reason_code"], "no_matching_service")
```

- [ ] **Step 7: Run the targeted test file to verify red**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: `FAIL` because `sync_topology.py` does not accept `commit_sha` or return the new result fields yet.

- [ ] **Step 8: Commit**

```bash
git add skills/context-hub/tests/test_gitlab_sync.py
git commit -m "test: define changed-files topology gate behavior"
```

## Task 4: Implement changed-files gating and structured skip semantics in `sync_topology.py`

**Files:**
- Modify: `skills/context-hub/scripts/sync_topology.py`
- Test: `skills/context-hub/tests/test_gitlab_sync.py`

- [ ] **Step 1: Add the scan-worthy matcher**

```python
def should_scan_repo_for_changed_files(paths: list[str]) -> tuple[bool, str, str]:
    ...
```

- [ ] **Step 2: Make matching mechanical and case-insensitive**

```python
filename = Path(path).name.lower()
normalized = path.strip().lower()
```

- [ ] **Step 3: Extend incremental sync inputs with `commit_sha`**

```python
def sync_services_for_repo(
    hub_root: Path,
    repo_url: str,
    branch: str | None,
    commit_sha: str | None,
) -> dict[str, object]:
    ...
```

- [ ] **Step 4: Fetch changed files before scanning any matched repo**

```python
changed_files = gitlab_adapter.get_commit_changed_files(repo_url, normalized_commit_sha)
decision_should_scan, reason_code, reason = should_scan_repo_for_changed_files(changed_files)
```

- [ ] **Step 5: Return informational skip results without mutating enrichment fields**

```python
return {
    "mode": "incremental",
    "decision": "skip",
    "matched_services": matched_names,
    "synced_services": [],
    "changed_files": changed_files,
    "reason_code": reason_code,
    "reason": reason,
    "system_path": system_path,
}
```

- [ ] **Step 6: Keep branch/default-branch/no-match as structured skip outcomes**

```python
return incremental_skip_result(..., reason_code="branch_mismatch", reason="branch feature/x does not match default_branch main")
```

- [ ] **Step 7: Only scan repo and save `system.yaml` when decision is `scan`**

```python
if decision_should_scan:
    for service_name, service in matched_services:
        summary = scan_repo_summary(service)
        ...
```

- [ ] **Step 8: Preserve full sync behavior**

```python
def sync_system_topology(..., repo_url: str | None = None, branch: str | None = None, commit_sha: str | None = None):
    if repo_url:
        return sync_services_for_repo(...)
    return sync_all_services(...)
```

- [ ] **Step 9: Re-run the targeted topology test file**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_gitlab_sync.py' -v`  
Expected: `OK`

- [ ] **Step 10: Commit**

```bash
git add skills/context-hub/scripts/sync_topology.py skills/context-hub/tests/test_gitlab_sync.py
git commit -m "feat: gate gitlab topology sync by changed files"
```

## Task 5: Define failing refresh-context tests for CLI validation and fatal error propagation

**Files:**
- Modify: `skills/context-hub/tests/test_refresh_context.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`

- [ ] **Step 1: Add a failing workflow parameter threading test**

```python
def test_run_refresh_workflow_threads_repo_branch_and_commit_to_gitlab_sync(self) -> None:
    refresh_context.run_refresh_workflow(
        self.hub_dir,
        sync_gitlab=True,
        gitlab_url="git@itgitlab.xylink.com:group/service.git",
        gitlab_branch="main",
        gitlab_commit="abc123",
    )
```

- [ ] **Step 2: Add a failing CLI validation test for missing commit**

```python
def test_refresh_context_rejects_incremental_gitlab_sync_without_commit(self) -> None:
    result = run_script(
        "refresh_context.py",
        str(self.hub_dir),
        "--sync-gitlab",
        "--gitlab-url",
        "git@itgitlab.xylink.com:group/service.git",
        "--gitlab-branch",
        "main",
    )
    self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 3: Add a failing CLI validation test for missing branch**

```python
def test_refresh_context_rejects_incremental_gitlab_sync_without_branch(self) -> None:
    result = run_script(
        "refresh_context.py",
        str(self.hub_dir),
        "--sync-gitlab",
        "--gitlab-url",
        "git@itgitlab.xylink.com:group/service.git",
        "--gitlab-commit",
        "abc123",
    )
    self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 4: Add a failing fatal-propagation test**

```python
def test_run_refresh_workflow_propagates_gitlab_changed_files_errors(self) -> None:
    with patch.object(refresh_context, "run_gitlab_sync", side_effect=ValueError("unable to read changed files")):
        with self.assertRaises(ValueError):
            refresh_context.run_refresh_workflow(...)
```

- [ ] **Step 5: Add a failing informational-skip test with a real orchestration seam**

```python
def test_run_refresh_workflow_does_not_turn_incremental_skip_reason_into_warning(self) -> None:
    with (
        patch.object(refresh_context, "refresh_shared_context", return_value=outputs),
        patch.object(refresh_context, "run_gitlab_sync", return_value={
            "mode": "incremental",
            "decision": "skip",
            "reason_code": "no_topology_signal",
            "reason": "docs-only changes",
            "changed_files": ["README.md"],
            "matched_services": ["meeting-control-service"],
            "synced_services": [],
            "system_path": outputs["system"],
        }),
        patch.object(refresh_context, "refresh_llms_txt", return_value=outputs["llms"]),
        patch.object(refresh_context, "run_validation_checks", return_value=[]),
    ):
        result = refresh_context.run_refresh_workflow(...)
    self.assertEqual(result["warnings"], [])
```

- [ ] **Step 6: Run the targeted refresh test file to verify red**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `FAIL` because `refresh_context.py` does not accept `gitlab_commit` or distinguish fatal GitLab errors from informational skip results yet.

- [ ] **Step 7: Commit**

```bash
git add skills/context-hub/tests/test_refresh_context.py
git commit -m "test: define refresh context changed-files contract"
```

## Task 6: Implement `refresh_context.py` and CI wiring for commit-driven incremental sync

**Files:**
- Modify: `skills/context-hub/scripts/refresh_context.py`
- Modify: `skills/context-hub/templates/gitlab-ci.yml`
- Modify: `skills/context-hub/tests/test_refresh_context.py`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`

- [ ] **Step 1: Add the new CLI flag**

```python
parser.add_argument("--gitlab-commit", default="", help="指定用于增量同步的 GitLab commit SHA")
```

- [ ] **Step 2: Thread `gitlab_commit` through `run_refresh_workflow()`**

```python
def run_refresh_workflow(..., gitlab_commit: str | None = None, ...) -> dict[str, object]:
    ...
```

- [ ] **Step 3: Enforce the repo+branch+commit triple**

```python
if sync_gitlab and normalized_gitlab_url and not normalized_gitlab_branch:
    raise ValueError("gitlab incremental sync requires --gitlab-branch")
if sync_gitlab and normalized_gitlab_url and not normalized_gitlab_commit:
    raise ValueError("gitlab incremental sync requires --gitlab-commit")
```

- [ ] **Step 4: Propagate fatal GitLab incremental errors instead of downgrading them**

```python
except ValueError:
    raise
```

- [ ] **Step 5: Only surface scan results as warnings when the result explicitly says `decision == \"error\"`**

```python
if isinstance(gitlab_result, dict) and gitlab_result.get("decision") == "error":
    warnings.append(str(gitlab_result["reason"]))
```

- [ ] **Step 6: Pass the commit SHA into the GitLab sync call**

```python
gitlab_result = run_gitlab_sync(
    hub_root,
    repo_url=normalized_gitlab_url or None,
    branch=normalized_gitlab_branch or None,
    commit_sha=normalized_gitlab_commit or None,
)
```

- [ ] **Step 7: Update the webhook CI template**

```yaml
script:
  - python3 scripts/refresh_context.py . \
      --sync-gitlab \
      --gitlab-url "$TRIGGER_REPO" \
      --gitlab-branch "$TRIGGER_BRANCH" \
      --gitlab-commit "$TRIGGER_COMMIT" \
      --auto-commit \
      --auto-push
```

- [ ] **Step 8: Re-run the targeted refresh test file**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_refresh_context.py' -v`  
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add skills/context-hub/scripts/refresh_context.py skills/context-hub/templates/gitlab-ci.yml skills/context-hub/tests/test_refresh_context.py
git commit -m "feat: wire changed-files gitlab sync through refresh workflow"
```

## Task 7: Update docs to match the final runtime contract

**Files:**
- Modify: `README.md`
- Modify: `skills/context-hub/SKILL.md`
- Modify: `docs/context-hub-specification.md`
- Modify: `docs/superpowers/specs/2026-04-13-context-hub-changed-files-gitlab-sync-design.md`
- Test: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`

- [ ] **Step 1: Document the webhook input contract**

```markdown
- `TRIGGER_REPO`
- `TRIGGER_BRANCH`
- `TRIGGER_COMMIT`
```

- [ ] **Step 2: Document fatal vs informational outcomes**

```markdown
`repo/branch/commit` 校验失败和 GitLab changed-files 读取失败会终止刷新；repo 未命中、branch 不匹配、空 changed files、docs-only commit 只会返回 skip。
```

- [ ] **Step 3: Document the first-version scan-worthy patterns**

```markdown
`pyproject.toml`、`requirements.txt`、`package.json`、`pom.xml`、`build.gradle`、`build.gradle.kts`、`go.mod`、`*.proto`、`openapi.*`、`swagger.*`
```

- [ ] **Step 4: Re-run the full test suite**

Run: `python3 -m unittest discover -s skills/context-hub/tests -p 'test_*.py' -v`  
Expected: `OK`

- [ ] **Step 5: Run syntax verification for touched scripts**

Run: `python3 -m py_compile skills/context-hub/scripts/integrations/gitlab_adapter.py skills/context-hub/scripts/sync_topology.py skills/context-hub/scripts/refresh_context.py`  
Expected: no output

- [ ] **Step 6: Commit**

```bash
git add README.md skills/context-hub/SKILL.md docs/context-hub-specification.md docs/superpowers/specs/2026-04-13-context-hub-changed-files-gitlab-sync-design.md
git commit -m "docs: document changed-files gitlab sync contract"
```

## Task 8: Run an end-to-end webhook smoke test

**Files:**
- Test only: temporary hub under `/tmp`

- [ ] **Step 1: Bootstrap a temporary hub**

Run: `python3 skills/context-hub/scripts/init_context_hub.py --output /tmp/context-hub-changed-files-smoke --name smoke --id smoke`  
Expected: hub skeleton created

- [ ] **Step 2: Execute a docs-only dry-run webhook refresh**

Run: `python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-changed-files-smoke --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main --gitlab-commit abc123 --dry-run`  
Expected: dry-run output plus no write-side failure; use mocks or fixture transport if the test harness exposes one, otherwise skip this smoke step and note the limitation in the execution log.

- [ ] **Step 3: Run consistency and stale checks on the temp hub**

Run: `python3 skills/context-hub/scripts/check_consistency.py /tmp/context-hub-changed-files-smoke`  
Expected: `✅ 全部通过`

Run: `python3 skills/context-hub/scripts/check_stale.py --hub /tmp/context-hub-changed-files-smoke`  
Expected: no blocking stale errors introduced by the webhook path

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: verify changed-files gitlab sync smoke flow"
```

## Review Notes

- Keep `refresh_context.py` warning semantics stable for validation warnings; only the GitLab incremental skip contract changes.
- Do not silently fall back from incremental mode to full sync when `gitlab_commit` is missing.
- Preserve monorepo behavior: one repo can still map to multiple services, but one commit-level changed-files decision gates the repo scan once.
- If the final implementation needs a small helper function for reusable incremental result payloads, add it in `sync_topology.py` instead of spreading dict literals across files.
