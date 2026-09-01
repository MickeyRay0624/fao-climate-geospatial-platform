# FAO Climate Geospatial Data & Decision Platform — Blueprint v0.1

本交付包把平台重构讨论落实为四项可评审、可开发的设计资产：

1. `FAO_CLIMATE_PLATFORM_BLUEPRINT_v0.1.md` — 信息架构、核心数据模型、权限模型和模块契约总规范；
2. `permission-matrix.csv` — 可导入表格或权限配置讨论的角色—权限矩阵；
3. `module-contract.schema.json` — 模块 manifest 的 JSON Schema；
4. `investment-prioritisation.module.yaml` — 投资与推广优先级模块示例契约；
5. `extension-field-support.module.yaml` — 推广员田间支持模块示例契约；
6. `core-data-model.mmd` — 可单独渲染的 Mermaid 核心领域关系图。

## 状态

- 版本：`0.1.0`
- 日期：`2026-08-28`
- 状态：`Proposed / for team review`
- 依据：`PROJECT_HANDOFF_CONTEXT_2026-08-28.md`

## 重要边界

本包中的“现状”来自项目交接材料；其余数据库表、权限代码、路由、生命周期和模块 manifest 均为目标设计提案，尚未在现有代码中实现。当前可运行系统仍是使用合成数据的 Cambodia commune 水稻韧性优先级 DSS MVP，不是生产平台，也不是田块级数字孪生。
