# 砚章 HTTP API v2

`v0.2.0-preview.2` 的 `/api/v2/*` 是“砚章·AI文字工作台”的项目化写作接口。正式路由以项目
为边界，覆盖公文、职场沟通、内容传播和学术研究；旧 `/api/*` 公文接口继续保留原路径与语义。

## 1. 协议约定

- 请求与响应使用 UTF-8 JSON，字段名采用 `snake_case`。
- 生产部署使用 `Authorization: Bearer WEB_TOKEN`；远程 `/mcp` 使用另一枚 MCP Token。
- JSON 请求设置 `Content-Type: application/json`。所有 v2 JSON 与文件响应均带
  `Cache-Control: no-store`。
- 项目资源 ID 由路径确定。正文再次携带同名 ID 时必须一致，错配返回 `409 identity_mismatch`。
- 时间使用带时区的 ISO 8601；ID 是不透明字符串，客户端不解析其结构。
- Provider 凭据由服务端环境持有，不属于 HTTP 请求模型。

标准分页列表为：

```json
{
  "items": [],
  "count": 0,
  "total": 0,
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

`count` 是本页数量，`total` 是筛选后的总数。场景包等非分页目录只返回 `items` 与 `count`；
工作流定义目录返回 `items/count/total/limit/offset`。分块读取资料或资产时，对象内包含
`chunk_offset`、`chunk_size`、`total_characters`、`has_more` 和 `next_offset`。

错误外壳为：

```json
{
  "error": {
    "code": "validation_error",
    "message": "请求字段校验失败",
    "details": [
      {"field": "name", "message": "String should have at least 1 character", "type": "string_too_short"}
    ]
  }
}
```

`details` 仅在存在结构化字段信息时出现，最多返回 20 项，且不回显密钥、完整请求或上游正文。
常见状态为 `400 invalid_json`、`409 identity_mismatch`、`413 request_too_large`、
`415 unsupported_media_type`、`422 validation_error`、`404 not_found`、`504 operation_timeout` 和
`500 internal_error`。

## 2. 正式路由目录

### 平台、项目与资料

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/v2/bootstrap` | 查看 v2 存储、模型路由、场景包、学术连接器与导入导出能力 |
| `GET` | `/api/v2/scene-packs` | 列出场景包，可按 `channel`、`content_type` 筛选 |
| `GET` | `/api/v2/scene-packs/{pack_id}` | 读取场景包、配方、内容块和事实策略 |
| `GET` | `/api/v2/workflow-definitions` | 分页读取可执行写作配方，可按 `scenario_pack_id` 筛选 |
| `POST` | `/api/v2/projects` | 创建写作项目 |
| `GET` | `/api/v2/projects` | 分页查询项目 |
| `GET` | `/api/v2/projects/{project_id}` | 读取项目 |
| `POST` | `/api/v2/projects/{project_id}/terms` | 新增或更新项目术语规则 |
| `GET` | `/api/v2/projects/{project_id}/terms` | 分页列出项目术语规则 |
| `DELETE` | `/api/v2/projects/{project_id}/terms/{term_id}` | 删除一条项目术语规则 |
| `POST` | `/api/v2/projects/{project_id}/briefs` | 保存规范化任务简报 |
| `POST` | `/api/v2/projects/{project_id}/materials` | 添加一项项目资料 |
| `GET` | `/api/v2/projects/{project_id}/materials` | 按类型、标签分页列出资料 |
| `GET` | `/api/v2/projects/{project_id}/materials/{material_id}` | 分块读取资料 |
| `POST` | `/api/v2/projects/{project_id}/materials/import` | 从 Base64 文档解析并保存资料 |
| `GET` | `/api/v2/projects/{project_id}/search` | 在资料、资产和文献中统一检索 |
| `POST` | `/api/v2/projects/{project_id}/headlines` | 生成标题、开头、小标题或段首观点句 |

