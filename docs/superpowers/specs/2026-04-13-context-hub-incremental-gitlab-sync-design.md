# Context Hub Incremental GitLab Sync Design

> 日期：2026-04-13
> 状态：draft
> 主题：为 `context-hub` 增加 repo-scoped 的 GitLab 增量同步能力，使 Webhook/CI 能按单仓库、单分支刷新共享拓扑，而不是每次都做 hub 级全量同步。

## 1. 背景

当前 `context-hub` 已经具备：

- `refresh_context.py` 负责 team export 聚合、可选 GitLab / ONES 同步、最小审计和可选 auto-commit
- `sync_topology.py` 负责基于 `topology/system.yaml` 中登记的 repo 扫描工程服务，并回写自动字段
- `.gitlab-ci.yml` 已经将 nightly 和 webhook job 都接到了 `refresh_context.py`

但当前 webhook 路径仍有一个明显缺口：

- Webhook 只能触发 hub 级刷新，不能只更新某个 repo 对应的 service
- `.gitlab-ci.yml` 声明了 `TRIGGER_REPO`，但当前 `refresh_context.py` 和 `sync_topology.py` 没有真正消费 repo-scoped 输入
- Webhook 高频触发时，如果每次都全量刷新，成本高、噪音大，也更容易把不相关 service 一起带进 commit

用户进一步确认了两个关键约束：

1. Webhook/CI 侧传入的仓库标识以“完整 repo URL”为准
2. repo URL 可能是 `https://host/group/service.git`，也可能是 `git@host:group/service.git`
3. 分支 gating 不是统一配置，而是“每个服务按自己的 `default_branch` 决定是否允许刷新”

## 2. 目标与非目标

### 2.1 目标

1. 支持 webhook 将完整 repo URL 和 branch 传入 `context-hub`
2. 让 `context-hub` 只刷新该 repo 对应的 service，而不是全量刷新所有 service
3. 让 `branch == service.default_branch` 成为增量刷新的唯一放行条件
4. 保持现有 nightly 全量同步能力不变
5. 保持最小审计、warning 阻断 auto-commit、dry-run 等现有安全约束不变

### 2.2 非目标

1. 本次不实现按提交文件路径进一步缩小扫描范围
2. 本次不实现多 repo 批量 webhook 合并
3. 本次不改变 ONES 同步策略
4. 本次不实现 webhook 事件源解析器；只约定 CI 传参和 runtime 行为

## 3. 输入契约

Webhook / CI 对 `context-hub` 提供两个显式输入：

- `repo URL`
- `branch`

在 CLI 中映射为：

- `refresh_context.py --gitlab-url <repo-url>`
- `refresh_context.py --gitlab-branch <branch>`

### 3.1 支持的 repo URL 形式

运行时必须兼容以下两种格式：

1. HTTPS
   `https://itgitlab.xylink.com/group/service.git`
2. SSH
   `git@itgitlab.xylink.com:group/service.git`

### 3.2 规范化结果

repo URL 在进入匹配逻辑前统一规范化为：

- `host`
- `path_with_namespace`

例如：

- `https://itgitlab.xylink.com/group/service.git`
  -> `host=itgitlab.xylink.com`, `path_with_namespace=group/service`
- `git@itgitlab.xylink.com:group/service.git`
  -> `host=itgitlab.xylink.com`, `path_with_namespace=group/service`

## 4. 匹配与分支规则

### 4.1 service 匹配

`sync_topology.py` 增量模式下不再遍历所有 service，而是：

1. 读取 `topology/system.yaml`
2. 对每个 `services.<name>.repo` 做同样的 repo URL 规范化
3. 使用 `host + path_with_namespace` 做精确匹配

这样可以避免：

- 不同 GitLab instance 上同名 repo 混淆
- 只传 repo 名导致的重名误匹配

### 4.2 branch gating

当 repo 匹配到某个 service 后：

- 只有 `gitlab_branch == service.default_branch` 时才允许刷新该 service
- 如果 `default_branch` 缺失，则 webhook 增量路径直接 `skip`
- `default_branch` 的补齐和纠偏交给 nightly 全量同步完成

### 4.3 多 service / monorepo 行为

同一个规范化 repo 可能对应多个 service。为避免把数据模型强行改成单值映射，本次定义为：

- `repo -> services[]`，而不是 `repo -> service`
- 增量路径会找出所有 repo 命中的 service
- 对每个命中的 service 单独执行 branch gating
- 最终只刷新 branch 放行的那部分 service

这意味着：

- monorepo 是允许的
- 不会因为同 repo 多 service 就直接报错
- 结果契约必须能表达 `matched_services` 和 `synced_services`

### 4.4 skip 行为

以下场景都不应报错中断：

1. repo URL 没匹配到任何 service
2. repo 匹配成功，但 branch 不等于该 service 的 `default_branch`
3. repo 匹配成功，但某个 service 缺少 `default_branch`

这两类情况都应该：

- 不触发对应 service 的 GitLab 增量 enrichment 写入
- 返回明确的 skip reason
- 允许调用方继续执行后续审计逻辑

这里要明确区分两层行为：

- `refresh_context.py` 作为 orchestrator，仍然会先运行 team export 聚合，这一步可能重写 `topology/system.yaml`
- “不修改 `system.yaml`”在本次特性中具体指：skip 场景不应额外改写 GitLab 增量 enrichment 的 service 字段

