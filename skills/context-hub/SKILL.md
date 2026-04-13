---
name: context-hub
description: |
  项目全局上下文管理。通过自然语言编排和本地脚本维护一个联邦式 context-hub，
  让 PM/设计/研发/QA 围绕共享上下文协作，但只维护各自有权限且允许共享的内容。
  触发词：创建 context-hub、初始化项目、新增能力、刷新共享上下文、同步 GitLab、同步 ONES、
  检查一致性、检查 stale、影响面分析、补充系统拓扑、补充测试来源。
---

## 触发条件

当用户请求涉及以下内容时自动激活：

- 初始化或维护项目 `context-hub`
- 新增 capability，或补充 `spec/design/architecture/testing`
- 刷新共享上下文、同步 GitLab / ONES 摘要、检查 stale、检查一致性
- 查询系统拓扑、测试来源、能力归属、影响面
- 询问当前 hub 是否缺材料、谁负责维护、是否可以继续协作

## 当前定位

这个 Skill 当前是 **Phase 2 orchestrator**，负责把自然语言请求映射到共享仓库读写、GitLab / ONES 摘要同步和本地脚本执行。

当前已经实现：

- 初始化联邦式 hub 骨架
- 创建 capability，并同步 `topology/domains.yaml` 与 `topology/ownership.yaml`
- 聚合团队 export 到共享 `topology/*` 和 `.context/llms.txt`
- 从 engineering repo 补全 `topology/system.yaml` 的自动字段
- 基于 `ones_tasks` 生成 capability `source-summary.yaml` 并回写状态
- 检查 GitLab / ONES 凭据是否可用于后续集成
- 运行一致性检查和 stale 审计
- 通过 `refresh_context.py` 统一编排，并支持可选 `auto-commit` / `auto-push`

当前没有实现：

- Figma / design 侧结构化同步
- 面向各角色的完整 workflow executor
- 默认无人值守完成所有 `git add/commit/push` 策略

如果任务需要上述能力，Skill 应明确说明它们属于后续阶段或环境集成工作，不要假装已经完成。

## 联邦维护模型

核心规则：

- 每个团队只维护自己有权限且允许共享的内容
- `context-hub` 只聚合共享导出结果，不越权抓取外部系统
- 共享层存摘要、索引、链接、freshness、ownership，不存敏感原文和凭据

当前阶段的团队边界：

- `product`：维护需求域和 capability 索引，可导出 `domains-fragment.yaml`
- `engineering`：维护服务与依赖摘要，可导出 `system-fragment.yaml`
- `qa`：维护测试来源摘要，可导出 `testing-fragment.yaml`
- `design`：已预留 `teams/design/exports/` 目录，后续阶段再扩展聚合规则

## 自然语言编排关系

当前阶段的工作关系如下：

1. 自然语言编排
   Skill 识别用户 intent，决定该读哪些共享文件、是否需要补问、是否需要运行本地脚本。
2. shared context
   共享上下文由 `IDENTITY.md`、`topology/*`、`capabilities/*`、`decisions/*`、`.context/llms.txt` 组成。
3. team exports
   各团队把允许共享的摘要写到 `teams/<team>/exports/*.yaml`，再由 `refresh_context.py` 聚合回共享层。
4. preflight
   `bootstrap_credentials_check.py` 只检查当前环境是否具备 GitLab / ONES 凭据，不做深度抓取。
5. sync + audit
   `sync_topology.py` 与 `sync_capability_status.py` 负责 GitLab / ONES 摘要同步，`check_consistency.py` 与 `check_stale.py` 在写入后验证契约完整性、归属关系、freshness 和阻塞项。

## 读取顺序

处理任务时优先按以下顺序读取：

1. `IDENTITY.md`
2. `topology/ownership.yaml`
3. `topology/domains.yaml`
4. `topology/system.yaml`
5. `topology/testing-sources.yaml`
6. `capabilities/<name>/`
7. `decisions/`
8. `.context/llms.txt`

