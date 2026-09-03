# 砚章公文写作 MCP

砚章把网页中的拟题、正文生成、改写、审校、文章来源库、文稿版本和 Word 导出能力
统一暴露为 MCP。支持两种使用方式：

- **本地 stdio**：MCP 客户端启动 `gongwen-mcp` 子进程，适合个人电脑上的 Codex、
  TraeCode 等客户端；
- **远程 Streamable HTTP**：MCP 与 `gongwen-web` 共用同一应用进程和 SQLite 数据，
  入口为 `https://DOMAIN/mcp`，适合部署服务器上的 WorkBuddy、TraeWork、扣子编程和
  其他远程 MCP 客户端。

网页 API 和 MCP 使用相同的领域服务、模型适配器、资源限制与持久化目录。MCP 不会另建一份
文章来源或文稿数据库。

## 1. 能力范围

### Tools

| 分组 | 工具 | 说明 |
| --- | --- | --- |
| 状态与方法 | `gongwen_get_status` | 查看服务、持久化、模型模式和能力状态 |
|  | `gongwen_get_methods` | 按文种获取标题公式、正文方法论和默认选项 |
| 写作 | `gongwen_generate_titles` | 批量拟题、九维评分、排序并返回推荐标题 |
|  | `gongwen_generate_document` | 按标题、材料与方法论生成正文并自动保存版本 |
|  | `gongwen_rewrite_text` | 润色、压缩、扩写或按指令改写文本 |
|  | `gongwen_review_document` | 检查结构、语言、占位符和可读性 |
|  | `gongwen_audit_document` | 将正文事实主张与用户材料建立证据映射 |
| 文稿 | `gongwen_save_document` | 新建文稿或按预期版本更新文稿 |
|  | `gongwen_list_documents` | 分页、检索文稿 |
|  | `gongwen_read_document` | 读取当前文稿 |
|  | `gongwen_list_versions` | 读取文稿的不可变版本列表 |
|  | `gongwen_read_version` | 读取指定历史版本 |
|  | `gongwen_delete_document` | 删除指定文稿 |
| 文章 | `gongwen_list_article_sources` | 列出当前可用文章来源 |
|  | `gongwen_search_articles` | 按关键词、来源和分页条件检索文章元数据 |
|  | `gongwen_read_article` | 读取一篇文章及正文 |
|  | `gongwen_get_style_references` | 从指定 `article_ids` 提取结构、标题与表达参考 |
|  | `gongwen_import_article_text` | 导入用户粘贴且注明来源的文章 |
|  | `gongwen_import_article_url` | 导入用户指定的文章 URL |
|  | `gongwen_collect_articles` | 按关键词、来源和日期范围执行有界自动采集 |
|  | `gongwen_delete_article` | 删除指定文章来源 |
| 导出 | `gongwen_export_docx` | 生成单篇 DOCX |
|  | `gongwen_export_documents_zip` | 把多篇文稿打包成 ZIP |
|  | `gongwen_mail_merge_docx` | 使用 Word 字段模板和数据行批量生成 DOCX |
| 模型 | `gongwen_test_model` | 测试服务端配置的真实模型 |
|  | `gongwen_get_model_usage` | 查看模型调用和 Token 用量摘要 |

删除类工具具有持久化副作用，客户端应在用户明确指定目标后调用。
`gongwen_generate_document` 会自动保存并返回 `id`、`version` 和最多 4000 字的 `preview`；
生成后通过 `gongwen_read_document` 分块读取全文，不再紧接着调用 `gongwen_save_document`。
`gongwen_generate_titles`、`gongwen_rewrite_text`、`gongwen_review_document` 和
`gongwen_audit_document` 不保存内容；手工组合或改写后的完整正文用
`gongwen_save_document` 建立新版本。

### Resources