## 5. 运行时设计

### 5.1 `sync_topology.py`

新增 repo-scoped 的增量入口，建议保留两个公开模式：

1. `full sync`
   现有行为，扫描所有 engineering service
2. `repo-scoped sync`
   只针对一个 repo URL 和 branch 刷新一个 service

建议新增的内部能力：

- `normalize_repo_url(repo_url) -> {host, path_with_namespace}`
- `find_services_by_repo(system_payload, repo_url) -> list[(service_name, service_dict)]`
- `should_sync_service_for_branch(service, branch) -> bool`
- `sync_services_for_repo(hub_root, repo_url, branch) -> result`

增量 result 至少包含：

- `mode`: `incremental`
- `matched_services`: list[str]
- `synced_services`: list[str]
- `reason`: optional
- `system_path`

### 5.1.1 URL 规范化放置位置

repo URL 规范化不能只存在于匹配层，还必须覆盖 GitLab API 调用层。

本次明确要求：

- 将 repo URL normalization 下沉到共享 helper
- 优先放在 `integrations/gitlab_adapter.py`，或由其调用的公共 helper 中
- `sync_topology.py` 与 `gitlab_adapter.py` 都复用同一套 canonicalization 规则

这样可以保证：

- service.repo 是 SSH、webhook 输入是 HTTPS 时仍能命中
- 命中后 GitLab adapter 也能正确构造 API 调用，而不是只在匹配层兼容 SSH

### 5.2 `refresh_context.py`

保持现有行为不变，但增加 GitLab 增量编排：

- 不带 `--gitlab-url` 时：
  - `--sync-gitlab` 继续走全量 topology sync
- 带 `--gitlab-url` 时：
  - `--sync-gitlab` 走 repo-scoped sync
  - `--gitlab-branch` 参与 branch gating

同时保留：

- 聚合 team exports
- ONES sync
- `check_consistency.py` / `check_stale.py`
- warning 阻断 `auto-commit`

这里也明确：

- webhook 增量模式只缩小 GitLab enrichment 的作用域
- team export 聚合仍保持 hub-scoped，不引入 service-scoped export aggregation

### 5.3 `.gitlab-ci.yml`

webhook job 改为把 repo URL 和 branch 显式传给 runtime：

```yaml
script:
  - python3 scripts/refresh_context.py . \
      --sync-gitlab \
      --gitlab-url "$TRIGGER_REPO" \
      --gitlab-branch "$TRIGGER_BRANCH" \
      --auto-commit \
      --auto-push
```

nightly job 保持全量：

```yaml
script:
  - python3 scripts/refresh_context.py . --sync-gitlab --sync-ones --auto-commit --auto-push
```

Webhook job 的触发前提也要收紧为同时拥有：

- `TRIGGER_REPO`
- `TRIGGER_BRANCH`

缺少任一变量都不应进入增量同步 job。

## 6. 安全与失败处理

### 6.1 自动提交边界

repo-scoped sync 即使只命中一个 service，也仍然必须遵守：

- 先写入
- 再审计
- 有 warning 就跳过 auto-commit/push

### 6.2 输入异常

以下情况应报明确错误：

- `--gitlab-url` 无法解析
- `--sync-gitlab` 启用增量模式但 branch 参数为空

以下情况应只 skip，不算错误：

- repo 未匹配到 service
- branch 不等于 `default_branch`
- service 缺少 `default_branch`

### 6.3 与现有 full sync 的关系

增量同步只优化 webhook 路径，不替代 nightly 全量同步。

nightly 仍是最终兜底：

- 补齐漏掉的 webhook
- 校正 `default_branch`
- 修复共享层漂移

## 7. 测试设计

本次最小测试集如下：

### 7.1 URL 规范化

- `https://host/group/service.git` 与 `git@host:group/service.git` 规范化结果一致

### 7.2 repo-scoped 匹配

- 只刷新匹配 repo 的 service
- 不影响未匹配 service
- 同 repo 多 service 时，只刷新命中的那组 service

### 7.3 branch gating

- branch 等于 `default_branch` 时执行刷新
- branch 不等于 `default_branch` 时跳过，并返回 skip reason
- `default_branch` 缺失时跳过，并返回 skip reason

### 7.4 refresh 编排

- `refresh_context.py` 在传入 `--gitlab-url` + `--gitlab-branch` 时调用 repo-scoped GitLab sync
- skip 情况下仍继续执行最小审计
- 有 warning 时不 auto-commit

### 7.5 CI 模板

- webhook job 包含 `TRIGGER_REPO` 与 `TRIGGER_BRANCH`
- nightly job 仍保留全量模式

## 8. 验收标准

满足以下条件即可视为本次特性完成：

1. webhook 输入完整 repo URL 与 branch 后，`context-hub` 能只刷新命中的 service 集合
2. SSH / HTTPS 两种 repo URL 都能正确匹配同一个 service
3. 非 default branch 的 webhook 不会改写 `system.yaml`
4. repo 未匹配到 service 时不会报错失败
5. 增量路径仍然跑最小审计，并在 warning 存在时跳过 auto-commit
6. 现有 nightly 全量同步路径保持可用

## 9. 当前明确不做

本次不实现以下能力：

- 基于 changed files 再次缩小扫描范围
- 按 MR 事件、tag 事件做差异化策略
- repo 到 capability 的直接联动刷新
- Figma / design 侧的增量同步
