# Context Hub Role Workflow Platform Design

> 日期：2026-04-14
> 状态：draft
> 主题：在现有 `context-hub` 联邦共享上下文基线之上，补齐 PM、UX、研发、QA 四条角色工作流，让团队成员可以通过自然语言稳定完成主工作物料的创建、补充、修订与对齐。

## 1. 背景

当前 `context-hub` 已经具备以下基础能力：

- 初始化一个联邦共享 hub
- 创建 capability 目录和基础文档
- 聚合 team exports 到 `topology/*`
- 基于 GitLab 刷新工程服务拓扑摘要
- 基于 ONES 刷新 capability 状态摘要
- 刷新 `.context/llms.txt`
- 执行一致性检查与 stale 审计

但它仍停留在“共享上下文仓库 + 脚本基线”阶段，尚未完成以下关键目标：

- PM、UX、研发、QA 能围绕同一个 capability 通过自然语言稳定工作
- 系统能自动判断当前应走哪条角色工作流，也允许用户显式指定角色
- 默认优先读取真实外部系统事实，但在权限不足或系统异常时能回退到 hub 摘要继续推进
- 各角色的输出最终稳定回写到现有 contract，而不是散落在新的临时文件结构里

用户已确认本次设计的关键约束：

1. 平台仍以 `context-hub` 仓库、本地脚本和自然语言编排为核心，不引入 Web Portal 作为必要前提。
2. 首版先补齐 PM、UX、研发、QA 四条 role workflow skeleton，不要求立刻做完整串行流水线。
3. 自然语言入口采用“混合模式”：
   - 默认自动判断角色
   - 允许用户显式指定角色覆盖
4. 最终产物仍沿用现有 contract：
   - PM -> `spec.md`
   - UX -> `design.md`
   - 研发 -> `architecture.md`
   - QA -> `testing.md`
5. 首版支持四类动作：
   - `create`
   - `extend`
   - `revise`
   - `align`
6. 默认走真实外部系统，但必须保留 hub fallback，而不是因为权限或外部系统故障整体失效。

## 2. 目标与非目标

### 2.1 目标

1. 补齐 PM、UX、研发、QA 四条角色工作流，使其都能通过自然语言稳定工作。
2. 支持混合入口：自动识别角色，也支持显式指定角色。
3. 让每条工作流都能对主工作物料执行 `create / extend / revise / align`。
4. 默认优先读取 ONES、GitLab、Figma 等真实系统事实。
5. 在权限不足、外部系统不可达或信息不完整时，优先回退到 hub 摘要继续产出可用结果。
6. 保持最终落盘面稳定，复用现有 `capabilities/*`、`topology/*`、`.context/llms.txt`、校验和审计链路。

### 2.2 非目标

1. 本次不引入新的 Web UI 或 Portal。
2. 本次不重做 capability 文档结构，不引入第二套主文档契约。
3. 本次不要求四个角色在单一 capability 上立即形成完整串行状态机。
4. 本次不把 `context-hub` 变成知识库平台、数据库或源码镜像。
5. 本次不在第一版实现重型 Figma 深度同步；第一版只做引用、链接和最小可达性能力。

## 3. 首版范围

首版平台能力定义如下：

- 角色范围：PM、UX、研发、QA
- 入口模式：混合入口
- 工作模式：默认 `fully-live`，但允许 fallback
- 文档范围：
  - `capabilities/<name>/spec.md`
  - `capabilities/<name>/design.md`
  - `capabilities/<name>/architecture.md`
  - `capabilities/<name>/testing.md`
- 索引范围：
  - `topology/domains.yaml`
  - `topology/system.yaml`
  - `topology/testing-sources.yaml`
  - `decisions/*.md`

### 3.1 动作模型

首版统一只支持四类动作：

- `create`
  - 当前角色主文档不存在或内容极少，需要初始化成可工作的第一版
- `extend`
  - 在保留现有结构的前提下补充信息
- `revise`
  - 根据新事实修订已有内容
- `align`
  - 对齐 hub 文档与外部系统或上下游文档的差异

所有角色 workflow 都必须接受同一套动作语义，以便自然语言入口和脚本执行面统一。

## 4. 核心设计原则

1. `角色入口统一，执行面分层`
   `SKILL.md` 负责自然语言路由，`scripts/workflows/*` 负责稳定执行，最终统一回写现有 contract。

