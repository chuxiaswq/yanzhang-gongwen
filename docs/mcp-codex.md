# 在 Codex 与通用 MCP 客户端中使用砚章

`v0.2.0-preview.2` 同时提供本机 stdio 和远程 Streamable HTTP。两种传输注册同一组工具并读取
同一项目数据；首选命令是 `yanzhang-mcp`，首选工具命名空间是 `yanzhang_*`。

## 1. 安装与本机注册

在砚章虚拟环境中安装项目：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

用绝对路径注册 stdio 服务：

```bash
codex mcp add yanzhang \
  --env YANZHANG_DATA_DIR=/ABSOLUTE/PATH/TO/PRIVATE-DATA \
  -- /ABSOLUTE/PATH/TO/VENV/bin/yanzhang-mcp --transport stdio
```

等价的 `~/.codex/config.toml`：

```toml
[mcp_servers.yanzhang]
command = "/ABSOLUTE/PATH/TO/VENV/bin/yanzhang-mcp"
args = ["--transport", "stdio"]

[mcp_servers.yanzhang.env]
YANZHANG_DATA_DIR = "/ABSOLUTE/PATH/TO/PRIVATE-DATA"
```

stdio 模式不需要远程 MCP Token；进程继承的环境中可配置 `YANZHANG_LLM_*`。使用与 Web 相同的
数据目录后，Codex 可继续网页中已建立的项目、资料和资产。

检查注册结果：

```bash
codex mcp list
codex mcp get yanzhang
```

## 2. 远程注册

服务器先按 [部署指南](../deploy/gongwen/README.md) 配置域名、HTTPS 和独立 MCP Token。客户端
环境只保存 MCP Token：

```bash
export YANZHANG_MCP_ACCESS_TOKEN=REPLACE_WITH_MCP_TOKEN
codex mcp add yanzhang \
  --url https://DOMAIN/mcp \
  --bearer-token-env-var YANZHANG_MCP_ACCESS_TOKEN
```

等价的 Codex 配置：

```toml
[mcp_servers.yanzhang]
url = "https://DOMAIN/mcp"
bearer_token_env_var = "YANZHANG_MCP_ACCESS_TOKEN"
```

通用客户端配置：

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

Web Token 与 MCP Token 是两个独立凭据。连接器配置只放 MCP Token，不放砚章服务器的模型
供应商密钥。

## 3. v0.2 工具目录

同一服务注册 45 个 `yanzhang_*` 工具；连同 26 个兼容 `gongwen_*` 工具共 71 个。

### 状态与场景包

| 工具 | 核心输入 | 作用 |
| --- | --- | --- |
| `yanzhang_get_status` | 无 | 查看项目、工作流、模型、学术和导出能力 |
| `yanzhang_list_scene_packs` | 可选 `channel`、`content_type` | 列出四个场景包与 19 个配方 |
| `yanzhang_get_scene_pack` | `pack_id` | 读取配方结构、渠道与事实策略 |

### 项目与资料

| 工具 | 核心输入 | 作用 |
| --- | --- | --- |
| `yanzhang_create_project` | `name`；可选描述、场景包、标签 | 创建隔离项目 |
| `yanzhang_list_projects` | 可选查询、场景包、分页 | 查找项目 |
| `yanzhang_get_project` | `project_id` | 读取项目元数据 |
| `yanzhang_upsert_project_term` | 项目、术语、首选表达；可选术语 ID、说明与不建议变体 | 新增或更新项目术语规则 |
| `yanzhang_list_project_terms` | `project_id`、分页 | 列出术语、首选表达和不建议变体 |
| `yanzhang_delete_project_term` | `project_id`、`term_id` | 删除一条项目术语规则 |
| `yanzhang_add_material` | `project_id`、`title`、`content`；可选 `material_id` | 添加来源、风格参考、历史稿、术语或笔记；稳定 ID 用于幂等更新 |
| `yanzhang_list_materials` | `project_id`；可选类型、标签、分页 | 列出项目资料 |
| `yanzhang_get_material` | `project_id`、`material_id`；可选分块参数 | 分块读取资料 |
| `yanzhang_search` | `project_id`、`query`；可选范围、标签、分页 | 在资料、资产和文献中统一检索 |

### 标题、工作流与资产

