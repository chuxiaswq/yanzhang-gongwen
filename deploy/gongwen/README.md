# 砚章 Web 生产部署

这套资产把个人版 Web 服务封装为两个容器：`gongwen` 运行应用并执行令牌认证，`proxy`
提供反向代理、压缩、安全响应头和可选的自动 HTTPS。应用进程以 UID/GID `10001` 运行，
该身份固定在镜像内，升级时持久卷权限保持稳定。根文件系统只读；文稿、版本、文章来源和
用量记录统一保存在独立的 Docker 持久卷中。

## 快速启动

需要 Docker Engine 与 Docker Compose v2。在仓库根目录执行：

```bash
./deploy/gongwen/start.sh
```

首次运行会创建权限为 `0600` 的 `deploy/gongwen/.env`，分别生成网页/API 访问令牌和
远程 MCP 访问令牌，构建镜像，等待应用和反向代理都通过健康检查后返回。默认只监听本机，
访问地址为：

```text
http://127.0.0.1:8080
```

两枚令牌只保存到本机 `.env`，启动日志不显示完整值。即使后续构建需要重试，凭据也已经
原子落盘。需要录入登录遮罩或 MCP 客户端时，按“访问令牌、数据与备份”一节在可信终端
手动查看对应令牌。
后续可用以下命令查看状态与日志：

```bash
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml ps
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml logs -f --tail=200
```

停止服务不会删除数据卷：

```bash
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml down
```

## 域名与 HTTPS

编辑 `deploy/gongwen/.env`：

```dotenv
GONGWEN_SITE_ADDRESS=gongwen.example.com
GONGWEN_BIND_ADDRESS=0.0.0.0
GONGWEN_HTTP_PORT=80
GONGWEN_HTTPS_PORT=443
GONGWEN_ALLOWED_HOSTS=127.0.0.1,localhost,[::1],gongwen.example.com
```

`GONGWEN_SITE_ADDRESS` 只填写一个不含协议和端口的域名；宿主机映射端口分别由
`GONGWEN_HTTP_PORT` 与 `GONGWEN_HTTPS_PORT` 控制。域名模式下，启动脚本还会核对
`GONGWEN_ALLOWED_HOSTS` 中包含完全相同的域名，避免服务启动后被主机名校验拦截。

将域名解析到服务器并放通 TCP 80、TCP/UDP 443，随后再次运行 `start.sh`。Caddy 会申请
并续期证书。若服务器前面已有负载均衡器或统一网关，可保留默认本机绑定，让上层网关代理
到 `127.0.0.1:8080`。启动脚本会阻止把纯 HTTP 入口直接绑定到非回环地址。
本机绑定可填写 `127.0.0.1`、`localhost`、`::1` 或 `[::1]`；脚本会统一为 Docker 与
浏览器都适用的 IPv4/IPv6 表示，IPv6 本机访问地址形如 `http://[::1]:8080`。

上传材料较大时，应同时调整应用的字节上限 `GONGWEN_MAX_REQUEST_BYTES` 和 Caddy 的
可读大小值 `GONGWEN_PROXY_MAX_REQUEST_SIZE`（例如分别设为 `8388608` 与 `8MB`），
保持两层边界一致。

反向代理容器显式将 `gongwen` 服务名加入 `NO_PROXY`，因此即使 Docker Desktop 或
宿主环境注入了 HTTP 代理，容器间的就绪检查和业务请求仍走私有 Compose 网络。

## 远程 MCP 接入

MCP 与网页服务运行在同一应用进程、使用同一持久卷和模型配置，不增加新的公网端口。
域名部署完成后，Streamable HTTP 地址为：

```text
https://DOMAIN/mcp
```

对于已经验证或提供官方 MCP 配置字段的客户端，如 WorkBuddy、TraeWork/TraeCode 和
扣子编程，可选择 **Streamable HTTP**，填写上面的 URL，并添加请求头：

```text
Authorization: Bearer MCP_TOKEN
```

其中 `MCP_TOKEN` 是 `.env` 内的 `GONGWEN_MCP_ACCESS_TOKEN`，不能使用网页登录令牌代替。
通用配置结构如下；不同客户端可能把传输类型显示为 `streamableHttp` 或 `http`：

