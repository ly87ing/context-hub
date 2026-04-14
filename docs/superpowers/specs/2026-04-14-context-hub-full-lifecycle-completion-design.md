# Context Hub Full Lifecycle Completion Design

> 日期：2026-04-14
> 状态：draft
> 主题：在当前 `context-hub` Phase 2 baseline 基础上，补齐完整产品研发周期所需的 capability control plane、语义一致性、design 结构化同步、自动流转与安全自动化。

## 1. 背景

当前 `context-hub` 已经具备以下可运行能力：

- 初始化联邦式 hub 骨架
- 创建 capability 并维护 `domains.yaml` / `ownership.yaml`
- 聚合 engineering / qa team export 到共享 `topology/*`
- 基于 GitLab 刷新 `system.yaml`
- 基于 ONES 刷新 capability `source-summary.yaml`
- PM / Design / Engineering / QA / maintenance role workflow v1
- PM 写 `spec.md` 后自动刷新 `downstream-checklist.yaml`
- PM 写 `spec.md` 后自动刷新 capability `iteration-index.yaml`
- 一致性检查、stale 审计与最小 `refresh_context.py` 编排

这让 `context-hub` 从“共享文档仓库”进入了“可被 AI 驱动的 capability 工作平台”阶段，但离“团队可以低摩擦地维护完整产品研发周期”还差几个关键闭环：

- design 侧仍然没有稳定的结构化共享摘要
- maintenance 只能报问题，不能给出可执行修复建议
- consistency 仍然以结构和 freshness 为主，缺少跨文档语义检查
- workflow 之间还没有统一的 lifecycle state 和自动流转
- iteration / release 目前只存在 capability 局部索引，没有全局视图
- git / webhook / scheduler 自动化仍停留在最小安全基线

## 2. 目标与非目标

### 2.1 目标

1. 让 AI 可以稳定判断一个 capability 当前处于哪个 lifecycle 阶段、缺什么、下一个该谁做。
2. 让 PM / Design / Engineering / QA 的输出在 capability 内形成共享 control plane，而不是靠人工阅读多个 Markdown 猜状态。
3. 让 maintenance 不只指出问题，还能输出具体 remediation 建议。
4. 让 `spec.md`、`design.md`、`architecture.md`、`testing.md` 与 `topology/*`、`source-summary.yaml` 之间具备最小语义一致性审计能力。
5. 让 design 侧拥有和 engineering / qa 对称的共享导出与聚合链路。
6. 让定时同步、webhook、auto-commit / auto-push 与审计阻断形成可控自动化。

### 2.2 非目标

1. 不把 `context-hub` 做成 Web Portal 或数据库。
2. 不在 hub 中保存 Figma 原始文件、源码副本或敏感配置。
3. 不引入全局超集权限账号。
4. 不在第一版完整实现 NLP 级“强语义理解”；语义一致性先做规则驱动和共享信号驱动。

## 3. 核心原则

1. `共享控制面优先`
   生命周期状态、iteration/release、semantic drift、downstream gap 都应落成明确 contract，而不是散落在脚本返回值里。

2. `角色职责不变，系统编排增强`
   PM 仍写 `spec.md`，Design 仍写 `design.md`，Engineering 仍写 `architecture.md`，QA 仍写 `testing.md`；平台只增加状态与审计层。

3. `先 deterministic，再智能建议`
   先把 state、index、audit、repair suggestion 变成确定性规则，再逐步增加更强的 AI 推断。

4. `自动化必须 fail closed`
   任意自动提交、自动推送、自动流转都必须先通过 validation / stale / semantic consistency。

## 4. 目标架构

### 4.1 Capability Control Plane

每个 capability 最终维护以下稳定控制面：

- `spec.md`
- `design.md`
- `architecture.md`
- `testing.md`
- `source-summary.yaml`
- `downstream-checklist.yaml`
- `iteration-index.yaml`
- `lifecycle-state.yaml`
- `semantic-consistency.yaml`

其中：

- `downstream-checklist.yaml` 表示 spec 变更后哪些 downstream 角色仍需跟进
- `iteration-index.yaml` 表示当前 capability 所处 iteration / release 以及变更累计次数
- `lifecycle-state.yaml` 表示每个角色当前状态、阻塞原因、下一步动作
- `semantic-consistency.yaml` 表示最近一次跨文档语义审计结果

### 4.2 Topology Control Plane

全局共享层新增以下视图：

- `topology/design-sources.yaml`
- `topology/releases.yaml`

含义：

- `design-sources.yaml` 聚合 design team 的共享导出结果与 Figma 引用摘要
- `releases.yaml` 聚合所有 capability 的当前 iteration / release 状态，用于全局查询与自动流转

### 4.3 Runtime Layer

在 `skills/context-hub/scripts/runtime/` 下新增四个核心模块：

- `lifecycle_state.py`
- `release_index.py`
- `semantic_consistency.py`
- `maintenance_advice.py`

职责如下：

- `lifecycle_state.py`
  - 根据 capability 主文档存在性、mtime、downstream checklist、semantic audit 结果和 source summary 推导各角色状态
- `release_index.py`
  - 从 capability `iteration-index.yaml` 聚合生成全局 `topology/releases.yaml`
- `semantic_consistency.py`
  - 以规则驱动方式检查 `spec/design/architecture/testing/source-summary/system/testing-sources` 之间的冲突
- `maintenance_advice.py`
  - 将结构缺口、freshness 问题、semantic drift 转换成面向 role 的修复建议

### 4.4 Workflow Layer

角色 workflow 的升级方向：

- `pm_workflow.py`
  - 写 `spec.md`
  - 刷新 `downstream-checklist.yaml`
  - 刷新 `iteration-index.yaml`
  - 更新 `lifecycle-state.yaml`
