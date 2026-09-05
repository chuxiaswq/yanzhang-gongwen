# 砚章·AI文字工作台 MCP 契约

本文是 `v0.2.0-preview.2` 的 MCP 服务契约。服务同时注册：

- 45 个项目化、多场景 `yanzhang_*` 工具；
- 既有 26 个 `gongwen_*` 公文工具；
- 既有 6 类 `gongwen://` Resources、11 类项目化 `yanzhang://` Resources 与 4 个公文 Prompt。

新旧工具使用同一进程、应用服务和 SQLite 数据目录，名字彼此独立，不用 alias 覆盖。v0.2
新增项目导出及学术实体只读 Resource；既有 Resource 与 Prompt 保持原 URI。Codex 注册和调用
范式见 [mcp-codex.md](mcp-codex.md)。

## 1. 传输、认证与配置

### 本机 stdio

```json
{
  "mcpServers": {
    "yanzhang": {
      "type": "stdio",
      "command": "/ABSOLUTE/PATH/TO/VENV/bin/yanzhang-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "YANZHANG_DATA_DIR": "/ABSOLUTE/PATH/TO/PRIVATE-DATA"
      }
    }
  }
}
```

### 远程 Streamable HTTP

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

远程入口使用无状态 Streamable HTTP 与 JSON 响应，单次请求体沿用
`YANZHANG_MAX_REQUEST_BYTES`。Web/API Token 与 MCP Token 分开生成和轮换；工具参数不接受
Provider API Key、模型 URL 或访问令牌。

首选命令是 `yanzhang-mcp`，兼容命令是 `gongwen-mcp`。`YANZHANG_*` 是首选配置前缀，同名
后缀的 `GONGWEN_*` 继续读取，二者并存时采用前者。

## 2. 共同类型与边界

所有 `yanzhang_*` 工具使用封闭 JSON Schema，未知字段返回 `invalid_request`。字符串会去除
首尾空白；列表中不接受空项或重复项。

| 类型 | 允许值 |
| --- | --- |
| `scenario_pack_id` | `gongwen`、`workplace`、`media`、`academic` |
| `channel` | `document`、`email`、`meeting`、`presentation`、`web`、`social`、`academic` |
| `kind`（资料） | `source`、`style_reference`、`prior_asset`、`terminology`、`note` |
| `headline_kind` | `title`、`opening`、`section_heading`、`topic_sentence` |
| `scope` | `all`、`materials`、`assets`、`literature` |
| `mode`（工作流） | `sync`、`background` |
| `resume_from` | `research`、`titles`、`outline`、`draft`、`review`、`export` |
| `status`（资产） | `draft`、`reviewed`、`final`、`archived` |
| `checks` | `structure`、`style`、`facts`、`citations`、`terminology` |
| `format`（资产导出） | `docx`、`markdown`、`text`、`html`、`pdf`、`latex`、`csv` |
| `provider`（文献） | `crossref`、`openalex`、`arxiv` |
| `format`（文献导入） | `bibtex`、`ris`、`csl-json` |
| `style`（参考文献） | `gb-t-7714`、`apa`、`mla`、`chicago` |

分页工具的 `limit` 默认 20、范围 1–100，`offset` 默认 0、范围 0–1000000。分块读取的
`chunk_offset` 默认 0、范围 0–500000；`chunk_size` 默认 8000、范围 500–20000。

### 任务简报公共字段

`yanzhang_generate_titles` 与 `yanzhang_create_workflow` 共享：

| 字段 | 必填/默认 | 限制 |
| --- | --- | --- |
| `project_id` | 必填 | 1–128 字符 |
| `topic` | 必填 | 1–300 字符，与保存后的简报/资产标题上限一致 |
| `goal` | 必填 | 1–2000 字符 |
| `audience` | 必填 | 1–500 字符 |
| `content_type` | 必填 | 1–100 字符 |
| `scenario_pack_id` | 必填 | 四个场景包之一 |
| `recipe_id` | 必填 | 1–100 字符，且属于所选场景包 |
| `channel` | `document` | 必须属于配方支持的渠道 |
| `tone` | `准确、清晰、得体` | 1–100 字符 |
| `length` | `standard` | 1–80 字符 |
| `target_language` | `zh-CN` | 2–35 字符 |
| `constraints` | `[]` | 最多 32 项，每项最多 500 字符 |
| `keywords` | `[]` | 最多 32 项，每项最多 500 字符 |
| `material_ids` | `[]` | 最多 128 个项目内资料 ID |
| `model_profile_id` | 空 | 填写时 1–100 字符 |
| `selected_title` | 空 | 已采用标题，填写时 1–300 字符 |
| `structure_override` | `[]` | 最多 24 个有序章节；非空时整体替代配方默认结构 |

