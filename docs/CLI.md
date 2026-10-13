# 管理 CLI 接入

CLI 是独立 Python 包，当前提供浏览器登录、续期、组织发现、权限查询和渠道只读查询。所有业务命令显式传组织 UUID。

## 安装与启用

从仓库根执行 `uv tool install ./cli`，用 `actvero --help` 查看命令。平台需开启 `ACTVERO_MANAGEMENT_ENABLED=true` 并配置独立公共 client `actvero-cli`；已有身份库不会因修改导入模板自动更新客户端。

## 安全存储

系统凭据库不可用时登录停止，不写明文替代。管理凭据不能由 Web Cookie、桌面令牌或个人访问密钥替代。403 表示当前资格问题，不能用自动重试绕过。

## 使用

```sh
actvero auth login --server https://actvero.example.com
actvero org list --json
actvero channels list --org <组织UUID> --json
```

命令与配套 Skill 见 [CLI README](../cli/README.md)。

## 参考

[文档导航](README.md) · [API 契约](api/openapi.json)