### 工作流、资产与交付

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v2/projects/{project_id}/workflows` | 创建可恢复写作工作流 |
| `POST` | `/api/v2/projects/{project_id}/workflows/{workflow_id}/run` | 同步/后台运行或恢复工作流 |
| `GET` | `/api/v2/projects/{project_id}/workflows/{workflow_id}` | 查询步骤、错误摘要与输出资产 |
| `POST` | `/api/v2/projects/{project_id}/workflows/{workflow_id}/cancel` | 请求取消尚未结束的工作流 |
| `POST` | `/api/v2/projects/{project_id}/assets` | 从已保存任务简报生成并保存母稿 |
| `GET` | `/api/v2/projects/{project_id}/assets` | 分页列出母稿与渠道变体 |
| `GET` | `/api/v2/projects/{project_id}/assets/{asset_id}` | 分块读取当前资产或指定版本 |
| `POST` | `/api/v2/projects/{project_id}/assets/{asset_id}/variants` | 从指定版本派生渠道变体 |
| `GET` | `/api/v2/projects/{project_id}/assets/{asset_id}/revisions` | 列出不可变版本快照 |
| `POST` | `/api/v2/projects/{project_id}/assets/{asset_id}/revisions` | 以乐观并发检查保存新版本 |
| `POST` | `/api/v2/projects/{project_id}/assets/{asset_id}/review` | 对指定资产执行六维审校 |
| `POST` | `/api/v2/projects/{project_id}/assets/{asset_id}/export` | 导出指定资产版本 |
| `GET` | `/api/v2/projects/{project_id}/exports/{artifact_id}` | 按项目归属下载已登记导出工件 |

### 学术研究

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v2/projects/{project_id}/academic/literature/search` | 查询 Crossref、OpenAlex 或 arXiv 元数据并保存候选 |
| `POST` | `/api/v2/projects/{project_id}/academic/literature/import` | 导入 BibTeX、RIS 或 CSL-JSON |
| `GET` | `/api/v2/projects/{project_id}/academic/literature` | 分页列出或检索项目文献记录 |
| `GET` | `/api/v2/projects/{project_id}/academic/literature/{record_id}` | 读取标准化文献记录 |
| `POST` | `/api/v2/projects/{project_id}/academic/evidence/extract` | 从给定正文提取带哈希与位置的证据 |
| `GET` | `/api/v2/projects/{project_id}/academic/evidence` | 分页列出证据，可按 `record_id` 筛选 |
| `GET` | `/api/v2/projects/{project_id}/academic/evidence/{evidence_id}` | 读取一条证据与来源谱系 |
| `POST` | `/api/v2/projects/{project_id}/academic/matrix` | 建立文献矩阵 |
| `GET` | `/api/v2/projects/{project_id}/academic/matrices` | 分页列出已保存文献矩阵 |
| `GET` | `/api/v2/projects/{project_id}/academic/matrices/{matrix_id}` | 读取一个文献矩阵 |
| `GET` | `/api/v2/projects/{project_id}/academic/claims` | 分页列出已保存研究主张 |
| `GET` | `/api/v2/projects/{project_id}/academic/claims/{claim_id}` | 读取一条研究主张 |
| `GET` | `/api/v2/projects/{project_id}/academic/citation-links` | 分页列出引用链，可按主张/文献/证据筛选 |
| `GET` | `/api/v2/projects/{project_id}/academic/citation-links/{link_id}` | 读取一条引用链 |
| `POST` | `/api/v2/projects/{project_id}/academic/citations/verify` | 核验论断—文献—证据链接 |
| `POST` | `/api/v2/projects/{project_id}/academic/bibliography` | 输出基础参考文献著录 |
| `POST` | `/api/v2/projects/{project_id}/academic/titles` | 生成学术标题候选 |
| `POST` | `/api/v2/projects/{project_id}/academic/outline` | 生成研究提纲 |
| `POST` | `/api/v2/projects/{project_id}/academic/abstract` | 起草研究摘要 |
| `POST` | `/api/v2/projects/{project_id}/academic/integrity` | 检查引用谱系与研究完整性 |
| `POST` | `/api/v2/projects/{project_id}/academic/rebuttal` | 生成逐条审稿回复草稿 |

