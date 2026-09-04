# 砚章·AI文字工作台运维手册

本文适用于 `v0.2.0-preview.2` 的个人服务器部署，覆盖启动检查、备份恢复、v0.1 升级、令牌
轮换、任务恢复和常见故障。完整环境变量见 [configuration.md](configuration.md)，容器首次部署见
[../deploy/gongwen/README.md](../deploy/gongwen/README.md)。

## 1. 运行基线

- Python 3.12 或 Docker Engine + Docker Compose v2。
- 本机默认监听 `127.0.0.1`；公网入口使用域名和 HTTPS。
- SQLite 个人版只运行一个应用工作进程，反向代理负责并发连接。
- Web/API 与 MCP 使用两枚不同的随机 Bearer Token，生产值各至少 32 字节。
- 数据目录或 Docker 持久卷只授予应用身份写权限；`.env` 权限为 `0600`。
- 访问日志默认关闭；开启时只记录方法、路径、状态码和耗时，不记录查询条件、客户端地址、
  请求头或正文；错误日志不收集正文、模型密钥或完整令牌。

首选配置名是 `YANZHANG_*`。旧 `GONGWEN_*` 同名后缀继续生效；两者并存时采用前者。部署
对象名称和脚本路径继续保留 `gongwen`，便于已有卷、网络和备份原地升级。

## 2. 启动与就绪检查

### 本机进程

```bash
export YANZHANG_DATA_DIR=/ABSOLUTE/PATH/TO/PRIVATE-DATA
yanzhang-web --host 127.0.0.1 --port 8787
```

浏览器打开 `http://127.0.0.1:8787/`。MCP 本机客户端使用 `yanzhang-mcp --transport stdio`；
stdio 进程与 Web 指向同一 `YANZHANG_DATA_DIR` 时共享项目与资产。

### 容器

```bash
./deploy/gongwen/scripts/start.sh
./deploy/gongwen/scripts/health.sh
```

`start.sh` 以根目录 `.env.example` 为模板创建私有 `deploy/gongwen/.env`，补齐两枚独立令牌，
校验配置，再等待应用和代理容器健康。`health.sh` 继续检查 SQLite schema、Web 鉴权、MCP 独立
凭据，以及 `/api/v2/projects` 和 `/api/v2/bootstrap` 公共能力入口。原有
`deploy/gongwen/*.sh` 入口继续兼容；
新运维记录统一使用 `deploy/gongwen/scripts/*`。

查看进程状态与近期日志：

```bash
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml ps
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml logs --tail=200
```

诊断时先记录时间、版本、失败入口、HTTP 状态或 MCP 错误码；不要把请求正文、认证头、查询词和
真实文件写入工单。需要临时开启访问日志时，先设置访问权限与短期保留，排障完成后关闭并清理；
应用日志已经省略查询字符串、客户端地址、请求头和正文。

## 3. 备份

更新、迁移、令牌调整和恢复演练前先创建一致性备份：

```bash
./deploy/gongwen/scripts/backup.sh [备份目录]
```

脚本通过 SQLite 在线备份 API 创建自包含快照，校验完整性与 schema，再原子发布到
`deploy/gongwen/backups/` 并生成 SHA-256。快照包含同一数据库内的旧公文表和 v0.2 项目、资料、
资产、证据、工作流及审计表。

备份策略建议：

1. 保留至少一个升级前快照和一个最近已验证快照；
2. 把副本同步到加密、访问隔离的异机存储；
3. 记录版本、创建时间、哈希和恢复演练结果，不记录正文；
4. 将浏览器本地草稿、已下载导出和外部插件数据视为独立数据源，按各自流程备份；
5. 定期在临时实例执行恢复演练，而不只检查文件存在。

在线检查数据库：

```bash
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml \
  exec -T gongwen gongwen-admin --database /var/lib/gongwen/gongwen.sqlite3 check
```

## 4. 恢复

恢复会替换当前数据库。先创建当前状态备份，再选择已校验快照：

```bash
./deploy/gongwen/scripts/restore.sh \
  deploy/gongwen/backups/gongwen-YYYYMMDDTHHMMSSZ-PID-RANDOM.sqlite3 --yes
```

恢复流程会取得部署锁、停止服务、检查备份完整性和必需表、原子替换数据库、恢复文件属主与权限、
重新启动并复检。完成后依次验证：

1. `./deploy/gongwen/scripts/health.sh` 通过；
2. 项目、旧文稿、知识资料和文字资产数量符合备份时间点；
3. 任取一个母稿与渠道变体，版本关系可读；
4. 任取一个带证据的资产，来源定位和引用关系可读；
5. Web 和 MCP 两类客户端都能使用各自令牌访问。

备份文件与 `.env` 分开保存；数据库恢复后，当前访问令牌、域名和模型配置保持原值。

## 5. 从 v0.1 升级到 v0.2

v0.2 保留旧 API、MCP、环境变量、SQLite 表和命名卷。首选升级入口会先生成已校验备份，再拉取
固定的代理镜像、重建应用、原地复用 `gongwen-web-data`，最后执行健康检查：

```bash
./deploy/gongwen/scripts/upgrade.sh [备份目录]
```

推荐验收顺序：

1. 记录当前版本并停止批量任务；
2. 拉取 `v0.2.0-preview.2`，保留当前 `.env` 和命名卷，运行上述升级入口；
3. 用旧 `/api/*` 与 `gongwen_*` 抽查既有文稿和自动化；
4. 通过 `/api/v2/*` 或 `yanzhang_*` 抽查场景包、项目、资料、标题、母稿、版本和证据关系；
5. 需要把旧文稿复制为新 `TextAsset` 时，在应用容器中调用幂等迁移，并保存返回的
   `assets_created`、`assets_existing`、`revisions_created` 和 `revisions_existing` 计数：

   ```bash
   docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml \
     exec -T gongwen python -c \
     'from yanzhang_core import WritingStorage; print(WritingStorage("/var/lib/gongwen/gongwen.sqlite3").migrate_legacy_gongwen())'
   ```