| URI 模板 | 内容 |
| --- | --- |
| `gongwen://status` | 当前服务状态 |
| `gongwen://methods/{document_type}` | 指定文种的方法论目录 |
| `gongwen://documents/{id}` | 当前文稿元数据及前 20000 字正文 |
| `gongwen://documents/{id}/versions/{version}` | 指定历史版本元数据及前 20000 字正文 |
| `gongwen://articles/{id}` | 指定文章来源元数据及前 20000 字正文 |
| `gongwen://exports/{id}` | MCP 生成并登记的 DOCX 或 ZIP 资源 |

导出工具返回 `artifact_id`、`filename`、`mime`、`size`、`sha256`、`resource_uri`、
`created_at` 和 `expires_at`。客户端通过 `gongwen://exports/{artifact_id}` Resource 读取
二进制内容。产物默认保存在 `GONGWEN_DATA_DIR/exports`，进程重启后仍可在有效期内读取；它是
可重建的派生产物，不是文稿事实源。默认有效期为 24 小时，单个 DOCX 上限 16 MiB、单个 ZIP
上限 64 MiB，目录总量上限 2 GiB；清理顺序为先过期、再最旧。过期后重新执行相应导出工具。

### Prompts

| Prompt | 用途 |
| --- | --- |
| `gongwen_title_workbench` | 先选方法、检索参考，再批量拟题和比较 |
| `gongwen_draft_from_materials` | 从用户材料到标题、正文、审校和保存的完整流程 |
| `gongwen_revise_document` | 读取现稿、分段修改、复核并保存新版本 |
| `gongwen_official_article_research` | 按范围采集权威文章并形成可追溯的写作参考 |

Prompt 参数分别为：标题工作台的 `topic`、`document_type=讲话稿`、`audience`；材料成文的
`topic`、`materials`、`document_type=工作总结`、`requirements`；修订流程的 `document_id`、
`requirements`；文章来源研究的 `keywords`、`source_ids=gmw,qiushi`、`date_range`。人民网
自动检索因当前入口使用 HTTP 而默认关闭，仅在部署端显式设置
`GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true` 后按需加入；检索关键词与日期范围会明文传输。

### Tool 输入字段与限制

所有 Tool 使用封闭 JSON Schema，未知字段会触发 `invalid_request`。`engine` 只接受
`auto`、`server`、`local`：`auto` 在服务端模型已配置时使用真实模型，否则使用本地确定性
引擎；`server` 明确要求服务端模型；`local` 明确使用确定性引擎。客户端不传入 Provider、
API Key、模型 URL 或访问令牌。

通用写作字段：

| 字段 | 默认值 | 限制 |
| --- | --- | --- |
| `document_type` | `工作总结` | 1–100 字符 |
| `topic` | 必填 | 1–300 字符 |
| `purpose` | 空 | 最多 2000 字符 |
| `audience` | 空 | 最多 500 字符 |
| `materials` | 空 | 字符串或列表；最多 16 项，单项最多 25000 字符，合计最多 50000 字符 |
| `tone` | `稳健规范` | 最多 100 字符 |
| `reference_style` | `权威媒体综合写法` | 最多 100 字符 |
| `style_reference_ids` | 空列表 | 最多 8 个不重复文章 ID，每个最多 128 字符 |
| `engine` | `auto` | `auto`、`server`、`local` |

`gongwen_generate_titles` 使用上述字段，并增加：`count` 默认 5、范围 1–20；
`formula_ids` 最多 12 个不重复 ID、每个最多 80 字符；`custom_title_formula` 可为最多
500 字符的规则，或包含 `name`（最多 100）、`template`（最多 300）、`rule`（最多 500）和
`style`（最多 80）的对象，其中 `template` 与 `rule` 至少填写一个。该工具不保存结果。

`gongwen_generate_document` 使用通用写作字段，并增加：

| 字段 | 默认值 | 限制或行为 |
| --- | --- | --- |
| `requirements` | 空 | 最多 4000 字符 |
| `fact_lock` | `true` | 布尔值 |
| `length` | `标准` | 最多 50 字符 |
| `title_count` | `5` | 1–20 |
| `title_formula_ids` | 空列表 | 最多 12 个不重复 ID，每个最多 80 字符 |
| `custom_title_formula` | 空 | 与拟题工具相同 |
| `selected_title` | 空 | 填写时为 1–300 字符 |
| `content_methodology_id` | 空 | 填写时为 1–80 字符 |
| `custom_methodology` | 空 | 自定义正文方法对象，见下文 |
| `document_id` | 空 | 填写时为 1–128 字符 |
| `expected_version` | 空 | 非负整数，并与 `document_id` 成对出现 |
| `version_note` | `MCP 自动生成` | 最多 500 字符 |