## 3. 状态、场景包与工作流定义

`GET /api/v2/bootstrap` 无业务参数，返回存储就绪状态、模型路由、4 个场景包/17 个配方的数量、
导入导出格式以及可用学术连接器。敏感配置只表达能力是否就绪。

```text
GET /api/v2/scene-packs?channel=document&content_type=工作总结
GET /api/v2/scene-packs/gongwen
GET /api/v2/workflow-definitions?scenario_pack_id=gongwen&limit=20&offset=0
```

`pack_id` 为 `gongwen`、`workplace`、`media` 或 `academic`。渠道为 `document`、`email`、
`meeting`、`presentation`、`web`、`social` 或 `academic`。工作流定义返回配方 ID、名称、说明、
场景包、文种、渠道、步骤和输出格式，可直接用于前端配方选择器。

## 4. 项目、任务简报与资料

### 创建项目

`POST /api/v2/projects`

```json
{
  "name": "季度经营复盘",
  "description": "汇总经营事实并派生多渠道版本",
  "scenario_pack_id": "workplace"
}
```

`name` 1–200 字符，描述最多 2000 字符；`scenario_pack_id` 默认 `gongwen`。查询项目使用：

```text
GET /api/v2/projects?query=季度&scenario_pack_id=workplace&limit=20&offset=0
GET /api/v2/projects/PROJECT_ID
```

### 项目术语

`POST /api/v2/projects/PROJECT_ID/terms` 新增术语；携带已有 `term_id` 时更新该项目内的同一条规则：

```json
{
  "term": "文字资产",
  "preferred_form": "文字资产",
  "description": "统一表述可编辑母稿与渠道变体",
  "discouraged_variants": ["文稿对象", "稿件资源"]
}
```

`term` 和 `preferred_form` 各 1–200 字符，说明最多 500 字符，不建议变体最多 32 项。列表使用
`GET /api/v2/projects/PROJECT_ID/terms?limit=20&offset=0`；删除使用
`DELETE /api/v2/projects/PROJECT_ID/terms/TERM_ID`。术语规则参与 `terminology` 审校，且所有读写都校验
项目归属。

### 保存任务简报

`POST /api/v2/projects/PROJECT_ID/briefs`

```json
{
  "title": "第三季度经营复盘",
  "goal": "形成面向管理层的结论与下一步行动",
  "audience": "经营管理层",
  "channel": "document",
  "content_type": "周报",
  "scenario_pack_id": "workplace",
  "recipe_id": "weekly-report",
  "tone": "凝练、结论先行",
  "length": "standard",
  "target_language": "zh-CN",
  "constraints": ["标题采用三段同构排比"],
  "keywords": ["增长", "问题", "行动"],
  "material_ids": ["MATERIAL_ID"],
  "model_profile_id": null
}
```

`title` 也接受 `topic` 作为输入别名；`material_ids` 也接受 `knowledge_item_ids`。保存前会校验
场景包、配方、渠道及资料均属于该项目。响应中的 `brief.id` 用于后续生成母稿。

### 添加、导入与读取资料

`POST /api/v2/projects/PROJECT_ID/materials`

```json
{
  "title": "第三季度经营数据",
  "content": "经核对的正文或数据说明",
  "kind": "source",
  "source_url": "https://SOURCE.example/item",
  "tags": ["经营", "已核对"]
}
```

`kind` 为 `source`、`style_reference`、`prior_asset`、`terminology` 或 `note`；内容最多
500000 字符，URL 最多 2000 字符，标签最多 64 项。

文件导入接受 TXT、Markdown、HTML、DOCX 与 PDF：

```json
{
  "filename": "调研材料.docx",
  "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "content_base64": "BASE64_DOCUMENT_BYTES",
  "mode": "merge",
  "title": "调研材料",
  "kind": "source",
  "source_url": "",
  "tags": ["调研"]
}
```

