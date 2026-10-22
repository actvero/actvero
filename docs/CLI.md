# 管理 CLI 接入

Actvero 提供独立的管理凭据与组织管理接口。仓库内 `cli/` 的 npm 客户端支持浏览器登录、续期、组织与权限发现、渠道只读查询，以及 Skills、MCP 与专家管理。原 Python 客户端保留用于只读兼容；两者使用同一管理登录协议，凭据存储相互独立。

## 平台启用

SaaS 平台运营人员可在 **平台运营 → 设置 → CLI 接入** 开启或关闭接口。保存后立即对新请求生效，无需重启；关闭不撤销已有登录，但会阻止后续请求，重新开启后仍有效的登录可以继续使用。已经发出的外部调用不能撤回。组织管理员没有修改平台开关的权限。

首次保存前，接口沿用 `ACTVERO_MANAGEMENT_ENABLED` 的部署默认值（默认关闭）；保存后使用数据库中的平台设置，环境变量不再覆盖该选择。社区版继续通过部署配置启用。新迁移保留原安装数据，初始值为空，不改变已有部署行为。

登录仍需配置独立 OIDC 公共客户端 `actvero-cli`，使用 PKCE S256 和本机回环回调。已有身份库不会因修改导入模板自动更新客户端。Web Cookie、桌面令牌与个人访问密钥不能替代管理凭据。

升级时运行 `alembic upgrade head`，当前目标为 `115j_cli_consent`。`113h_management_merge` 合并统一品牌与资源管理两条迁移链；`111f_management_resources` 新增请求回执表和登录授权范围，`112g_management_mcp_oauth` 新增独立的 CLI MCP OAuth 尝试表。旧登录尝试和现有会话保持只读。按照[安装与升级](DEPLOYMENT.md)先备份再迁移；迁移不会自动打开管理接口。

## 复制指令给 Agent

在 CLI 接入页点击“复制给 Agent”，粘贴到 Codex、Claude Code 等支持终端操作的 Agent。指令携带部署配置中的平台地址、固定 npm 版本、Skill 安装说明、能力检查、登录与组织权限核验步骤，不包含登录凭据。平台地址由 `ACTVERO_APP_URL` 决定。

Agent 可以安装并检查客户端；用户在浏览器完成登录，然后选择允许访问的组织及“只读查询”或“管理资源”，点击确认才授予权限。接入提示词与 Skill 不决定权限，Agent 不应代替用户确认授权。接入指令不会自动创建、发布或删除资源，也不会修改服务器或身份服务配置。只有接口已开启时才能使用复制按钮；页面不把开关状态当作 OIDC 登录已验证。

## 客户端

推荐使用 `@actvero/cli` npm 客户端，安装和完整命令见 [CLI README](../cli/README.md)。仓库开发使用 `make cli-bootstrap cli-check cli-test`；直接运行 `node cli/dist/index.js --help` 可避免同名旧入口干扰。构建与安装只依赖此仓库和锁定的 npm 依赖。

原 Python 客户端仍可通过 `uv tool install ./cli` 安装，仅提供只读能力；对应检查为 `make cli-legacy-check cli-legacy-test`。使用 `command -v actvero` 与 `actvero --version` 确认实际入口，不让两个同名全局命令相互覆盖。

先执行 `actvero platform info --server <平台地址> --json`。返回 `management_disabled` 表示功能关闭；缺少 `resource_contract_version: 1` 或 `experts.write`、`skills.write`、`mcp.write` 表示服务端版本未就绪。安装 CLI 不会启用接口或部署服务器。

```sh
actvero auth login --server https://actvero.example.com
actvero org list --json
actvero channels list --org <组织UUID> --json
```

新客户端统一执行 `auth login`。浏览器授权页默认选择只读，但不会预选组织或自动确认。用户确认只读时授予 `management:read`；确认管理时授予 `management:read management:write`。`--write` 仅保留命令兼容，不能替代用户在浏览器的决定。续期保留原组织和权限，不会提升权限。

需要调整权限、组织或账号时重新运行 `auth login`，不用先退出。CLI 保留原会话，待新授权确认保存到系统凭据库后才撤销旧会话；取消、超时或保存失败时保留原会话。旧会话撤销网络失败会保留清理记录并提示，下次命令重试。显式退出仍使用 `auth logout`。

### 浏览器授权契约

