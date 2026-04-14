# Context Hub 当前实现规范

> 本文档描述当前仓库中已经落地的 `context-hub` 能力边界，而不是未来愿景的全集。

如果你需要先理解团队应该怎么使用这套仓库、目录应该怎么组织、一个 capability 从需求到测试怎么维护，先看 [docs/guides/context-hub-lifecycle-guide.md](guides/context-hub-lifecycle-guide.md)。

## 1. 定位

`context-hub` 是一个共享 Git 仓库，用来沉淀项目可共享的上下文。它不是源码镜像、不是知识库平台，也不是拥有全局权限的中心服务。

当前实现的目标是建立一个可运行的联邦维护基线，并补上最小 GitLab / ONES 同步闭环：

- 各团队只维护自己有权限且允许共享的内容
- 共享层只保存摘要、索引、链接、ownership 和 freshness
- 本地脚本可以初始化、聚合、同步、校验、审计并驱动 role workflow 写入这个共享层

## 2. 联邦维护模型

### 2.1 基本原则

- `context-hub` 只聚合共享导出结果，不越权抓取外部系统
- 没有一个默认存在的全局超集权限账号
- 权限不足时优先消费共享摘要，而不是强行下钻源系统

### 2.2 团队边界

- `product`：维护需求域、capability 索引，当前可导出 `domains-fragment.yaml`
- `engineering`：维护服务和依赖摘要，当前可导出 `system-fragment.yaml`
- `qa`：维护测试来源摘要，当前可导出 `testing-fragment.yaml`
- `design`：当前创建 `teams/design/exports/` 目录，但暂未定义聚合 schema

### 2.3 共享导出要求

任何 team export 如果存在，都必须带上以下 metadata：

- `maintained_by`
- `source_system`
- `source_ref`
- `visibility`
- `last_synced_at`
- `confidence`

## 3. Shared Context 契约

当前共享层由以下文件构成：

- `IDENTITY.md`
- `topology/system.yaml`
- `topology/domains.yaml`
- `topology/testing-sources.yaml`
- `topology/ownership.yaml`
- `capabilities/<name>/spec.md`
- `capabilities/<name>/design.md`
- `capabilities/<name>/architecture.md`
- `capabilities/<name>/testing.md`
- `capabilities/<name>/source-summary.yaml`（仅在配置 `ones_tasks` 后生成）
- `decisions/_index.md`
- `decisions/_template.md`
- `.context/llms.txt`

团队维护层位于：

- `teams/product/exports/`
- `teams/design/exports/`
- `teams/engineering/exports/`
- `teams/qa/exports/`

运行时脚本位于生成后的 hub：

- `scripts/create_capability.py`
- `scripts/refresh_context.py`
- `scripts/bootstrap_credentials_check.py`
- `scripts/sync_topology.py`
- `scripts/sync_capability_status.py`
- `scripts/check_consistency.py`
- `scripts/check_stale.py`
- `scripts/runtime/`
- `scripts/integrations/`
- `scripts/workflows/`

## 4. 当前已实现能力

### 4.1 初始化

`init_context_hub.py` 会生成一个新 hub，包含：

- 共享文档骨架
- `IDENTITY.md`、`topology/system.yaml`、`topology/domains.yaml`、`topology/testing-sources.yaml`、`topology/ownership.yaml`
- `decisions/_index.md`、`decisions/_template.md`
- `capabilities/_templates/`
- `teams/*/exports/`
- `.context/llms.txt`
- `templates/` 完整模板目录（含 `templates/role-intake/`）
- `.gitlab-ci.yml`、`.gitignore`
- `scripts/create_capability.py`
- `scripts/refresh_context.py`
- `scripts/update_llms_txt.py`
- `scripts/bootstrap_credentials_check.py`
- `scripts/sync_topology.py`
- `scripts/sync_capability_status.py`
- `scripts/check_consistency.py`
- `scripts/check_stale.py`
- `scripts/_common.py`
- `scripts/yaml_compat.py`
- `scripts/runtime/`
- `scripts/integrations/`
- `scripts/workflows/`