`mode=merge` 将解析结果合并为一项资料；`mode=blocks` 按非空内容块分别保存。输入先经过文件
类型、大小、压缩结构、活动内容和外链限制，再进入资料库。`data_base64` 是
`content_base64` 的兼容别名。

```text
GET /api/v2/projects/PROJECT_ID/materials?kind=source&tags=经营,已核对&limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/materials/MATERIAL_ID?chunk_offset=0&chunk_size=8000
GET /api/v2/projects/PROJECT_ID/search?query=经营成效&scope=all&limit=20&offset=0
```

`scope` 为 `all`、`materials`、`assets` 或 `literature`；标签既可逗号分隔，也可重复提供同名
查询参数。

## 5. 标题与开头

`POST /api/v2/projects/PROJECT_ID/headlines` 使用与工作流相同的任务简报字段，但主题字段名为
`topic`，并增加 `count`、`headline_kind` 与 `formula_ids`：

```json
{
  "topic": "第三季度经营复盘",
  "goal": "形成面向管理层的结论与下一步行动",
  "audience": "经营管理层",
  "content_type": "周报",
  "scenario_pack_id": "workplace",
  "recipe_id": "weekly-report",
  "channel": "document",
  "tone": "凝练、结论先行",
  "length": "standard",
  "target_language": "zh-CN",
  "constraints": ["标题采用三段同构排比"],
  "keywords": ["增长", "问题", "行动"],
  "material_ids": ["MATERIAL_ID"],
  "count": 8,
  "headline_kind": "title",
  "formula_ids": []
}
```

`headline_kind` 为 `title`、`opening`、`section_heading` 或 `topic_sentence`；`count` 1–12。
响应返回候选、评分与方法说明，不创建文字资产。

### 可解释表达公式目录

标题内核先生成并评分当前类型下的全部合格公式，再按总分截取 `count`，因此排在目录后部但更适合
当前主题的公式也可进入推荐结果。传入 `formula_ids` 时，仅在指定公式中全局评分；未知 ID、重复
ID 或与 `headline_kind` 不匹配的 ID 返回字段校验错误。候选同时返回 `formula_id`、
`formula_name`、`techniques`、`rationale` 和七项评分，便于页面解释排序依据。

| 表达位置 | 代表公式 ID | 结构说明 |
| --- | --- | --- |
| 大标题 | `main-subtitle`、`parallel-triad`、`parallel-quartet`、`antithesis`、`progression`、`numbered-quartet` | 主副题、三段/四段排比、对偶、递进及“一二三四”式 |
| 开头 | `direct`、`parallel-triad`、`parallel-quartet`、`antithesis`、`progression`、`evidence` | 开门见山、排比导入、对偶判断、递进导入和证据边界 |
| 小标题 | `topic-colon`、`parallel-triad`、`parallel-quartet`、`antithesis`、`progression` | 主副式小标题、三段/四段动作链、对偶和递进 |
| 段首句 | `direct`、`parallel-triad`、`parallel-quartet`、`antithesis`、`progression`、`evidence` | 直接统领、排比统领、对偶判断、递进判断和证据提示 |

这些公式只重组任务简报中的主题、目标、受众、文种和表达焦点；模板不补造数字、日期、机构、
成果或引语。阿拉伯数字若未出现在简报事实边界中，会降低 `factual_restraint` 评分。

## 6. 工作流

### 创建

`POST /api/v2/projects/PROJECT_ID/workflows` 使用上节的任务简报公共字段，并增加：

```json
{
  "auto_review": true,
  "requested_exports": ["docx", "markdown"]
}
```

完整请求中仍需包含 `topic`、`goal`、`audience`、`content_type`、`scenario_pack_id` 与
`recipe_id`。`requested_exports` 最多 7 个唯一值，可选 `docx`、`markdown`、`text`、`html`、
`pdf`、`latex`、`csv`。创建响应返回工作流状态与步骤计划。