2. `最终落盘面保持稳定`
   不新增第二套业务主文档结构，避免破坏现有 `llms.txt`、consistency、stale 与 topology 链路。

3. `实时事实优先，hub fallback 兜底`
   默认优先读取真实外部系统；失败时退回 hub 已同步摘要；如果连 hub 也不足，则明确 `blocked`。

4. `最小补问`
   只追问完成当前动作所需的最少问题，不做泛化访谈。

5. `跨角色只指出缺口，不越权改写`
   允许工作流识别上下游缺口，但不直接改动其他角色的主文档。

6. `写入必须可验证`
   每次写入后至少触发最小校验；只有通过最小校验后才能宣称本次写入成功。

## 5. 平台架构

### 5.1 Interaction Orchestrator

位于 `skills/context-hub/SKILL.md`，负责：

- 识别用户 intent
- 判断目标 role
- 判断动作类型
- 定位目标 capability
- 决定是否需要访问 ONES / GitLab / Figma
- 在必要时补最少问题
- 调度对应 workflow
- 写后触发最小校验与必要的共享层刷新

### 5.2 Role Workflow Layer

新增：

- `scripts/workflows/pm_workflow.py`
- `scripts/workflows/design_workflow.py`
- `scripts/workflows/engineering_workflow.py`
- `scripts/workflows/qa_workflow.py`
- `scripts/workflows/maintenance_workflow.py`
- `scripts/workflows/common.py`

职责：

- 收集 role 所需上下文
- 拉取 role 所需实时事实
- 构造统一工作上下文
- 生成或修订目标文档
- 输出统一结构化结果

### 5.3 Integration Layer

位于 `scripts/integrations/`，负责：

- ONES 事实读取
- GitLab 事实读取
- Figma 引用与最小可达性读取
- 凭据发现与安全规则复用

新增：

- `scripts/integrations/figma_adapter.py`

### 5.4 Runtime Layer

位于 `scripts/runtime/`，负责：

- capability 定位
- 路径解析
- 原子写入
- 共享 helper
- precondition / post-write validation

### 5.5 Contract Layer

最终对外暴露的稳定 contract 保持为：

- `IDENTITY.md`
- `topology/*`
- `capabilities/<name>/{spec,design,architecture,testing}.md`
- `decisions/*.md`
- `.context/llms.txt`

新增的 role workflow 只是一层执行面，不是新的业务主文档体系。

## 6. 文件与目录结构

### 6.1 新增

- `skills/context-hub/scripts/workflows/__init__.py`
- `skills/context-hub/scripts/workflows/common.py`
- `skills/context-hub/scripts/workflows/pm_workflow.py`
- `skills/context-hub/scripts/workflows/design_workflow.py`
- `skills/context-hub/scripts/workflows/engineering_workflow.py`
- `skills/context-hub/scripts/workflows/qa_workflow.py`
- `skills/context-hub/scripts/workflows/maintenance_workflow.py`
- `skills/context-hub/scripts/integrations/figma_adapter.py`
- `skills/context-hub/templates/role-intake/pm.md`
- `skills/context-hub/templates/role-intake/design.md`
- `skills/context-hub/templates/role-intake/engineering.md`
- `skills/context-hub/templates/role-intake/qa.md`

### 6.2 修改

- `skills/context-hub/SKILL.md`
- `skills/context-hub/scripts/init_context_hub.py`
- `skills/context-hub/scripts/runtime/hub_paths.py`
- `skills/context-hub/scripts/runtime/capability_ops.py`
- `skills/context-hub/scripts/runtime/validation.py`
- `skills/context-hub/scripts/check_consistency.py`
- `README.md`
- `docs/context-hub-specification.md`

### 6.3 职责边界

- `SKILL.md`
  - 只做自然语言层路由和补问
- `workflows/*.py`
  - 只做角色级执行
- `integrations/*.py`
  - 只做外部系统读取，不直接写 hub 文档
- `runtime/*.py`
  - 只做路径、IO、校验、公共 helper

## 7. 角色工作流

### 7.1 PM Workflow

读取：

- `IDENTITY.md`
- `topology/domains.yaml`
- capability 现有 `spec.md`
- 必要的 ONES 摘要

写入：

- `capabilities/<name>/spec.md`
- 必要时更新 capability 索引

典型动作：

