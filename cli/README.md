# Actvero CLI

用于管理 Actvero 平台的独立命令行客户端。支持多组织下的 **Skills、MCP 服务、专家**，适合终端操作和 Agent 调用。平台继续负责权限、版本、审计与发布校验。

当前为 `0.2.0-dev.2` 开发预览版，使用 npm 的 `next` 标签。配套平台须部署包含 `115j_cli_consent` 迁移的浏览器授权与资源管理 API；仅安装 CLI 不会升级服务器。原 Python CLI 的只读命令仍兼容。

## 安装与 Agent Skill

需要 Node.js 24 或更高版本，以及可用的系统凭据库：macOS Keychain、Windows Credential Manager 或 Linux Secret Service。

```sh
npm install --global @actvero/cli@0.2.0-dev.2
actvero --version
actvero --help
# 无需全局安装的固定版本调用
npx --yes --package=@actvero/cli@0.2.0-dev.2 actvero --help
# 安装配套 Codex Skill；--to 是 skills 父目录，已有同名目录不会覆盖
actvero agent-skill install --to "$HOME/.codex/skills"
```

Claude Code 可将安装目录改为 `$HOME/.claude/skills`；其他 Agent 可直接使用离线手册。自定义 CODEX_HOME 时使用其 skills 子目录。刷新宿主 Skill 发现或开启新会话后，可用 `$actvero-management` 调用。若安装过同名 Python 命令，先用 `command -v actvero`（PowerShell 使用 `Get-Command actvero`）确认入口，或使用上面的 npx。

完整、无需已有项目上下文的入口为 [Actvero 管理 Skill](skills/actvero-management/SKILL.md)，包括 [安装与平台/组织初始化](skills/actvero-management/references/bootstrap.md)、[共同操作与交付](skills/actvero-management/references/operations.md)、[Skills](skills/actvero-management/references/skills.md)、[MCP](skills/actvero-management/references/mcp.md)、[专家](skills/actvero-management/references/experts.md)、[错误恢复](skills/actvero-management/references/recovery.md) 与 [完整命令/字段索引](skills/actvero-management/references/commands.md)。

```sh
actvero guide list
actvero guide show bootstrap
actvero schema show ExpertUpdate
actvero example show expert > ./expert.json
actvero agent-skill path
```

这些命令无需登录、凭据库或网络。guide 的正文在 JSON 的 content 字段；schema 是随包发布的契约快照，平台仍负责实际输入校验。没有单独的 init 命令，“初始化”指登录已有平台并选择组织，不创建账号、组织或数据库。

## 平台配置与登录