`custom_methodology` 包含 `name`（最多 100）、`summary`（最多 500）、`logic`（最多 1000）、
`steps`（1–16 个不重复步骤，每项最多 200）和 `fact_strategy`（最多 500）。

生成工具会直接建立版本：让服务生成 ID 时同时省略 `document_id` 和 `expected_version`；
指定全新 ID 时传 `expected_version: 0`；更新现有 ID 时传
`gongwen_read_document` 返回的 `current_version`。响应包含 `id`、`version`、`title`、
`document_type`、`preview`、`character_count`、`preview_truncated`、`outline`、
`title_candidates` 和 `meta`；`preview` 最多 4000 字，全文随后分块读取。

改写与审校：

| 工具 | 输入字段与限制 | 保存行为 |
| --- | --- | --- |
| `gongwen_rewrite_text` | `text` 1–100000；`instruction` 最多 2000；`mode` 最多 80；`tone` 最多 100；`engine` | 不保存 |
| `gongwen_review_document` | `content` 1–200000；`title` 最多 300；`document_type` 最多 100；`materials` 为最多 50000 字符的字符串；`engine`；`compact` 默认 `true`，仅返回前 20 个问题 | 不保存 |
| `gongwen_audit_document` | `content` 1–30000；`title` 最多 300；`materials` 最多 16 项、单项 25000、合计 50000，且正文与材料合计最多 60000；`compact` 默认 `true`，返回指标和前 100 个问题 | 不保存 |

文稿与版本：

| 工具 | 输入字段与限制 |
| --- | --- |
| `gongwen_save_document` | `title` 1–300、`content` 1–500000、`document_type` 最多 100、`version_note` 最多 500；`document_id`/`expected_version` 使用与生成工具相同的成对规则 |
| `gongwen_list_documents` | `limit` 默认 20、范围 1–100；`offset` 0–1000000；`search` 填写时 1–200 字符 |
| `gongwen_read_document` | `document_id` 1–128；`chunk_offset` 默认 0、范围 0–500000；`chunk_size` 默认 8000、范围 500–20000 |
| `gongwen_list_versions` | `document_id` 1–128；`limit` 默认 20、范围 1–100；`offset` 0–1000000 |
| `gongwen_read_version` | 在文稿分块字段基础上增加 `version`，取值从 1 开始 |
| `gongwen_delete_document` | `document_id` 1–128 |

`gongwen_save_document` 的 `metadata` 最多 100 个字段，字段名最多 100 字符，单值最多
100000 个 JSON 字符，整个对象最多 100000 个 JSON 字符。列表响应包含 `has_more`；分块读取的
`content` 包含 `text`、`offset`、`size`、`total_characters`、`has_more` 和 `next_offset`。

文章来源：

| 工具 | 输入字段与限制 |
| --- | --- |
| `gongwen_list_article_sources` | 无 |
| `gongwen_search_articles` | `query` 最多 200；`source_id` 填写时 1–50；`limit` 默认 20、范围 1–100；`offset` 0–1000000 |
| `gongwen_read_article` | `article_id` 1–128；`chunk_offset` 默认 0、范围 0–2000000；`chunk_size` 默认 8000、范围 500–20000 |
| `gongwen_get_style_references` | `article_ids` 必填 1–8 个不重复 ID、每个最多 128；`max_excerpt_chars` 默认 360、范围 80–1000 |
| `gongwen_import_article_text` | `title` 1–500、`content` 1–2000000、`source_id` 默认 `manual` 且最多 50、`source_name` 默认 `用户导入` 且最多 100、`url` 最多 2000、`published_date` 最多 50、`summary` 最多 500、`style_features` 最多 20 个不重复非空项且每项最多 80 |
| `gongwen_import_article_url` | `url` 1–2000；可选 `source_id` 1–50；`style_features` 最多 20 个不重复非空项且每项最多 80 |
| `gongwen_collect_articles` | `keywords` 1–20 项、每项最多 100；`source_ids` 1–10 项、每项最多 50；`start_date`、`end_date` 可选并使用 `YYYY-MM-DD`，开始日期不晚于结束日期；`limit` 默认 20、范围 1–100 |
| `gongwen_delete_article` | `article_id` 1–128 |

