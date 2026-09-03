# 砚章公文写作 · Preview

砚章是一个面向个人使用的公文写作 Web 与 MCP 服务。它把标题工作台、结构化成稿、文章来源库、事实审校、版本管理和 Word 导出放在同一个本地应用中，并可接入支持 MCP 的桌面工具。

> 当前版本为公开预览版 `0.1.0b1`，对应发布标签 `v0.1.0-preview.1`。建议先在个人设备或独立服务器上试用，并在升级前备份数据。

## 主要能力

- 标题公式、排比结构、标题评分和候选排序
- 按公文类型、材料与方法论生成正文
- 改写、质量审校、材料事实核对
- 人民网、光明网、求是网文章的手动导入和范围采集
- SQLite 文稿库、文章库、历史版本及模型用量记录
- DOCX、MERGEFIELD 批量替换及 ZIP 导出
- 26 个 MCP 工具、6 类资源入口、4 个工作流 Prompt
- 同一服务同时提供 Web、stdio MCP 和 Streamable HTTP MCP

本项目与上述媒体或相关客户端厂商不存在隶属或官方合作关系。来源名称仅用于描述兼容范围；文章版权及使用要求以来源网站说明为准。

## 隐私优先的默认设置

- 未配置模型服务时使用确定性演示引擎，不向模型供应商发送材料。
- 数据默认写入操作系统的个人应用数据目录，也可通过 `GONGWEN_DATA_DIR` 指定独立目录。
- 网页访问令牌与远程 MCP 令牌彼此独立；生产模式要求两者均为至少 32 字节的随机值。
- 模型密钥只从本地环境变量读取；页面临时密钥仅保留在当前页面内存中。
- 人民网自动检索当前涉及明文 HTTP 上游，默认关闭；显式设置 `GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true` 后才会启用。手动导入 HTTPS 链接及其他 HTTPS 来源不受影响。
- 发布白名单排除 `.env`、SQLite、文章、文稿、备份、导出文件、日志和本机路径。

详细说明见 [PRIVACY.md](PRIVACY.md) 与 [SECURITY.md](SECURITY.md)。

## 快速开始

要求 Python 3.12 或更新版本。建议使用独立虚拟环境：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

Windows PowerShell 激活方式：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

启动本机 Web：

```bash
gongwen-web --host 127.0.0.1 --port 8787
```

然后访问 `http://127.0.0.1:8787/`。开发模式默认仅监听本机；需要服务器部署时使用下方 Docker 方案。

## 配置真实模型

本机运行时先把密钥导入当前进程环境；Docker 部署写入 `deploy/gongwen/.env`，服务器也可通过密钥管理工具注入。下面是 shell 环境变量示例：

```bash
export GONGWEN_LLM_PROVIDER=openai
export GONGWEN_LLM_MODEL=MODEL_NAME
export GONGWEN_LLM_API_KEY=REPLACE_WITH_PRIVATE_KEY
export GONGWEN_LLM_BASE_URL=https://MODEL_PROVIDER.example/v1
```

`openai` 支持 OpenAI 兼容接口；内置适配器还包括 `anthropic` 与 `gemini`。使用 DeepSeek、通义千问或其他兼容接口时，选择 OpenAI 兼容适配器并填写供应商公布的 HTTPS 基础地址。

完整环境变量见 [docs/configuration.md](docs/configuration.md)。

## MCP

### 本地 stdio

安装后，MCP 客户端可直接启动：

```json
{
  "mcpServers": {
    "yanzhang": {
      "command": "/ABSOLUTE/PATH/TO/VENV/bin/gongwen-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "GONGWEN_DATA_DIR": "/ABSOLUTE/PATH/TO/PRIVATE-DATA"
      }
    }
  }
}
```

### 远程 Streamable HTTP

生产部署后的地址为 `https://DOMAIN/mcp`，请求头为：

```text
Authorization: Bearer MCP_TOKEN
```

MCP Token 与网页 Token 分开设置。WorkBuddy Connector 位于 [`integrations/workbuddy-gongwen`](integrations/workbuddy-gongwen)，TraeWork、TraeCode、扣子等支持 Streamable HTTP 与自定义 Header 的客户端可按 [MCP 接入文档](docs/gongwen-mcp.md) 配置。

## Docker 部署

```bash
./deploy/gongwen/start.sh
```

首次运行会在 `deploy/gongwen/.env` 中生成两枚独立令牌，文件权限设置为 `0600`，终端日志不显示完整令牌。仅在可信交互式终端查看：

```bash
./deploy/gongwen/show-token.sh web
./deploy/gongwen/show-token.sh mcp
```

默认入口为 `http://127.0.0.1:8080`。公网域名、HTTPS、备份和恢复步骤见 [部署说明](deploy/gongwen/README.md)。

## 开发与离线验证

```bash
export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/yanzhang-venv"
uv sync --frozen --all-extras
PYTHONDONTWRITEBYTECODE=1 GONGWEN_DATA_DIR="$(mktemp -d)" uv run pytest -p no:cacheprovider
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --cache-dir="${TMPDIR:-/tmp}/yanzhang-mypy-cache" gongwen_web gongwen_mcp yanzhang
python scripts/release_audit.py
uv build
python scripts/package_connector.py dist
python scripts/release_audit.py --artifacts dist
python scripts/write_checksums.py dist
```

测试通过模拟传输和本机 ASGI 客户端运行，不依赖真实模型凭据或公网。CI 在安装依赖后设置失效代理，以便及时发现意外的公网请求。

## 发布

发布标签使用 `vX.Y.Z-preview.N`，Python 包版本使用对应的 `X.Y.ZbN`。例如：

```text
v0.1.0-preview.1  ->  0.1.0b1
```

推送标签后，GitHub Actions 会重新执行测试、白名单与敏感信息检查，构建 wheel、sdist 与
`yanzhang-workbuddy-connector-0.1.0-preview.1.zip`，生成 `SHA256SUMS` 并创建预发布条目。详细步骤见
[docs/releasing.md](docs/releasing.md)。

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。