`metadata.authorization_contract_version=2` 表示支持新流程。CLI 调用 `login/start` 时传 `authorization_version=2`，打开返回的平台 `/cli/authorize` 页面。临时 state 在 URL 片段中传递。用户登录 Web 后，通过独立 `/api/v1/cli-authorization/context` 与 `/decision` 接口查看和确认授权；接口要求有效浏览器会话、Origin 和 CSRF，并检查当前组织管理员资格。它们不会返回 CLI 凭据。

确认结果绑定登录尝试、浏览器身份、组织和 scope，随后通过独立 `actvero-cli` OIDC 客户端完成 PKCE 回环登录。`login/exchange` 再核对原登录证明、身份一致性及当前组织资格，才签发管理凭据。拒绝、过期、重复确认、换账号、CLI 开关关闭均不能继续签发。每个资源请求仍检查组织是否在会话授权集合内及当前成员权限；`org list` 仅列出本次授权组织。

### 升级兼容

CLI `0.2.0-dev.2` 的新登录需要浏览器授权契约；旧服务器会明确报不兼容。新平台保留旧客户端的只读登录，不接受旧协议新申请写权限。`115j_cli_consent` 撤销缺少浏览器确认的历史写会话，要求通过新客户端重新授权；原只读会话继续可用，仍按当前组织成员权限校验。数据库降级不会恢复已撤销的会话，并撤销新协议会话，防止旧版本失去组织限制后扩大授权。迁移保留业务资源和其他客户端会话。

平台发布新接入指令前，需先发布对应 CLI npm 版本；开发验证可使用仓库构建或本地打包文件。

所有资源命令显式携带组织 UUID。平台每次检查当前成员状态、组织状态、角色与平台运营分配关系；平台运营身份不自动获得任意组织权限。资源读写及请求回查均要求该组织管理员资格。写授权不绕过角色限制。

## 资源接口

基础路径为 `/api/v1/management/organizations/{org_id}`。响应统一为 `organization`、`result`，写操作额外包含 `request_id`。技能 ZIP 下载例外，返回二进制及组织、请求编号、SHA-256 响应头。字段与模型以[生成 API 契约](api/openapi.json)为准。

| 资源 | 接口范围 |
| --- | --- |
| `skills` | 列表、详情、ZIP 预览和导入、资料/范围修改、版本发布与下架、未发布草稿删除、分发记录、文件概览和文本预览、ZIP 下载、分类增删改与排序 |
| `mcp` | 服务列表/创建/配置更新/删除、展示资料、配置导入导出、能力发现和策略、手工凭据保存与断开、CLI OAuth、工具/提示词/资源测试、活动记录、内置内容维护 |
| `experts` | 列表、草稿创建和编辑、详情与发布资格、使用范围、精确依赖查询与更新、发布/下架/删除、技能影响与依赖更新回执、分类增删改与排序 |
| `commands/{request_id}` | 当前用户在指定组织的写操作状态及成功结果 |

这些路由与 Web 路由调用相同的资源操作和领域校验。Web 保留原有 Cookie、CSRF 与权限流程。分类删除需要当前修订号、确认时资源数量和迁移目标，资源数量发生变化返回 409。创建 MCP 默认关闭，保存不触发外网发现；发现需要显式调用。

`GET /api/v1/management/metadata` 保留 `contract_version: 1` 和旧只读 `scope` 字段，新增 `supported_scopes`、`resource_contract_version: 1` 及能力列表。新客户端在资源操作前检查能力；旧客户端的登录请求不带 `scope` 时仍使用只读。新协议中的 scope 仅由浏览器确认结果决定。

## 写操作回执

资源写请求必须带 `X-Management-Request-ID` UUID。ZIP 预览和配置导入预览是只读校验，不需要此头。技能和专家使用当前 `revision`，MCP 配置更新使用 `version`，管理接口删除 MCP 时必须提供 `?version=<当前版本>`。

回执以组织、用户、请求编号共同定位。平台使用 HMAC 记录 HTTP 方法、路径、查询字符串和原始请求正文的指纹，不保存请求正文、ZIP 或明文凭据；成功结果沿用脱敏的资源响应。MCP 测试调用和 OAuth 发起仅保存 `result_retained: false`，不保存测试参数、结果正文或授权地址；同编号重放返回 `command_result_not_retained`，不会再次执行。同编号只有完全一致的请求可回放成功结果，修改内容返回 `command_conflict`。