```json
{
  "mcpServers": {
    "gongwen-writing": {
      "type": "streamableHttp",
      "url": "https://DOMAIN/mcp",
      "headers": {
        "Authorization": "Bearer MCP_TOKEN"
      }
    }
  }
}
```

豆包工作目前作为真机兼容性验证目标，需依据实际客户端版本验证 Streamable HTTP、
自定义 `Authorization` 请求头和工具调用；验证范围与记录要求见
[`docs/gongwen-mcp.md`](../../docs/gongwen-mcp.md)。

服务同时支持标准的 `Accept: application/json, text/event-stream` 与
`Content-Type: application/json` 请求。各客户端的导入文件、stdio 用法和完整工具契约见
[`docs/gongwen-mcp.md`](../../docs/gongwen-mcp.md)。

## 访问令牌、数据与备份

网页/API 使用 `GONGWEN_ACCESS_TOKEN`，远程 `/mcp` 使用独立的
`GONGWEN_MCP_ACCESS_TOKEN`。两者都至少为 32 字节，只传入应用容器，不写入镜像；Caddy
不保存凭据。启动脚本只报告令牌已经生成及其保存位置，不把令牌值写到终端或部署日志。
确需录入浏览器或 MCP 客户端时，在未共享屏幕、未开启会话录制的可信服务器终端中按需查看：

```bash
./deploy/gongwen/show-token.sh web
./deploy/gongwen/show-token.sh mcp
```

该查看脚本只向交互式终端显示结果，重定向或管道调用会终止，以降低令牌进入 CI 日志、命令
替换结果或普通文本文件的概率。使用后清理终端回滚内容，不把结果粘贴到工单、聊天记录或
版本库。

轮换时，把 `.env` 中对应一行改成以 `CHANGE_ME_` 开头的占位值，再运行 `start.sh`；脚本会
生成新值并以 `0600` 权限原子替换文件。两类新值都不写入启动日志，运行后用上面的查看脚本
按需录入客户端。只轮换其中一枚不会使另一类客户端失效。文件中每个令牌字段都应只
保留一条；启动脚本会拒绝重复项，避免旧值覆盖新值。

宿主机脚本仅按白名单读取两枚访问令牌、站点、绑定地址和端口，把 `.env` 内容当作纯数据
解析，全程不把文件载入 shell。旧部署的 `.env` 缺少 MCP 字段时，`start.sh` 会自动生成并
追加该字段。运维字段建议保持一行一个 `KEY=value`；简单的成对单引号或双引号也可使用。
模型密钥等其余字段由 Compose 直接传入容器。

如需由服务端统一保管模型密钥，可在同一文件填写 `GONGWEN_LLM_PROVIDER`、
`GONGWEN_LLM_MODEL`、`GONGWEN_LLM_API_KEY` 和可选的 `GONGWEN_LLM_BASE_URL`；这些值
仅注入应用容器。`deepseek`、`qwen`、`custom` 会使用 OpenAI 兼容适配器，且要填写
对应的基础 URL。全部留空时仍可使用确定性模式，也可沿用页面中的临时连接设置。

生产模式下，页面中的临时连接留空基础 URL 时使用所选 Provider 的官方默认
地址；若要填写自定义基础 URL，需先把完整 HTTPS 地址加入
`GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST` 逗号分隔列表。匹配会校验主机、端口和完整
路径（末尾斜杠视为等价），而不是只比较域名前缀。页面传入的 `endpoint` 只可使用
相对路径，因此请求仍会停留在已选基础地址内。该列表只约束页面自带密钥的临时
连接，不限制由运维人员设置的 `GONGWEN_LLM_BASE_URL`。

人民网当前公开自动检索入口使用 HTTP。为避免检索主题和日期范围经明文网络传输，部署样例
默认设置 `GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=false`；光明网、求是网自动采集及
人民网 HTTPS 文章链接手工导入保持可用。部署者在了解该边界后，可显式设为 `true`；页面仍
默认不勾选人民网，并在提交前显示明文传输提示。服务端拒绝未开启时绕过页面直接提交的
人民网自动采集请求，错误信息不会带回实际检索条件。