`structure_override` 每节为 `{id, title, purpose, required}`：`id` 1–80 字符、`title`
1–100 字符、`purpose` 1–500 字符，`required` 默认 `true`。同一列表内的章节 ID 与标题
必须各自唯一，输入顺序即提纲与母稿顺序。

### 执行模式与结果来源

模板演示使用确定性模板、公式和规则，没有调用任何大模型，不消耗模型 Token；MCP 仍可读写
本地服务中的项目、资料和文稿。主动来源导入或公开文献查询仍会联网。`live=false` 是工作流
创建、渠道变体和模型增强审校的默认值，服务端配置了模型也不会自动启用实时调用。显式
`live=true` 只使用服务端模型；未配置时返回稳定错误 `model_configuration_error`，不静默返回模板稿。

生成与审校结果中的 `execution` 包含 `mode`、`engine`、`provider`、`model`、`label`、`uses_model`。
规则执行为 `local / deterministic`，供应商与模型为 `null`，`uses_model=false`；真实模型执行为
`live / language_model`，返回实际配置的供应商和型号，不把 `resolved_route` 中的画像当成型号。
`yanzhang_get_asset` 顶层 `execution` 和版本列表的可选 `Revision.execution` 来自所选版本；
手工修订及没有记录的历史版本为 `null`，不根据当前配置补猜。结果不返回密钥或模型接口地址。

## 3. 状态与场景包工具

| 工具 | 输入 | 行为 |
| --- | --- | --- |
| `yanzhang_get_status` | 无 | 返回通用写作、项目、工作流、学术、导出和模型可用状态，不返回密钥 |
| `yanzhang_list_scene_packs` | 可选 `channel`、`content_type` 1–100 | 列出匹配的场景包和配方 |
| `yanzhang_get_scene_pack` | `pack_id` | 返回受众、配方、章节、渠道、输出格式与事实策略 |

四个场景包共 19 个配方：

- `gongwen`：`work-summary`、`briefing-material`、`leadership-speech`（领导讲话）、
  `research-report`（调研报告）、`implementation-plan`、`meeting-minutes`；
- `workplace`：`work-email`、`weekly-report`、`business-proposal`、`meeting-followup`、
  `presentation-outline`；
- `media`：`press-release`、`wechat-article`、`social-post`、`short-video-script`；
- `academic`：`literature-review`、`research-outline`、`research-abstract`、`reviewer-response`。

场景不只是显示名称。类型化场景指引统一约束写法、语气、结构、材料角色和审校关注点：公文强调
行文与任务落实，职场强调结论与行动项，传播区分事实与观点，学术围绕问题、方法、证据和引用。
场景定义来自 `yanzhang_core/scenario_profiles.py`，配方仍由 `yanzhang_core/packs.py` 注册；
Web 使用同一目录的生成副本。内置写法卡是方法说明，不表示工具已检索或读过来源正文。
四个场景另提供 26 张写法方法卡：公文 6、职场 7、传播 6、学术 7，区别于 19 个配方的章节
结构。职场/传播材料及团队范例由用户手工导入；学术使用导入文献、原文证据与已有公开元数据
连接器，本轮未新增商业媒体自动采集工具。

## 4. 项目与资料工具

| 工具 | 输入字段与限制 | 副作用 |
| --- | --- | --- |
| `yanzhang_create_project` | `name` 1–200；`description` 最多 2000；`scenario_pack_id=gongwen`；`tags` 最多 32 项、单项 100 | 创建项目 |
| `yanzhang_list_projects` | 可选 `query` 1–200、`scenario_pack_id`；标准分页 | 无 |
| `yanzhang_get_project` | `project_id` 1–128 | 无 |
| `yanzhang_upsert_project_term` | `project_id`；`term` / `preferred_form` 1–200；可选 `term_id`、说明和最多 32 个不建议变体 | 新增或更新项目术语规则 |
| `yanzhang_list_project_terms` | `project_id`；标准分页 | 列出项目术语与首选表达 |
| `yanzhang_delete_project_term` | `project_id`、`term_id` 1–128 | 删除一条项目术语规则 |
| `yanzhang_add_material` | `project_id`；可选 `material_id` 1–128；`title` 1–500；`content` 1–500000；`kind=source`；`source_url` 最多 2000；`tags` 最多 64 项、单项 100 | 创建知识资料；在同一项目内传稳定 ID 时幂等更新 |
| `yanzhang_list_materials` | `project_id`；可选 `kind`、最多 32 个标签；标准分页 | 无 |
| `yanzhang_get_material` | `project_id`、`material_id`；标准分块字段 | 无 |
| `yanzhang_search` | `project_id`；`query` 1–2000；`scope=all`；最多 32 个标签；标准分页 | 无 |

