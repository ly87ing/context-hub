# Context Hub Changed-Files GitLab Sync Design

> 日期：2026-04-13
> 状态：draft
> 主题：在现有 repo-scoped GitLab 增量同步之上，增加 commit 驱动的 changed-files gate，让 `context-hub` 只在 topology 相关文件变更时才扫描 repo。

## 1. 背景

当前 `context-hub` 已经具备：

- webhook / CI 可向 `refresh_context.py` 传入完整 `repo URL` 与 `branch`
- `sync_topology.py` 已支持 repo-scoped 增量同步
- `sync_topology.py` 会按 service 自己的 `default_branch` 做 gating
- `refresh_context.py` 会在写入后执行最小审计，并在有 warning 时跳过 auto-commit

当前增量路径仍然偏粗：

- 只要 repo 命中且 branch 放行，就会继续扫描该 repo
- 即使这次 commit 只是改了 `README.md` 或普通业务代码，也会触发 repo 扫描

用户希望进一步收敛：

1. webhook 继续传完整 `repo URL`
2. webhook 继续按 service 自己的 `default_branch` 放行
3. 外部系统当前稳定提供的是 `current commit SHA`
4. changed files 最简单、最实用的获取方式是直接调用 GitLab API

## 2. 目标与非目标

### 2.1 目标

1. 在现有 `repo URL + branch` 增量同步基础上加入 `commit SHA`
2. 让 `context-hub` 先读取这个 commit 的 changed files，再决定是否值得扫描 repo
3. 只在 topology 相关文件变更时才执行 GitLab repo scan
4. 保持现有 nightly full sync 不变
5. 保持现有审计与 warning 阻断 auto-commit 的安全边界不变

### 2.2 非目标

1. 本次不实现基于 commit range 的 diff 分析
2. 本次不实现 changed files 由外部 CI 预先计算后传入
3. 本次不实现基于 changed files 的 capability 联动刷新
4. 本次不引入对业务代码语义的分析，只做路径模式判断

## 3. 输入契约

Webhook / CI 在 GitLab 增量模式下提供三个输入：

- `repo URL`
- `branch`
- `commit SHA`

映射到 `refresh_context.py` 的 CLI：

- `--gitlab-url <repo-url>`
- `--gitlab-branch <branch>`
- `--gitlab-commit <sha>`

### 3.1 参数约束

在启用 `--sync-gitlab` 且传入 `--gitlab-url` 时：

- `--gitlab-branch` 必须存在
- `--gitlab-commit` 必须存在

否则应直接报错，而不是 silently fallback。

## 4. Changed Files 获取

### 4.1 获取方式

changed files 通过 GitLab API 按 `repo URL + commit SHA` 读取。

新增 adapter 能力：

- `get_commit_changed_files(repo_url, commit_sha) -> list[str]`

返回值只保留 changed file paths，不在 hub 中落完整 diff。

### 4.2 位置

changed-files 获取逻辑放在 `integrations/gitlab_adapter.py`，与现有 repo URL canonicalization 共享一套规则。

这样可以确保：

- HTTPS / SSH repo URL 都能走同一个匹配与 API 调用路径
- 外层 `sync_topology.py` 只关心“拿到 changed file paths 后如何判定”

## 5. Scan-Worthy 判定

### 5.1 核心原则

changed files 不是为了描述所有代码变化，而是为了回答一个问题：

> “这次 commit 是否值得重新扫描 repo 并刷新 topology enrichment？”

### 5.2 第一版 scan-worthy patterns

第一版只认高信号文件：

- `pyproject.toml`
- `requirements.txt`
- `package.json`
- `pom.xml`
- `build.gradle`
- `build.gradle.kts`
- `go.mod`
- `*.proto`
- `openapi.yaml`
- `openapi.yml`
- `swagger.yaml`
- `swagger.yml`

### 5.3 第一版显式 skip 场景

以下 changed files 不触发 repo scan：

- `README.md`
- `docs/**`
- 普通业务代码实现文件，例如 `*.py`、`*.ts`、`*.java`、`*.go`
- 注释或测试改动

原因不是这些文件不重要，而是：