### 4.2 Capability 生命周期起点

`create_capability.py` 会：

- 创建标准 capability 目录和四类角色文档
- 在 `topology/domains.yaml` 中登记 capability
- 在 `topology/ownership.yaml` 中登记 capability 归属
- 保存 capability 的 `ones_tasks`
- 刷新 `.context/llms.txt`

### 4.3 Role Workflow Platform v1

role workflow v1 由 `SKILL.md` 和 `scripts/workflows/*.py` 共同构成：

- `SKILL.md` 负责 mixed-entry 路由，按 `显式角色 > 目标文档/动作词 > capability 缺口` 推断 role
- 动作 contract 固定为 `create` / `extend` / `revise` / `align`
- mutating workflow 一律通过 `--content-file` 接收草稿，再由脚本负责写入目标文档
- 外部系统读取结果统一映射为 `live_ok` / `fallback_to_hub` / `blocked`
- `scripts/workflows/common.py` 提供 shared helper，包括 role normalization、target-file mapping、mutation request 和统一结果结构
- `scripts/workflows/pm_workflow.py` 写 `spec.md`；只有 PM `create` 可以 bootstrap 缺失 capability；每次写后都会刷新 `downstream-checklist.yaml`、`iteration-index.yaml`、`lifecycle-state.yaml` 和 hub 级 `topology/releases.yaml`
- `scripts/workflows/design_workflow.py` 写 `design.md`；可选读取 Figma URL 并做轻量 probe，同时刷新 `lifecycle-state.yaml`
- `scripts/workflows/engineering_workflow.py` 写 `architecture.md`；可选读取 GitLab repo 并做轻量 lookup，同时刷新 `lifecycle-state.yaml`
- `scripts/workflows/qa_workflow.py` 写 `testing.md`；优先读取 ONES 测试任务，失败时回退到 `topology/testing-sources.yaml`，同时刷新 `lifecycle-state.yaml`
- `scripts/workflows/maintenance_workflow.py` 做只读审计，结合 `lifecycle-state.yaml`、`downstream-checklist.yaml` 和 `semantic-consistency.yaml` 返回 `pending_roles`、`blocking_issues`、`suggested_repairs`
- PM workflow 可选接收 `iteration` / `release` 标签，并把它们收敛到 capability 下的 `iteration-index.yaml`

#### 4.3.1 迭代变更维护规则

同一个 capability 在不同迭代中的需求演进，默认持续维护在同一目录下，而不是按迭代复制出多套 `spec/design/architecture/testing`：

- 长周期锚点始终是 `capabilities/<name>/`
- 迭代是该 capability 的一次变更来源，不是新的顶层 contract 单元
- 只有当后续工作已经不再属于同一个能力边界时，才应创建新的 capability

当迭代发生需求变更时，按受影响面联动维护：

- 业务目标、范围、规则、验收变化：更新 `spec.md`
- 交互、状态、页面流程、视觉约束变化：更新 `design.md`
- 服务边界、接口、依赖、实现约束变化：更新 `architecture.md`
- 测试范围、回归面、环境依赖、验收口径变化：更新 `testing.md`

维护原则如下：

- 不要求每次迭代机械地重写四份文档；只同步受影响的角色文档
- `spec.md` 是需求变更的主入口；任何迭代范围变化至少应在 `spec.md` 留下痕迹，且 PM workflow 写后会刷新 `downstream-checklist.yaml`、`iteration-index.yaml` 与 `lifecycle-state.yaml`
- `iteration-index.yaml` 用来记录 capability 当前所处的 iteration / release，以及同一标签下累计发生过多少次 PM 变更
- `spec.md` 的“变更记录”用于记录迭代级变化
- 影响技术决策边界的变更，除更新 `architecture.md` 外，还应补充 `decisions/*.md`
- 影响真实任务来源时，应维护 `topology/domains.yaml` 中 capability 的 `ones_tasks`
- `sync_capability_status.py` 会根据 `ones_tasks` 汇总生成 `source-summary.yaml`，并回写 `status`、`last_synced_at`、`source_ref`