### 运行、恢复和取消

```text
POST /api/v2/projects/PROJECT_ID/workflows/WORKFLOW_ID/run
GET  /api/v2/projects/PROJECT_ID/workflows/WORKFLOW_ID
POST /api/v2/projects/PROJECT_ID/workflows/WORKFLOW_ID/cancel
```

运行请求体：

```json
{
  "mode": "background",
  "resume_from": null
}
```

`mode` 为 `sync` 或 `background`。首次运行处于 `queued` 状态时可省略 `resume_from`；显式提供时，
它必须等于服务端记录的首个未成功步骤。`failed` 和 `waiting_review` 状态恢复时必须提供该校验值，
避免重复已经成功的步骤；它不是任意回退或重跑指令。`succeeded` 和 `cancelled` 已是终态：省略
`resume_from` 时返回当前结果，提供时返回状态错误。合法恢复同样支持 `background`，接口在校验并
入队后返回，再通过 GET 查询。步骤值为 `research`、`titles`、`outline`、`draft`、`review` 或
`export`。超时后先查询工作流的步骤状态与输出资产 ID，再提交首个未成功步骤。
扁平兼容路径 `/api/v2/workflows/{workflow_id}[/run|/cancel]` 必须在请求体或查询中携带
`project_id`；新客户端使用上述项目路径。持久化工作流错误只返回稳定错误码和脱敏消息。

## 7. 母稿、变体与版本

### 从任务简报生成母稿

`POST /api/v2/projects/PROJECT_ID/assets`

```json
{
  "brief_id": "BRIEF_ID",
  "title": "第三季度经营复盘",
  "live": false
}
```

`brief_id` 必须属于当前项目。`live=false` 使用确定性本地组合器；`live=true` 由服务端模型画像与
路由决定。创建成功后同时写入母稿和第一个不可变版本。

### 列表与分块读取

```text
GET /api/v2/projects/PROJECT_ID/assets?status=draft&content_type=周报&limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/assets/ASSET_ID?revision=1&chunk_offset=0&chunk_size=8000
```

`status` 为 `draft`、`reviewed`、`final` 或 `archived`。省略 `revision` 时读取当前版本。

### 保存新版本

`POST /api/v2/projects/PROJECT_ID/assets/ASSET_ID/revisions`

```json
{
  "expected_revision": 1,
  "note": "调整开头并补充依据",
  "title": "第三季度经营复盘",
  "status": "reviewed",
  "blocks": [
    {
      "id": "BLOCK_ID",
      "kind": "paragraph",
      "order": 0,
      "text": "开门见山提出本期判断。",
      "locked": false,
      "knowledge_item_ids": ["MATERIAL_ID"],
      "evidence_ids": []
    }
  ]
}
```

传 `expected_revision` 可检测并发编辑；命中冲突时读取最新资产与版本，再合并内容块。省略
`blocks` 时沿用现有内容，仍可调整标题、状态或版本说明。版本列表使用：

```text
GET /api/v2/projects/PROJECT_ID/assets/ASSET_ID/revisions?limit=20&offset=0
```

### 渠道变体

`POST /api/v2/projects/PROJECT_ID/assets/ASSET_ID/variants`

```json
{
  "target_channel": "presentation",
  "instruction": "压缩为 8 页 PPT 提纲，每页一个结论",
  "source_revision": 1,
  "model_profile_id": null,
  "live": false
}
```

变体作为独立资产保存，并通过 `parent_asset_id` 关联母稿；省略 `source_revision` 时使用当前版本。

### 六维审校

`POST /api/v2/projects/PROJECT_ID/assets/ASSET_ID/review`

```json
{
  "checks": ["structure", "style", "facts", "citations", "terminology"],
  "material_ids": ["MATERIAL_ID"],
  "model_profile_id": null,
  "live": false
}
```