- 第一版目标是“低复杂度、稳定、可预测地减少无意义扫描”
- 依赖 / 构建 / API 契约文件最直接影响 topology enrichment
- 业务代码语义变化留给后续更深的分析阶段

### 5.4 判定结果

建议新增：

- `should_scan_repo_for_changed_files(paths) -> tuple[bool, str]`

返回：

- `True`：继续 repo scan
- `False`：skip，并返回 reason，例如：
  - `docs-only changes`
  - `commit does not touch topology-relevant files`

## 6. 运行时设计

### 6.1 `gitlab_adapter.py`

新增：

- `get_commit_changed_files(repo_url, commit_sha)`

要求：

- 复用现有 repo URL normalization
- 复用现有 GitLab instance / token 发现逻辑
- 失败时抛出明确异常，不返回伪结果

### 6.2 `sync_topology.py`

repo-scoped 增量路径新增第一步：

1. repo 命中 service 集合
2. branch 与每个 service 的 `default_branch` 做 gating
3. 用 `commit SHA` 获取 changed files
4. 用 changed files 做 scan-worthy 判定
5. 只有判定通过时才继续当前 repo scan

如果 changed-files 判定不通过：

- 不扫描 repo tree
- 不修改该 repo 命中 service 的 GitLab enrichment 字段
- 返回 skip reason

### 6.3 `refresh_context.py`

保持当前编排顺序不变：

1. 聚合 team exports
2. GitLab 增量同步
3. ONES 同步
4. 审计
5. warning 阻断 auto-commit

新增：

- `--gitlab-commit`
- 对 webhook GitLab 增量模式做三元组校验：
  - repo URL
  - branch
  - commit SHA

### 6.4 `.gitlab-ci.yml`

webhook job 改为要求并传入：

- `TRIGGER_REPO`
- `TRIGGER_BRANCH`
- `TRIGGER_COMMIT`

示例：

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

nightly full sync 保持不变。

## 7. 返回契约

在现有 repo-scoped result 上新增：

- `changed_files`: list[str]

最终增量结果建议至少包含：

- `mode`
- `matched_services`
- `synced_services`
- `changed_files`
- `reason`
- `system_path`

## 8. 错误与 Skip 规则

### 8.1 错误

以下情况应直接报错：

- `repo URL` 非法
- `branch` 缺失
- `commit SHA` 缺失
- GitLab API 无法读取该 commit 的 changed files

### 8.2 Skip

以下情况应 skip，不算错误：

- repo 未命中 service
- branch 不等于 service 的 `default_branch`
- service 缺少 `default_branch`
- changed files 不命中 scan-worthy patterns

## 9. 测试设计

### 9.1 `gitlab_adapter`

- 能按 `repo URL + commit SHA` 读取 changed file paths
- HTTPS / SSH repo URL 都能正确工作

### 9.2 `sync_topology`

- changed files 命中依赖 / API 契约文件时执行 repo scan
- changed files 只有 docs / 普通代码实现时直接 skip
- repo 未命中 service 时 skip
- branch 不匹配时 skip
- `default_branch` 缺失时 skip

### 9.3 `refresh_context`

- 传入 `gitlab_url + gitlab_branch + gitlab_commit` 时正确透传
- 缺任一必需参数时报错
- 不带 `gitlab_url` 时，nightly full sync 路径保持不变

### 9.4 CI 模板

- webhook job 需要 `TRIGGER_REPO && TRIGGER_BRANCH && TRIGGER_COMMIT`
- nightly job 保持全量模式

## 10. 验收标准

满足以下条件即可视为本次设计达标：

1. webhook 输入 `repo URL + branch + commit SHA` 后，系统先读取 changed files 再决定是否扫描 repo
2. docs-only / 非 topology 相关 commit 不会触发 repo scan
3. topology 相关 commit 才会触发 repo scan
4. branch gating 与 repo matching 仍保持成立
5. nightly full sync 不回归
6. warning 仍会阻断 auto-commit

## 11. 当前明确不做

本次不实现：

- commit range 或 merge request diff 分析
- CI 预计算 changed files
- 基于 changed files 的 capability 联动刷新
- 对业务代码语义进行更深层的拓扑推断
