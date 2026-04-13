# Context Hub Federated Automation Design

> 日期：2026-04-13
> 状态：draft
> 主题：将 `context-hub` 从本地脚手架升级为面向多团队、按权限边界联邦维护、支持自然语言编排和持续自动化同步的共享上下文仓库。

## 1. 背景

当前 `context-hub` 已具备以下基础能力：

- 初始化一个新的 hub 骨架
- 创建 capability 目录
- 刷新 `.context/llms.txt`
- 运行最小一致性检查

但它还不能满足以下目标：

- 团队所有成员都能通过自然语言在同一个共享 hub 中开展工作
- 不同岗位按自己的权限边界获取和维护上下文
- GitLab / ONES / Figma 等外部系统持续向 hub 输送最新事实
- 当个人没有源码仓库权限时，依然能依赖 hub 中的共享摘要开展工作

用户已确认新的核心约束：

- 不同角色拥有不同权限，不能假设产品、设计、QA 都能直接访问研发仓库
- 不引入一个拥有全局超集权限的中心账号
- 每个团队只自动维护自己有权限、且允许共享的上下文
- `context-hub` 负责聚合、标准化和分发共享上下文，不负责越权抓取

## 2. 目标与非目标

### 2.1 目标

1. 通过一个共享的 `context-hub` 让 PM、设计、研发、QA、TL/Manager 都能用自然语言开展工作。
2. 让各团队基于自己的权限边界持续维护可共享的上下文导出结果。
3. 让 `context-hub` 自动聚合这些导出结果，生成统一可消费的项目上下文。
4. 让外部系统故障、权限不足或部分数据缺失时，工作流可以降级而不是整体失效。
5. 让仓库内的文档契约、拓扑索引、能力目录和 AI 发现入口保持一致。

### 2.2 非目标

1. 不将 `context-hub` 变成知识库平台、数据库或 Web Portal。
2. 不在 hub 中存储源码副本、敏感配置或明文凭据。
3. 不要求所有角色都直接访问所有外部系统。
4. 不在第一阶段实现重型 Figma 深度同步；第一阶段先做稳定引用与索引。

## 3. 核心设计原则

1. `联邦维护，统一消费`
   各团队各自维护自己有权限的共享上下文导出，`context-hub` 只做聚合。

2. `共享摘要优先于实时直连`
   非必要情况下，优先消费 hub 中已同步的共享摘要；只有确实需要且当前执行者有权限时，才下钻到外部系统。

3. `自然语言是入口，runtime 是执行面`
   `SKILL.md` 负责自然语言编排；`scripts/` 负责稳定、可测试、可在 CI 中运行的自动化执行。

4. `权限不足时降级，不中断`
   如果当前用户无权限访问某个仓库或系统，则回退到 hub 中的共享上下文，并明确标注缺失部分。

5. `写入必须可验证`
   任何落盘动作至少触发最小校验；自动同步任务必须支持 `dry-run`。

## 4. 架构分层

### 4.1 Interaction Orchestrator

位于 `skills/context-hub/SKILL.md`，负责：

- 识别用户 intent
- 决定读取哪些 hub 文件
- 判断是否需要访问 GitLab / ONES / Figma
- 发现信息缺失时只追问当前动作所需的最少问题
- 决定写入哪些文件
- 写入后触发最小校验和必要的自动提交

### 4.2 Hub Runtime

位于 `skills/context-hub/scripts/runtime/` 和 `skills/context-hub/scripts/workflows/`，负责：

- hub 初始化
- capability 生命周期操作
- 上下文刷新
- 聚合导出结果
- 提交与推送
- 校验与 stale 审计

### 4.3 Integration Adapters

位于 `skills/context-hub/scripts/integrations/`，负责：

- 复用 `gitlab` skill 的实例识别和 Token 约定
- 复用 `ones` skill 的凭据和安全约束
- 预留 `figma_adapter.py`
- 对话期和自动运行期共享同一套凭据发现逻辑

### 4.4 Repository Contract

hub 仓库对外暴露的统一契约：

- `IDENTITY.md`
- `topology/system.yaml`
- `topology/domains.yaml`
- `topology/testing-sources.yaml`
- `topology/ownership.yaml`
- `capabilities/<name>/spec.md`
- `capabilities/<name>/design.md`
- `capabilities/<name>/architecture.md`
- `capabilities/<name>/testing.md`
- `decisions/*.md`
- `.context/llms.txt`

### 4.5 Automation Loops

系统包含两条闭环：

1. `对话闭环`
   自然语言触发 -> 读取共享上下文 -> 读取实时事实 -> 生成或更新文件 -> 最小校验 -> commit/push

2. `持续维护闭环`
   团队级同步任务 -> 写入 `teams/<team-id>/exports/` -> 聚合脚本刷新 `topology/*` 和 `.context/llms.txt` -> 审计 -> commit/push

