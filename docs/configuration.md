# 配置参考

配置均通过环境变量提供。包含密钥的值应保存在本地 `.env`、容器 Secret 或服务器密钥管理工具中。

## 运行与数据

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GONGWEN_ENV` | `development` | `development`、`test` 或 `production` |
| `GONGWEN_HOST` | `127.0.0.1` | Web 监听地址 |
| `GONGWEN_PORT` | `8787` | Web 监听端口 |
| `GONGWEN_WORKERS` | `1` | SQLite 个人版生产环境固定为 1 |
| `GONGWEN_DATA_DIR` | 系统个人应用数据目录 | SQLite 与导出根目录 |
| `GONGWEN_ACCESS_LOG` | `false` | HTTP 访问日志；请求目标可能包含查询条件，仅在已有脱敏与保留策略时显式开启 |
| `GONGWEN_MAX_REQUEST_BYTES` | `8388608` | 请求体字节上限 |
| `GONGWEN_RATE_LIMIT_REQUESTS` | 生产模式 `120` | 窗口内请求数；开发模式 0 表示关闭 |
| `GONGWEN_RATE_LIMIT_WINDOW_SECONDS` | `60` | 限流窗口秒数 |

## 身份与网络

| 变量 | 说明 |
| --- | --- |
| `GONGWEN_ACCESS_TOKEN` | Web/API Bearer Token；生产模式至少 32 字节 |
| `GONGWEN_MCP_ACCESS_TOKEN` | `/mcp` 独立 Bearer Token；与 Web Token 不同 |
| `GONGWEN_ALLOWED_HOSTS` | 逗号分隔的精确 Host 白名单 |
| `GONGWEN_CORS_ORIGINS` | 逗号分隔的精确 HTTPS Origin 白名单 |
| `GONGWEN_TRUSTED_PROXY_IPS` | 允许提供代理头的 IP 或网段 |
| `GONGWEN_HSTS_SECONDS` | HTTPS 环境下 HSTS 秒数 |
| `GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST` | 页面临时模型连接可使用的精确 HTTPS 基础地址 |
| `GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH` | 默认 `false`；是否启用涉及 HTTP 上游的人民网自动检索 |

## 服务端模型

| 变量 | 说明 |
| --- | --- |
| `GONGWEN_LLM_PROVIDER` | `openai`、`anthropic`、`gemini`；兼容接口使用 `openai` |
| `GONGWEN_LLM_MODEL` | 模型名称 |
| `GONGWEN_LLM_API_KEY` | 私有模型凭据 |
| `GONGWEN_LLM_BASE_URL` | 可选基础地址；兼容接口需要填写 HTTPS 地址 |
| `GONGWEN_LLM_TIMEOUT_SECONDS` | 模型请求超时，最大 300 秒 |

生产示例见 `deploy/gongwen/env.example`。部署脚本会生成独立 Web/MCP Token，并将 `.env` 权限设置为 `0600`。