## 权限降级规则

当共享上下文不足时：

- 先判断是否已经有对应 team export 或共享摘要
- 若没有，再判断是否只需要做 `bootstrap_credentials_check.py` 的 preflight
- 当前阶段不应声称已经完成 Figma 同步或完整角色 workflow
- 如果用户当前没有权限，明确指出缺的是哪类信息、通常由哪个团队维护、建议补哪个 export 或共享文档

## 写入目标

常见写入目标：

- 初始化 hub：`IDENTITY.md`、`topology/*`、`decisions/`、`capabilities/_templates/`、`.context/llms.txt`
- 新增 capability：`capabilities/<name>/`、`topology/domains.yaml`、`topology/ownership.yaml`
- 团队共享摘要：`teams/<team>/exports/*.yaml`
- 聚合刷新：`topology/domains.yaml`、`topology/system.yaml`、`topology/testing-sources.yaml`、`.context/llms.txt`
- ONES 摘要同步：`capabilities/<name>/source-summary.yaml`、`topology/domains.yaml`

## 写后动作

写入后至少执行最小校验：

- 修改 capability 或 topology：运行 `check_consistency.py`
- 修改 team export 或 freshness：运行 `refresh_context.py` 后再跑 `check_consistency.py` / `check_stale.py`
- 修改 `ones_tasks`：运行 `sync_capability_status.py` 或 `refresh_context.py --sync-ones`
- 如果用户明确要求 git 操作，再根据当前环境单独执行；不要默认宣称已经自动提交或推送

## 本地命令

在本仓库中可直接执行：

```bash
python3 skills/context-hub/scripts/init_context_hub.py --output /tmp/demo-hub --name "Demo" --id demo
python3 skills/context-hub/scripts/create_capability.py --hub /tmp/demo-hub --name voting --domain meeting --ones-task TASK-1
python3 skills/context-hub/scripts/refresh_context.py /tmp/demo-hub --sync-gitlab --sync-ones
python3 skills/context-hub/scripts/refresh_context.py /tmp/demo-hub --sync-gitlab --gitlab-url git@itgitlab.xylink.com:group/service.git --gitlab-branch main --gitlab-commit abc123
python3 skills/context-hub/scripts/bootstrap_credentials_check.py --check-ones
python3 skills/context-hub/scripts/sync_topology.py --hub /tmp/demo-hub
python3 skills/context-hub/scripts/sync_capability_status.py --hub /tmp/demo-hub --ones-team TEAM-UUID
python3 skills/context-hub/scripts/check_consistency.py --hub /tmp/demo-hub
python3 skills/context-hub/scripts/check_stale.py --hub /tmp/demo-hub
```

初始化后，生成的 hub 自带：

- `scripts/create_capability.py`
- `scripts/refresh_context.py`
- `scripts/sync_topology.py`
- `scripts/sync_capability_status.py`
- `scripts/bootstrap_credentials_check.py`
- `scripts/check_consistency.py`
- `scripts/check_stale.py`
- `scripts/runtime/`
- `scripts/integrations/`

## 使用原则

- 以共享上下文为默认事实来源
- 以 team export 为共享层更新入口
- 以 preflight 判断是否具备后续集成条件
- 以 sync + audit 保证仓库契约可持续维护
- webhook 增量同步只缩小 GitLab enrichment 的作用域，team export 聚合仍保持 hub-scoped
- GitLab webhook 增量模式要求 `repo URL + branch + commit SHA` 三元组；缺参或 changed-files 读取失败直接报错，信息性 skip 不单独升级成 warning
- 第一版 changed-files gate 只认依赖清单与 API 契约文件：`pyproject.toml`、`requirements.txt`、`package.json`、`pom.xml`、`build.gradle*`、`go.mod`、`*.proto`、`openapi.*`、`swagger.*`
