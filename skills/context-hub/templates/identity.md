# {project_name}

> {summary}

## 业务域

| 域 | 职责 | Owner |
|:--|:--|:--|
{domain_rows}

## 技术栈

- 后端：待自动识别
- 前端：待自动识别
- 基础设施：待自动识别

## 外部系统

| 系统 | 用途 | 地址 |
|:--|:--|:--|
| GitLab | 代码仓库 | {gitlab_url} |
| ONES | 需求和测试管理 | {ones_url} |
| Figma | 设计稿 | {figma_url} |

## AI 使用须知

本仓库是项目全局上下文的唯一入口。使用顺序：
1. 读本文件了解项目全貌
2. 读 topology/ 了解系统组成和服务地址
3. 读 capabilities/ 了解具体业务能力（含 spec/设计/架构/测试）
4. 读 decisions/ 了解架构约束和决策历史
5. 通过 topology/system.yaml 中的 repo 地址读取实际代码