先用搜索结果选定文章 ID，再把这些 ID 交给 `gongwen_get_style_references`。读取文章正文也采用
与文稿相同的 `has_more`/`next_offset` 分块续读方式。

导出与模型：

| 工具 | 输入字段与限制 |
| --- | --- |
| `gongwen_export_docx` | `document_id` 1–128；`version` 可选且从 1 开始；`template_style` 为 `standard` 或 `brief`；`filename` 可选、最多 120 |
| `gongwen_export_documents_zip` | `documents` 1–50 项；每项使用 `document_id`、可选 `version`、`template_style`、可选 `filename`；ZIP `filename` 默认 `批量公文.zip`、最多 120 |
| `gongwen_mail_merge_docx` | `document_id`、可选 `version`、`template_style`；`rows` 1–200 行；`filename` 默认 `批量公文.zip`、最多 120 |
| `gongwen_test_model` | `engine` 默认 `auto`；明确测试真实服务端模型时使用 `server` |
| `gongwen_get_model_usage` | `limit` 默认 20、范围 1–100；`offset` 0–1000000；返回全局汇总与分页记录 |

邮件合并每行最多 100 个字段，字段名最多 100 字符，单值最多 100000 个 JSON 字符，全部
`rows` 最多 1000000 个 JSON 字符；批量 ZIP 和邮件合并在展开后的标题、正文、元数据与文件名
总量上限均为 5000000 字符。

`gongwen_get_status` 和 `gongwen_list_article_sources` 无输入；`gongwen_get_methods` 的
`document_type` 可省略，填写时为 1–100 字符。

## 2. 本地 stdio

安装项目后，默认入口使用 stdio：

```bash
cd /ABSOLUTE/PATH/yanzhang-gongwen
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

export GONGWEN_DATA_DIR=/ABSOLUTE/PATH/gongwen-data
gongwen-mcp --transport stdio
```

本地 MCP 客户端的通用 JSON 配置：

```json
{
  "mcpServers": {
    "gongwen-writing": {
      "type": "stdio",
      "command": "/ABSOLUTE/PATH/yanzhang-gongwen/.venv/bin/gongwen-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "GONGWEN_DATA_DIR": "/ABSOLUTE/PATH/gongwen-data"
      }
    }
  }
}
```

stdio 与 Web 进程都把文稿和文章来源写入 `GONGWEN_DATA_DIR/gongwen.sqlite3`，导出产物写入
`GONGWEN_DATA_DIR/exports`；两种接入方式指向同一持久目录即可共享数据。

真实模型继续使用现有的 `GONGWEN_LLM_*` 服务端配置。长期模型密钥放在操作系统或部署平台的
secret manager 中，MCP 工具参数只传写作任务内容。真实模型超时最多可配置为 300 秒；客户端
也应给生成、审校和采集工具保留 300 秒，状态、方法、列表等轻量调用通常更快。

## 3. 远程 Streamable HTTP

生产部署把 MCP 挂载在 Web 应用同一进程的 `/mcp`：

```text
https://DOMAIN/mcp
```

在 `deploy/gongwen/.env` 设置一枚独立令牌：

```dotenv
GONGWEN_MCP_ACCESS_TOKEN=REPLACE_WITH_AN_INDEPENDENT_32_BYTE_RANDOM_TOKEN
```

然后按现有部署流程重建服务：

```bash
./deploy/gongwen/start.sh
./deploy/gongwen/smoke.sh
```

远程客户端使用：