推荐执行顺序：

1. PM 用 `revise` 或 `align` 更新 `spec.md`
2. Design / Engineering / QA 仅对受影响文档执行对应的 `extend` / `revise` / `align`
3. 若 `ones_tasks` 发生变化，运行 `sync_capability_status.py` 或 `refresh_context.py --sync-ones`
4. 写后运行 `check_consistency.py`；需要 freshness 检查时再运行 `check_stale.py`

这条规则的目标是让同一个 capability 在多次迭代中保持单一事实源，同时保留足够的变更轨迹和跨角色一致性。

### 4.4 Shared Context 聚合与编排

`refresh_context.py` 当前负责编排本地聚合与可选同步：

- 从 `product` 读取 `domains-fragment.yaml`
- 从 `design` 读取 `design-fragment.yaml`
- 从 `engineering` 读取 `system-fragment.yaml`
- 从 `qa` 读取 `testing-fragment.yaml`
- 合并到 `topology/*`
- 刷新 `topology/releases.yaml`
- 刷新 `.context/llms.txt`
- 可选执行 `sync_topology.py`
- 可选执行 `sync_capability_status.py`
- 可选执行 `sync_design_context.py`
- 写入后自动执行 `check_consistency.py` / `check_stale.py` / `check_semantic_consistency.py`
- 仅在没有 validation warning 和 semantic warning 时执行 `auto-commit` / `auto-push`
- webhook 增量模式支持 `--gitlab-url` + `--gitlab-branch` + `--gitlab-commit`，先做 changed-files gating，再缩小 GitLab enrichment 的作用域

如果 export 之间出现冲突，脚本会报错退出；webhook 增量模式下 `repo/branch/commit` 缺失或 GitLab changed-files 读取失败也会直接报错退出。repo 未命中、branch 不匹配、`default_branch` 缺失、空 changed files、docs-only commit 只会返回信息性 skip，不会单独升级成 warning。validation warning 或显式 error decision 仍会阻断自动提交。

### 4.5 GitLab / ONES 集成基线

`sync_topology.py` 当前会：

- 以 `engineering` 导出的服务 repo 为起点
- 通过 GitLab adapter 查 repo 树和关键文件
- 补全 `lang`、`framework`、`depends_on`、`provides`、`default_branch`
- 回写 `source_system`、`source_ref`、`last_synced_at`、`confidence`
- 保留手工维护字段，例如 `owner`、`notes`、`visibility`
- 在 webhook 增量模式下按 repo URL 命中 service 集合，并按各自 `default_branch` 做 branch gating
- 只有当前 commit 的 changed files 命中 topology-relevant patterns 时才继续扫描 repo
- 第一版 patterns 只包含 `pyproject.toml`、`requirements.txt`、`package.json`、`pom.xml`、`build.gradle`、`build.gradle.kts`、`go.mod`、`*.proto`、`openapi.*`、`swagger.*`

`sync_capability_status.py` 当前会：

- 读取 `topology/domains.yaml` 中 capability 的 `ones_tasks`
- 调用 ONES adapter 获取 task 摘要
- 生成 `capabilities/<path>/source-summary.yaml`
- 回写 capability 的 `status`、`last_synced_at`、`source_ref`
- 支持 `--ones-team` 作为 team UUID override

### 4.6 凭据预检

`bootstrap_credentials_check.py` 当前只做 preflight：

- 检查 GitLab 凭据是否存在
- 可选检查 ONES 凭据是否存在
- 输出 JSON 结果，不打印敏感值

它不负责真正的数据拉取或仓库扫描。

### 4.7 审计

`check_consistency.py` 会检查：

- 必需文件、脚本和 runtime/integrations 目录
- capability 模板文件
- `domains.yaml`、`ownership.yaml`、capability 目录交叉引用
- `teams/*/exports/` 是否存在
- export metadata 是否完整
- `ones_tasks` 对应 capability 是否存在 `source-summary.yaml`
- `.context/llms.txt` 是否包含共享索引、ownership / freshness 标记，以及 design / release 索引
- `scripts/runtime/lifecycle_state.py`、`release_index.py`、`semantic_consistency.py`、`maintenance_advice.py` 等 control-plane 资产