SaaS 平台运营人员可在“设置 → CLI 接入”开启接口并复制 Agent 接入指令；首次保存前沿用 `ACTVERO_MANAGEMENT_ENABLED` 部署默认值，保存后以平台设置为准。社区版通过部署配置启用。登录需配置独立 OIDC 公共客户端 `actvero-cli`。已有身份库不会因修改导入模板自动更新客户端；依照平台 [CLI 接入文档](https://github.com/actvero/actvero/blob/main/docs/CLI.md) 配置。资源接口变更在合入部署后生效。

```sh
# 无需登录，先核对平台已部署所需管理能力
actvero platform info --server https://actvero.example.com --json
# 浏览器中选择组织和只读／管理权限，并由本人确认
actvero auth login --server https://actvero.example.com
actvero auth status
actvero org list --json
actvero org permissions --org <组织UUID>

# 调整授权或账号时直接重新登录；取消会保留原会话
actvero auth login --server https://actvero.example.com
```

新登录要求平台返回 `authorization_contract_version=2`。`--write` 仅保留兼容，不能改变浏览器确认的权限。新授权保存后撤销原会话；撤销失败会提示并在后续命令重试。升级平台后，历史写会话需要重新授权，旧只读会话仍兼容。

每条资源命令都必须显式填写 `--org`。命令响应包含服务端确认的组织信息；同一用户可访问多个获授权组织，平台运营身份不会自动取得组织资源权限。资源管理要求该组织的管理员资格。

登录令牌、续期恢复记录只保存在系统凭据库。凭据库不可用时停止，不回退到明文文件。默认平台和不含请求正文的写操作编号保存在 `~/.config/actvero-cli/`；可用 `ACTVERO_CLI_HOME` 改变这个非机密配置目录。

## Skills

```sh
actvero skills preview ./my-skill.zip --org <组织UUID>
actvero skills import ./my-skill.zip --version 1.0.0 --org <组织UUID>
actvero skills list --org <组织UUID> --json
actvero skills show <技能UUID> --org <组织UUID>
actvero skills files <技能UUID> --version-id <版本UUID> --org <组织UUID>
actvero skills file <技能UUID> --version-id <版本UUID> --path <详情中返回的包内路径> --org <组织UUID>
actvero skills download <技能UUID> --version-id <版本UUID> --out ./skill.zip --org <组织UUID>
actvero skills distributions --skill <技能UUID> --org <组织UUID>
actvero skills publish <技能UUID> --version-id <版本UUID> --revision <修订号> --org <组织UUID>
actvero skills withdraw <技能UUID> --version-id <版本UUID> --revision <修订号> --org <组织UUID>
```

ZIP 必须通过平台 Skill 校验；CLI 不运行包内脚本。导入只创建草稿，默认使用范围为管理员。`--metadata` 接收展示资料与使用范围 JSON；新增已有技能的版本时，同时传 `--skill` 和 `--revision`。`update --file` 修改资料与范围，`delete-draft` 仅能删除从未发布的草稿版本。

`skills files` 返回 SKILL.md 概览；完整文件清单位于 `skills show` 的版本 files 数组或 preview 响应。

## MCP 服务

```sh
actvero mcp create --file ./examples/mcp.json --org <组织UUID>
actvero mcp list --org <组织UUID>
actvero mcp show <服务UUID> --org <组织UUID>
actvero mcp update <服务UUID> --file ./service-update.json --org <组织UUID>
actvero mcp connect <服务UUID> --file ./credentials.json --org <组织UUID>
actvero mcp discover <服务UUID> --org <组织UUID>
actvero mcp capabilities <服务UUID> --org <组织UUID>
actvero mcp delete <服务UUID> --version <配置版本> --org <组织UUID>
```

创建默认关闭；保存配置不会自动发现或执行远端工具。更新文件应使用 `McpServiceUpdate` 字段并带当前 `version`，其中 `enabled` 控制启停；不能直接把完整查询响应当成写入文件。`discover` 会实际连接目标服务。`connect` 只保存本人或组织共享手工凭据，文件格式为 `{"values":{"字段名":"值"}}`；此类文件应保留在仓库外。

还提供 `policy`、`presentation`、`disconnect`、`preview-import`、`import` 和 `export`。导出不包含凭据。`mcp contents list/create/update/delete` 管理内置提示词与资源，写入使用 `--file` 的 `McpContentInput` JSON。

```sh
# 测试会实际执行工具，可能产生真实业务副作用
actvero mcp run <服务UUID> --file ./examples/mcp-run.json --org <组织UUID>
actvero mcp activities --category call --service <服务UUID> --org <组织UUID>

# CLI 发起上游 OAuth；上游需登记平台管理 OAuth 回调地址
actvero mcp oauth start <服务UUID> --org <组织UUID>
actvero mcp oauth status <尝试UUID> --org <组织UUID>
actvero mcp oauth complete <尝试UUID> --org <组织UUID>
actvero mcp oauth cancel <尝试UUID> --org <组织UUID>
```

OAuth 先打开系统浏览器，浏览器完成后回到 CLI 查询 `status`，状态为 `awaiting_confirmation` 时执行 `complete`。只有原 CLI 会话可以确认；尝试 10 分钟过期。`start --no-browser` 仅输出地址。发起响应丢失后，可用该请求 UUID 作为尝试编号查询恢复。授权 URL 含临时 state，不共享或写入日志。取消已经完成的尝试不会断开连接，断开请用 `mcp disconnect`。

## 专家

```sh
actvero experts create --file ./examples/expert.json --org <组织UUID>
actvero experts dependencies --kind skills --org <组织UUID>
actvero experts dependencies --kind connectors --org <组织UUID>
actvero experts show <专家UUID> --org <组织UUID>
actvero experts check <专家UUID> --org <组织UUID>
actvero experts publish <专家UUID> --revision <修订号> --version 1.0.0 --org <组织UUID>
actvero experts withdraw <专家UUID> --revision <修订号> --org <组织UUID>
```

专家使用平台专家 JSON 草稿，不是桌面专家 ZIP。`update --file` 使用 `ExpertUpdate`，`scope --file` 修改使用范围，`refresh-skills --file` 使用 `ExpertSkillRefresh` 更新精确技能引用。更新均需当前 `revision`；依赖版本、摘要、组织与可用状态由平台校验。`check` 返回草稿的发布资格，不等于执行专家或验证真实任务质量。`experts skill-impact --skill <UUID> --target-version <UUID>` 查询更新影响；`dependency <UUID> --kind skills --version-id <UUID>` 查询精确依赖，`dependency-command <UUID>` 查询依赖更新回执。以上均需 `--org`。

## 分类和下载

Skills 与专家均支持 `categories list/create/rename/move/delete`：

```sh
actvero skills categories list --org <组织UUID>
actvero skills categories create --name 开发工具 --org <组织UUID>
actvero skills categories rename <分类ID> --name 新名称 --revision <修订号> --org <组织UUID>
actvero skills categories move <分类ID> --direction up --revision <修订号> --org <组织UUID>
actvero skills categories delete <分类ID> --target uncategorized --count <确认数量> --revision <修订号> --org <组织UUID>
```

专家分类把 `skills` 换成 `experts`。删除分类会迁移资源，不删除资源本身；修订号或数量已变化则拒绝。系统分类 `uncategorized` 不能修改或删除。

下载需要写授权，因为平台记录分发。CLI 校验组织、请求编号、20 MB 大小上限和 SHA-256，不覆盖已有文件，不自动解压或执行。中断后可使用原 `--request-id` 恢复，仍需当前访问权限；平台不会重复记录该次分发。`skills icons` 查询图标目录。

## 写入回查与脚本调用

每次写操作发送前会将请求 UUID 写到标准错误和本地非机密记录。标准输出只包含 JSON；`--json` 使用单行 JSON。命令失败返回非零退出码，错误使用 `code`、`message` 等字段。

```sh
actvero commands show <请求UUID> --org <组织UUID> --json
```

回执为 `pending`、`succeeded` 或 `unknown`。网络超时后先回查原编号；`succeeded` 通常包含原结果。MCP 测试和 OAuth 发起仅保留执行状态，结果为 `result_retained: false`；不保存测试参数、结果正文或授权 URL。正在执行或结果不明时，平台不会重发。不要通过新编号盲目再次执行发布、导入或发现。确认资源现状、解决失败原因后，才提交新的操作。

可用 `--request-id <UUID>` 重用编号：同组织、同用户、同方法、同路径、同原始正文的成功请求返回原结果（不保留正文的操作返回 `command_result_not_retained`）；内容不一致返回 409。必须使用同一份输入文件。修订号冲突不会自动覆盖；重新读取资源并人工核对。权限撤销立即生效，即使是回查原请求也须具备当前组织权限。

## 源码位置与旧客户端

此目录是 npm 客户端的完整源码。仓库根执行 `make cli-bootstrap cli-check cli-test`，或在本目录执行下面的 npm 命令。构建不读取其他项目目录。`src/actvero_cli/`、`tests/` 和 `pyproject.toml` 保留原 Python 只读客户端的兼容实现；新功能使用 TypeScript 的 `src/*.ts` 和 `test/*.test.ts`，Python 文件不进入 npm 包。

## 开发与发布

```sh
npm ci
npm run check
npm test
npm run build
npm pack --dry-run
```

源码开发可用 `node dist/index.js` 或 `npm link`。目录：`src/` 命令、认证、HTTP 与存储；`test/` 隔离测试；`examples/` 非机密请求示例；`skills/` Agent 手册；`schemas/` 离线接口契约；`scripts/` 公开内容检查与 schema 更新；`.github/workflows/` CI。过程记录、真实配置和凭据不进入仓库或 npm 包。

依赖用途与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。测试使用临时目录、内存凭据与回环 HTTP；真实 OIDC、操作系统凭据库和 MCP 远端服务须在目标系统另行验收。代码 CI 不发布 npm 包。

发布者需具备 npm 的 actvero 组织权限，按 [npm 官方发布说明](https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/) 登录并满足当前发布认证要求。开发预览使用 `npm publish --access public --tag next`。npm 首次发布可能同时建立 latest；若 registry 拒绝删除它，需让默认入口指向当前修正版，避免安装旧版。是否稳定仍以版本说明与实际验收为准，Agent 建议固定版本或显式使用 next。先审阅 pack 文件清单及内容，再发布；发布后核对 registry 版本、完整性摘要和干净安装。后续有发布仓库与流水线时可配置 [Trusted Publishing](https://docs.npmjs.com/trusted-publishers/)，代码 CI 当前不自动发布。

## 许可

MIT，见 [LICENSE](LICENSE)。
