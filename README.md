# 砚章·AI文字工作台

**当前预览：`v0.2.0-preview.2`（Python 包版本 `0.2.0b2`）**

砚章是一套本地优先、证据可追溯、可通过 Web 与 MCP 使用的中文文字工作台。它把任务简报、
项目资料、标题与开头、块编辑母稿、渠道变体、证据链、六维审校和 Word 交付串成一条工作流；
模型通过可替换 Provider 接入，默认使用确定性本地流程。

**“模板演示”没有调用任何大模型，也不消耗模型 Token。** 它使用内置模板、写作公式和规则评分，
用于体验流程，并非某个免费模型。项目、资料和文稿仍可通过本地服务持久化；主动导入在线文章或
查询文献时仍会访问对应来源，演示模式不等于所有功能断网。

## 四个场景包

| 场景包 | 内置写作配方 | 主要交付 |
| --- | --- | --- |
| 公文与综合材料 `gongwen` | 工作总结、汇报材料、领导讲话、调研报告、实施方案、会议纪要 | 规范母稿、历史版本、DOCX 与批量文件 |
| 职场沟通 `workplace` | 工作邮件、周报、业务方案、会后跟进、PPT 提纲 | 邮件、报告、行动项和演示提纲 |
| 内容传播 `media` | 新闻稿、公众号文章、社交媒体帖、短视频脚本 | 一稿多用的渠道变体 |
| 学术与研究写作 `academic` | 文献综述、研究提纲、研究摘要、审稿意见回复 | 文献矩阵、论断—证据链接、参考文献与回复稿 |

四个场景包共内置 19 个配方、26 张场景写法方法卡（公文 6、职场 7、传播 6、学术 7）；
方法卡与配方章节结构是不同层次。公文包包含 `leadership-speech`（领导讲话）与
`research-report`（调研报告）。

切换场景不只是换文种：写法方法、语气、字段提示、示例、资料入口和自检清单随场景一起切换。
公文使用正式材料的规范与党报写法参考；职场强调结论、决策和行动项；内容传播区分事实、观点
与受众表达；学术以研究问题、方法、证据与引用为中心。模板生成与真实模型提示也使用对应场景
规则，而不是把所有任务都套入公文结构。

浏览器按项目与场景隔离当前资料选择和编辑状态，党政媒体样文与研究文献、业务资料分开使用。
切换后旧请求的迟到结果不覆盖当前任务；上一场景的草稿和候选不自动视为新场景成果。
职场和传播场景使用用户手工导入的业务材料、团队范例或内容素材；学术场景使用手工导入文献、
原文证据及已有公开元数据查询连接器。本轮场景适配未新增商业媒体自动采集连接器。

来源名称只用于说明兼容与检索范围；本项目与相关媒体、学术数据库或客户端厂商不存在隶属关系或
官方合作，文章、文献和平台内容按各来源规则使用。

## 工作方式

```text
项目
  └─ 任务简报 WritingBrief ──关联──> 项目资料 KnowledgeItem
          │                              └─> 证据摘录 Evidence（style_reference 除外）
          └─ 写作配方 ─> 内容块 ─> 母稿 TextAsset ─> 渠道变体
                                      │
                                      ├─> 可核查主张 Claim ─> 引用关系 Citation ─> Evidence
                                      └─> 六维审校 ─> 版本快照 Revision ─> 正式交付
```

模型画像 `ModelProfile` 只描述能力、成本/质量/延迟层级和隐私模式，不保存模型密钥。公文、
职场、内容和学术任务共用项目资料与文字资产模型；学术包另提供 BibTeX、RIS、CSL-JSON、
Crossref、OpenAlex、arXiv、证据定位和引用完整性检查。

`WritingBrief` 可同时保存用户采用的标题 `selected_title` 和有序结构 `structure_override`；
创建工作流时可用 `brief_id` 复用同一份已保存简报，响应也返回该 ID，便于页面将母稿、
版本和审校结果绑定到同一任务。项目资料可由调用方提供稳定 `material_id` 做幂等更新；
`kind=style_reference` 的项目资料（包括选中的文章）只用于结构、标题节奏、语气和句式参考，
不进入正文事实或证据链。

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
时提交到所选服务。页面显示供应商、具体模型及结果的执行来源，模型画像不等于实际型号。

| 操作 | 模型连接范围 |
| --- | --- |
| 单篇起草、标题实验室、润色、单篇审校 | 模板演示，或页面临时 API 连接 / 服务端默认模型 |
| 项目工作流母稿、渠道变体、项目模型增强审校 | `live=false` 为规则演示；`live=true` 只使用服务端配置 |
| 项目表达焦点、学术标题 / 提纲 / 摘要 / 引用检查等 | 当前为确定性规则功能，切到 API 模式也不代表这些功能调用了模型 |

项目工作流需显式传入 `live=true` 才调用模型；默认 `false`，即使服务端已配置模型也保持演示。
真实模型请求遇到未配置服务端模型时返回配置错误，不静默生成模板稿。页面临时密钥只在当前页面
内存中保留，项目工作流不会接收该密钥。完整设置见 [配置参考](docs/configuration.md)。

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
页码、统计方法、结论和目标期刊规则。当前学术任务使用已关联的书目元数据、用户导入原文或
正文摘录；原文证据优先于书目说明进入研究写作，元数据只识别来源。综述、研究提纲、摘要和
审稿回复使用各自结构，通用研究论文保留六章；摘要和逐条回复走对应功能而非论文提纲。
书目命中不代表已阅读全文，没有研究证据时保留框架与待补标记。内置写法卡是结构
方法说明，不是抓取到的来源文章。学术全文自动获取、目标期刊精确排版和真实模型成稿质量均需
独立验证，不由场景切换或演示结果保证。详见 [隐私说明](PRIVACY.md)、[学术写作](docs/academic-writing.md)
与 [安全策略](SECURITY.md)。

## 开发与发布校验

```bash
export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/yanzhang-venv"
uv sync --frozen --all-extras
uv run python scripts/build_scenario_catalog.py --check
PYTHONDONTWRITEBYTECODE=1 YANZHANG_DATA_DIR="$(mktemp -d)" uv run pytest -p no:cacheprovider
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --cache-dir="${TMPDIR:-/tmp}/yanzhang-mypy-cache" \
  gongwen_web gongwen_mcp yanzhang yanzhang_core yanzhang_academic
uv export --frozen --all-extras --no-emit-project --format requirements-txt \
  --output-file "${TMPDIR:-/tmp}/yanzhang-all-requirements.txt"
uv run pip-audit --requirement "${TMPDIR:-/tmp}/yanzhang-all-requirements.txt" \
  --progress-spinner off
python scripts/release_audit.py
```

更新记录见 [CHANGELOG.md](CHANGELOG.md)，发布流程见 [docs/releasing.md](docs/releasing.md)。

场景配置以 `yanzhang_core/scenario_profiles.py` 为单一来源，配方仍由 `yanzhang_core/packs.py`
维护。修改后运行 `uv run python scripts/build_scenario_catalog.py` 更新浏览器目录；
`--check` 对生成文件执行只读一致性校验。勿手工修改生成的
`gongwen_web/static/scenario_catalog.js` 或在页面再维护一套配方表，详见
[架构说明](docs/architecture.md#场景目录的单一来源)。

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。