- 新建需求说明
- 补充业务规则
- 修订范围、目标和验收条件
- 对齐 ONES 与本地 spec 的差异

fallback：

- ONES 不可达或无权限时，允许基于 hub 现有 `spec.md`、`domains.yaml` 与本地共享摘要继续修订，但必须标记“未实时校验”

### 7.2 UX Workflow

读取：

- `spec.md`
- `decisions/*.md`
- 现有 `design.md`
- Figma 链接、页面引用、节点引用

写入：

- `capabilities/<name>/design.md`

典型动作：

- 新建设计说明
- 补充状态、交互、边界条件
- 修订与 spec 的不一致处
- 对齐 Figma 引用与设计文档

fallback：

- Figma 不可达时，仍允许基于 `design.md + spec.md + Figma 链接引用` 工作，而不是整体失败

说明：

- 首版平台层面统一使用 `design_workflow.py`
- 自然语言入口接受 `UX`、`设计` 两种角色别名

### 7.3 Engineering Workflow

读取：

- `spec.md`
- `design.md`
- `architecture.md`
- `topology/system.yaml`
- `decisions/*.md`
- 当前执行者有权限时的 GitLab 实时代码或仓库结构摘要

写入：

- `capabilities/<name>/architecture.md`
- 必要时新增或修订 `decisions/*.md`

典型动作：

- 新建技术方案
- 补充服务影响面、依赖、接口、实现约束
- 修订方案与真实代码现状的偏差
- 对齐 design/spec 与实现边界

fallback：

- 无 GitLab 权限时，基于 `topology/system.yaml`、历史 `architecture.md`、共享摘要继续出方案，但标记“未实时核对代码”

### 7.4 QA Workflow

读取：

- `spec.md`
- `design.md`
- `architecture.md`
- `testing.md`
- `topology/testing-sources.yaml`
- 必要的 ONES 测试任务或回归摘要

写入：

- `capabilities/<name>/testing.md`

典型动作：

- 新建测试方案
- 补充测试范围、风险、回归面、环境依赖
- 修订与研发方案或设计变更不一致的测试点
- 对齐 ONES 测试任务与本地测试文档

fallback：

- ONES 或测试平台不可达时，仍能基于现有 `testing.md` 与共享测试索引继续工作

### 7.5 统一边界规则

- PM 不直接写 `design.md` / `architecture.md` / `testing.md`
- UX 不直接改 `spec.md`
- 研发不直接改 `testing.md`
- QA 不直接改 `architecture.md`
- 允许指出跨角色缺口，但真正改动交给对应 role workflow 落盘

## 8. 混合入口与补问策略

### 8.1 角色识别优先级

1. 用户显式指定角色
2. 根据目标文档和动作词推断
3. 根据当前 capability 缺口推断

映射建议：

- `spec / 需求 / 范围 / 验收` -> PM
- `设计 / 交互 / 状态 / 页面 / Figma / UX` -> UX
- `架构 / 技术方案 / 依赖 / 服务 / 实现 / GitLab` -> 研发
- `测试 / 用例 / 回归 / 风险 / 覆盖 / QA` -> QA

### 8.2 动作识别

自然语言入口最终统一解析为：

- `role`
- `action`
- `capability`
- `evidence_sources`

### 8.3 最小补问顺序

如果当前信息不足，按以下顺序补问：

1. 先确认 capability
2. 再确认 role
3. 再确认 action
4. 最后补缺失事实

规则：

- 每次只问完成当前动作必需的最少问题
- 不因“信息可能还不够完整”就展开泛化调查

## 9. 数据流与 fallback

### 9.1 标准执行流

每条 role workflow 都遵循同一条确定性数据流：

1. 定位 capability
2. 读取 hub 现状
3. 读取 role intake 模板
4. 拉取实时事实
5. 形成工作上下文
6. 生成或修订目标文档
7. 执行最小校验
8. 返回结构化结果

### 9.2 capability 定位

定位顺序：

1. `topology/domains.yaml` 精确匹配
2. `capabilities/*` 目录匹配
3. 仍不确定时，补一个澄清问题

规则：

- PM 可以触发“创建 capability + 初始化 `spec.md`”
- UX / 研发 / QA 默认不自动创建 capability，需已有 capability 或 PM 先建

### 9.3 实时系统读取顺序

最佳实践不是“一上来全查外部系统”，而是：