| 工具 | 核心输入 | 作用 |
| --- | --- | --- |
| `yanzhang_generate_titles` | 项目、主题、目标、受众、场景包、配方、文种 | 生成标题、开头、小标题或段首观点句候选 |
| `yanzhang_create_workflow` | 完整任务简报；可选 `brief_id`、自动审校和导出格式 | 创建可恢复工作流并返回绑定的 `brief_id` |
| `yanzhang_run_workflow` | `project_id`、`workflow_id`；可选同步/后台和恢复步骤 | 在项目作用域内运行或恢复工作流 |
| `yanzhang_get_workflow` | `project_id`、`workflow_id` | 查询项目内步骤、脱敏错误摘要与输出资产 |
| `yanzhang_cancel_workflow` | `project_id`、`workflow_id` | 请求取消项目内尚未完成的工作流 |
| `yanzhang_list_assets` | `project_id`；可选状态、文种、分页 | 列出母稿和渠道变体 |
| `yanzhang_get_asset` | `project_id`、`asset_id`；可选版本与分块 | 读取文字资产或历史版本 |
| `yanzhang_create_variant` | 项目、源资产、目标渠道 | 从指定版本派生渠道变体 |
| `yanzhang_list_revisions` | `project_id`、`asset_id`、分页 | 列出不可变版本快照 |
| `yanzhang_review_asset` | 项目、资产；可选检查项、资料、模型画像和 `live` | 只评分所选维度；显式实时模式叠加模型审校并返回实际路由 |
| `yanzhang_export_asset` | 项目、资产；可选版本、格式、模板、文件名 | 导出 DOCX/Markdown/文本/HTML/PDF/LaTeX/引用矩阵 CSV |

### 学术与研究写作

| 工具 | 核心输入 | 作用 |
| --- | --- | --- |
| `yanzhang_search_literature` | 项目、查询、Crossref/OpenAlex/arXiv | 查询公开文献元数据并保存候选 |
| `yanzhang_import_literature` | 项目、BibTeX/RIS/CSL-JSON 内容 | 解析并保存文献记录 |
| `yanzhang_list_literature` | 项目；可选查询、摘要和分页 | 列出已保存文献 |
| `yanzhang_get_literature` | `project_id`、`record_id` | 读取标准化元数据与来源追踪 |
| `yanzhang_list_evidence` / `yanzhang_get_evidence` | 项目、可选文献筛选或证据 ID | 列出或读取持久化证据片段 |
| `yanzhang_extract_evidence` | 项目、文献、正文；可选查询和数量 | 提取带哈希与位置的证据片段 |
| `yanzhang_build_literature_matrix` | 项目、文献 ID；可选证据和问题 | 比较研究对象、方法、发现与局限 |
| `yanzhang_list_literature_matrices` / `yanzhang_get_literature_matrix` | 项目、分页或矩阵 ID | 列出或读取持久化文献矩阵 |
| `yanzhang_list_research_claims` / `yanzhang_get_research_claim` | 项目、分页或主张 ID | 列出或读取持久化研究主张 |
| `yanzhang_list_citation_links` / `yanzhang_get_citation_link` | 项目、可选关系筛选或链接 ID | 列出或读取持久化引用关系 |
| `yanzhang_verify_citations` | 项目、文献、证据、研究主张、引用链接 | 逐项核验引用链与覆盖率 |
| `yanzhang_format_bibliography` | 项目、文献 ID、引用样式 | 输出基础 GB/T 7714、APA、MLA 或 Chicago 著录 |
| `yanzhang_suggest_academic_titles` | 研究简报；可选文献和数量 | 生成有来源边界的学术标题 |
| `yanzhang_create_academic_outline` | 研究简报、文献和证据 | 创建可追溯研究提纲 |
| `yanzhang_draft_abstract` | 研究简报；可选主张、链接和字数 | 起草带待补提示的摘要 |
| `yanzhang_review_academic_integrity` | 稿件及相关文献/证据/主张/期刊 | 检查引用谱系、稿件论断以及期刊必备章节和篇幅；自定义规则逐条转为人工核对项 |
| `yanzhang_prepare_rebuttal` | 项目、审稿意见、实际修改记录 | 生成逐条回复草稿 |

字段枚举、默认值和数量边界见 [完整 MCP 契约](gongwen-mcp.md)。工具 schema 设置
`additionalProperties: false`，未定义字段会作为参数错误返回。

四个场景包现共提供 19 个配方。`gongwen` 除工作总结、汇报材料、实施方案和会议纪要外，
新增 `leadership-speech`（领导讲话）与 `research-report`（调研报告）。`yanzhang_create_workflow` 还可传入
`selected_title`（1–300 字符）和最多 24 个 `structure_override` 章节；每节包含唯一
`id`、唯一 `title`、`purpose` 和 `required`，工作流将把这组有序章节用于提纲与母稿。

## 4. 推荐调用顺序

### 通用写作

1. `yanzhang_get_status` 检查能力；
2. `yanzhang_list_scene_packs` / `yanzhang_get_scene_pack` 选择配方；
3. `yanzhang_create_project` 建项目；
4. `yanzhang_add_material` 添加事实和风格资料；需要重试或同步时传稳定 `material_id` 做幂等写入，
   并用 `yanzhang_upsert_project_term` 维护首选术语；
5. `yanzhang_generate_titles` 先比较标题、开头、小标题或观点句；采用候选后将其写入 `selected_title`，
   有自定义结构时同时写入 `structure_override`；