省略 `material_id` 时每次生成新资料 ID；指定稳定 ID 时，同项目首次调用创建资料，后续调用更新
同一项资料。已属于其他项目的 ID 不会被改挂到当前项目。

项目术语会参与 `terminology` 审校：发现不建议变体时指向首选表达。所有术语、资料、搜索范围与
返回 ID 都受 `project_id` 隔离。长资料使用
`has_more`/`next_offset` 继续读取，而不是把全文反复放进模型上下文。

## 5. 标题、工作流与资产工具

### 标题

`yanzhang_generate_titles` 使用任务简报公共字段，并增加：

| 字段 | 默认 | 限制 |
| --- | --- | --- |
| `count` | `8` | 1–12 |
| `headline_kind` | `title` | 标题、开头、小标题或段首观点句 |
| `formula_ids` | `[]` | 最多 20 个唯一公式 ID，每个最多 100 字符 |

工具按任务简报与确定性公式生成候选，返回评分与方法信息。生成开头、小标题或段首句时，
`selected_title` 作为当前母稿主题；表达焦点依次使用 `keywords` 首项、`structure_override` 首节
标题、已采用标题、首项事实资料标题和任务主题。明确关联的非 `style_reference` 资料最多取前 16 项、每项
前 4000 字作为事实克制评分边界；在缺少自定义结构、关键词和已采用标题时，首项事实资料标题还会
作为焦点兜底。确定性本地引擎不会从资料正文抽取新说法或改写为候选，避免把参考正文误当成已核定
表述；`style_reference` 正文不进入本地候选或事实评分。工具不创建文字资产，响应中的
`context_usage` 说明本次进入评分的事实资料 ID、排除的风格资料数量和单项摘录上限。

