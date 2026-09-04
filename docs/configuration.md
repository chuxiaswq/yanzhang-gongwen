# 砚章·AI文字工作台配置参考

`v0.2.0-preview.1` 的首选环境变量前缀是 `YANZHANG_`。为便于原部署原地升级，每个运行时变量
也接受同名后缀的 `GONGWEN_` 写法；例如 `YANZHANG_DATA_DIR` 对应
`GONGWEN_DATA_DIR`。两者同时设置时，`YANZHANG_*` 优先。

密钥值应保存在权限受控的本地 `.env`、容器 Secret 或服务器密钥管理工具中。环境变量示例只
填写占位值，不把真实凭据提交到版本库。

## 最小本机配置

默认配置只监听本机，并使用确定性本地引擎：

```bash
export YANZHANG_DATA_DIR=/ABSOLUTE/PATH/TO/PRIVATE-DATA
yanzhang-web --host 127.0.0.1 --port 8787
```

CLI 参数 `--host`、`--port` 和 `--workers` 会覆盖对应运行时默认值。个人 SQLite 部署使用一个
应用工作进程。

## 运行与数据

| 首选变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YANZHANG_ENV` | `development` | `development`、`test` 或 `production` |
| `YANZHANG_HOST` | `127.0.0.1` | 应用监听地址 |
| `YANZHANG_PORT` | `8787` | 应用监听端口 |
| `YANZHANG_WORKERS` | `1` | SQLite 个人版保持为 1 |
| `YANZHANG_DATA_DIR` | 系统个人应用数据目录 | SQLite、导出及运行数据根目录 |
| `YANZHANG_ACCESS_LOG` | `false` | 应用脱敏访问日志；省略查询条件、客户端地址、请求头和正文 |
| `YANZHANG_MAX_REQUEST_BYTES` | `8388608` | 请求体上限，允许范围 1 KiB–100 MiB |
| `YANZHANG_RATE_LIMIT_REQUESTS` | 生产 `120`，其他 `0` | 窗口内请求数；0 表示本进程限流关闭 |
| `YANZHANG_RATE_LIMIT_WINDOW_SECONDS` | `60` | 限流窗口秒数 |
| `YANZHANG_HSTS_SECONDS` | 生产 `31536000`，其他 `0` | HTTPS 环境的 HSTS 秒数 |

默认数据目录：

- Linux：`${XDG_DATA_HOME:-~/.local/share}/yanzhang/gongwen`
- macOS：`~/Library/Application Support/Yanzhang/Gongwen`
- Windows：`%LOCALAPPDATA%\Yanzhang\Gongwen`

## 身份与网络边界

| 首选变量 | 说明 |
| --- | --- |
| `YANZHANG_ACCESS_TOKEN` | Web 与 `/api/*`、`/api/v2/*` 的 Bearer Token；生产或非回环监听时至少 32 字节 |
| `YANZHANG_MCP_ACCESS_TOKEN` | `/mcp` 的独立 Bearer Token；生产或非回环监听时与 Web Token 分开设置且至少 32 字节 |
| `YANZHANG_ALLOWED_HOSTS` | 逗号分隔的精确 Host 白名单 |
| `YANZHANG_CORS_ORIGINS` | 逗号分隔的完整 HTTPS Origin 白名单 |
| `YANZHANG_TRUSTED_PROXY_IPS` | 可提供代理头的 IP 或网段 |
| `YANZHANG_CLIENT_LLM_BASE_URL_ALLOWLIST` | 浏览器临时模型连接可使用的精确 HTTPS 基础地址 |
| `YANZHANG_ENABLE_INSECURE_PEOPLE_SEARCH` | 默认 `false`；人民网 HTTP 自动检索的显式开关 |
| `YANZHANG_ALLOW_UNAUTHENTICATED` | 默认 `false`；仅用于明确设计为公开访问的实例 |

生产模式会校验：Web/MCP 两枚令牌均不是示例值、二者不同、Host/CORS/代理列表没有通配符、
应用工作进程为 1。远程 MCP 端点是 `/mcp`；MCP 令牌不授予 Web/API 会话权限，Web 令牌也不
用于 MCP。

该边界也应用于非生产运行：`YANZHANG_HOST` 或命令行 `--host` 一旦选择非回环地址，启动前会
要求独立且至少 32 字节的 MCP 令牌；Web 令牌同样必填，除非部署者显式设置
`YANZHANG_ALLOW_UNAUTHENTICATED=true` 将 Web 设计为公开入口。本机开发继续使用默认
`127.0.0.1`，避免把测试实例意外暴露到局域网。

`YANZHANG_CLIENT_LLM_BASE_URL_ALLOWLIST` 采用完整 URL 精确匹配；协议、主机、端口和路径都
参与比较，尾部斜杠视为等价。页面传入的接口路径仍须是相对路径。

## 服务端模型

| 首选变量 | 说明 |
| --- | --- |
| `YANZHANG_LLM_PROVIDER` | `openai`、`anthropic`、`gemini`；兼容接口使用 `openai` |
| `YANZHANG_LLM_MODEL` | 模型名称 |
| `YANZHANG_LLM_API_KEY` | 私有模型凭据 |
| `YANZHANG_LLM_BASE_URL` | 可选基础地址；OpenAI 兼容接口填写供应商 HTTPS 地址 |
| `YANZHANG_LLM_TIMEOUT_SECONDS` | 模型请求超时，最大 300 秒 |
| `YANZHANG_ALLOW_INSECURE_LOCAL_MODEL` | 默认 `false`；生产环境仅在回环本地模型使用 HTTP 时显式开启 |

示例：

```bash
export YANZHANG_LLM_PROVIDER=openai
export YANZHANG_LLM_MODEL=MODEL_NAME
export YANZHANG_LLM_API_KEY=REPLACE_WITH_PRIVATE_KEY
export YANZHANG_LLM_BASE_URL=https://MODEL_PROVIDER.example/v1
```

`deepseek`、`qwen` 和 `custom` 仍是兼容输入，会归一化到 OpenAI 兼容适配器，并要求同时提供
基础 URL。推荐直接填写 `openai` 作为 Provider 名，把具体供应商放在模型名称和基础地址中。
生产环境的服务端基础地址默认要求 HTTPS，且拒绝 URL 用户信息、查询参数与片段。如模型只在
同一台机器的回环地址提供 HTTP，可显式设置 `YANZHANG_ALLOW_INSECURE_LOCAL_MODEL=true`；
该开关不接受局域网或公网 HTTP 地址。

模型画像 `ModelProfile` 记录能力、上下文、隐私模式和成本/质量/延迟层级，不存储 API Key。
`local_only`、`economy`、`balanced`、`quality` 路由预设只选择画像；真正的密钥仍来自服务器
环境。任务只有在用户启动真实模型步骤时才向所选 Provider 发送相应内容。

## 来源与学术连接器

- 人民网自动搜索当前使用 HTTP 上游，默认保持关闭；人民网 HTTPS 文章链接仍可手工导入。
- 光明网、求是网与学术元数据连接器按用户提交的关键词、标识和数量范围发出请求。
- Crossref、OpenAlex、arXiv 访问公开服务，不读取模型密钥；部署网络应允许所选连接器的 HTTPS
  域名，并设置出口代理、超时与访问策略。
- 导入本地 BibTeX、RIS、CSL-JSON、PDF 或 DOCX 本身不触发公开元数据查询。
- PDF 文本提取依赖可选 `pypdf` 组件；DOCX 使用标准 ZIP/XML 包解析。

## Docker 部署变量

根目录 `.env.example` 是 v0.2 的完整样例。首次运行
`deploy/gongwen/scripts/start.sh` 时，脚本会将它复制为权限 `0600` 的
`deploy/gongwen/.env`，再生成相互独立的 Web 与 MCP Token。可通过
`YANZHANG_ENV_TEMPLATE` 指向另一份模板，通过 `YANZHANG_ENV_FILE` 指向另一份私有配置文件。
部署脚本与 Compose 保留旧对象名和 `GONGWEN_*` 兼容字段，现有卷、网络和备份可原地沿用；
应用与运维脚本均按 `YANZHANG_*` 优先规则读取。

常用宿主配置包括：

| 变量 | 用途 |
| --- | --- |
| `YANZHANG_SITE_ADDRESS` | Caddy 站点地址；本机默认 `:80`，公网填写一个域名 |
| `YANZHANG_BIND_ADDRESS` | 宿主监听地址 |
| `YANZHANG_HTTP_PORT` / `YANZHANG_HTTPS_PORT` | 宿主映射端口 |
| `YANZHANG_PROXY_MAX_REQUEST_SIZE` | 代理请求体上限，应与应用上限一致 |
| `YANZHANG_IMAGE` / `YANZHANG_CADDY_IMAGE` | 应用与代理镜像 |
| `YANZHANG_DATA_VOLUME` | 应用持久卷；已有部署可继续使用 `gongwen-web-data` |
| `YANZHANG_COMPOSE_PROJECT` | Compose 项目标识 |
| `YANZHANG_LOG_MAX_SIZE` / `YANZHANG_LOG_MAX_FILES` | 容器日志轮换 |
| `TZ` | 容器时区 |

`deploy/gongwen/scripts/{start,health,backup,restore,upgrade}.sh` 是首选运维入口。已有
`deploy/gongwen/*.sh` 入口继续兼容，方便旧自动化平滑迁移；新脚本会先解析 `YANZHANG_*`，
必要时再读取同名后缀的 `GONGWEN_*`。

## 兼容映射

所有应用运行时变量都按同名后缀映射：

```text
YANZHANG_SUFFIX  >  GONGWEN_SUFFIX  >  内置默认值
```

例如：

```dotenv
YANZHANG_ACCESS_LOG=false
GONGWEN_ACCESS_LOG=false
```

同时出现时使用第一行。升级建议是：先升级程序并保留旧变量，完成健康检查与备份，再逐项添加
`YANZHANG_*`；确认新配置生效后清理重复值。备份、恢复、令牌轮换和回退见
[operations.md](operations.md)。