应用访问日志默认关闭，因为标准请求行可能记录文稿搜索词或文章来源查询条件。如需排障，先
制定日志访问权限、脱敏和短期保留策略，再临时设置 `GONGWEN_ACCESS_LOG=true`；排障结束后
恢复为 `false` 并清理相关日志。应用错误响应和模型用量表不保存请求正文或模型密钥。

应用数据位于 `gongwen-web-data` 持久卷。在线创建一致性 SQLite 备份：

```bash
./deploy/gongwen/backup.sh
```

备份默认写入 `deploy/gongwen/backups/`，文件名包含 UTC 时间、进程号和随机后缀，并附带
SHA-256；该目录和 `.env` 均已排除在镜像上下文与版本管理之外。容器内临时快照放在持久
数据卷，不受 `/tmp` 容量限制。复制到宿主机时先使用唯一的 `.partial` 文件，再从容器中
读取这份宿主机文件做完整性与 schema 校验。快照在生成时转为自包含的 SQLite `DELETE`
journal 格式，可从只读文件挂载直接复检；通过后再原子改名发布。退出时会清理临时文件及
其 `-wal`、`-shm` 边车文件。在线检查当前数据库的完整性、schema 和数据量：

```bash
docker compose --env-file deploy/gongwen/.env -f deploy/gongwen/compose.yaml \
  exec -T gongwen gongwen-admin --database /var/lib/gongwen/gongwen.sqlite3 check
```

恢复前先再做一次备份，然后传入选定备份并显式确认。脚本会先停止两个服务，校验版本与
必需表，再调用 `gongwen-admin restore` 原子替换数据库、恢复非 root 文件归属、复查
完整性并重新启动；恢复中途出错时会尝试拉起原有服务：

```bash
./deploy/gongwen/restore.sh \
  deploy/gongwen/backups/gongwen-YYYYMMDDTHHMMSSZ-PID-RANDOM.sqlite3 --yes
```

建议把备份再同步到加密的异机存储，并定期做恢复演练。

`start.sh`、`backup.sh`、`restore.sh` 共用部署锁，同一时间只执行一项变更操作。进程被强制
终止并留下锁目录时，后续操作会检查记录的 PID，确认进程已结束后原子接管并回收陈旧锁；
仍在运行的操作会保留锁并返回明确提示。

## 更新与核验

拉取新代码后重新运行 `start.sh`，Compose 会重建应用镜像并保留持久卷。部署前可做静态核验：

应用启动时会核对数据库 schema 版本；遇到比当前程序更新或不匹配的数据库时会保留原版本标记并停止启动，避免旧镜像覆盖新数据。升级或回退前先执行一次备份。

镜像中的运行时 Python 包由 `deploy/gongwen/requirements.lock` 锁定版本和下载哈希，
PEP 517 构建后端及其依赖则由 `requirements-build.in` 和 `requirements-build.lock`
锁定。安装这两份哈希锁后，镜像以 `--no-deps --no-build-isolation` 安装当前仓库包，
避免在构建隔离环境再解析另一组在线依赖。修改 `pyproject.toml` 并刷新 `uv.lock`
后，重新导出运行时锁，再以它为约束刷新构建锁，并将所有锁文件一起提交：
镜像构建对包索引和文件 CDN 设置 60 秒单次超时和 10 次重试，短暂的 DNS、代理或
TLS 中断可直接重试构建；包文件最终仍必须通过锁文件中的 SHA-256 校验。

```bash
uv lock --check
uv export --format requirements.txt --no-dev --no-emit-project --locked \
  --output-file deploy/gongwen/requirements.lock
uv pip compile deploy/gongwen/requirements-build.in \
  --constraints deploy/gongwen/requirements.lock --generate-hashes --universal \
  --python-version 3.12 --no-annotate \
  --output-file deploy/gongwen/requirements-build.lock
```

```bash
docker compose --env-file deploy/gongwen/env.example \
  -f deploy/gongwen/compose.yaml config --quiet
```

服务就绪后检查：

```bash
./deploy/gongwen/smoke.sh
```

脚本依次检查进程存活、SQLite 就绪、网页 API 的令牌认证，以及 `/mcp` 在无令牌和误用网页
令牌时均返回 `401`、使用 MCP 令牌时能完成标准 `initialize`。写作、文稿库、文章来源库和
导出接口均经过网页/API 令牌认证，MCP 工具统一经过独立 MCP 令牌认证。
