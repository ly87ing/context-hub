# Context Hub

> 一个面向联邦协作的 AI Skill，用自然语言和本地脚本维护项目共享上下文仓库。

## 这是什么

`context-hub` 的目标不是替代 GitLab、ONES 或 Figma，而是把各团队愿意共享且有权限维护的上下文整理成一个可被 AI 和团队成员统一消费的 Git 仓库。

Phase 1 当前已实现的是一个可本地运行的基础闭环：

- 初始化联邦式 hub 骨架
- 创建 capability 目录并维护 domain / ownership 索引
- 聚合 team exports 到共享 `topology/*`
- 刷新 `.context/llms.txt`
- 做凭据 preflight、一致性检查和 stale 审计

还没有实现：

- 自动深度扫描代码仓库
- 自动同步 ONES/Figma 全量事实
- 默认自动完成所有 git 提交和推送

## 联邦维护模型

共享仓库只维护“可共享结果”，不维护越权抓取的原始事实。

- `product` 维护需求域与 capability 索引
- `engineering` 维护服务、依赖、实现约束等共享摘要
- `qa` 维护测试来源、回归资产等共享摘要
- `design` 在 Phase 1 先预留导出目录，后续阶段再扩展聚合

每个团队只维护自己有权限且允许共享的内容；`context-hub` 负责聚合、标准化和分发，不负责构造一个全局超集权限账号。

## 工作关系

Phase 1 的四个关键层次如下：

1. 自然语言编排：`skills/context-hub/SKILL.md` 判断读取顺序、缺口补问和脚本调用。
2. shared context：`IDENTITY.md`、`topology/*`、`capabilities/*`、`decisions/*`、`.context/llms.txt` 是所有角色默认读取的共享层。
3. team exports：`teams/<team>/exports/*.yaml` 是各团队输出共享摘要的入口；`refresh_context.py` 负责聚合回共享层。
4. preflight / audit：`bootstrap_credentials_check.py` 只做凭据预检，`check_consistency.py` 和 `check_stale.py` 做契约与新鲜度审计。

## 本地命令

在本仓库中可直接运行的命令如下：

```bash
python3 skills/context-hub/scripts/init_context_hub.py \
  --output /tmp/meeting-control-hub \
  --name "会议控制平台" \
  --id meeting-control

python3 skills/context-hub/scripts/create_capability.py \
  --hub /tmp/meeting-control-hub \
  --name voting \
  --title "投票功能" \
  --domain meeting-control

python3 skills/context-hub/scripts/refresh_context.py /tmp/meeting-control-hub
python3 skills/context-hub/scripts/bootstrap_credentials_check.py --check-ones
python3 skills/context-hub/scripts/check_consistency.py --hub /tmp/meeting-control-hub
python3 skills/context-hub/scripts/check_stale.py --hub /tmp/meeting-control-hub
```

说明：

- `init_context_hub.py` 在新 hub 中生成共享目录、模板、`scripts/runtime/`、`scripts/integrations/` 以及后续维护脚本
- `create_capability.py` 维护 capability 文档骨架、`domains.yaml` 和 `ownership.yaml`
- `refresh_context.py` 当前只聚合本地 team exports，不做外部系统深扫
- `bootstrap_credentials_check.py` 只报告 GitLab / ONES 凭据是否就绪
- `check_consistency.py` 校验路径、ownership、exports metadata、`.context/llms.txt`
- `check_stale.py` 检查 export freshness 和 `in-progress` capability 的阻塞项

## 生成的 hub 结构

Phase 1 初始化后的目录结构大致如下：

```text
my-project-hub/
├── IDENTITY.md
├── topology/
│   ├── system.yaml
│   ├── domains.yaml
│   ├── testing-sources.yaml
│   └── ownership.yaml
├── capabilities/
│   └── _templates/
├── decisions/
├── teams/
│   ├── product/exports/
│   ├── design/exports/
│   ├── engineering/exports/
│   └── qa/exports/
├── .context/llms.txt
└── scripts/
    ├── create_capability.py
    ├── refresh_context.py
    ├── bootstrap_credentials_check.py
    ├── check_consistency.py
    ├── check_stale.py
    ├── runtime/
    └── integrations/
```

## 后续阶段

Phase 2 / 3 仍待实现：

- GitLab 深度扫描与真实拓扑抽取
- ONES 摘要同步与更多 source adapter
- 面向 PM / 设计 / 研发 / QA 的角色化 workflow executor

详见 [docs/context-hub-specification.md](docs/context-hub-specification.md)
