# 安装、初始化与切换

本手册适用于 CLI 0.2.0-dev.1；这是开发预览版。平台必须部署资源管理接口，不能因为 npm 安装成功就认为现有服务器支持这些功能。

## 1. 获得命令

检查 `node --version` 和 `npm --version`。需要 Node ≥24，推荐 Node 24 LTS。缺少 Node 时从 [Node 官方下载](https://nodejs.org/en/download/) 安装适合当前系统的版本，或使用用户已有版本管理器；不要替换项目锁定的 Node 环境。

固定版本调用，无需全局安装：

```sh
npx --yes --package=@actvero/cli@0.2.0-dev.1 actvero --version
npx --yes --package=@actvero/cli@0.2.0-dev.1 actvero guide show overview
```

长期使用：

```sh
npm install --global @actvero/cli@0.2.0-dev.1
actvero --version
actvero --help
```

文中 `actvero ...` 均可替换成上述 `npx --yes --package=... actvero ...`。本包名带 `@actvero/`，不要安装无作用域的同名包。测试新版本时用 `npm view @actvero/cli dist-tags --json` 核对，再明确选版本；不要在任务执行中无提示自动升级。

权限错误优先使用 npx 或用户级 Node 环境，不默认 sudo 全局安装。安装报 404 时先核对注册表 `npm config get registry`，按用户网络策略选择官方 registry；不要把 404 当作已安装。网络离线且未缓存包时需要联网或用户提供已验证 tarball。

如果 `actvero --help` 不包含 `guide/schema/skills/mcp/experts`，用 `command -v actvero`（PowerShell: `Get-Command actvero`）排查同名旧命令，再用固定版本 npx 避免歧义。

## 2. 安装本 Skill

CLI 已包含完整 Skill。无需创建仓库或下载另一份手册。

```sh
# Codex，未自定义 CODEX_HOME 时
actvero agent-skill install --to "$HOME/.codex/skills"
# Claude Code，用户级 skills 目录
actvero agent-skill install --to "$HOME/.claude/skills"
actvero agent-skill path
```

只执行适合当前 Agent 的一条 install；`--to` 是 skills 父目录，命令在其中创建 `actvero-management/`。如果 Codex 使用自定义 CODEX_HOME，改用该目录下的 `skills`。PowerShell 可使用 `--to "$HOME/.codex/skills"`。

已有同名 Skill 时拒绝覆盖。先比较已有修改，再按用户选择备份/替换；不要删除用户定制。安装后按宿主方式刷新 Skill 发现或开新会话，可显式使用 `$actvero-management`。不支持 Skill 文件的 Agent 也可直接读 `actvero guide show overview` 和相关主题，完成相同工作。

## 3. 检查目标平台

URL 是平台基础地址，例如 `https://actvero.example.com`，不是 `/console`、登录页或 `/api/v1/management`。确实部署在路径前缀下时保留该前缀。远程必须 HTTPS；仅 localhost/回环可 HTTP；不能带用户名密码、查询或锚点。

```sh
actvero platform info --server https://actvero.example.com --json
```

应返回 `contract_version=1`、`resource_contract_version=1`、`instance_id`、`supported_scopes`、`capabilities`。Skills/MCP/专家分别需 `skills.read/write`、`mcp.read/write`、`experts.read/write`；分类、下载、MCP OAuth/run/activities/contents 还需对应同名能力（完整名称见 `schema show Metadata`）。

如果 404/关闭/版本不兼容，先确认 URL，再向平台管理员报告。平台需部署包含 `111f_management_resources`、`112g_management_mcp_oauth` 的版本，通过 SaaS 后台“设置 → CLI 接入”开启接口（需 `114i_cli_settings` 迁移）；首次保存前和社区版使用 `ACTVERO_MANAGEMENT_ENABLED` 部署默认值。登录还需配置独立 OIDC 公共客户端 `actvero-cli`。只修改 Realm 导入模板不会更新已有身份库。管理员根据平台 [CLI 接入文档](https://github.com/actvero/actvero/blob/main/docs/CLI.md) 更新实际部署；本 Skill 不自动部署或升级数据库。能力响应才是当前服务器依据。

## 4. 登录与工作空间初始化

这里的“初始化”是选择已有平台、登录和选择已有组织。CLI 没有 `init`，也不初始化新平台或创建账号/组织。

```sh
actvero auth status --server https://actvero.example.com --json
# 尚未登录；查询任务默认只读
actvero auth login --server https://actvero.example.com
# 执行已获授权的资源维护时，首次登录申请写权限
actvero auth login --server https://actvero.example.com --write
```

两条 login 按任务二选一。浏览器登录由用户完成，CLI 在当前机器本地回调等待最多 5 分钟。成功后运行 status，核对账号、scope 与会话期限。不要读取或输出系统凭据库内容。

已有只读会话需写入、或更换同平台账号：

```sh
actvero auth logout --server https://actvero.example.com
actvero auth login --server https://actvero.example.com --write --reauthenticate
```

`--reauthenticate` 要求浏览器重新验证，不会覆盖已有 CLI 会话，所以仍先 logout。退出只影响所选平台 CLI 登录，浏览器可能保留原 SSO。

凭据需要 macOS Keychain、Windows Credential Manager 或 Linux Secret Service。无凭据库/无桌面浏览器的 CI、SSH 无头环境目前没有受支持的 token/password/device-code 登录替代方案。不要退回明文凭据；在具备条件的工作站运行，或报告这个阻塞。只读离线手册不受影响。

## 5. 查组织并锁定目标

```sh
actvero org list --server https://actvero.example.com --page 1 --json
actvero org show --server https://actvero.example.com --org <ORG_UUID> --json
actvero org permissions --server https://actvero.example.com --org <ORG_UUID> --json
```

`org list` 返回顶层 `items/total/page/page_size`；组织对象有 `org_id/name/role/available/reason/permissions/membership_id`。检查 available 和实际权限，资源维护要求目标组织管理员；平台运营身份本身不授予组织资源权限。逐页读取直到已读达到 total，不能只搜索第一页。

## 6. 切换平台/组织

每次显式传目标 `--server URL --org UUID`。同平台换组织不必重新登录；组织 ID 在每个平台重新查，不跨平台沿用。不同平台分别登录，凭据按规范化 URL 隔离，最近成功登录的平台成为默认值。

一个平台 URL 只保存一个当前账号，没有具名账号 profile；换账号需 logout/login。别名域名被当作另一个凭据目标。非机密配置默认 `~/.config/actvero-cli/`；`ACTVERO_CLI_HOME` 只改变配置、锁和请求记录目录，**不能隔离同 URL 的系统凭据**。Agent 不应依赖默认平台完成写操作。