## 5. 联邦权限模型

### 5.1 三层权限面

1. `共享层`
   所有团队成员可见的 hub 内容。这里不存敏感事实原文，只存可共享摘要、索引、链接、影响面和新鲜度。

2. `实时事实层`
   GitLab / ONES / Figma 等外部系统的实时信息。访问严格受当前执行者权限约束。

3. `团队维护层`
   各团队自己的同步任务和导出逻辑，只同步本团队有权限且允许共享的内容。

### 5.2 团队维护边界

示例职责划分：

- `product` 团队：维护需求来源、验收条件、里程碑、ONES 工作项摘要
- `design` 团队：维护 Figma 页面索引、状态矩阵摘要、设计约束摘要
- `engineering` 团队：维护服务拓扑、接口契约摘要、依赖关系、实现约束
- `qa` 团队：维护测试资产索引、环境依赖、回归面、自动化仓库摘要

### 5.3 结果聚合规则

`context-hub` 聚合的是“共享导出结果”，不是直接从每个源系统无差别读取所有信息。

每份导出结果必须至少携带：

- `maintained_by`
- `source_system`
- `source_ref`
- `visibility`
- `last_synced_at`
- `confidence`

## 6. 仓库结构变更

目标结构：

```text
context-hub/
├── IDENTITY.md
├── topology/
│   ├── system.yaml
│   ├── domains.yaml
│   ├── testing-sources.yaml
│   └── ownership.yaml
├── capabilities/
│   ├── _templates/
│   └── <capability>/
├── decisions/
├── teams/
│   ├── product/
│   │   └── exports/
│   ├── design/
│   │   └── exports/
│   ├── engineering/
│   │   └── exports/
│   └── qa/
│       └── exports/
├── .context/
│   └── llms.txt
└── scripts/
    ├── runtime/
    ├── integrations/
    ├── workflows/
    ├── init_context_hub.py
    ├── refresh_context.py
    ├── sync_topology.py
    ├── sync_capability_status.py
    ├── update_llms_txt.py
    ├── check_consistency.py
    └── check_stale.py
```

## 7. 自然语言触发面

### 7.1 初始化与维护

典型 intent：

- 初始化项目 hub
- 补全团队维护边界
- 同步最新拓扑
- 刷新共享上下文
- 检查 hub 是否 stale 或不一致

### 7.2 能力工作流

典型 intent：

- 新增 capability
- 写 spec
- 梳理设计状态
- 写技术方案
- 写测试策略
- 做影响面分析

### 7.3 查询与审计

典型 intent：

- 某个功能依赖哪些服务
- 某个服务影响哪些能力
- 哪些 capability 缺少上下游材料
- 哪些团队导出的共享摘要已经过期

### 7.4 权限降级规则

当当前用户对外部系统无权限时：

1. 优先回答 hub 中已有的共享摘要。
2. 若共享摘要不足，则指出：
   - 缺失的是哪类信息
   - 由哪个团队维护
   - 当前用户是否需要请求同步或补录
3. 不因为单个源系统不可读而中断整个工作流。

## 8. 各岗位闭环工作流

### 8.1 PM

读取：

- `IDENTITY.md`
- `topology/domains.yaml`
- capability 现有文档
- 必要的 ONES 摘要

写入：

- `capabilities/<name>/spec.md`
- 必要时更新 capability 索引

### 8.2 设计

读取：

- `spec.md`
- `decisions/`
- 设计索引导出
- 必要的 Figma 链接

写入：

- `design.md`

### 8.3 研发

读取：

- `spec.md`
- `design.md`
- `topology/system.yaml`
- `decisions/`
- 当前用户有权限时的 GitLab 实时代码

写入：

- `architecture.md`
- 必要时新增 `decisions/NNN-*.md`

### 8.4 QA

读取：

- `spec.md`
- `design.md`
- `architecture.md`
- `topology/testing-sources.yaml`
- ONES 测试资产摘要

写入：

- `testing.md`

### 8.5 TL / Manager / Ops

重点走查询与审计入口：

- 当前能力是否具备开工条件
- 哪些域缺上下文
- 哪些服务变化影响当前迭代
- 哪些共享摘要过期

## 9. 集成与凭据复用

### 9.1 GitLab

复用 `gitlab` skill 已定义的：

- 实例注册表
- URL 到实例的映射规则
- Token 环境变量约定

对话期：

- `context-hub` 作为上层 orchestrator，按需调用 GitLab 读取事实

自动运行期：

- `sync_topology.py` 等脚本直接读取同一套环境变量完成扫描和同步

### 9.2 ONES

复用 `ones` skill 已定义的：

- `ONES_TOKEN`
- `ONES_USER_UUID`
- `ONES_TEAM_UUID`
- 不打印、不回显、不落盘凭据的安全规则