执行前先持久化 `pending`，然后重新授权并获取组织写锁。成功变为 `succeeded`；异常变为 `unknown`。进程中断可能留下 `pending`。异常状态保守处理，因为网络操作可能已发生或独立保存审计事实，不能推断为“什么都没做”。服务器不会自动再次派发 `pending` 或 `unknown`。MCP 发现和测试不跨网络等待持有会话锁，并在派发和返回边界重新校验当前权限、会话和配置版本；已经发出的上游操作无法撤回。

网络超时后按原编号回查。成功响应丢失可以获取原结果；结果不明时先核对资源和审计，确认后再发起新操作。409 修订冲突需重新读取并核对，不自动覆盖。权限被撤销后不能读取历史回执，也不能回放原成功请求。回执没有自动到期清理；运维应把它作为业务记录备份，不通过删除回执解除执行限制。

## 下载与 MCP OAuth

`POST /skills/{skill_id}/versions/{version_id}/download` 记录一次分发，成功回执仅保存包摘要、大小和版本信息。同一请求编号可重取原包，但每次交付均重新鉴权。响应为 `application/zip`，包含 `X-Organization-ID`、`X-Management-Request-ID`、`X-Content-SHA256`。CLI 在 20 MB 上限内校验完整文件，不覆盖已有文件，不自动解压或执行。

MCP OAuth 使用独立流程：

1. `POST /mcp/services/{service_id}/oauth/start`，返回尝试编号与授权 URL；尝试编号等于发起请求的 UUID。
2. 浏览器访问上游授权页，回调 `/api/v1/management/mcp/oauth/callback`。此回调使用 state 和 PKCE，忽略 Web Cookie，仅暂存加密凭据。
3. `GET /mcp/oauth/{attempt_id}` 查询状态。发起响应丢失时，可用原请求 UUID 找回尚未结束的授权 URL。
4. `POST /mcp/oauth/{attempt_id}/complete` 由发起 CLI 会话确认连接。`POST /mcp/oauth/{attempt_id}/cancel` 取消尚未完成的授权。

上游 OAuth 客户端必须配置此回调地址。尝试有效期 10 分钟；其他 CLI 会话或组织不能接管。断开连接或重新发起授权会取消未完成尝试；配置变更、退出登录、权限撤销、过期后不能附加凭据。取消已完成的尝试不会撤销连接，应使用 `disconnect`；断开平台连接不保证撤销上游令牌。

OAuth URL 含临时 state，仅交给系统浏览器或本人操作，不提交仓库。工具测试可能产生真实业务副作用，须显式调用；回执和 MCP 活动记录不包含参数与结果正文。新增能力通过 `skills.categories`、`skills.download`、`experts.categories`、`mcp.oauth`、`mcp.run`、`mcp.activities`、`mcp.contents` 单独声明，旧平台缺少能力时客户端明确拒绝。

## 桌面能力边界

本 CLI 管理平台上的资源。桌面本机专家 ZIP 导入、本机 MCP 凭据、工作区及专家会话执行属于桌面运行时，不会因为平台启用 `experts.write` 自动获得命令行入口。平台 MCP 和本机 MCP 分别保存凭据；配置其中一个不会同步另一个。桌面端当前提供相应界面和专家创建工具，尚无对应的 `actvero desktop` 命令。自动化接入需要桌面项目提供受认证的本机操作接口，不能直接编辑其加密配置文件。

## 凭据存储与验证边界

客户端系统凭据库不可用时登录停止，不写明文替代。续期先保存恢复请求编号，保存新凭据后确认；退出请求未确认时阻止新的业务请求。HTTP 仅允许本机回环地址，远端平台使用 HTTPS。

平台测试使用独立 PostgreSQL schema 和模拟身份提供方，覆盖角色/组织隔离、回执、防重复执行、现有 Web 行为、OAuth 分阶段确认及迁移保留；本机真实 HTTP/SSE MCP 测试和 Node 到 Python HTTP 流程覆盖 CLI 维护命令。真实 OIDC 登录、操作系统凭据库、跨系统安装和远端 MCP 服务需在目标环境验收；本地测试通过不代表生产部署已经完成。

## 参考

[文档导航](README.md) · [身份与授权](IDENTITY-FLOW.md) · [专家管理](EXPERTS.md) · [Skills 管理](SKILLS-WORKBENCH.md) · [MCP 服务管理](MCP-WORKBENCH.md)