`checks` 映射为事实与证据、逻辑与结构、清晰与简洁、受众与语气、语言与规范、格式与交付维度；
响应只返回并评分本次所选维度。`live=false` 使用本地确定性审校，`live=true` 才请求服务端模型
增强。响应含 `effective_mode`、`resolved_route`、`requested_model_profile_id` 与
`model_issue_count`。审校响应与正文分开；采纳修改后用版本端点保存新快照。

### 导出与下载

`POST /api/v2/projects/PROJECT_ID/assets/ASSET_ID/export`

```json
{
  "format": "docx",
  "revision": 1,
  "template_id": "standard",
  "filename": "季度经营复盘.docx"
}
```

格式为 `docx`、`markdown`、`text`、`html`、`pdf`、`latex` 或 `csv`；其中 `csv` 输出带有来源、
定位和哈希的引用矩阵。DOCX 按 `ContentBlock.kind` 与 `heading_level` 建立段落，并避免重复输出资产
标题。`template_id` 仅适用于 DOCX，可选 `standard` 或 `brief`；省略时使用 `standard`。
响应包含 `artifact_id`、文件名、媒体类型、大小、SHA-256、`project_id`、`asset_id`、
`revision_id`、`creator` 和项目作用域的 `yanzhang://` Resource URI；随后通过
`GET /api/v2/projects/PROJECT_ID/exports/ARTIFACT_ID` 下载。扁平
`/api/v2/exports/ARTIFACT_ID` 仅用于旧版未分项目工件。下载响应采用附件 Content-Disposition、
`nosniff` 与 `no-store`。导出文件是可重建派生产物，资产版本是正文事实源。

## 8. 学术接口

### 文献、证据与引用

```text
POST /api/v2/projects/PROJECT_ID/academic/literature/search
```

```json
{"query":"digital governance","provider":"crossref","limit":10}
```

`query` 长度为 1–1000 字符；`provider` 为 `crossref`、`openalex` 或 `arxiv`。查询会访问公开
元数据服务，并把返回候选保存到当前项目。文件导入示例：

```text
POST /api/v2/projects/PROJECT_ID/academic/literature/import
```

```json
{"format":"bibtex","content":"@article{key,title={Title}}","tags":["治理"]}
```

`format` 为 `bibtex`、`ris` 或 `csl-json`。`tags` 会与每条记录已有的 `keywords` 去重合并并保存，
合计最多 100 项。读取记录使用：

```text
GET /api/v2/projects/PROJECT_ID/academic/literature?query=治理&include_abstract=false&limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/academic/literature/RECORD_ID?include_abstract=true
```

文献、证据、文献矩阵、研究主张和引用链都提供项目级分页列表与单条读取，列表均返回标准
`items/count/total/limit/offset/has_more` 外壳：

```text
GET /api/v2/projects/PROJECT_ID/academic/evidence?record_id=RECORD_ID&limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/academic/evidence/EVIDENCE_ID
GET /api/v2/projects/PROJECT_ID/academic/matrices?limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/academic/matrices/MATRIX_ID
GET /api/v2/projects/PROJECT_ID/academic/claims?limit=20&offset=0
GET /api/v2/projects/PROJECT_ID/academic/claims/CLAIM_ID
GET /api/v2/projects/PROJECT_ID/academic/citation-links?claim_id=CLAIM_ID&record_id=RECORD_ID&evidence_id=EVIDENCE_ID
GET /api/v2/projects/PROJECT_ID/academic/citation-links/LINK_ID
```

每个 ID 都必须属于路径中的项目；跨项目单条读取返回 `404 not_found`，列表不会混入其他
项目记录。客户端在项目切换或本地缓存丢失后，使用这五类列表重建可继续操作的学术工作区。

证据与引用的核心请求：

```text
POST /api/v2/projects/PROJECT_ID/academic/evidence/extract
POST /api/v2/projects/PROJECT_ID/academic/matrix
POST /api/v2/projects/PROJECT_ID/academic/citations/verify
POST /api/v2/projects/PROJECT_ID/academic/bibliography
```