6. 迁移只复制旧表的标识、时间和完整版本序列；原表保持原值，重复运行会报告已存在记录；
7. 逐步添加 `YANZHANG_*` 变量。新旧同名变量同时存在时，确认实际读取的是新前缀值；
8. 保留升级前快照，直至关键项目与客户端完成验收。

如需回退：停止新写入，备份当前数据库，切回旧镜像并恢复升级前快照。v0.2 新表对旧版本属于额外
数据，但使用升级前快照能避免旧程序与升级后写入交叉。

## 6. 令牌与模型密钥轮换

只在可信交互式终端查看部署生成的令牌：

```bash
./deploy/gongwen/show-token.sh web
./deploy/gongwen/show-token.sh mcp
```

`show-token.sh` 是保留的兼容运维入口；首选启动、检查、备份、恢复和升级入口均位于
`deploy/gongwen/scripts/`。

轮换步骤：

1. 在 `.env` 中把目标令牌改成相应 `CHANGE_ME_...` 占位值；
2. 运行 `./deploy/gongwen/scripts/start.sh`，脚本生成新值并原子保存；
3. 只向对应客户端更新 Web 或 MCP 凭据；
4. 运行 `./deploy/gongwen/scripts/health.sh`，确认旧凭据失效、新凭据工作；
5. 清除终端滚动记录、剪贴板和临时配置副本。

模型密钥在供应商侧创建新值，通过 `YANZHANG_LLM_API_KEY` 更新服务器后重启应用，再撤销旧值。
模型密钥不放进 MCP 参数、WorkBuddy Connector、模型画像或项目资料。

## 7. 工作流和版本恢复

- `TextAsset` 的每次保存生成不可变 `Revision`；发生并发冲突时读取最新 revision，比较内容块后
  以最新版本号重新提交，不覆盖未读改动。
- 母稿和渠道变体通过 `parent_asset_id` 关联，但各自独立保存。恢复母稿版本不会自动回滚变体；
  按资产逐项选择目标版本。
- 工作流记录包含步骤状态。远程模型或来源连接器超时后，先确认是否已经产生资产/版本，再从失败
  步骤恢复，避免重复发布或重复导出。
- 导出产物有独立有效期。过期文件重新从指定资产版本导出，不以过期资源 URI 作为事实来源。
  v0.2 下载使用 `/api/v2/projects/{project_id}/exports/{artifact_id}` 或返回的项目作用域
  `yanzhang://` URI；旧平铺入口只处理 v0.1 未分项目工件。
- 审校建议与正文分开；应用建议后保存新版本，并保留采用或忽略原因。

## 8. 常见故障

### 服务未就绪

检查容器状态与 `gongwen-admin ... check`。若提示 schema 版本高于程序，使用匹配版本镜像；若
完整性检查失败，保留现场副本并从最近已验证备份恢复。

### `401` 或连接器登录失败

确认客户端连接的是 `/mcp` 而不是 Web API，并使用 MCP Token。Web Token 与 MCP Token 彼此独立；
轮换后应同步更新 WorkBuddy、Codex 或其他客户端的本地 Secret。

### `403`、Host 或 CORS 错误

把实际域名加入 `YANZHANG_ALLOWED_HOSTS`，跨站浏览器来源加入
`YANZHANG_CORS_ORIGINS`。两者使用精确值；反向代理地址加入可信代理列表。修改后重启并执行
冒烟检查。

### `413` 或大文件解析失败

应用 `YANZHANG_MAX_REQUEST_BYTES` 与 Caddy `YANZHANG_PROXY_MAX_REQUEST_SIZE` 保持一致。
同时核对解析器自身的文件、页数、压缩层级和解压总量上限。超长资料按章节导入，证据定位保留
原文件哈希和页码/段落信息。

### 模型请求失败

运行状态检查，核对 Provider、模型名、HTTPS 基础地址、允许列表和超时。先切换本地确定性模式
完成结构编辑；远程连接恢复后，仅重跑需要模型的步骤。日志中只保留错误类别、耗时和用量摘要。

### 学术元数据查找失败

Crossref、OpenAlex、arXiv 可能限流或短暂超时。遵循连接器返回的等待时间，缩小关键词和数量
范围后重试。手工导入记录保持 `metadata_verified=false`，直到公开连接器返回匹配记录且作者
核对完成。

### 引用核验提示错配

检查 `record_id`、来源哈希、页码/段落/字符位置和原文版本。未知文献、来源哈希变化、直接引语
缺页码、数字论断缺证据或低支撑度都保留人工复核，不用格式化成功作为真实性依据。

### SQLite 忙或写入冲突

确认应用工作进程为 1，停止额外直接写数据库的脚本。等待现有任务结束后重试；持续出现时先做
一致性备份和完整性检查，再检查磁盘空间、卷权限和异常长事务。

## 9. 更新与发布核验

部署更新前先验证锁文件和 Compose 配置，更新后运行冒烟流程：

```bash
uv lock --check
docker compose --env-file .env.example \
  -f deploy/gongwen/compose.yaml config --quiet
./deploy/gongwen/scripts/health.sh
```

正式发布包还应通过测试、ruff、mypy、源码/产物隐私审计和 `SHA256SUMS` 校验。完整清单见
[releasing.md](releasing.md)。
