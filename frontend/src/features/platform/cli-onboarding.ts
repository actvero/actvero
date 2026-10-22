export const CLI_VERSION = '0.2.0-dev.1'

export function cliOnboardingPrompt(serverUrl: string, write: boolean): string {
  const server = JSON.stringify(serverUrl)
  return `请帮我配置 Actvero 平台管理 CLI，目标平台地址是 ${server}，本次接入权限为${write ? '读写管理' : '只读查询'}。

1. 检查 Node.js 和 npm，需要 Node.js ≥24。检查已有 actvero 的版本和帮助，避免误用同名旧 Python CLI。
2. 安装固定版本：npm install --global @actvero/cli@${CLI_VERSION}。如全局目录不可写，使用 npx --yes --package=@actvero/cli@${CLI_VERSION} actvero 代替后续 actvero 命令，不使用 sudo。
3. 运行 actvero guide show bootstrap。若你是 Codex，执行 actvero agent-skill install --to "$HOME/.codex/skills"（自定义 CODEX_HOME 时使用其 skills 目录）；Claude Code 使用 "$HOME/.claude/skills"。已有同名 Skill 时保留原文件，先比较；其他 Agent 直接读取 guide。使用配套 actvero-management 操作说明。
4. 把上述平台地址作为一个完整的 --server 参数，按当前 shell 安全引用。运行 actvero platform info --server <平台地址> --json，确认 resource_contract_version=1 及所需 capabilities。若管理接口关闭或不兼容，报告原因并停止，不修改服务器配置。
5. 运行 actvero auth status --server <平台地址> --json；已有有效且授权范围合适的会话就复用，否则运行 actvero auth login --server <平台地址>${write ? ' --write' : ''}。${write ? '已有只读会话需升级时，先说明会退出此平台的 CLI 会话，再执行 auth logout --server <平台地址> 和上述带 --write 的登录。' : ''}需要我本人在浏览器完成登录时，清楚提示并等待；不要索取聊天中的密码或令牌，不读取 Web Cookie 或其他客户端凭据。系统凭据库不可用时报告原因，不退回明文保存。
6. 运行 actvero org list --server <平台地址> --json，检查分页。若有多个可用组织，请让我选择；不要猜组织 UUID。用 org permissions --server <平台地址> --org <实际组织UUID> --json 核验权限。
7. 完成后报告实际 CLI 版本、平台、组织和授权范围。后续资源命令都显式带 --server 和 --org。本次只完成接入，不自动创建、发布或删除业务资源；读写授权不代表我已经授权所有业务操作。不要把仅安装成功说成连接成功。`
}