`check_semantic_consistency.py` 会：

- 按 capability 生成 `semantic-consistency.yaml`
- 检查 `spec.md` / `design.md` / `architecture.md` / `testing.md` 与共享 topology 之间的关键语义冲突
- 把 issue 结构化到 `severity`、`rule_id`、`source_files`、`suggested_role`

`check_stale.py` 会检查：

- export 的 `last_synced_at` 是否超期
- `in-progress` capability 是否缺失关键文档，造成下游阻塞
- 带 `ones_tasks` 的 capability 是否长期未同步
- `lifecycle-state.yaml` 和 `semantic-consistency.yaml` 是否长期未刷新，或已产生 blocker

## 5. 自然语言编排与脚本关系

当前关系可以概括为：

1. 自然语言编排
   `SKILL.md` 根据用户意图决定 role / action / capability、是否需要补问、是否需要运行本地脚本。
2. role workflow
   `scripts/workflows/*.py` 负责确定性执行、目标文档写入和统一结构化结果输出。
3. shared context
   AI 默认先消费共享层，而不是假设自己能访问所有源系统。
4. team exports
   当共享层需要更新时，由各团队先写各自 export，再通过 `refresh_context.py` 聚合。
5. preflight / live integrations
   如果任务需要 GitLab / ONES / Figma 事实，先用 `bootstrap_credentials_check.py` 判断是否具备条件，再按需运行 workflow lookup 或 `sync_topology.py` / `sync_capability_status.py`。
6. audit
   写入后使用 `check_consistency.py` 和 `check_stale.py` 做最小验证，避免错误状态继续传播。

## 6. 本地命令

在当前仓库中可执行的命令：

```bash
python3 skills/context-hub/scripts/init_context_hub.py \
  --output /tmp/context-hub-demo \
  --name "会议控制平台" \
  --id meeting-control

python3 skills/context-hub/scripts/create_capability.py \
  --hub /tmp/context-hub-demo \
  --name voting \
  --title "投票功能" \
  --domain meeting-control \
  --ones-task TASK-1

python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-demo --sync-gitlab --sync-ones
python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-demo --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main --gitlab-commit abc123
python3 skills/context-hub/scripts/bootstrap_credentials_check.py --check-ones
python3 skills/context-hub/scripts/sync_topology.py --hub /tmp/context-hub-demo
python3 skills/context-hub/scripts/sync_capability_status.py --hub /tmp/context-hub-demo --ones-team TEAM-UUID
python3 skills/context-hub/scripts/workflows/pm_workflow.py --hub /tmp/context-hub-demo --capability voting --action create --domain meeting --content-file /tmp/spec.md --output-format json
python3 skills/context-hub/scripts/workflows/design_workflow.py --hub /tmp/context-hub-demo --capability voting --action align --figma-url https://www.figma.com/design/FILE123/Voting --content-file /tmp/design.md --output-format json
python3 skills/context-hub/scripts/workflows/engineering_workflow.py --hub /tmp/context-hub-demo --capability voting --action revise --repo-url git@itgitlab.xylink.com:group/voting-service.git --gitlab-branch main --content-file /tmp/architecture.md --output-format json
python3 skills/context-hub/scripts/workflows/qa_workflow.py --hub /tmp/context-hub-demo --capability voting --action extend --content-file /tmp/testing.md --output-format json
python3 skills/context-hub/scripts/workflows/maintenance_workflow.py --hub /tmp/context-hub-demo --capability voting --output-format json
python3 skills/context-hub/scripts/check_consistency.py --hub /tmp/context-hub-demo
python3 skills/context-hub/scripts/check_stale.py --hub /tmp/context-hub-demo
```

## 7. 当前明确未实现

以下内容不属于当前已交付能力：

- 深度 Figma / design 侧结构化同步
- 跨全生命周期的多角色状态机和自动流转
- 默认无人值守完成所有 git add/commit/push
- 更细粒度的增量 webhook 编排和冲突自动处理