`formula_ids` 是实际筛选条件，并非展示提示。留空时，服务先对当前 `headline_kind` 的完整公式
目录评分，再截取 `count`；指定后，只对所选公式评分。大标题可选 `main-subtitle`、
`parallel-triad`、`parallel-quartet`、`antithesis`、`progression`、`numbered-quartet` 等；
开头、小标题和段首句各自也提供排比、对偶、递进及三段/四段式公式。候选中的
`formula_name`、`techniques` 和 `rationale` 用于解释结构与排序依据。完整目录与 HTTP 示例见
[http-api-v2.md](http-api-v2.md#可解释表达公式目录)。

### 工作流

`yanzhang_create_workflow` 使用任务简报公共字段，并增加：

| 字段 | 默认 | 限制 |
| --- | --- | --- |
| `brief_id` | 空 | 已保存项目简报 ID，1–128 字符；填写时完整规范化简报（包括 `material_ids`、`selected_title`、`structure_override`）必须与已存内容一致 |
| `live` | `false` | 显式 `true` 使用服务端模型；未配置时返回 `model_configuration_error` |
| `auto_review` | `true` | 是否在写作后运行审校步骤 |
| `requested_exports` | `[]` | 最多 7 个唯一资产导出格式 |

公共字段中的 `selected_title` 存在时工作流保留该标题，否则采用推荐候选；非空
`structure_override` 作为工作流提纲与母稿的完整有序结构。`live` 在创建时保存，后续运行和恢复
沿用该值；创建结果及工作流对象的 `execution` 披露该路径。标题、提纲和自动审校步骤仍使用规则，
母稿 `draft` 步骤按 `live` 选择引擎，上述四类步骤输出标注自己的 `execution`。

省略 `brief_id` 时服务创建并保存新简报；传入时复用同项目的已保存简报。创建响应顶层
返回 `brief_id`，工作流对象也返回同一 `brief_id`；客户端用它绑定后续资产、版本和审校结果。
后续运行、查询、取消或恢复返回的 `workflow.brief_id` 保持不变；只有创建响应另外提供顶层
`brief_id`。已保存的 `brief_id` 绑定项目和完整规范化内容；修改简报时使用新 ID，不跨项目复用。

其余工作流工具：

| 工具 | 输入 | 行为 |
| --- | --- | --- |
| `yanzhang_run_workflow` | `project_id`、`workflow_id`；`mode=sync`；可选 `resume_from` | 首次运行或校验后从首个未成功步骤恢复；真实模型/来源步骤可能访问网络 |
| `yanzhang_get_workflow` | `project_id`、`workflow_id` 1–128 | 返回项目内状态、步骤、脱敏错误摘要与输出资产 ID |
| `yanzhang_cancel_workflow` | `project_id`、`workflow_id` 1–128 | 请求取消项目内尚未完成的工作流 |

首次运行处于 `queued` 时可省略 `resume_from`；显式提供时必须与首个未成功步骤一致。
`failed`、`waiting_review` 恢复必须提供该步骤值，已经成功的步骤不会被回退。`succeeded`、
`cancelled` 省略该字段时幂等返回终态，携带该字段时返回状态错误。`background` 对首次运行和合法
恢复均保持后台执行。运行、查询、取消和恢复都会同时校验 `project_id`；跨项目 ID 与不存在的 ID
统一按 `not_found` 处理。请求超时前后先用 `yanzhang_get_workflow` 读取状态和步骤，再决定是否
恢复，以免产生重复资产或导出。工作流只持久化稳定错误码和脱敏摘要，不保存上游异常正文。

### 文字资产

| 工具 | 输入字段与限制 | 行为 |
| --- | --- | --- |
| `yanzhang_list_assets` | `project_id`；可选 `status`、`content_type` 1–100；标准分页 | 列出母稿与变体 |
| `yanzhang_get_asset` | `project_id`、`asset_id`；可选 `revision>=1`；标准分块字段 | 读取当前或指定版本 |
| `yanzhang_create_variant` | 项目、源资产、`target_channel`；`instruction` 最多 4000；可选 `source_revision>=1`、模型画像；`live=false` | 生成带父资产关系的渠道变体 |
| `yanzhang_list_revisions` | `project_id`、`asset_id`；标准分页 | 列出不可变版本 |
| `yanzhang_review_asset` | 项目、资产；`checks` 默认结构/风格/事实/引用，1–5 项；最多 128 个资料 ID；可选模型画像；`live=false` | 只返回并评分所选检查映射到的维度；显式实时模式增加模型审校 |
| `yanzhang_export_asset` | 项目、资产；`format=docx`；可选 `revision>=1`、`template_id=standard|brief`、`filename` 1–200 | 生成导出工件 |

`target_channel` 使用共同渠道枚举。`yanzhang_review_asset` 中 `structure` 映射逻辑/格式，
`style` 映射清晰度/语气/语言，`facts` 与 `citations` 映射证据，`terminology` 映射语言；响应同时
返回 `execution`、`effective_mode`、`resolved_route`、请求画像和模型问题数。仅 `live=true` 且模型已配置、
路由允许网络时执行模型增强，本地规则始终先执行。导出返回文件名、媒体类型、大小、哈希、
`project_id`、`asset_id`、`revision_id`、`creator` 和项目作用域 Resource URI；DOCX 直接保留
内容块的标题层级，并去除与资产标题重复的标题块。`template_id` 仅用于 DOCX：
`standard` 是规范文稿样式，`brief` 是紧凑简报样式；其他格式携带该字段会作为参数错误处理。

## 6. 学术与研究写作工具

本节的学术拟题、提纲、摘要、证据提取、引用核验、完整性检查和审稿回复等当前使用本地规则
引擎，不是模型调用接口。页面切换 API 或为 MCP 客户端选择模型，不会让这些工具自动调用
砚章服务端模型。公开文献检索是单独的网络操作，使用来源连接器而非模型 Provider。

当前学术写作使用项目关联的书目元数据及用户导入原文、证据摘录。书目只识别来源，正文与证据
才支持研究论断；没有真实文献或研究结果时输出框架与待补位置，不补造引文。党政媒体样文与
学术材料分开使用。全文自动获取、目标期刊精确排版与真实模型效果不由本节工具或场景切换保证。

### 文献检索与导入

| 工具 | 输入字段与限制 | 行为 |
| --- | --- | --- |
| `yanzhang_search_literature` | `project_id`、`query` 1–1000；`provider=crossref`；`limit` 1–50，默认 10 | 访问公开元数据服务，并把返回候选保存到当前项目 |
| `yanzhang_import_literature` | `project_id`；`content` 1–2000000；`format` 为 BibTeX/RIS/CSL-JSON；最多 32 个标签 | 解析并保存记录 |
| `yanzhang_list_literature` | `project_id`；可选 `query`、摘要开关与标准分页 | 列出项目内已保存文献 |
| `yanzhang_get_literature` | `project_id`、`record_id` 1–200；`include_abstract=true` | 读取标准化记录和来源追踪 |

导入时，`tags` 会与每条记录已有的 `keywords` 去重合并，并随文献记录持久化；二者合计最多
100 项。

DOI 只做规范化。文件或手工导入默认不设置 `metadata_verified`；只有公开连接器返回记录可设置该
标记，作者仍应与原始页面核对。公开元数据响应先核对 `Content-Length`，再分块读取，单次正文
硬上限为 2 MiB。

### 证据与引用

| 工具 | 输入字段与限制 | 行为 |
| --- | --- | --- |
| `yanzhang_list_evidence` | `project_id`；可按 `record_id` 筛选；标准分页 | 列出项目证据片段 |
| `yanzhang_get_evidence` | `project_id`、`evidence_id` | 读取一条证据及来源谱系 |
| `yanzhang_extract_evidence` | 项目、文献、`text` 1–500000；`query` 最多 2000；`max_snippets` 1–100，默认 20 | 创建含 `record_id`、来源哈希与位置的证据片段 |
| `yanzhang_build_literature_matrix` | 项目；1–200 个文献 ID；最多 1000 个证据 ID；`query` 最多 2000 | 构建文献比较矩阵 |
| `yanzhang_list_literature_matrices` | `project_id`、标准分页 | 列出已保存文献矩阵 |
| `yanzhang_get_literature_matrix` | `project_id`、`matrix_id` | 读取一个文献矩阵 |
| `yanzhang_list_research_claims` | `project_id`、标准分页 | 列出核验流程保存的研究主张 |
| `yanzhang_get_research_claim` | `project_id`、`claim_id` | 读取一条研究主张 |
| `yanzhang_list_citation_links` | `project_id`；可按主张、文献或证据筛选；标准分页 | 列出引用关系 |
| `yanzhang_get_citation_link` | `project_id`、`link_id` | 读取一条引用关系 |
| `yanzhang_verify_citations` | 项目；1–200 个文献 ID；1–1000 个证据 ID；1–500 个 `ResearchClaim`；最多 1000 个链接 | 返回逐项状态与覆盖率 |

核验只使用请求中提供且项目内可见的 `BibliographicRecord` 和 `EvidenceSnippet`。未知文献 ID、
来源哈希错配、低语义/词汇支撑度分别进入复核或无效状态；哈希匹配不评价作者对原文的解释。

### 研究写作

三个工具 `yanzhang_suggest_academic_titles`、`yanzhang_create_academic_outline` 与
`yanzhang_draft_abstract` 共享研究简报字段：

| 字段 | 必填/默认 | 限制 |
| --- | --- | --- |
| `project_id` | 必填 | 1–128 |
| `title` | 必填 | 1–500 |
| `research_question` | 必填 | 1–2000 |
| `discipline` | 空 | 最多 200 |
| `purpose` | 空 | 最多 2000 |
| `audience` | `学术读者` | 1–200 |
| `document_type` | `研究论文` | 1–100 |
| `language` | `zh-CN` | 2–20 |
| `keywords` / `constraints` | `[]` | 各最多 30 项、单项最多 500 |
| `method_notes` | 空 | 最多 10000 |
| `record_ids` | `[]` | 最多 1000 个文献 ID |

工具专有字段：

- `yanzhang_suggest_academic_titles`：`count` 默认 5、范围 1–10；
- `yanzhang_create_academic_outline`：`evidence_ids` 最多 1000；
- `yanzhang_draft_abstract`：`claims` 最多 500、`links` 最多 1000、`max_characters` 默认 800、
  范围 100–20000。

`yanzhang_create_academic_outline` 返回的 `outline.task_type` 新增为五值枚举：
`literature-review`、`research-outline`、`abstract`、`rebuttal`、`research-paper`。
输入仍由 `document_type` 选择任务：综述使用问题/主题/分歧/空白四节，研究提纲使用问题/框架/
资料方法/章节四节，摘要使用背景目的/方法/结果/结论四节，审稿回复使用总体说明/逐条回复/
修改定位/保留意见四节；通用研究论文保留引言至结论的六章。`task_type` 是输出标识，不是工具
新增输入参数。摘要正文由 `yanzhang_draft_abstract` 返回，`abstract.task_type` 固定为 `abstract`；
逐条回复正文仍由 `yanzhang_prepare_rebuttal` 根据意见与实际修改生成。

领域函数 `create_outline(..., journal=...)` 以非空 `journal.required_sections` 优先覆盖默认
章节；当前 MCP 提纲请求不接收 `journal`，期刊参数仍由完整性检查工具接收。

项目母稿消费浏览器学术材料包时优先分配原文证据块。本地组合的 480 字符上限只用于证据正文，
文献 ID、证据 ID 标记和材料包中已有的完整定位行独立保留；截断正文前另列
“下文已截断，不代表完整引文；请回查原始证据及上下文。”提示，不将提示混入原文。
书目和包说明不充当研究结论；真实模型上下文单列
`bibliographic_metadata`，与事实 `knowledge` 分离。它是内部提示字段，不是 MCP 工具的新参数。

其余学术工具：

| 工具 | 输入字段与限制 | 行为 |
| --- | --- | --- |
| `yanzhang_format_bibliography` | 项目；1–1000 个文献 ID；`style=gb-t-7714` | 输出基础 GB/T 7714、APA、MLA 或 Chicago 著录 |
| `yanzhang_review_academic_integrity` | 项目；`manuscript` 1–1000000；文献/证据各最多 1000；主张最多 500；链接最多 1000；可选 `JournalProfile` | 检查缺引、元数据、页码、数字证据、哈希、稿件论断与期刊要求 |
| `yanzhang_prepare_rebuttal` | 项目；1–200 个 `ReviewComment`；最多 200 个修改映射，值最多 20000 字符 | 生成与实际修改对应的逐条回复 |

基础参考文献格式不宣称覆盖所有期刊变体。研究方法、统计分析、直接引语、页码和核心结论保留
人工复核节点。完整边界见 [academic-writing.md](academic-writing.md)。

`JournalProfile` 的 `required_sections` 最多 30 项；`title_max_characters` 范围 5–1000，
`abstract_max_characters` 范围 100–20000，`manuscript_max_words` 范围 500–500000，
`custom_rules` 最多 50 项。前四类要求由确定性规则对本次 `manuscript` 检查；每条
`custom_rules` 都返回独立的信息级人工核对项，始终保留人工确认状态。结果附带原始字符数、
中日韩表意字符/拉丁词组混合计词数和本次期刊画像 ID。

## 7. 兼容 `gongwen_*` 工具

| 分组 | 工具 |
| --- | --- |
| 状态与方法 | `gongwen_get_status`、`gongwen_get_methods` |
| 写作 | `gongwen_generate_titles`、`gongwen_generate_document`、`gongwen_rewrite_text`、`gongwen_review_document`、`gongwen_audit_document` |
| 文稿 | `gongwen_save_document`、`gongwen_list_documents`、`gongwen_read_document`、`gongwen_list_versions`、`gongwen_read_version`、`gongwen_delete_document` |
| 文章 | `gongwen_list_article_sources`、`gongwen_search_articles`、`gongwen_read_article`、`gongwen_get_style_references`、`gongwen_import_article_text`、`gongwen_import_article_url`、`gongwen_collect_articles`、`gongwen_delete_article` |
| 导出 | `gongwen_export_docx`、`gongwen_export_documents_zip`、`gongwen_mail_merge_docx` |
| 模型 | `gongwen_test_model`、`gongwen_get_model_usage` |

兼容工具继续遵守 v0.1 的关键规则：

- `engine` 取 `auto`、`server` 或 `local`；模型和访问凭据不进入参数；
- 兼容生成、拟题、改写与审校按请求文种选择场景指引，避免把职场、传播和学术任务套为公文；
- `gongwen_generate_document` 自动保存并返回 `id`、`version` 与最多 4000 字预览；全文通过
  `gongwen_read_document` 分块读取；
- 指定新 `document_id` 时使用 `expected_version: 0`，更新时使用最新 `current_version`；
- 文稿最大 500000 字符，文章最大 2000000 字符，常用分块为 500–20000 字符；
- `gongwen_collect_articles` 的关键词 1–20 项、来源 1–10 项、`limit` 1–100；
- `gongwen_get_style_references` 接受 1–8 个文章 ID，只把文章作为结构与表达参考，不作为正文事实或证据链来源；
- 删除文稿/文章是持久化副作用；客户端先向用户复述目标 ID 与标题；
- 导出工件默认 24 小时有效，过期后由原文稿和版本重新生成。

### 按场景改写与审校

`gongwen_rewrite_text` 保留原参数，并新增可选 `document_type`：

| 字段 | 必填 / 默认 | 限制与含义 |
| --- | --- | --- |
| `text` | 必填 | 1–100000 字符，要改写的文本 |
| `document_type` | `""` | 最多 100 字符，按当前成果类型选择公文、职场、传播或学术语域 |
| `instruction` | `提升表达的规范性、准确性和凝练度` | 最多 2000 字符 |
| `mode` | `polish` | 最多 80 字符 |
| `tone` | `稳健规范` | 最多 100 字符 |
| `engine` | `auto` | `auto`、`server` 或 `local` |

省略 `document_type` 保持旧调用兼容，自由文本按中性职场场景处理；建议传入当前成果类型，
例如 `文献综述`、`邮件`、`新闻稿` 或 `工作总结`。`gongwen_review_document` 已有的
`document_type` 现用于选择对应场景的审校重点，无需新增参数。

`gongwen_get_methods` / `gongwen://methods/{document_type}` 从全部核心配方派生
`recipe-<recipe_id>` 结构，同时保留旧结构方法。非党政配方默认返回各自的 5 类标题公式，
不继承党报写法；场景的 26 张方法卡与该接口的结构方法集合属于不同目录。

## 8. Resources 与兼容 Prompts

### Resources

| URI 模板 | 内容 |
| --- | --- |
| `gongwen://status` | 当前服务状态 |
| `gongwen://methods/{document_type}` | 指定文种的方法论目录 |
| `gongwen://documents/{id}` | 当前文稿元数据及前 20000 字正文 |
| `gongwen://documents/{id}/versions/{version}` | 指定历史版本元数据及前 20000 字正文 |
| `gongwen://articles/{id}` | 指定文章来源元数据及前 20000 字正文 |
| `gongwen://exports/{id}` | 仅读取 v0.1 兼容工具生成的未分项目导出工件 |
| `yanzhang://projects/{project_id}/exports/{artifact_id}` | 校验项目归属后读取 v0.2 资产导出工件 |
| `yanzhang://projects/{project_id}/academic/literature` | 项目文献记录集合 |
| `yanzhang://projects/{project_id}/academic/literature/{record_id}` | 一条项目文献记录 |
| `yanzhang://projects/{project_id}/academic/evidence` | 项目证据片段集合 |
| `yanzhang://projects/{project_id}/academic/evidence/{evidence_id}` | 一条项目证据片段 |
| `yanzhang://projects/{project_id}/academic/matrices` | 项目文献矩阵集合 |
| `yanzhang://projects/{project_id}/academic/matrices/{matrix_id}` | 一个项目文献矩阵 |
| `yanzhang://projects/{project_id}/academic/claims` | 项目研究主张集合 |
| `yanzhang://projects/{project_id}/academic/claims/{claim_id}` | 一条项目研究主张 |
| `yanzhang://projects/{project_id}/academic/citation-links` | 项目引用关系集合 |
| `yanzhang://projects/{project_id}/academic/citation-links/{link_id}` | 一条项目引用关系 |

### Prompts

| Prompt | 作用 |
| --- | --- |
| `gongwen_title_workbench` | 方法→文章来源→标题比较 |
| `gongwen_draft_from_materials` | 材料→标题→成文→审校→保存 |
| `gongwen_revise_document` | 读取→分段修订→复核→新版本 |
| `gongwen_official_article_research` | 有界采集权威文章并形成可追溯参考 |

导出文件是可重建派生产物，不是正文事实源。v0.2 工件只从携带同一 `project_id` 的
`yanzhang://projects/.../exports/...` 读取；旧 `gongwen://exports/{artifact_id}` 不读取 v0.2
项目工件。默认单 DOCX 上限 16 MiB、单 ZIP 上限 64 MiB、导出目录总量上限 2 GiB。

## 9. WorkBuddy 与国产工具集成

仓库提供可打包的 WorkBuddy Connector：

```text
integrations/workbuddy-gongwen/
├── connector-meta.json
├── mcp.json
├── token-schema.json
├── icon.svg
└── skills/gongwen/SKILL.md
```

连接器版本为 `0.2.0-preview.2`，默认服务器名 `yanzhang-writing`，凭据字段
`YANZHANG_MCP_ACCESS_TOKEN`。把 `DOMAIN` 换成部署域名后导入客户端，先调用
`yanzhang_get_status`，再验证项目、资料、标题、母稿、变体、审校、学术与导出。

从仓库根目录生成可重复的 Connector ZIP：

```bash
python scripts/package_connector.py dist
```

产物为 `dist/yanzhang-workbuddy-connector-0.2.0-preview.2.zip`。在 WorkBuddy 的 Connector
管理界面导入后，填写部署端生成的 MCP Token；Token Schema 会将它映射到
`${YANZHANG_MCP_ACCESS_TOKEN}`，真实值不会写入 ZIP。更新域名或 Skill 后重新打包并导入同版本
测试实例，确认 71 个工具的目录与实际服务一致，再发布给正式工作区。

豆包/扣子、Trae、WorkBuddy 的原生 MCP 配置入口可按同一组参数登记：传输选 Streamable HTTP，
地址填 `https://DOMAIN/mcp`，认证 Header 填 `Authorization: Bearer MCP_TOKEN`，生成与审校超时
设为 300 秒。保存后先同步工具并运行只读的 `yanzhang_get_status`；随后依次验证一个临时项目、
一项资料、一组标题和一份本地模式母稿。客户端若把传输显示为 `http`，以其文档确认该选项实际
使用 Streamable HTTP 并保留自定义 Header。

其他客户端只要支持 Streamable HTTP 与自定义 `Authorization` Header，即可使用第 1 节通用
配置。部分产品把传输类型显示为 `http` 或“Streamable HTTP”；客户端版本、Header 传递、超时
和工具数量上限应在真机逐项验证。stdio 客户端使用本机配置，不暴露远程端口。

## 10. 错误、重试与副作用

常见稳定错误类别：

| 类别 | 处理 |
| --- | --- |
| `invalid_request` | 按返回字段路径修正类型、枚举、长度或未定义字段 |
| `model_configuration_error` | 检查服务端模型配置与路由设置，再重试显式实时请求 |
| `brief_conflict` | 已保存的稳定简报 ID 对应不同内容；保留旧记录并为新内容使用新 ID |
| `project_scope_error` | 核对项目 ID；该资源 ID 已绑定其他项目，不应跨项目复用 |
| `not_found` | 核对项目、资料、资产、版本或文献 ID |
| `operation_timeout` | 查询工作流或资源状态后，从明确步骤恢复 |
| `internal_error` | 记录时间与错误类别，查看服务端脱敏日志 |
| HTTP `401/403` | 核对 `/mcp`、MCP Token、Host 与代理配置 |
| HTTP `413/422` | 分块资料或调整部署请求体上限 |
| HTTP `429` | 遵循等待时间并缩小并发/查询范围 |

只读工具可按同一参数重试。创建项目、添加资料、运行工作流、创建变体、导出、外部查询和旧删除
工具具有副作用；超时后先读取状态或列表，确认结果是否已经落盘。`yanzhang_add_material`
携带稳定 `material_id` 时可在同一项目内安全重放；省略时重试会创建新记录。版本更新采用最新版本号，避免
覆盖其他客户端的新改动。

## 11. 数据与引用边界

- 真实模型只接收当前步骤明确选中的任务内容和资料；`ModelProfile` 不保存密钥。
- `kind=style_reference` 的项目资料（包括文章来源）只用于学习结构、标题节奏、语气和句式；
  它不进入正文事实或证据链，正文事实仍以其他明确关联的项目资料和证据链为准。
- Crossref、OpenAlex、arXiv 查询会发送检索词或文献标识；本地格式导入本身不发起查询。
- DOI 规范化、`metadata_verified`、来源哈希、语义评分和参考文献排版各自表达不同证据层级。
- 项目数据、浏览器站点数据、导出、备份和第三方供应商记录应分别管理。

部署与令牌轮换见 [operations.md](operations.md)，环境变量见
[configuration.md](configuration.md)，隐私详情见 [../PRIVACY.md](../PRIVACY.md)。
