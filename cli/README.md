# Actvero 管理 CLI

独立 Python 包，支持浏览器登录、凭据续期、显式组织选择与渠道只读查询。业务命令必须指定组织 UUID。

```sh
uv sync --frozen --directory cli
uv run --directory cli actvero --help
uv run --directory cli actvero auth login --server https://actvero.example.com
uv run --directory cli actvero org list --json
uv run --directory cli actvero channels list --org <UUID> --json
```

在仓库根目录运行这些命令。也可以用 `uv tool install ./cli` 安装。平台需启用独立管理接口并配置 CLI OIDC client，见 [CLI 接入](../docs/CLI.md)。

凭据保存到系统凭据库；凭据库不可用时停止，不回退到明文。当前不提供资源写操作或模型、MCP、Skills、专家管理命令。

检查：`make cli-bootstrap cli-check cli-test`。配套 Skill 位于 [agent-skills](../agent-skills/actvero-management/SKILL.md)。
