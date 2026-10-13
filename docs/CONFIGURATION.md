# 配置参考

环境变量定义见 `.env.example` 与 `backend/app/core/config.py`。使用环境生成器创建秘密，不把示例占位符直接用于运行。下面列出常用分组。

| 配置 | 用途 |
| --- | --- |
| `ACTVERO_PLATFORM_EDITION` | community 单组织或 saas 多组织 |
| `ACTVERO_APP_URL` | 浏览器可见应用地址 |
| `ACTVERO_OIDC_ISSUER` | 外部身份发行者 |
| `ACTVERO_DATABASE_URL` | 原生开发的业务数据库 URL |
| `ACTVERO_SESSION_ENCRYPTION_KEY` | 持久会话及凭据加密，升级时保留 |
| `ACTVERO_WEB_CLIENT_SECRET` / `ACTVERO_PROVISIONER_CLIENT_SECRET` | 身份客户端秘密 |
| `ACTVERO_SMTP_*` | 应用邮件设置 |
| `ACTVERO_WEB_SESSION_POLICY` / `ACTVERO_DESKTOP_SESSION_POLICY` | 独立 Web 与桌面会话策略 |
| `ACTVERO_MANAGEMENT_ENABLED` | 是否开放独立管理 CLI 接口 |
| `ACTVERO_MCP_ALLOWED_PRIVATE_ORIGINS` | MCP 内网来源白名单 |
| `ACTVERO_LLM_ALLOWED_PRIVATE_ORIGINS` | 模型渠道内网来源白名单 |
| `ACTVERO_MCP_PUBLIC_DNS` / `ACTVERO_LLM_PUBLIC_DNS` | 相应公网解析策略 |

完整 Compose 使用容器内部地址连接数据库和身份服务；原生开发使用宿主地址。容器内 127.0.0.1 指向容器自己，调用宿主服务需配置实际可达地址及精确白名单。

Web、桌面、CLI 策略独立。滚动恢复需要与身份服务会话上限相匹配；变更配置不会复活旧会话。环境、数据目录和私钥只保存在部署环境或秘密管理系统。