```json
{
  "mcpServers": {
    "gongwen-writing": {
      "type": "streamableHttp",
      "url": "https://DOMAIN/mcp",
      "headers": {
        "Authorization": "Bearer REPLACE_WITH_MCP_TOKEN"
      },
      "timeout": 300000
    }
  }
}
```

远程 FastMCP 使用无状态 HTTP 和 JSON 响应，单次请求体沿用 `GONGWEN_MAX_REQUEST_BYTES`；
部署模板默认 2 MiB。远程入口使用 HTTPS 域名；MCP 令牌至少 32 字节，并与网页访问令牌分开
生成和轮换。反向代理须保留
`Authorization`、`Accept`、`Content-Type`、`Mcp-Session-Id`、`MCP-Protocol-Version` 和
`Last-Event-ID` 请求头，并允许同源的 GET、POST、DELETE 方法。

## 4. WorkBuddy Connector

仓库已经提供符合 WorkBuddy Connector 目录结构的集成包：

```text
integrations/workbuddy-gongwen/
├── connector-meta.json
├── mcp.json
├── token-schema.json
├── icon.svg
└── skills/gongwen/SKILL.md
```

使用前：

1. 把 `mcp.json` 中的 `DOMAIN` 替换为真实 HTTPS 域名；
2. 保留 `${GONGWEN_MCP_ACCESS_TOKEN}` 占位符，连接时在 WorkBuddy 表单填写令牌；
3. 把整个 `workbuddy-gongwen` 目录打包并导入或提交审核；
4. 先测试 `gongwen_get_status`，再测试拟题、读取和 DOCX 导出流程。

元数据固定为 `source: gongwen-writing`、`type: mcp`、`version: 0.1.0-preview.1`、
`minWorkbuddyVersion: 4.23.0` 和 `auth_mode: token`。连接器只配置一个
Streamable HTTP Server，超时为 300000 ms，真实令牌不进入集成文件。轻量查询通常很快；
五分钟窗口也覆盖真实模型生成、较长审校和有界文章来源采集。

## 5. TraeCode 与 TraeWork

### TraeCode CLI

运行 `traecli config edit`，在 `trae_cli.yaml` 添加：

```yaml
mcp_servers:
  - name: gongwen-writing
    type: http
    url: https://DOMAIN/mcp
    timeout: 300s
    headers:
      Authorization: "Bearer REPLACE_WITH_MCP_TOKEN"
```

启动 TraeCode CLI 后输入 `/mcp` 检查连接和工具清单。TraeCode 项目级配置也可放在
`.trae/mcp.json`：

```json
{
  "mcpServers": {
    "gongwen-writing": {
      "type": "http",
      "url": "https://DOMAIN/mcp",
      "headers": {
        "Authorization": "Bearer REPLACE_WITH_MCP_TOKEN"
      },
      "timeout": "300s"
    }
  }
}
```

### TraeWork

在 TRAE 企业版控制台进入 **个人设置 → MCP → 创建 → 手动配置**，选择 Streamable HTTP，
填写 `https://DOMAIN/mcp`，并添加 `Authorization: Bearer REPLACE_WITH_MCP_TOKEN`。
保存后在 MCP 管理面板启用服务。TraeWork 桌面版云端环境和网页版可使用控制台中已登记的
MCP Server；服务域名须从相应云端环境可访问。

## 6. 扣子编程

扣子编程提供基于已有 MCP 服务创建自定义插件的入口：

1. 进入目标工作空间的 **资源库**；
2. 选择 **+资源 → 插件**，类型选择 **MCP**；
3. 插件 URL 填写 `https://DOMAIN/mcp`；该入口使用 HTTPS 域名而非 IP 地址；
4. 授权方式选择 **Service → Service token / API key**，位置选择 **Header**，参数名填写
   `Authorization`，值填写 `Bearer REPLACE_WITH_MCP_TOKEN`；
5. 保存后同步工具，先试运行 `gongwen_get_status` 与 `gongwen_generate_titles`；
6. 测试通过后发布插件，供智能体和工作流调用。

## 7. Codex