6. 简报已由 Web/HTTP 保存时，把返回的 `brief_id` 传给 `yanzhang_create_workflow`；否则省略
   `brief_id` 由工作流创建并保存简报。即使传入 `brief_id`，仍须提交完整必填简报字段，
   且规范化后的内容必须与已存简报一致。再调用 `yanzhang_run_workflow`，并校验创建响应中的
   `brief_id` 以绑定项目母稿；后台模式用
   `yanzhang_get_workflow` 查询，必要时从明确步骤恢复；
7. `yanzhang_get_asset` 分块读取母稿，`yanzhang_create_variant` 派生邮件、演示、网页或社交版本；
8. `yanzhang_review_asset` 查看六维问题，修订后用 `yanzhang_list_revisions` 复核版本；
9. `yanzhang_export_asset` 交付选定版本。

工作流的运行、查询、取消和恢复始终同时传入创建时的 `project_id`。审校只希望本地规则时保持
`live=false`；显式使用服务端模型时传 `live=true`，并检查响应的 `effective_mode` 与
`resolved_route`。导出后优先按返回的项目作用域 Resource URI 读取文件。
运行、查询、取消或恢复响应的 `workflow.brief_id` 与创建时一致；只有创建响应另外提供顶层
`brief_id`。
`kind=style_reference` 的项目资料（包括选中的文章）只供结构、标题节奏、语气和句式参考，
不进入正文事实或证据链。

### 学术写作

1. 创建 `academic` 项目；
2. 用公开连接器搜索，或从 BibTeX/RIS/CSL-JSON 导入已有记录；
3. 读取记录并提取带来源哈希和位置的证据；
4. 建文献矩阵，再拟题和提纲；
5. 对每个关键主张建立 `ClaimCitationLink` 并运行引用核验；
6. 起草摘要，执行学术完整性检查，最后格式化参考文献；
7. 研究方法、统计结论、直接引语、页码和目标期刊细则由作者逐项复核。

## 5. 示例提示

连接成功后可直接对 Codex 说明：

```text
用砚章创建一个“季度经营复盘”项目，选择 workplace/weekly-report；先把我提供的三份资料
存入项目，再生成 8 个标题并解释排序。等我选题后创建母稿，派生一版工作邮件和一版 PPT 提纲，
完成六维审校，但先不要导出。
```

学术示例：

```text
在砚章 academic 项目中导入这份 CSL-JSON，围绕给定研究问题建立文献矩阵；只基于来源哈希
匹配的证据生成提纲，标出未知文献、缺页码、数字证据不足和需要人工核对的方法结论。
```

## 6. 兼容工具与资源

已有 26 个 `gongwen_*` 工具继续提供原公文拟题、成文、改写、审校、文章库、版本与 Word 导出。
已有 6 类 `gongwen://` Resources 和 4 个 Prompt 继续注册。v0.2 另提供 11 类项目化
`yanzhang://` Resources：一类按项目读取导出工件，十类按项目列出/读取文献、证据、矩阵、研究
主张与引用关系。旧命令 `gongwen-mcp` 和 `GONGWEN_*` 配置也继续读取。

v0.2 导出 URI 为 `yanzhang://projects/{project_id}/exports/{artifact_id}`，读取时校验项目归属；
旧 `gongwen://exports/{id}` 只读取兼容工具生成的未分项目工件。导出元数据同时包含项目、资产、
修订和创建操作。学术 Resource 的完整 URI 表见
[完整 MCP 契约](gongwen-mcp.md#8-resources-与兼容-prompts)。

新项目优先使用 `yanzhang_*`，因为它显式表达项目、资料、母稿/变体、工作流和学术关系；已有
自动化可继续调用 `gongwen_*`。两套工具是独立名字，不通过 alias 覆盖彼此。

## 7. 隐私与故障处理

- stdio 参数在本机进程间传递；远程模式的工具参数通过部署域名发送，公网入口使用 HTTPS。
- 公开来源或真实模型工具具有网络副作用；先缩小资料和查询范围，再调用相应步骤。
- 已保存的 `brief_id` 同时绑定项目与规范化内容；相同输入可安全重放，内容变化时使用新 ID。
- MCP 返回稳定错误类别，如 `invalid_request`、`brief_conflict`、`project_scope_error`、`not_found`、
  `operation_timeout` 和 `internal_error`；修正字段或状态后重试，不把完整请求正文复制到日志。
- 后台工作流超时后先查询状态；导出与发布前核对目标资产 ID 和版本，避免重复动作。
- `metadata_verified`、DOI 规范化、引用评分和参考文献排版的边界见
  [academic-writing.md](academic-writing.md)。

移除 Codex 注册使用 `codex mcp remove yanzhang`；服务器令牌轮换见
[operations.md](operations.md)。
