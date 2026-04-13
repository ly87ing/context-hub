# Context Hub 当前实现规范

> 本文档描述当前仓库中已经落地的 `context-hub` 能力边界，而不是未来愿景的全集。

## 1. 定位

`context-hub` 是一个共享 Git 仓库，用来沉淀项目可共享的上下文。它不是源码镜像、不是知识库平台，也不是拥有全局权限的中心服务。

当前实现的目标是建立一个可运行的联邦维护基线，并补上最小 GitLab / ONES 同步闭环：

- 各团队只维护自己有权限且允许共享的内容
- 共享层只保存摘要、索引、链接、ownership 和 freshness
- 本地脚本可以初始化、聚合、同步、校验和审计这个共享层

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

## 4. 当前已实现能力

### 4.1 初始化

`init_context_hub.py` 会生成一个新 hub，包含：

- 共享文档骨架
- `IDENTITY.md`、`topology/system.yaml`、`topology/domains.yaml`、`topology/testing-sources.yaml`、`topology/ownership.yaml`
- `decisions/_index.md`、`decisions/_template.md`
- `capabilities/_templates/`
- `teams/*/exports/`
- `.context/llms.txt`
- `templates/` 完整模板目录
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

### 4.2 Capability 生命周期起点

`create_capability.py` 会：

- 创建标准 capability 目录和四类角色文档
- 在 `topology/domains.yaml` 中登记 capability
- 在 `topology/ownership.yaml` 中登记 capability 归属
- 保存 capability 的 `ones_tasks`
- 刷新 `.context/llms.txt`

### 4.3 Shared Context 聚合与编排

`refresh_context.py` 当前负责编排本地聚合与可选同步：

- 从 `product` 读取 `domains-fragment.yaml`
- 从 `engineering` 读取 `system-fragment.yaml`
- 从 `qa` 读取 `testing-fragment.yaml`
- 合并到 `topology/*`
- 刷新 `.context/llms.txt`
- 可选执行 `sync_topology.py`
- 可选执行 `sync_capability_status.py`
- 写入后自动执行 `check_consistency.py` / `check_stale.py`
- 可选执行 `auto-commit` / `auto-push`
- webhook 增量模式支持 `--gitlab-url` + `--gitlab-branch`，只缩小 GitLab enrichment 的作用域

如果 export 之间出现冲突，脚本会报错退出；如果外部同步或审计只产生 warning，脚本会保留结果但跳过自动提交。

### 4.4 GitLab / ONES 集成基线

`sync_topology.py` 当前会：

- 以 `engineering` 导出的服务 repo 为起点
- 通过 GitLab adapter 查 repo 树和关键文件
- 补全 `lang`、`framework`、`depends_on`、`provides`、`default_branch`
- 回写 `source_system`、`source_ref`、`last_synced_at`、`confidence`
- 保留手工维护字段，例如 `owner`、`notes`、`visibility`
- 在 webhook 增量模式下按 repo URL 命中 service 集合，并按各自 `default_branch` 做 branch gating

`sync_capability_status.py` 当前会：

- 读取 `topology/domains.yaml` 中 capability 的 `ones_tasks`
- 调用 ONES adapter 获取 task 摘要
- 生成 `capabilities/<path>/source-summary.yaml`
- 回写 capability 的 `status`、`last_synced_at`、`source_ref`
- 支持 `--ones-team` 作为 team UUID override

### 4.5 凭据预检

`bootstrap_credentials_check.py` 当前只做 preflight：

- 检查 GitLab 凭据是否存在
- 可选检查 ONES 凭据是否存在
- 输出 JSON 结果，不打印敏感值

它不负责真正的数据拉取或仓库扫描。

### 4.6 审计

`check_consistency.py` 会检查：

- 必需文件、脚本和 runtime/integrations 目录
- capability 模板文件
- `domains.yaml`、`ownership.yaml`、capability 目录交叉引用
- `teams/*/exports/` 是否存在
- export metadata 是否完整
- `ones_tasks` 对应 capability 是否存在 `source-summary.yaml`
- `.context/llms.txt` 是否包含共享索引、ownership / freshness 标记

`check_stale.py` 会检查：

- export 的 `last_synced_at` 是否超期
- `in-progress` capability 是否缺失关键文档，造成下游阻塞
- 带 `ones_tasks` 的 capability 是否长期未同步

## 5. 自然语言编排与脚本关系

当前关系可以概括为：

1. 自然语言编排
   `SKILL.md` 根据用户意图决定读哪些共享文件、是否需要补问、是否需要运行本地脚本。
2. shared context
   AI 默认先消费共享层，而不是假设自己能访问所有源系统。
3. team exports
   当共享层需要更新时，由各团队先写各自 export，再通过 `refresh_context.py` 聚合。
4. preflight / sync
   如果任务需要 GitLab / ONES 事实，先用 `bootstrap_credentials_check.py` 判断是否具备条件，再按需运行 `sync_topology.py` / `sync_capability_status.py`。
5. audit
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
python3 skills/context-hub/scripts/refresh_context.py /tmp/context-hub-demo --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main
python3 skills/context-hub/scripts/bootstrap_credentials_check.py --check-ones
python3 skills/context-hub/scripts/sync_topology.py --hub /tmp/context-hub-demo
python3 skills/context-hub/scripts/sync_capability_status.py --hub /tmp/context-hub-demo --ones-team TEAM-UUID
python3 skills/context-hub/scripts/check_consistency.py --hub /tmp/context-hub-demo
python3 skills/context-hub/scripts/check_stale.py --hub /tmp/context-hub-demo
```

## 7. 当前明确未实现

以下内容不属于当前已交付能力：

- Figma / design 侧结构化同步
- 完整的角色化 workflow executor
- 默认无人值守完成所有 git add/commit/push
- 更细粒度的增量 webhook 编排和冲突自动处理