- 证据提取需要 `record_id` 与 `text`，可传 `query`、`max_snippets`；
- 文献矩阵需要 `record_ids`，可传 `evidence_ids`、`query`；
- 引用核验需要 `record_ids`、`evidence_ids` 和 `claims`，可传 `links`；
- 参考文献需要 `record_ids`，样式为 `gb-t-7714`、`apa`、`mla` 或 `chicago`。

核验只使用当前项目内、调用时明确选择的文献记录与证据。DOI 规范化不代表元数据已经核实；
`metadata_verified` 只由公开连接器返回记录设置。

### 标题、提纲、摘要、完整性与审稿回复

这组端点共享研究简报字段：`title`、`research_question`，以及可选的 `discipline`、`purpose`、
`audience`、`document_type`、`language`、`keywords`、`constraints`、`method_notes`、`record_ids`。

```text
POST /api/v2/projects/PROJECT_ID/academic/titles
POST /api/v2/projects/PROJECT_ID/academic/outline
POST /api/v2/projects/PROJECT_ID/academic/abstract
POST /api/v2/projects/PROJECT_ID/academic/integrity
POST /api/v2/projects/PROJECT_ID/academic/rebuttal
```

- 标题可传 `count`（1–10，默认 5）；提纲可传 `evidence_ids`；摘要可传 `claims`、`links`、`max_characters`；
- 完整性检查需要 `manuscript`，并可传文献、证据、论断、链接与 `journal`。其中 `journal`
  支持 `required_sections`、`title_max_characters`、`abstract_max_characters`、
  `manuscript_max_words` 和 `custom_rules`；响应同时返回 `manuscript_characters`、混合语言
  计词的 `manuscript_words` 与 `journal_profile_id`；
- 审稿回复需要 `comments`，可用 `changes` 映射每条意见对应的实际修改。

字段结构、数量限制和引用真实性边界见 [学术写作指南](academic-writing.md) 与
[MCP 完整契约](gongwen-mcp.md)。HTTP 与 MCP 调用同一应用服务和项目数据库。

## 9. 浏览器兼容别名

v0.2 页面保留下列扁平路径，便于渐进升级。新集成优先使用第 2 节的项目嵌套路由；调用别名时
在请求体或查询参数显式传 `project_id`。

| 兼容路径 | 对应正式能力 |
| --- | --- |
| `POST /api/v2/writing/briefs` | 保存任务简报 |
| `POST /api/v2/headlines/generate` | 生成标题类候选 |
| `GET/POST /api/v2/knowledge` | 列出/添加项目资料 |
| `GET /api/v2/knowledge/search` | 统一检索 |
| `GET/POST /api/v2/assets` | 列出/创建资产 |
| `/api/v2/assets/{asset_id}/*` | 读取、变体、版本、审校与导出 |
| `/api/v2/academic/*` | 学术搜索、导入、证据、引用和研究写作 |

正式服务不再使用 `/api/v2/writing/jobs`；页面中的开头、小标题和段首句统一通过
`headline_kind` 调用标题端点。

## 10. 副作用、并发与兼容 `/api/*`

- GET 状态、目录、列表、读取和搜索可按相同参数重试。
- POST 创建项目、资料、简报、工作流、资产、版本、变体、导出和学术记录具有持久化副作用；
  请求超时后先查询相应资源。
- 母稿与变体分别维护版本。编辑保存时携带最新 `expected_revision`，以便识别并发冲突。
- 真实模型、文章来源与学术元数据请求在 SQLite 事务外执行，结果通过短事务写入。
- v0.1 `/api/*` 继续服务原公文页面与自动化，包括健康/就绪、方法论、拟题、生成、改写、审校、
  事实审校、模型连接、文稿/版本、文章来源和 DOCX/批量导出。

两套 API 使用同一 Web Token、中间件和数据目录；旧路径保持原请求/响应语义。部署、数据迁移与
回退步骤见 [运维手册](operations.md)。