### 9.3 Figma

第一阶段只要求：

- 记录团队链接、文件链接、页面链接、节点链接
- 在 `design.md` 和导出索引中建立稳定引用

第二阶段再考虑深度 adapter。

## 10. 脚本重构方案

### 10.1 保留并升级

- `init_context_hub.py`
- `sync_topology.py`
- `update_llms_txt.py`
- `check_consistency.py`
- `check_stale.py`

### 10.2 新增

- `scripts/runtime/hub_paths.py`
- `scripts/runtime/hub_io.py`
- `scripts/runtime/commit_ops.py`
- `scripts/runtime/capability_ops.py`
- `scripts/runtime/validation.py`
- `scripts/integrations/credentials.py`
- `scripts/integrations/gitlab_adapter.py`
- `scripts/integrations/ones_adapter.py`
- `scripts/workflows/pm_workflow.py`
- `scripts/workflows/design_workflow.py`
- `scripts/workflows/engineering_workflow.py`
- `scripts/workflows/qa_workflow.py`
- `scripts/workflows/maintenance_workflow.py`
- `scripts/refresh_context.py`
- `scripts/sync_capability_status.py`
- `scripts/bootstrap_credentials_check.py`

## 11. 模板与契约文件

新增模板建议：

- `templates/identity.md`
- `templates/system.yaml`
- `templates/domains.yaml`
- `templates/testing-sources.yaml`
- `templates/ownership.yaml`
- `templates/llms.txt`
- `templates/role-intake/pm.md`
- `templates/role-intake/design.md`
- `templates/role-intake/engineering.md`
- `templates/role-intake/qa.md`

## 12. 验证体系

### 12.1 Contract Validation

检查：

- hub 基础结构是否齐全
- YAML / Markdown 契约是否合法
- capability 索引是否完整
- 交叉引用是否完整
- `.context/llms.txt` 是否与聚合结果同步

### 12.2 Workflow Validation

最小 smoke test 覆盖：

- 初始化 hub
- 创建 capability
- 刷新 context
- 聚合团队导出

### 12.3 Integration Validation

Adapter 只做：

- 实例解析
- 凭据存在检查
- 最小连通性检查
- 只读查询预检

### 12.4 Role Acceptance Validation

固定验收场景：

- PM：新增投票功能
- 设计：梳理投票面板状态
- 研发：做投票技术方案
- QA：设计测试方案

只要这些场景不能稳定读写到正确文件，就不能认定系统达标。

## 13. 失败处理

### 13.1 缺凭据

- 只提示缺少的变量名
- 降级为只读 hub 或草稿生成

### 13.2 外部系统不可达

- 继续使用 hub 已有共享上下文
- 明确标记未实时验证的事实

### 13.3 信息不足

- 只追问完成当前动作所需的最少问题

### 13.4 写入失败

- 先生成临时结果，再原子替换
- `auto-commit` 失败时保留工作树供人工处理

### 13.5 自动同步冲突

- 保留人工维护字段
- 自动字段重新生成
- 将冲突写入审计结果

## 14. 分阶段交付

### Phase 1: Orchestrator + Runtime 基线

交付：

- 重写 `SKILL.md`
- 引入 runtime / integrations / workflows 目录
- 打通初始化、capability 创建、`llms.txt` 刷新、一致性检查
- 建立统一凭据发现与 `dry-run` 机制

### Phase 2: GitLab / ONES 真集成

交付：

- 完成 `sync_topology.py`
- 完成 ONES 摘要同步
- 完成 `refresh_context.py`
- 完成 CI / cron 持续维护闭环

### Phase 3: 联邦维护与角色闭环验收

交付：

- `teams/<team-id>/exports/` 联邦维护机制
- 聚合逻辑与 freshness 标记
- PM / 设计 / 研发 / QA 的自然语言闭环验收
- “谁被什么缺口阻塞”的团队开工性判断

## 15. 达标标准

只有同时满足以下条件，才可以宣称 `context-hub` 达到目标：

1. 能初始化一个团队共用的 hub。
2. 能基于团队权限边界持续自动维护共享上下文。
3. 各岗位能通过自然语言稳定完成主要工作物料。
4. 权限不足或源系统异常时，工作流能降级而不是瘫痪。
5. hub 中的共享内容足以让无源码权限的角色继续推进工作。

## 16. 当前实现约束

在本次设计落地时，需要明确以下现实约束：

1. 当前仓库不是 git repo，因此本阶段无法完成“写 spec 并提交 commit”的要求，只能先落盘文档。
2. 当前 `sync_topology.py` 仍处于半成品状态，后续实现必须先补齐 GitLab adapter 和自动字段扫描。
3. `yaml_compat.py` 当前无 `PyYAML` 时只兼容 JSON 子集，后续若要长期承载真实 YAML，需要补强解析兼容性。
