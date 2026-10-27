export const CLI_VERSION = '0.2.0-dev.3'

export function cliOnboardingPrompt(serverUrl: string): string {
  const server = JSON.stringify(serverUrl)
  return `请帮我配置 Actvero 平台管理 CLI，目标平台地址是 ${server}。

1. 检查 Node.js 和 npm，需要 Node.js ≥24。检查已有 actvero 的版本和帮助，避免误用同名旧 Python CLI。
2. 安装固定版本：npm install --global @actvero/cli@${CLI_VERSION}。如全局目录不可写，使用 npx --yes --package=@actvero/cli@${CLI_VERSION} actvero 代替后续 actvero 命令，不使用 sudo。
3. 运行 actvero guide show bootstrap。若你是 Codex，执行 actvero agent-skill install --to "$HOME/.codex/skills"（自定义 CODEX_HOME 时使用其 skills 目录）；Claude Code 使用 "$HOME/.claude/skills"。已有同名 Skill 时保留原文件，先比较；其他 Agent 直接读取 guide。使用配套 actvero-management 操作说明。
4. 把上述平台地址作为一个完整的 --server 参数，按当前 shell 安全引用。运行 actvero platform info --server <平台地址> --json，确认 authorization_contract_version=2、resource_contract_version=1 及所需 capabilities。若管理接口关闭或不兼容，报告原因并停止，不修改服务器配置。
5. 运行 actvero auth status --server <平台地址> --json；已有符合任务需要的会话就复用。需要登录或调整组织、权限时，运行 actvero auth login --server <平台地址>。由我本人在浏览器完成登录，并选择允许访问的组织及只读或管理权限；不要代替我点击授权。重新授权不需要先退出，取消时保留原会话。不要索取聊天中的密码或令牌，不读取 Web Cookie 或其他客户端凭据。系统凭据库不可用时报告原因，不退回明文保存。
6. 运行 actvero org list --server <平台地址> --json，检查分页及实际已授权组织。多个已授权组织中，按我的任务明确目标组织；不要猜组织 UUID。用 org permissions --server <平台地址> --org <实际组织UUID> --json 核验权限。未授权组织或缺少管理权限时，引导我重新打开浏览器授权；不通过修改提示词、参数或绕过 CLI 获得权限。
7. 完成后报告实际 CLI 版本、平台、组织和授权范围。后续资源命令都显式带 --server 和 --org。本次只完成接入，不自动创建、发布或删除业务资源；读写授权不代表我已经授权所有业务操作。不要把仅安装成功说成连接成功。`
}