- `design_workflow.py`
  - 写 `design.md`
  - 更新 `lifecycle-state.yaml`
- `engineering_workflow.py`
  - 写 `architecture.md`
  - 更新 `lifecycle-state.yaml`
- `qa_workflow.py`
  - 写 `testing.md`
  - 更新 `lifecycle-state.yaml`
- `maintenance_workflow.py`
  - 读取 `lifecycle-state.yaml`、`semantic-consistency.yaml`
  - 返回 `pending_roles`、`blocking_issues`、`suggested_repairs`

### 4.5 Team Export / Sync Layer

需要补齐 design 侧的共享导出与同步链路：

- `teams/design/exports/design-fragment.yaml`
- `sync_design_context.py`
- `integrations/figma_adapter.py` 扩展为：
  - file / page / node 引用解析
  - 最小结构化 probe
  - 可选的 frame / flow 摘要

其目标不是复制 Figma，而是抽取共享约束：

- 设计文件引用
- 页面 / flow 索引
- 关键状态集合
- 节点引用和更新时间

### 4.6 Automation Layer

`refresh_context.py` 最终将编排以下动作：

1. 聚合 team exports
2. 可选 GitLab sync
3. 可选 ONES sync
4. 可选 design sync
5. 刷新 `topology/releases.yaml`
6. 运行 `check_consistency.py`
7. 运行 `check_stale.py`
8. 运行 `check_semantic_consistency.py`
9. 仅在全部通过时执行 auto-commit / auto-push

CI / scheduler / webhook 目标是把这条链路自动化，但仍保持本地脚本为唯一执行面。

## 5. 生命周期状态机

每个 capability 在每个角色下统一使用以下状态：

- `missing`
- `draft`
- `aligned`
- `needs_align`
- `blocked`

状态推导示例：

- 主文档不存在：`missing`
- 文档存在，但从未跟进当前 spec 变更：`needs_align`
- 文档存在，且在当前 checklist 之后更新：`aligned`
- semantic consistency 报 blocker：`blocked`
- capability 刚创建但尚未完成最小内容：`draft`

全 capability 级别还维护一个汇总状态：

- `bootstrapping`
- `in_progress`
- `ready_for_review`
- `blocked`
- `released`

这个汇总状态不替代 `domains.yaml` 中的业务状态，而是平台状态。

## 6. 语义一致性模型

首版 semantic consistency 使用确定性规则，不依赖大模型自由发挥。

### 6.1 检查来源

- `spec.md`
- `design.md`
- `architecture.md`
- `testing.md`
- `source-summary.yaml`
- `topology/system.yaml`
- `topology/testing-sources.yaml`
- 可选 design shared summary

### 6.2 典型规则

- `spec.md` 声称 capability 已上线，但 `source-summary.yaml` 仍显示 planned
- `design.md` 提及关键状态，但 `testing.md` 未覆盖
- `architecture.md` 声称依赖某服务，但 `system.yaml` 中不存在
- `testing.md` 引用某环境或来源，但 `testing-sources.yaml` 未登记
- `spec.md` 引入新的 iteration / release，但 capability 当前 `iteration-index.yaml` 未更新

### 6.3 输出契约

`semantic-consistency.yaml` 至少包含：

- `capability`
- `audited_at`
- `status`
- `issues`
- `blocking_issue_count`
- `warning_issue_count`

每条 issue 至少包含：

- `severity`
- `rule_id`
- `message`
- `source_files`
- `suggested_role`

## 7. Maintenance Remediation 模型

maintenance workflow 升级后的返回结构应包含：

- `pending_roles`
- `blocking_issues`
- `suggested_repairs`
- `next_role`
- `next_action`

`suggested_repairs` 不是直接改文档，而是输出面向某角色的修复建议，例如：

- `design` 应补“投票进行中/已结束”状态矩阵
- `engineering` 应确认 `vote-service` 是否真实存在于 `system.yaml`
- `qa` 应补与新状态相关的回归点

## 8. 阶段拆分

### Phase 3A: Lifecycle Control Plane

- `lifecycle-state.yaml`
- `topology/releases.yaml`
- workflow 写后自动刷新 lifecycle / release index
- maintenance 改为基于 lifecycle state 决策

### Phase 3B: Maintenance Remediation

- `maintenance_advice.py`
- maintenance 返回修复建议
- 将结构缺口与 freshness 问题标准化成 remediation item

### Phase 3C: Semantic Consistency

- `semantic-consistency.yaml`
- `check_semantic_consistency.py`
- refresh / maintenance 接入 semantic audit

### Phase 3D: Design Structured Sync

- `teams/design/exports/design-fragment.yaml`
- `topology/design-sources.yaml`
- `sync_design_context.py`
- 扩展 `figma_adapter.py`

### Phase 3E: Safe Automation

- 定时同步 / webhook 统一入口
- `auto-commit` / `auto-push` 只在全部审计通过时执行
- 引入更细粒度的 skip / block / repair reason

## 9. 验收标准

只有同时满足以下条件，才可以宣称“完整产品研发周期维护闭环已达成”：

1. 任一 capability 都能回答：
   - 当前 iteration / release 是什么
   - 哪个角色还没跟进
   - 是否存在 blocker
   - 下一步该谁做
2. maintenance 能输出明确 remediation 建议，而不是只报缺文件
3. semantic consistency 能稳定抓到跨角色文档的关键冲突
4. design 侧有稳定共享导出与聚合契约
5. `refresh_context.py` 可以编排 GitLab / ONES / design sync、release index、semantic audit 和安全自动提交
6. 所有新增 contract 都纳入 init、consistency、stale、workflow 与 smoke 测试
