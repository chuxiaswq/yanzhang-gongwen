# 砚章·AI文字工作台

**当前预览：`v0.2.0-preview.1`（Python 包版本 `0.2.0b1`）**

砚章是一套本地优先、证据可追溯、可通过 Web 与 MCP 使用的中文文字工作台。它把任务简报、
项目资料、标题与开头、块编辑母稿、渠道变体、证据链、六维审校和 Word 交付串成一条工作流；
模型通过可替换 Provider 接入，未配置模型时仍可使用确定性本地流程。

## 四个场景包

| 场景包 | 内置写作配方 | 主要交付 |
| --- | --- | --- |
| 公文与综合材料 `gongwen` | 工作总结、汇报材料、实施方案、会议纪要 | 规范母稿、历史版本、DOCX 与批量文件 |
| 职场沟通 `workplace` | 工作邮件、周报、业务方案、会后跟进、PPT 提纲 | 邮件、报告、行动项和演示提纲 |
| 内容传播 `media` | 新闻稿、公众号文章、社交媒体帖、短视频脚本 | 一稿多用的渠道变体 |
| 学术与研究写作 `academic` | 文献综述、研究提纲、研究摘要、审稿意见回复 | 文献矩阵、论断—证据链接、参考文献与回复稿 |

来源名称只用于说明兼容与检索范围；本项目与相关媒体、学术数据库或客户端厂商不存在隶属关系或
官方合作，文章、文献和平台内容按各来源规则使用。

## 工作方式

```text
项目
  └─ 任务简报 WritingBrief ──关联──> 项目资料 KnowledgeItem
          │                              └─> 证据摘录 Evidence
          └─ 写作配方 ─> 内容块 ─> 母稿 TextAsset ─> 渠道变体
                                      │
                                      ├─> 可核查主张 Claim ─> 引用关系 Citation ─> Evidence
                                      └─> 六维审校 ─> 版本快照 Revision ─> 正式交付
```

模型画像 `ModelProfile` 只描述能力、成本/质量/延迟层级和隐私模式，不保存模型密钥。公文、
职场、内容和学术任务共用项目资料与文字资产模型；学术包另提供 BibTeX、RIS、CSL-JSON、
Crossref、OpenAlex、arXiv、证据定位和引用完整性检查。

## 五分钟开始

需要 Python 3.12 或更新版本：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
yanzhang-web --host 127.0.0.1 --port 8787
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
yanzhang-web --host 127.0.0.1 --port 8787
```

打开 `http://127.0.0.1:8787/`。默认数据位于操作系统的个人应用数据目录；也可在启动前设置：

```bash
export YANZHANG_DATA_DIR=/ABSOLUTE/PATH/TO/PRIVATE-DATA
```

## 接入模型

服务端统一使用模型时，配置 `YANZHANG_LLM_*`：

```bash
export YANZHANG_LLM_PROVIDER=openai
export YANZHANG_LLM_MODEL=MODEL_NAME
export YANZHANG_LLM_API_KEY=REPLACE_WITH_PRIVATE_KEY
export YANZHANG_LLM_BASE_URL=https://MODEL_PROVIDER.example/v1
```

内置适配 OpenAI 兼容接口、Anthropic 与 Gemini；DeepSeek、通义千问等兼容接口使用
`openai` Provider 并填写供应商公布的 HTTPS 基础地址。任务内容仅在用户主动运行真实模型步骤
时提交到所选服务。完整设置见 [配置参考](docs/configuration.md)。

## MCP

本地客户端启动 stdio 服务：

```json
{
  "mcpServers": {
    "yanzhang": {
      "command": "/ABSOLUTE/PATH/TO/VENV/bin/yanzhang-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "YANZHANG_DATA_DIR": "/ABSOLUTE/PATH/TO/PRIVATE-DATA"
      }
    }
  }
}
```

远程入口为 `https://DOMAIN/mcp`，使用独立的 `YANZHANG_MCP_ACCESS_TOKEN`：

```json
{
  "mcpServers": {
    "yanzhang": {
      "type": "streamableHttp",
      "url": "https://DOMAIN/mcp",
      "headers": {
        "Authorization": "Bearer ${YANZHANG_MCP_ACCESS_TOKEN}"
      },
      "timeout": 300000
    }
  }
}
```

45 个 `yanzhang_*` 工具组成 v0.2 项目、资料、术语、工作流、资产与学术命名空间；已有 26 个
`gongwen_*` 工具及 `gongwen://` Resources、Prompts 继续使用，合计 71 个工具。WorkBuddy 集成包在
[`integrations/workbuddy-gongwen`](integrations/workbuddy-gongwen)，Codex 与通用客户端配置见
[MCP 接入](docs/mcp-codex.md) 和 [完整 MCP 契约](docs/gongwen-mcp.md)。豆包/扣子、Trae、
WorkBuddy 等支持 Streamable HTTP 与自定义认证 Header 的客户端共用远程配置。

## 个人服务器部署

```bash
./deploy/gongwen/scripts/start.sh
./deploy/gongwen/scripts/health.sh
```

默认入口为 `http://127.0.0.1:8080`。首次启动会生成彼此独立的 Web 与 MCP 访问令牌；公网
使用域名和 HTTPS。升级前执行备份：

```bash
./deploy/gongwen/scripts/backup.sh
```

升级使用 `./deploy/gongwen/scripts/upgrade.sh [备份目录]`；恢复使用
`./deploy/gongwen/scripts/restore.sh BACKUP --yes`。原有 `deploy/gongwen/*.sh` 入口继续兼容，
新部署和运维记录统一采用 `deploy/gongwen/scripts/*`。

详细步骤见 [部署指南](deploy/gongwen/README.md) 和 [运维手册](docs/operations.md)。

## 兼容性

v0.2 是增量升级：

- 新接口使用 `/api/v2/*`，旧 `/api/*` 继续服务原公文页面与现有自动化；
- 新 MCP 工具使用 `yanzhang_*`，旧 `gongwen_*`、`gongwen://` 与现有 Prompt 保持可用；
- `YANZHANG_*` 为首选环境变量；同名后缀的 `GONGWEN_*` 仍受支持，同时设置时前者优先；
- `yanzhang-web` / `yanzhang-mcp` 为首选命令，`gongwen-web` / `gongwen-mcp` 保留。

接口字段和调用示例见 [HTTP API v2](docs/http-api-v2.md)。

## 数据与学术边界

正文、资料、版本、证据和文献默认保存在本地 SQLite/文件目录；项目没有遥测、广告追踪或
自动错误上报。DOI 规范化不代表元数据已经核验；`metadata_verified` 只由公开元数据连接器的
返回记录设置。论断—证据链接与来源哈希用于证明“引用了哪段材料”，仍需作者核对原文含义、
页码、统计方法、结论和目标期刊规则。详见 [隐私说明](PRIVACY.md)、[学术写作](docs/academic-writing.md)
与 [安全策略](SECURITY.md)。

## 开发与发布校验

```bash
export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/yanzhang-venv"
uv sync --frozen --all-extras
PYTHONDONTWRITEBYTECODE=1 YANZHANG_DATA_DIR="$(mktemp -d)" uv run pytest -p no:cacheprovider
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --cache-dir="${TMPDIR:-/tmp}/yanzhang-mypy-cache" \
  gongwen_web gongwen_mcp yanzhang yanzhang_core yanzhang_academic
python scripts/release_audit.py
```

更新记录见 [CHANGELOG.md](CHANGELOG.md)，发布流程见 [docs/releasing.md](docs/releasing.md)。

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。