Codex 的 `~/.codex/config.toml` 或可信项目内 `.codex/config.toml` 可配置远程服务：

```toml
[mcp_servers.gongwen-writing]
url = "https://DOMAIN/mcp"
bearer_token_env_var = "GONGWEN_MCP_ACCESS_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 300
```

启动 Codex 前设置令牌：

```bash
export GONGWEN_MCP_ACCESS_TOKEN=REPLACE_WITH_MCP_TOKEN
codex mcp get gongwen-writing
```

本地 stdio 配置：

```toml
[mcp_servers.gongwen-writing]
command = "/ABSOLUTE/PATH/yanzhang-gongwen/.venv/bin/gongwen-mcp"
args = ["--transport", "stdio"]
startup_timeout_sec = 30
tool_timeout_sec = 300

[mcp_servers.gongwen-writing.env]
GONGWEN_DATA_DIR = "/ABSOLUTE/PATH/gongwen-data"
```

使用 `codex mcp list` 查看服务，在 Codex 交互界面输入 `/mcp` 查看工具状态。

## 8. 其他 MCP 客户端

支持 stdio 的客户端使用第 2 节通用 JSON；支持远程 Streamable HTTP 与自定义请求头的客户端
使用第 3 节配置。不同客户端可能把传输类型写成 `http`、`streamableHttp` 或通过界面选择
“Streamable HTTP”，以客户端官方字段为准。

接入检查顺序：

1. 初始化响应和 `tools/list`；
2. `gongwen_get_status`；
3. `gongwen_get_methods` 与 `gongwen_generate_titles`；
4. `gongwen_generate_document` 自动保存、文稿分块读取和版本读取；
5. 文章来源检索；
6. DOCX 导出 Resource；
7. 令牌错误、参数错误、并发版本冲突、请求大小和频率限制场景。

## 9. 豆包相关适配状态

公文 MCP 服务遵循标准 stdio 与 Streamable HTTP 协议，因此可继续对接采用标准 MCP 客户端的
国产工具。火山引擎已有产品公开了 Streamable HTTP/SSE MCP Server 登记与 Header 鉴权能力；
豆包消费者端的通用自定义 MCP 配置入口、字段格式和版本覆盖仍以客户端实际界面为准，当前
列入真机兼容性验证清单，不把它标记为已完成适配。若客户端提供远程 MCP 的 URL 与 Header
字段，可先用第 3 节参数执行联调。

## 10. 使用边界与排障

- `401/403`：检查是否使用 `GONGWEN_MCP_ACCESS_TOKEN`，并确认请求头包含 `Bearer ` 前缀；
- `404`：确认路径完整为 `/mcp`，且部署已经更新到包含 MCP 挂载的版本；
- `409`：文稿发生并发更新，先读取最新版本，再携带新的预期版本保存；
- `413/422`：根据返回的字段路径和大小说明拆分材料或修正参数；
- `429`：按响应中的等待时间再次调用；
- 导出读取异常：重新导出并立即读取返回的 `gongwen://exports/{id}`；
- 采集耗时：缩小来源、日期、关键词或 `limit`，一次请求维持有界范围。

SQLite 仍按单进程部署约束运行，多个 MCP 客户端共享同一服务实例时使用现有并发版本控制。

## 官方参考

- [Model Context Protocol：Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [WorkBuddy：Connector](https://open.workbuddy.cn/docs/connector)
- [WorkBuddy：Skill](https://open.workbuddy.cn/docs/skill)
- [WorkBuddy：MCP 使用指南](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)
- [TRAE：TraeCode CLI 模型上下文协议](https://docs.trae.cn/cli_model-context-protocol)
- [TRAE：企业版模型上下文协议](https://docs.trae.cn/enterprise_model-context-protocol)
- [扣子编程：基于 MCP 服务创建插件](https://docs.coze.cn/guides_create_a_plugin_based_on_mcp)
- [OpenAI Codex：MCP](https://developers.openai.com/codex/mcp)
- [火山引擎：MCP Server 登记示例](https://www.volcengine.com/docs/85637/2477487?lang=zh)
