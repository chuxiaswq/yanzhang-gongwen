# 更新记录

本项目采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的组织方式，版本号遵循语义化版本与 PEP 440 预发布规则。

## [0.1.0b1] - 2026-09-04

### 新增

- 个人公文写作 Web 页面与 SQLite 持久化。
- 标题公式、方法论成稿、改写、审校和高级事实核对。
- 文章来源导入、范围采集、检索和风格引用。
- DOCX、MERGEFIELD 与批量 ZIP 导出。
- 26 个 MCP 工具、资源和 Prompt，支持 stdio 与 Streamable HTTP。
- WorkBuddy Connector 及 Trae、扣子等客户端接入示例。
- Docker/Caddy 部署、健康检查、备份和恢复工具。

### 安全

- Web 与 MCP 使用独立 Bearer Token，生产模式校验长度、占位值与重复使用。
- 构建采用公开发行白名单，加入敏感信息扫描、逐成员审计和 SHA-256 校验和。
- 默认数据目录迁移到操作系统个人应用数据目录，避免从当前目录误读数据。
- 人民网明文 HTTP 自动检索默认关闭，需显式配置后启用。
- 部署启动和健康检查避免在日志及进程参数中展示访问令牌。