1. 先读 hub
2. 再根据动作决定是否必须实时读取
3. 只有当前动作真的需要时才查外部系统

示例：

- `extend spec` 不一定需要全量 ONES 事实
- `align spec with ONES` 必须查 ONES
- `revise architecture from current repo` 必须查 GitLab
- `align design with Figma` 才优先查 Figma

### 9.4 fallback 状态

每次外部读取统一返回三类状态：

- `live_ok`
- `fallback_to_hub`
- `blocked`

对应行为：

- `live_ok`
  - 正常生成结果
- `fallback_to_hub`
  - 继续生成，但在结果中写明“未实时核对”
- `blocked`
  - 不乱写文档，返回最小缺口说明和下一步建议

### 9.5 统一输出契约

每个 workflow 都应返回至少以下字段：

- `role`
- `action`
- `capability`
- `target_file`
- `used_sources`
- `live_status`
- `warnings`
- `updated_paths`

## 10. 写入与校验

### 10.1 写入规则

- 只覆盖目标角色自己的主文档
- 原子写入
- 不跨角色偷偷改别人的主文档

### 10.2 最小校验

首版每次写后至少执行：

- capability 文件存在性检查
- 文档非空检查
- capability 与 topology 引用一致性检查
- `.context/llms.txt` 是否需要刷新

### 10.3 刷新策略

- 如果 workflow 改动了索引或 capability 元数据：
  - 自动触发 `refresh_context.py` 或等价的最小共享层刷新
- 如果只是单文档修订：
  - 只跑最小 consistency 检查，不强制全量同步

## 11. 验收标准

只有同时满足以下条件，才可以宣称首版平台达标：

1. 混合入口可用
   - 用户可以显式说角色，也可以不说
   - 系统能稳定识别 `role + action`
   - 信息不足时只补最少问题

2. 四条 role workflow 都能稳定落盘
   - PM 能新建、补充、修订、对齐 `spec.md`
   - UX 能新建、补充、修订、对齐 `design.md`
   - 研发能新建、补充、修订、对齐 `architecture.md`
   - QA 能新建、补充、修订、对齐 `testing.md`

3. 默认走实时系统，但有可靠降级
   - GitLab / ONES / Figma 可用时优先读取实时事实
   - 无权限或系统异常时不直接瘫痪
   - 能 fallback 到 hub 共享摘要继续产出可用草稿
   - 如果 hub 也不足，则明确 `blocked`

4. 写后可验证
   - 每次写入后至少有最小校验
   - capability 与 topology 契约不被破坏
   - `.context/llms.txt` 刷新策略清晰

5. 固定验收场景可通过
   - PM：新增一个 capability 的需求说明
   - UX：补齐该 capability 的界面、状态与交互说明
   - 研发：结合 GitLab 现状产出技术方案
   - QA：结合 `spec/design/architecture` 产出测试方案

## 12. 分阶段实现顺序

### Phase A：Workflow Skeleton 与统一结果契约

交付：

- `scripts/workflows/*`
- `workflows/common.py`
- 统一输入输出契约
- 最小写入与校验接口

目标：

- 先把“能稳定读写正确文件”做实

### Phase B：四条 Role Workflow 最小可用

交付：

- PM -> `spec.md`
- UX -> `design.md`
- 研发 -> `architecture.md`
- QA -> `testing.md`

目标：

- 先保证四条路都通，再引入更复杂的实时判断

### Phase C：默认实时系统接入

交付：

- PM 接 ONES
- UX 接 Figma 轻量 adapter
- 研发接 GitLab
- QA 接 ONES + `testing-sources.yaml`
- 打通 `live_ok / fallback_to_hub / blocked`

### Phase D：混合入口自然语言编排

交付：

- `SKILL.md` 角色识别
- 动作识别
- 最小补问
- workflow 分发

## 13. 风险与约束

1. `fully-live` 默认模式会放大权限差异与外部系统稳定性问题，因此 fallback 设计不是附加项，而是主路径的一部分。
2. UX workflow 在首版不适合做重型 Figma 深度同步，应先把“稳定引用 + 对齐设计文档”做实。
3. 如果把角色逻辑直接堆进 `SKILL.md`，后续维护成本会快速失控，因此必须尽早抽离到 `scripts/workflows/*`。
4. 如果引入新的主文档结构，会直接破坏现有 consistency / stale / llms / topology 链路，因此首版必须坚持最终 contract 不变。

